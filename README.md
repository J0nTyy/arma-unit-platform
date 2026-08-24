# Arma Unit Platform

A Discord-based unit management system for an Arma 3 gaming community, built
as a real application rather than a single bot script. Discord is the primary
*interface*; the platform underneath will grow to cover missions, scheduling,
signups, attendance, statistics, qualifications, lore, onboarding, an AI
assistant and Arma server integration.

**Current phase: 3 — Discord UX, channels, operations & attendance.**
Architecture details live in [PROJECT.md](PROJECT.md).

---

## 1. Current capabilities

- **Operations**: schedule a mission as an operation through a guided flow
  (mission picker → date/time modal → preview → publish), polished operation
  posts with live 🟢 Attend / 🟡 Maybe / 🔴 Can't-Attend buttons, rosters,
  FIFO waitlist with automatic promotion, and a staff management panel
  (lock, reschedule, complete, cancel, repost)
- **Automatic reminders**: 24-hour and 1-hour channel reminders mentioning
  confirmed attendees — database-driven, so they survive bot restarts
- **Mission publishing**: post polished mission embeds to the configured
  channel, duplicate-aware (update the existing post instead of reposting),
  auto-refreshed on `/unit sync` when statuses change
- **Server setup UI**: `/unit setup` configures channels, staff/mission-maker
  roles, timezone, unit name and reminders via native select menus — and can
  create the recommended channel set (with confirmation and sensible
  permissions)
- **Mission system** (Phase 2): missions live in a GitHub repository,
  validated against one schema implementation shared by the bot and the
  local CLI (`python -m tools.validate_mission <dir>`)
- Persistent buttons (attendance, briefs, rosters) that keep working after
  restarts; permission checks enforced server-side on every click
- PostgreSQL (SQLAlchemy 2 async + Alembic), structured logging, centralized
  error handling, FastAPI `GET /health`, Docker Compose, 130-test suite

### Commands

Every command and parameter is described in Discord itself; `/help` shows a
curated overview (staff sections appear only for staff).

| Command | What it does | Access |
| --- | --- | --- |
| `/help` | What can this bot do for you? | everyone |
| `/ping` / `/about` | Liveness / what the bot is | everyone |
| `/missions [search] [status]` | Browse missions, drill into details | members |
| `/mission view <mission>` | Mission card + Brief/Objectives buttons | members |
| `/operations` | Upcoming operations, drill in & attend | members |
| `/operation view <operation>` | One operation with attendance buttons | members |
| `/profile` | Your upcoming ops and attendance record | members |
| `/mission publish <mission>` | Publish a mission post (guided) | mission makers |
| `/operation create [mission]` | Schedule an operation (guided) | mission makers |
| `/operation manage` | Lock / reschedule / complete / cancel | staff |
| `/unit setup` | Channels, roles, timezone, reminders | administrators |
| `/unit sync` | Refresh missions from GitHub | staff |
| `/unit diagnostics` | Bot / database / repository health | staff |

## 2. Architecture

```
Discord                       HTTP clients (future: webhooks, telemetry, dashboard)
   ↓                              ↓
Bot commands & events         FastAPI app
   ↓                              ↓
        Application services  (business logic, transactions)
                    ↓
        Repositories          (query logic only)
                    ↓
        Database              (PostgreSQL via SQLAlchemy async)

Integrations (stubs today): GitHub (mission files) · OpenAI (AI assistant) · Arma (gameplay)
```

Rules that keep this maintainable:

- **Commands contain no business logic.** They validate the interaction and
  call a service. Services own transactions and raise typed application
  errors; repositories only build queries.
- **Persistent state lives in the database**, never in Discord messages.
- **External systems live behind integration clients** (`app/integrations/`).
  Nothing else in the codebase makes raw HTTP calls to GitHub/OpenAI/Arma.
- **The bot and API run in one process today** but are independent asyncio
  tasks behind factories, so they can be split into separate
  processes/containers later without a rewrite.

## 3. Requirements

