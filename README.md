# 19-Step English Learning — Reservation Bot

A production-grade Telegram bot for booking live English-learning session slots.
Built with **Python 3.12**, **Aiogram 3**, **FastAPI**, **PostgreSQL**, **SQLAlchemy 2 async**, **Redis**, **APScheduler**, and **Docker**.

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
     ┌───────▼──┐  ┌──────▼──────┐  ┌───────▼──────────────────┐
     │ Services │  │ Repositories│  │  APScheduler Jobs         │
     │  layer   │  │   (async)   │  │  • slot generation        │
     └───────┬──┘  └──────┬──────┘  │  • reservation lifecycle  │
             │            │         │  • same-day reminders      │
             │            │         │  • pre-session reminders   │
             │            │         │  • daily broadcast         │
             │            │         └───────────────┬────────────┘
             │            │                         │
     ┌───────▼────────────▼─────────────────────────▼──────┐
     │              PostgreSQL  ·  Redis                    │
     └──────────────────────────────────────────────────────┘
```

### Clean Architecture Layers

| Layer | Responsibility |
|---|---|
| **Handlers** | Receive Telegram updates, call services, respond |
| **Services** | Business logic, orchestration, rule enforcement |
| **Repositories** | Data access — all DB queries live here |
| **Models** | SQLAlchemy ORM entities |
| **Cache** | Redis client, key factory, distributed locks |
| **Schedulers** | Background jobs: slot generation, lifecycle, reminders, broadcast |
| **Templates** | Jinja2 templates for broadcast message rendering |

---

## Features

### Core Booking

- **Registration flow** — auto-detected Telegram name, confirm/edit, gender, country
- **Country search** — inline keyboard with live search for 195+ countries + flags
- **Slot booking** — date picker → time picker → confirm, with full validation
- **Smart channel prioritization** — slots from Channel 1 first; Channel 2+ unlocks when Channel 1 reaches the 70% fill threshold
- **Reservation management** — view upcoming reservations and cancel future ones
- **Reservation lifecycle** — scheduler auto-transitions past `active` reservations to `completed` every 30 minutes; only future slots count toward the active limit
- **Special terminal slot** — an optional 11:59 PM slot is appended after the normal 30-minute interval range; it stays on the same calendar day (no midnight rollover), is fully reservable, appears in reminders and broadcasts, and is controlled by `ENABLE_FINAL_MIDNIGHT_SLOT` / `FINAL_SLOT_TIME`
- **Same-day booking cutoff** — bookings blocked after 12:00 PM in both UI and backend
- **Same-day cancellation cutoff** — cancel button hidden and backend rejects after 12:00 PM; future days always cancellable
- **Profile editing** — name, gender, country

### Participation Score

- **+1** awarded on successful booking; **−1** on cancellation
- Reserve + cancel nets zero — farming is blocked by design
- Immutable `score_transactions` audit ledger — every delta is a permanent row
- Atomic SQL updates (`participation_score = participation_score + delta`) — no read-modify-write race
- Score visible in user profile and in daily broadcasts
- Extensible: no-show penalty and admin manual adjustment already implemented

### Notification & Reminder System

- **Same-day reminder** — sent at `SAME_DAY_REMINDER_HOUR` (default 12:00 PM) to every user with a reservation on that day; includes channel name and invite link
- **Pre-session reminder** — sent `PRE_SESSION_REMINDER_MINUTES` (default 30) minutes before session start; scheduler polls every 5 minutes with a ±5-minute window to tolerate jitter
- **Duplicate prevention** — `notification_logs` table with `UNIQUE(reservation_id, reminder_type)`; already-sent reminders are excluded by a NOT IN subquery before any message is attempted
- **Failure isolation** — each user is processed independently; a blocked bot or deleted account logs a `FAILED` row and does not affect other deliveries
- **Redis locks** prevent concurrent runs across multiple instances

### Daily Schedule Broadcast

- **Per-channel broadcast** — at `DAILY_BROADCAST_HOUR` (default 12:00 PM), today's session schedule is published to every active Telegram channel
- **Channel isolation** — each channel receives only its own reservations; timezone-correct date casting (`AT TIME ZONE`) for accurate local-day filtering
- **Jinja2 template** — message layout lives in `app/templates/schedule_message.j2`; update the template without touching Python
- **Reservation entries** — each entry shows time, clock emoji, gender emoji, country flag, public user ID, and participation score
- **Special event blocks** — insert rows into `schedule_events` (with `channel_id=NULL` for global events) to inject custom blocks (e.g. "Collective Dhikr") without code changes
- **Auto-pin** — new broadcast is pinned; previous day's message is unpinned (controlled by `ENABLE_BROADCAST_AUTO_PIN` and `DELETE_PREVIOUS_BROADCAST`)
- **Deduplication** — `broadcast_logs` with `UNIQUE(channel_id, broadcast_date)` prevents double-broadcast; failed attempts are retried on the next run
- **Full audit trail** — every broadcast outcome (sent/failed + `telegram_message_id`) stored in `broadcast_logs` for future retries and admin tooling

### Reliability

- Race-condition protection — Redis distributed lock per slot + `SELECT FOR UPDATE NOWAIT`
- Re-booking after cancellation — partial unique index (`WHERE status = 'active'`) allows a slot to be booked again
- Rate limiting — sliding window, 30 req/min per user
- Anti-flood — 500ms minimum between actions
- Structured JSON logging via structlog
- Health endpoint — `/health` checks DB + Redis
- Webhook + Polling modes — webhook for production, polling for dev

---

## Project Structure

```
19-step/
├── app/
│   ├── api/                      # FastAPI app, webhook & health routers
│   ├── bot/
│   │   ├── client.py             # Shared Bot singleton for scheduler jobs
│   │   ├── handlers/             # Aiogram update handlers
│   │   ├── keyboards/            # Reply + Inline keyboards
│   │   ├── middlewares/          # Rate limit, anti-flood, session, user context
│   │   ├── states/               # FSM state groups
│   │   └── filters/
│   ├── cache/                    # Redis client + key factory (all keys centralised)
│   ├── core/                     # Config (pydantic-settings), logging, exceptions
│   ├── db/
│   │   ├── base.py               # DeclarativeBase, UUID/Timestamp mixins
│   │   ├── session.py            # Async engine + session factory
│   │   └── models/               # ORM models (all imported in __init__.py)
│   ├── repositories/             # Data-access layer — one class per aggregate
│   ├── schedulers/
│   │   ├── setup.py              # APScheduler wiring — all jobs registered here
│   │   └── jobs/                 # One module per job function
│   │       ├── slot_generation.py
│   │       ├── reservation_lifecycle.py
│   │       ├── reminders.py      # same-day + pre-session reminder jobs
│   │       └── broadcast.py      # daily schedule broadcast job
│   ├── services/                 # Business logic
│   │   ├── broadcast.py          # BroadcastService — per-channel orchestration
│   │   ├── notification.py       # NotificationService + ReminderService
│   │   ├── schedule_formatter.py # Jinja2 renderer for broadcast messages
│   │   ├── reservation.py
│   │   ├── score.py              # ParticipationScoreService
│   │   ├── slot.py
│   │   └── user.py
│   ├── templates/
│   │   └── schedule_message.j2   # Broadcast message template
│   └── utils/
├── admin-panel/                  # Next.js 14 admin panel (TypeScript, Tailwind, React Query)
│   ├── app/
│   │   ├── (dashboard)/
│   │   │   ├── layout.tsx        # Dashboard shell with sidebar
│   │   │   ├── users/            # User list + detail pages + components
│   │   │   └── reservations/     # Reservations page + components
│   │   └── login/                # Login page
│   ├── components/Sidebar.tsx    # Shared sidebar nav
│   ├── lib/
│   │   ├── api.ts                # Axios instance with JWT auto-refresh
│   │   ├── auth.ts               # Cookie/localStorage token helpers
│   │   └── api/
│   │       ├── users.ts          # Typed user API functions
│   │       └── reservations.ts   # Typed reservation API functions
│   └── store/auth.ts             # Zustand auth store
├── migrations/
│   └── versions/
│       ├── 0001_initial_schema.py
│       ├── 0002_add_channel_to_slots.py
│       ├── 0003_partial_unique_slot_reservation.py
│       ├── 0004_reservation_lifecycle_indexes.py
│       ├── 0005_participation_score.py
│       ├── 0006_notification_logs.py
│       ├── 0007_broadcast_and_schedule_events.py
│       └── 0008_admin_audit_logs.py
├── tests/
│   ├── conftest.py
│   └── test_services/
│       ├── test_schedule_formatter.py
│       └── test_broadcast.py
├── scripts/
│   └── seed_countries.py
├── docker/Dockerfile
├── docker-compose.yml
├── main_polling.py
└── .env.example
```

---

## Scheduled Jobs

All jobs run inside the same process as the bot (APScheduler with `AsyncIOScheduler`). Redis distributed locks prevent concurrent runs in multi-instance deployments.

| Job | Schedule | Description |
|---|---|---|
| `slot_generation` | 00:00 & 06:00 daily | Generate slots for the next 14 days across all active channels |
| `reservation_lifecycle` | Every 30 min | Transition past `active` reservations → `completed` |
| `same_day_reminders` | `SAME_DAY_REMINDER_HOUR`:00 daily | Send today's session reminder to all users with a reservation |
| `pre_session_reminders` | Every 5 min | Send pre-session reminder to users whose slot starts in ~`PRE_SESSION_REMINDER_MINUTES` min |
| `daily_broadcast` | `DAILY_BROADCAST_HOUR`:00 daily | Publish today's schedule to each active Telegram channel |

---

## Database Schema

```
countries          users                        channels
──────────         ──────────────────────────── ──────────────────
id (PK)            id (PK)                      id (PK)
code (UQ)          telegram_id (UQ)             name
name (UQ)          public_user_code (UQ)        telegram_channel_id
flag_emoji         full_name                    invite_link
is_active          username                     capacity
                   gender                       priority
                   country_id (FK)              is_active
                   participation_score  ←score
                   is_active
                   is_banned

