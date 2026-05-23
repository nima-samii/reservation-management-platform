# 19-Step English Learning — Reservation Bot

A production-grade Telegram bot for booking live English-learning session slots.
Built with **Python 3.12**, **Aiogram 3**, **FastAPI**, **PostgreSQL**, **SQLAlchemy 2 async**, **Redis**, and **Docker**.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Telegram Users                           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTPS
                ┌───────────▼────────────┐
                │   FastAPI + Uvicorn    │  ← Webhook handler
                │   /webhook  /health    │
                └───────────┬────────────┘
                            │
          ┌─────────────────▼──────────────────┐
          │          Aiogram Dispatcher          │
          │  Middlewares → Routers → Handlers   │
          └──┬────────────┬──────────────────┬──┘
             │            │                  │
     ┌───────▼──┐  ┌──────▼──────┐  ┌───────▼──────┐
     │ Services │  │ Repositories│  │  Schedulers  │
     │  layer   │  │   (async)   │  │  (APSched)   │
     └───────┬──┘  └──────┬──────┘  └───────┬──────┘
             │            │                  │
     ┌───────▼────────────▼──────────────────▼──────┐
     │           PostgreSQL  ·  Redis                │
     └───────────────────────────────────────────────┘
```

### Clean Architecture Layers

| Layer | Responsibility |
|---|---|
| **Handlers** | Receive Telegram updates, call services, respond |
| **Services** | Business logic, orchestration, rule enforcement |
| **Repositories** | Data access — all DB queries live here |
| **Models** | SQLAlchemy ORM entities |
| **Cache** | Redis client, rate limiting, distributed locks |
| **Schedulers** | Slot generation + reservation lifecycle transitions |

---

## Features

- **Registration flow** — auto-detected Telegram name, confirm/edit, gender, country
- **Country search** — inline keyboard with live search for 195+ countries + flags
- **Slot booking** — date picker → time picker → confirm, with full validation
- **Smart channel prioritization** — slots displayed from Channel 1 first; Channel 2+ unlocks per-day when the preceding channel reaches 70% fill ratio
- **Reservation management** — view upcoming reservations and cancel future ones
- **Reservation lifecycle** — scheduler auto-transitions past `active` reservations to `completed` every 30 minutes; only future slots count toward the active limit
- **Same-day booking cutoff** — bookings for today blocked after 12:00 PM (noon) in both UI and backend
- **Same-day cancellation cutoff** — cancelling today's reservation blocked after 12:00 PM; future days always cancellable
- **Profile editing** — name, gender, country (never changes telegram_id)
- **Race-condition protection** — Redis distributed lock per slot + DB `SELECT FOR UPDATE NOWAIT`
- **Re-booking after cancellation** — partial unique index (`WHERE status = 'active'`) allows the same slot to be booked again after cancellation
- **Rate limiting** — sliding window, 30 req/min per user
- **Anti-flood** — 500ms minimum between actions
- **Slot generation** — APScheduler generates 14-day rolling slots at midnight & 6 AM
- **Structured logging** — JSON via structlog
- **Health endpoint** — `/health` checks DB + Redis
- **Webhook + Polling modes** — webhook for production, polling for dev

---

## Project Structure

```
19-step/
├── app/
│   ├── api/                  # FastAPI app, webhook & health routers
│   ├── bot/
│   │   ├── handlers/         # Aiogram update handlers
│   │   ├── keyboards/        # Reply + Inline keyboards
│   │   ├── middlewares/      # Rate limit, anti-flood, session, user context
│   │   ├── states/           # FSM state groups
│   │   └── filters/          # IsRegistered / IsNotRegistered
│   ├── cache/                # Redis client + key factory
│   ├── core/                 # Config (pydantic-settings), logging, exceptions
│   ├── db/
│   │   ├── base.py           # DeclarativeBase, mixins
│   │   ├── session.py        # Async engine + session factory
│   │   └── models/           # ORM models
│   ├── repositories/         # Data-access layer
│   ├── schedulers/           # APScheduler setup + jobs
│   ├── services/             # Business logic
│   └── utils/                # Datetime helpers
├── migrations/               # Alembic env + versions
├── scripts/
│   └── seed_countries.py     # One-time country seeder
├── docker/
│   └── Dockerfile
├── docker-compose.yml        # Production compose
├── docker-compose.dev.yml    # Dev override (polling mode)
├── main_polling.py           # Local dev entrypoint
├── alembic.ini
├── requirements.txt
├── pyproject.toml
└── .env.example
```

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repo>
cd 19-step
cp .env.example .env
# Edit .env — set BOT_TOKEN and POSTGRES_PASSWORD at minimum
```

### 2. Run with Docker (recommended)

```bash
# Production (webhook mode)
docker compose up --build

# Development (polling mode, hot-reload)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

Docker Compose will:
1. Start PostgreSQL and Redis
2. Run `alembic upgrade head`
3. Run `seed_countries.py`
4. Start the application

### 3. Local development (no Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Set up .env, then run migrations
alembic upgrade head

# Seed countries
python scripts/seed_countries.py

# Run in polling mode
python main_polling.py
```

---

## Database Schema

