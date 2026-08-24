# Arma Unit Platform

A Discord-based unit management system for an Arma 3 gaming community, built
as a real application rather than a single bot script. Discord is the primary
*interface*; the platform underneath will grow to cover missions, scheduling,
signups, attendance, statistics, qualifications, lore, onboarding, an AI
assistant and Arma server integration.

**Current phase: 2 — GitHub mission repository.** Architecture details live
in [PROJECT.md](PROJECT.md).

---

## 1. Current capabilities

- **Mission system**: missions live in a separate GitHub repository
  (structured `mission.json` / `objectives.json` / `slots.json` + Markdown
  briefing), indexed into the database by `/mission sync`, served by
  `/mission list · view · brief · validate · search` with autocomplete
- **One validation implementation** shared by Discord commands, sync, and a
  local CLI (`python -m tools.validate_mission <dir>`) — errors tell mission
  makers exactly what to fix
- Discord bot with slash commands: `/ping`, `/about`, `/status`, and an
  administrator-only `/config setup` / `/config view` group
- Declarative permission levels (public / member / staff / admin) enforced
  server-side on every command
- Centralized command error handling — users get friendly messages, full
  details go to the logs with a reference ID
- PostgreSQL database layer (SQLAlchemy 2 async + Alembic migrations) with a
  working `GuildConfiguration` model so the bot supports multiple servers
- Structured logging (readable in development, JSON in production)
- Minimal HTTP API (`GET /health`) running alongside the bot
- Docker Compose local environment (app + PostgreSQL)
- Test suite (configuration, database, services, API)

### Commands

Every command also shows its description directly in Discord, and `/help`
prints this list in the server.

| Command | What it does | Access |
| --- | --- | --- |
| `/help` | List every command and what it does | everyone |
| `/ping` | Check that the bot is responsive | everyone |
| `/about` | What the bot is, version and environment | everyone |
| `/status` | Bot, Discord and database health | everyone |
| `/mission list [status] [map] [type]` | List missions, optionally filtered | members |
| `/mission view <id>` | Mission details + View Brief / View Objectives buttons | members |
| `/mission brief <id>` | The full mission briefing (long briefs attach as a file) | members |
| `/mission validate <id>` | Check a mission's files against the schema, live from GitHub | members |
| `/mission search <query>` | Search missions by ID, name, map, tags, maker, … | members |
| `/mission sync` | Refresh the mission index from GitHub | staff (Manage Server) |
| `/config setup` | Register this Discord server in the database | administrators |
| `/config view` | Show this server's stored configuration | administrators |

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

   (`19456` = View Channels + Send Messages + Embed Links.)
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

- Operation scheduling, announcements, signups and rosters (Phase 3 —
  design sketch in [PROJECT.md](PROJECT.md))
- Unit member profiles, qualifications and roles
- Attendance tracking and player statistics
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