reservation_slots              reservations
─────────────────              ────────────────────────────────
id (PK)                        id (PK)
slot_datetime                  user_id (FK)
channel_id (FK)                slot_id (FK)
is_booked                      channel_id (FK)
UQ: (slot_datetime,            status ¹
     channel_id)               notes

score_transactions             notification_logs
──────────────────             ─────────────────────────────
id (PK)                        id (PK)
user_id (FK)                   reservation_id (FK)
reservation_id (FK)            reminder_type  ²
transaction_type               status  ³
score_delta                    error_message
reason                         sent_at
meta (JSONB)                   UQ: (reservation_id, reminder_type)
created_at

schedule_events                broadcast_logs
───────────────                ──────────────────────────────
id (PK)                        id (PK)
channel_id (FK, nullable)      channel_id (FK, nullable)
event_date                     telegram_message_id
title                          broadcast_date
sort_order                     status  ⁴
is_active                      error_message
                               sent_at
                               UQ: (channel_id, broadcast_date)

admin_audit_logs
──────────────────────────────
id (PK)
action                         — e.g. "user_patched", "score_adjusted", "no_show_applied"
admin_username
entity_type                    — "user" | "reservation" | ...
entity_id
details                        — human-readable change summary
ip_address
created_at
```

> ¹ `reservation.status`: `active` · `completed` · `cancelled` · `expired`
>
> ² `notification_logs.reminder_type`: `same_day` · `pre_session`
>
> ³ `notification_logs.status`: `sent` · `failed`
>
> ⁴ `broadcast_logs.status`: `sent` · `failed`
>
> Partial unique index on `reservations(slot_id) WHERE status = 'active'` — allows re-booking after cancellation.

---

## Reservation Rules

| Rule | Value |
|---|---|
| Sessions per day (per user) | 1 |
| Max active (future) reservations | 10 |
| Booking window | Next 14 days |
| Session hours | 4:00 PM – 11:30 PM + optional 11:59 PM terminal slot (Asia/Baghdad) |
| Slot duration | 30 minutes (interval slots); 11:59 PM is a special terminal slot |
| Same-day booking cutoff | 12:00 PM — today's slots hidden after cutoff |
| Same-day cancellation cutoff | 12:00 PM — cancel button hidden after cutoff |
| Channel unlock threshold | 70% daily fill ratio of preceding channel |
| Lifecycle job interval | Every 30 minutes (`active` → `completed`) |

---

## Channel Management

Users book **slots**, not channels — channel assignment is transparent to the user.

Each active channel gets its own set of slots per day. Channels are exposed to users in priority order using a **fill-ratio gate**:

1. **Channel 1** slots are always shown first ("Recommended Slots").
2. Once Channel 1's daily fill ratio reaches `CHANNEL_CAPACITY_THRESHOLD` (default 70%), Channel 2 slots become visible ("More Available Slots").
3. The same rule cascades for Channel 3, 4, etc.

**Daily broadcast**: at `DAILY_BROADCAST_HOUR` each channel receives its own schedule message — containing only that channel's reservations. The bot must be an admin in each channel with **Post messages** and **Pin messages** permissions.

**Adding a channel**: insert a row into the `channels` table with the appropriate `priority` value, add `CHANNEL_N_*` variables to `.env`, and redeploy. The slot-generation scheduler picks it up automatically.

---

## Broadcast Message Format

Each channel's daily broadcast looks like this:

```
📅 Live Sessions Today
Echoes  •  Wednesday, May 29, 2026
🌍 Asia/Baghdad

