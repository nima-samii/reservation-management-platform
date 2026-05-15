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
| **Schedulers** | Background job for slot generation |

---

## Features

- **Registration flow** — auto-detected Telegram name, confirm/edit, gender, country
- **Country search** — inline keyboard with live search for 195+ countries + flags
- **Slot booking** — date picker → time picker → confirm, with full validation
- **Channel auto-assignment** — fills channels in priority order; moves to next at 70% capacity
- **Reservation management** — view and cancel future reservations
- **Profile editing** — name, gender, country (never changes telegram_id)
- **Race-condition protection** — Redis distributed lock per slot + DB `SELECT FOR UPDATE NOWAIT`
- **Rate limiting** — sliding window, 30 req/min per user
- **Anti-flood** — 500ms minimum between actions
- **Slot generation** — APScheduler generates 14-day slots at midnight & 6 AM
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

reservation_slots      reservations           audit_logs
─────────────────      ────────────           ──────────
id (PK)                id (PK)                id (PK)
slot_datetime (UQ)     user_id (FK)           user_id (FK)
is_booked              slot_id (FK, UQ)       action
                       channel_id (FK)        entity_type
                       status                 details
                       notes                  created_at
```

---

## Reservation Rules

| Rule | Value |
|---|---|
| Sessions per day | 1 |
| Max simultaneous active reservations | 10 |
| Booking window | Next 14 days |
| Session hours | 4:00 PM – 12:00 AM (Asia/Baghdad) |
| Slot duration | 30 minutes |
| Channel switch threshold | 70% capacity |

---

## Channel Management

Channels are assigned automatically — the user never picks a channel.

1. All active channels are ordered by `priority` (ascending).
2. For each channel, the system calculates `active_reservations / capacity`.
3. The first channel below the `CHANNEL_CAPACITY_THRESHOLD` (default 70%) is selected.
4. If no channel has space, the reservation is rejected with a clear error.

To add a new channel, insert a row into the `channels` table with a higher `priority` value.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | **required** | Telegram Bot API token |
| `POSTGRES_PASSWORD` | **required** | DB password |
| `WEBHOOK_URL` | empty | Public HTTPS URL; empty = polling mode |
| `WEBHOOK_SECRET` | empty | Telegram webhook secret token |
| `TIMEZONE` | `Asia/Baghdad` | System timezone for slot scheduling |
| `MAX_ACTIVE_RESERVATIONS` | `10` | Max reservations per user |
| `MAX_RESERVATION_DAYS_AHEAD` | `14` | Booking window in days |
| `CHANNEL_CAPACITY_THRESHOLD` | `0.70` | Fraction to trigger channel switch |
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
- **`reservations.status`** enum supports: `active`, `cancelled`, `completed`, `no_show`
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