- **Docker path (recommended):** Docker Desktop only.
- **Native path:** Python 3.12+ and a PostgreSQL server (or SQLite for a
  quick spin — see below).

## 4. Local setup

```bash
git clone <this repo>
cd "arma bot"
cp .env.example .env     # then fill in DISCORD_TOKEN and DISCORD_APPLICATION_ID
```

### Option A — Docker (recommended)

```bash
docker compose up --build
```

This starts PostgreSQL, applies database migrations, and runs the bot + API.
The API is available at http://localhost:8000/health.

### Option B — native Python

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -e ".[dev]"

# Point DATABASE_URL at your PostgreSQL, or use SQLite for a quick spin:
#   DATABASE_URL=sqlite+aiosqlite:///./dev.db

alembic upgrade head     # apply database migrations
python -m app.main       # start the bot + API
```

## 5. Environment variables

| Variable                 | Required | Default       | Purpose                                        |
| ------------------------ | -------- | ------------- | ---------------------------------------------- |
| `DISCORD_TOKEN`          | ✅       | —             | Bot token (keep secret)                        |
| `DISCORD_APPLICATION_ID` | ✅       | —             | Application ID from the developer portal       |
| `DATABASE_URL`           | ✅       | —             | Async database URL (see `.env.example`)        |
| `DEV_GUILD_IDS`          | —        | unset         | Comma-separated guild IDs with instant command sync |
| `ENVIRONMENT`            | —        | `development` | `development` / `staging` / `production`      |
| `LOG_LEVEL`              | —        | `INFO`        | Standard Python log level                      |
| `API_ENABLED`            | —        | `true`        | Run the HTTP API alongside the bot             |
| `API_HOST` / `API_PORT`  | —        | `127.0.0.1` / `8000` | API bind address                        |
| `GITHUB_MISSIONS_OWNER`  | for `/mission` | unset  | GitHub user/org owning the missions repo       |
| `GITHUB_MISSIONS_REPOSITORY` | for `/mission` | unset | Missions repository name                    |
| `GITHUB_MISSIONS_BRANCH` | —        | `main`        | Branch the bot reads missions from             |
| `GITHUB_TOKEN`           | private repos | unset    | Fine-grained PAT (contents: read-only)         |
| `OPENAI_API_KEY`         | —        | unset         | Reserved for a future phase (unused)           |

The application fails at startup with a clear message if required values are
missing. Plain `postgresql://` / `sqlite://` URLs are automatically upgraded
to the async drivers the app uses. **Never commit `.env`.**

## 6. Discord application setup

1. Go to https://discord.com/developers/applications and click **New Application**.
2. On **General Information**, copy the **Application ID** → `DISCORD_APPLICATION_ID`.
3. Go to **Bot** → click **Reset Token**, copy the token → `DISCORD_TOKEN`.
   No privileged intents are needed in Phase 1.
4. Invite the bot to your server (replace `YOUR_APP_ID`):

   ```
   https://discord.com/api/oauth2/authorize?client_id=YOUR_APP_ID&scope=bot%20applications.commands&permissions=19456
   ```

   (`19456` = View Channels + Send Messages + Embed Links. To let the bot
   **create the recommended channels** in `/unit setup`, re-invite with
   Manage Channels + Manage Roles included — the setup flow shows the exact
   URL when needed.)
5. For development, copy your server's ID (right-click the server icon with
   Developer Mode enabled) into `DEV_GUILD_IDS` so slash commands appear
   instantly. Multiple servers are supported, comma-separated (e.g.
   `DEV_GUILD_IDS=123,456` for a test server plus your main server). Without
   it, global sync can take up to an hour. The same invite URL works for
   every server — the bot serves many servers at once.

## 6b. Missions repository setup

Missions live in their own GitHub repository. To set it up:

1. Create a new GitHub repository (private is fine), e.g. `unit-missions`.
2. Copy the contents of [missions-repo-template/](missions-repo-template/)
   into it, commit, and push — it includes two example missions, a mission
   template, JSON Schemas for editor IntelliSense, and the mission-maker
   guide (`MISSION_MAKER.md`).