━━━━━━━━━━━━━━━━━━━━━

🕓 4:00 PM
👩‍💼 🇲🇾 Malaysia  │  ID: ABC123  │  ⭐ 20

🕔 5:00 PM
👨‍💼 🇮🇶 Iraq  │  ID: XY7890  │  ⭐ 15

━━━━━━━━━━━━━━━━━━━━━

🕌 Collective Dhikr (Salawat Gathering)

━━━━━━━━━━━━━━━━━━━━━

📌 Reserve your session via the bot.

📺 Echoes → https://t.me/+...
```

The layout is rendered by `app/templates/schedule_message.j2`. Special event blocks (e.g. "Collective Dhikr") are injected from the `schedule_events` table — set `channel_id = NULL` for a block that appears in all channels.

---

## Environment Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `BOT_TOKEN` | **required** | Telegram Bot API token |
| `POSTGRES_PASSWORD` | **required** | Database password |
| `WEBHOOK_URL` | empty | Public HTTPS URL; empty = polling mode |
| `WEBHOOK_SECRET` | empty | Telegram webhook secret token |
| `TIMEZONE` | `Asia/Baghdad` | pytz timezone for all datetime logic and scheduling |

### Reservation Rule Variables

| Variable | Default | Description |
|---|---|---|
| `MAX_ACTIVE_RESERVATIONS` | `10` | Max future active reservations per user |
| `MAX_RESERVATION_DAYS_AHEAD` | `14` | Booking window in days |
| `CHANNEL_CAPACITY_THRESHOLD` | `0.70` | Daily fill ratio to unlock the next channel |
| `SAME_DAY_CUTOFF_HOUR` | `12` | Hour (0–23) after which same-day booking is blocked |
| `SAME_DAY_CANCEL_CUTOFF_HOUR` | `12` | Hour (0–23) after which same-day cancellation is blocked |
| `SLOT_START_HOUR` | `16` | First slot hour of the day |
| `SLOT_END_HOUR` | `24` | Last slot boundary (exclusive) |
| `SLOT_DURATION_MINUTES` | `30` | Slot length in minutes |
| `ENABLE_FINAL_MIDNIGHT_SLOT` | `true` | Append a special terminal slot after the interval range |
| `FINAL_SLOT_TIME` | `23:59` | Time (HH:MM, 24-hour) of the terminal slot — stays on the same calendar day |

### Notifications & Reminders

| Variable | Default | Description |
|---|---|---|
| `SAME_DAY_REMINDER_HOUR` | `12` | Hour (0–23) same-day reminders are dispatched |
| `PRE_SESSION_REMINDER_MINUTES` | `30` | Minutes before session start for pre-session reminder |

### Daily Broadcast

| Variable | Default | Description |
|---|---|---|
| `DAILY_BROADCAST_HOUR` | `12` | Hour (0–23) daily schedule is published to each channel |
| `ENABLE_BROADCAST_AUTO_PIN` | `true` | Pin the broadcast message after sending |
| `DELETE_PREVIOUS_BROADCAST` | `false` | Delete yesterday's broadcast when publishing today's |

### Channels

| Variable | Description |
|---|---|
| `CHANNEL_N_ID` | Telegram channel/group ID (negative integer) |
| `CHANNEL_N_NAME` | Display name used in confirmations, reminders, and broadcasts |
| `CHANNEL_N_INVITE` | Public invite link included in reminders and the daily broadcast |

Add `CHANNEL_2_*`, `CHANNEL_3_*` etc. to register additional channels. Channels are loaded dynamically — no code changes required.

### Rate Limiting & Other

| Variable | Default | Description |
|---|---|---|
| `RATE_LIMIT_REQUESTS` | `30` | Requests per window per user |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window |
| `ANTI_FLOOD_SECONDS` | `0.5` | Minimum seconds between user actions |
| `LOG_FORMAT` | `json` | `json` (production) or `console` (dev) |
| `ADMIN_IDS` | empty | Comma-separated Telegram user IDs for admins |

---

## Quick Start

### 1. Clone & configure

```bash
git clone <repo>
cd 19-step
cp .env.example .env
# Edit .env — set BOT_TOKEN, POSTGRES_PASSWORD, CHANNEL_1_* at minimum
```

### 2. First-time setup (installs deps, runs migrations, seeds DB)

```bash
make setup
```

### 3. Run with Docker (recommended)

```bash
make build        # production — webhook mode
make dev          # development — polling mode + hot-reload
```

Docker Compose will:

1. Start PostgreSQL and Redis
2. Run `alembic upgrade head` (all migrations)
3. Run `seed_countries.py`
4. Start the application with all scheduled jobs active

### 4. Local development (no Docker)

```bash
make install      # pip install -r requirements.txt
make migrate-local
make seed-local
make run          # polling mode
```

### All available commands

```bash
make help
```

---

## Running Tests

```bash
make test          # full suite, verbose
make test-fast     # no verbose output
make test-cov      # with coverage report
```

Test coverage includes:

- `test_slot_generation.py` — 13 tests covering interval generation, 11:59 PM terminal slot append/disable/dedup, chronological order, same-day calendar integrity, `_slots_per_day` count accuracy
- `test_schedule_formatter.py` — 25 tests covering clock emojis, time formatting, 11:59 PM rendering (time label, clock emoji, no date rollover), all template rendering paths (empty schedule, entries, events, country flags, gender emojis, invite links)
- `test_broadcast.py` — 8 tests covering deduplication, per-channel isolation, Telegram failure handling, pin/unpin lifecycle

---

## Admin Panel

A web-based admin panel is included in `admin-panel/` (Next.js 14, TypeScript, Tailwind CSS).

### Start admin panel

```bash
make admin-up      # Docker — port 3000 (requires main stack to be running first)
make admin-dev     # Local dev server — port 3000
```

Open `http://localhost:3000` and sign in with the credentials from your `.env`.