```
countries          users               channels
──────────         ──────────          ──────────
id (PK)            id (PK)             id (PK)
code (UQ)          telegram_id (UQ)    name
name (UQ)          public_user_code    telegram_channel_id
flag_emoji         full_name           invite_link
is_active          username            capacity
                   gender              priority
                   country_id (FK)     is_active
                   is_active
                   is_banned

reservation_slots              reservations                    audit_logs
─────────────────              ────────────                    ──────────
id (PK)                        id (PK)                         id (PK)
slot_datetime                  user_id (FK)                    user_id (FK)
channel_id (FK)                slot_id (FK)                    action
is_booked                      channel_id (FK)                 entity_type
UQ: (slot_datetime,            status ¹                        details
     channel_id)               notes                           created_at
```

> ¹ `status` values: `active` · `completed` · `cancelled` · `expired`
>
> Partial unique index on `reservations(slot_id) WHERE status = 'active'` — allows re-booking a slot after its reservation is cancelled or completed.

---

## Reservation Rules

| Rule | Value |
|---|---|
| Sessions per day (per user) | 1 |
| Max active (future) reservations | 10 |
| Booking window | Next 14 days |
| Session hours | 4:00 PM – 12:00 AM (Asia/Baghdad) |
| Slot duration | 30 minutes |
| Same-day booking cutoff | 12:00 PM noon — today's date hidden after cutoff |
| Same-day cancellation cutoff | 12:00 PM noon — cancel button hidden after cutoff |
| Channel unlock threshold | 70% daily fill ratio of preceding channel |
| Lifecycle job interval | Every 30 minutes (`active` → `completed` for past slots) |

---

## Channel Management

Users book **slots**, not channels — channel assignment is transparent.

Each active channel gets its own set of slots per day. Channels are exposed to users in priority order using a **fill-ratio gate**:

1. **Channel 1** slots are always shown first ("Recommended Slots").
2. The system computes Channel 1's daily fill ratio: `active_reservations_today / slots_per_day`.
3. Once the ratio reaches `CHANNEL_CAPACITY_THRESHOLD` (default 70%), Channel 2 slots become visible ("More Available Slots").
4. The same rule cascades — Channel 3 unlocks when Channel 2 reaches 70%, and so on.

The channel a slot belongs to is determined at slot-generation time. The `(slot_datetime, channel_id)` pair is unique, so each channel has its own parallel set of slots per day.

To add a channel: insert a row into the `channels` table with the appropriate `priority` value and redeploy (the slot-generation scheduler will pick it up).

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | **required** | Telegram Bot API token |
| `POSTGRES_PASSWORD` | **required** | DB password |
| `WEBHOOK_URL` | empty | Public HTTPS URL; empty = polling mode |
| `WEBHOOK_SECRET` | empty | Telegram webhook secret token |
| `TIMEZONE` | `Asia/Baghdad` | System timezone for all datetime logic |
| `MAX_ACTIVE_RESERVATIONS` | `10` | Max future active reservations per user |
| `MAX_RESERVATION_DAYS_AHEAD` | `14` | Booking window in days |
| `CHANNEL_CAPACITY_THRESHOLD` | `0.70` | Daily fill ratio to unlock the next channel |
| `SAME_DAY_CUTOFF_HOUR` | `12` | Hour (0–23) after which same-day booking is blocked |
| `SAME_DAY_CANCEL_CUTOFF_HOUR` | `12` | Hour (0–23) after which same-day cancellation is blocked |
| `SLOT_START_HOUR` | `16` | First slot hour of the day |
| `SLOT_END_HOUR` | `24` | Last slot boundary (exclusive) |
| `SLOT_DURATION_MINUTES` | `30` | Slot length in minutes |
| `RATE_LIMIT_REQUESTS` | `30` | Requests allowed per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |
| `ANTI_FLOOD_SECONDS` | `0.5` | Minimum seconds between user actions |
| `LOG_FORMAT` | `json` | `json` (production) or `console` (dev) |
| `ADMIN_IDS` | empty | Comma-separated telegram IDs for admins |

---

## Admin Panel Readiness

The architecture is designed for clean admin panel addition:

- **Services** contain all business logic with no Telegram coupling → reusable from admin HTTP endpoints
- **Repositories** are injectable → testable and reusable
- **`audit_logs` table** tracks all user actions
- **`channels` table** fully manageable via DB / API
- **`users.is_banned`** flag ready for blacklist feature
- **`reservations.status`** lifecycle: `active` → `completed` (auto), `cancelled` (user), `expired` (future admin use)
- **`booking_rules.py`** contains pure, stateless policy functions (`is_same_day_cutoff_passed`, `can_cancel_reservation`) — easily unit-tested and reusable outside the bot
- FastAPI already running — add `/admin` routers without touching bot code

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Security Notes

- Webhook secret token validated on every update
- Non-root Docker user
- No hardcoded secrets — all via environment variables
- SQL injection impossible — SQLAlchemy ORM + parameterized queries
- Redis slot locks prevent race conditions on booking
- `SELECT FOR UPDATE NOWAIT` prevents double-booking at the DB level
- Rate limiting and anti-flood on all user interactions