3. Create a **fine-grained personal access token** (GitHub → Settings →
   Developer settings → Fine-grained tokens) scoped to that repository with
   **Contents: Read-only** permission.
4. Fill in `.env`: `GITHUB_MISSIONS_OWNER`, `GITHUB_MISSIONS_REPOSITORY`,
   `GITHUB_TOKEN` (and `GITHUB_MISSIONS_BRANCH` if not `main`).
5. Restart the bot and run `/mission sync` in Discord (requires Manage
   Server), then `/mission list`.

## 7. Database setup

- **Docker:** nothing to do — compose starts PostgreSQL and runs
  `alembic upgrade head` automatically.
- **Native PostgreSQL:** create a database and user, set `DATABASE_URL`, then
  run `alembic upgrade head`.
- **New migrations** (later phases): edit/add models under
  `app/database/models/`, then
  `alembic revision --autogenerate -m "describe change"` and review the
  generated file before applying it.

## 8. Running the bot

| Task              | Command                                     |
| ----------------- | ------------------------------------------- |
| Everything (Docker) | `docker compose up --build`              |
| Bot + API (native)  | `python -m app.main`                     |
| Apply migrations    | `alembic upgrade head`                   |
| Health check        | `curl http://localhost:8000/health`      |

On startup the bot logs its Discord connection, database health, loaded
extensions and how many slash commands were synced. In Discord, verify with
`/ping`, then run `/config setup` (as an administrator) to register the server.

## 9. Running tests

```bash
pip install -e ".[dev]"
pytest
```

Tests run against SQLite and mocked transports — no PostgreSQL, Discord
token, or network access needed.

## 10. Project structure

```
app/
├── bot/                  # Discord interface layer
│   ├── commands/         #   slash commands (general, admin)
│   ├── events/           #   gateway event listeners
│   ├── bot.py            #   UnitBot: wiring + extension loading + command sync
│   ├── permissions.py    #   PermissionLevel + @require() check
│   └── error_handler.py  #   centralized command error handling
├── api/                  # HTTP interface layer (FastAPI)
│   └── routes/           #   /health today; webhooks/telemetry later
├── services/             # business logic, transactions, typed errors
├── database/
│   ├── models/           # SQLAlchemy models (GuildConfiguration)
│   ├── repositories/     # query logic
│   └── database.py       # engine + session factory + health probe
├── integrations/         # boundaries to external systems (stubs in Phase 1)
│   ├── github/           #   future mission-file source of truth
│   ├── openai/           #   future AI assistant (tool-based, no raw DB access)
│   └── arma/             #   future gameplay/server integration
├── config.py             # pydantic-settings; fails fast on bad config
├── logging_config.py     # dev/prod log formats
├── errors.py             # application error hierarchy
└── main.py               # entrypoint: runs bot + API as asyncio tasks

migrations/               # Alembic (async) + initial revision
tests/                    # pytest suite
docker/                   # Dockerfile
docker-compose.yml        # app + PostgreSQL for local development
```

## 11. Planned future phases (not implemented)

None of the following exists yet — the architecture just leaves room for it:

- Structured slot signups (pick Rifleman/Medic/… from slots.json) and squad
  rosters (Phase 4 — design sketch in [PROJECT.md](PROJECT.md))
- Player statistics and qualifications built on attendance history
- After-action reports and campaign progression
- AI-powered unit assistant (via controlled application tools)
- Arma 3 server/gameplay integration and telemetry (incl. objective results)
- GitHub push webhooks for automatic mission sync
- Web dashboard on top of the HTTP API

## 12. Development principles

1. Discord is an interface, not the application.
2. Persistent unit state belongs in the database.
3. GitHub will be the source of truth for version-controlled mission content.
4. The AI assistant will call controlled application tools — never raw SQL.
5. Secure by default: no hardcoded secrets, server-side permission checks,
   validate external input.
6. New features should be new modules/services, not rewrites.
7. No premature complexity — build systems when a phase needs them.