### Generate credentials

```bash
# Bcrypt hash for ADMIN_PASSWORD
make hash pw=yourpassword

# Random secret for ADMIN_JWT_SECRET
make gen-secret
```

### Endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `POST /api/admin/auth/login` | public | Returns `access_token` + `refresh_token` |
| `POST /api/admin/auth/refresh` | public | Rotates refresh token (old token invalidated) |
| `POST /api/admin/auth/logout` | public | Revokes refresh token from Redis |
| `GET /api/admin/health` | JWT | DB + Redis reachability check |
| `GET /api/admin/users` | JWT | Paginated user list — search, filter, sort |
| `GET /api/admin/users/{id}` | JWT | Full user profile + recent 20 score transactions |
| `PATCH /api/admin/users/{id}` | JWT | Edit name, gender, country, active/ban status |
| `POST /api/admin/users/{id}/score` | JWT | Admin score adjustment (delta ±1–100, reason required) |
| `GET /api/admin/users/{id}/score-history` | JWT | Paginated score transaction history |
| `POST /api/admin/users/{id}/send-message` | JWT | Send Telegram message to user via bot |
| `GET /api/admin/countries` | JWT | All active countries (for edit dropdowns) |
| `GET /api/admin/reservations` | JWT | Paginated reservations — date, channel, status, search filters + summary bar |
| `GET /api/admin/reservations/{id}` | JWT | Full reservation detail |
| `POST /api/admin/reservations/{id}/no-show` | JWT | Apply no-show penalty (idempotent, score-traced, audit-logged) |
| `GET /api/admin/reservations/export` | JWT | CSV or JSON export, up to 90-day range |
| `GET /api/admin/channels` | JWT | All channels (for filter dropdowns) |

### Implementation phases

| Phase | Status | Scope |
|---|---|---|
| 1 — Auth & scaffold | ✅ Done | JWT auth, login page, protected routes, Docker wiring |
| 2 — User management | ✅ Done | List/search/ban users, inline edit, score adjustment, send Telegram message |
| 3 — Reservations & no-show | ✅ Done | Reservation list with filters, no-show penalty, CSV/JSON export |
| 4 — Schedule events & stats | 🔲 Planned | Inject Dhikr blocks, dashboard stats |

See [`adminpanel.md`](adminpanel.md) for the full API reference and phase tracker.

---

## Security Notes

- Webhook secret token validated on every incoming update
- Non-root Docker user
- No hardcoded secrets — all configuration via environment variables
- SQL injection impossible — SQLAlchemy ORM + parameterized queries only
- Redis slot locks prevent race conditions on concurrent booking
- `SELECT FOR UPDATE NOWAIT` prevents double-booking at the DB level
- Rate limiting and anti-flood on all user interactions
