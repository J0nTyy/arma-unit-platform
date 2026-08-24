# Arma Unit Platform — Project Documentation

Living architecture document. The [README](README.md) covers quickstart/setup;
this file explains how the system is built and why.

**Version 0.2.0 — Phase 2 (GitHub mission repository) complete.**
(This file was created in Phase 2; Phase 1's documentation lived in the README.)

---

## 1. Architecture

```
Discord                          HTTP clients (future: webhooks, telemetry, dashboard)
   ↓                                 ↓
Bot commands & events            FastAPI app (GET /health)
   ↓                                 ↓
        Application services  (business logic, transactions, typed errors)
             ↓                        ↓
        Repositories             Integrations
             ↓                        ↓
        PostgreSQL               GitHub API   ·   OpenAI (stub)   ·   Arma (stub)
        (unit state,             (mission content —
         mission index)           source of truth)
```

Layer rules (enforced by convention, checked in review):

- Discord commands contain no business logic; they call services and format
  the results (`app/bot/commands/`).
- Services own database transactions and translate infrastructure failures
  into typed `AppError`s with user-safe messages (`app/services/`).
- Repositories contain query logic only (`app/database/repositories/`).
- All GitHub HTTP traffic goes through `app/integrations/github/client.py`.
  Nothing else in the codebase calls the GitHub API.
- Domain logic that must be shared across interfaces lives in `app/missions/`
  (schema models + validation) — used identically by the bot, the sync
  indexer, and the local CLI validator.

## 2. GitHub integration

`GitHubClient` (httpx) is a thin transport layer over two endpoints:

- **Contents API** — fetch one file's text (base64-decoded)
- **Git Trees API** (`?recursive=1`) — list every path in the repo in a
  single request; this is how missions are discovered without N API calls

Auth is a fine-grained PAT (`GITHUB_TOKEN`) with read-only access to the
missions repository's contents. Public repos work without a token but are
rate-limited to 60 requests/hour. Failures map to typed errors:
`GitHubFileNotFoundError` (missing path) and `GitHubUnavailableError`
(network/5xx/auth/rate-limit), which the central Discord error handler turns
into friendly messages.

## 3. Mission repository structure

A **separate Git repository** (create it from `missions-repo-template/`):

```
active/<MISSION-ID>-short-name/     # missions in rotation or in progress
    mission.json                    # structured metadata (schema-validated)
    brief.md                        # human-readable briefing (Markdown)
    objectives.json                 # structured objectives, telemetry-ready IDs
    slots.json                      # intended player composition
archived/                           # retired missions
templates/mission-template/         # starting point for new missions
schema/*.schema.json                # generated JSON Schemas (editor IntelliSense)
.vscode/settings.json               # wires the schemas into VS Code
```

Principles: **structured data in JSON, prose in Markdown**; folder names
start with the mission ID; IDs are unique forever.

## 4. Mission schema

Defined once, in pydantic models (`app/missions/models.py`). The JSON Schema
files in the missions repo are **generated** from these models via
`python -m tools.export_mission_schema` — regenerate and commit them to the
missions repo whenever the models change.

`mission.json` fields: `id` (`OP-001` style, `^[A-Z]{2,6}-\d{2,4}$`), `name`,
`status`, `mission_maker`, `description` (≤ 500 chars — prose goes in
brief.md), `map`, `mission_type` (free text), `difficulty`
(easy/standard/hard/veteran), `minimum_players`/`maximum_players`,
`estimated_duration_minutes`, `factions[]`, `required_mods[]`, `tags[]`
(normalized lowercase), `version` (semver). Unknown keys are **rejected**
(catches typos); a `$schema` key is tolerated for editor support.
Enum-ish strings are case-insensitive on input.

`objectives.json`: array of `{id, name, description, type
(primary/secondary/optional), required}`. IDs unique per mission — they are
the stable keys Arma telemetry will later report against.

`slots.json`: `{categories: [{name, slots: [{role, count}]}]}` — generic on
purpose; different makers structure compositions differently.

## 5. Mission lifecycle

| Status        | Meaning                                                  |
| ------------- | -------------------------------------------------------- |
| `draft`       | Idea/skeleton; may be incomplete; not playable            |
| `development` | Actively being built                                      |
| `review`      | Content-complete; awaiting staff review / test session    |
| `ready`       | Approved and playable; schedulable as an operation        |
| `archived`    | Retired; folder moves to `archived/`                      |

The status lives in `mission.json` (source of truth: Git). Status/location
mismatches (e.g. `ready` mission in `archived/`) are validation warnings.

## 6. Sync & caching model

```
GitHub  --/mission sync-->  mission index (DB table `missions`)  -->  list/search/view
GitHub  ---------------- live fetch ---------------------------->  brief/objectives/validate
```

- `/mission sync` (staff): one Trees API call to discover mission
  directories, four file fetches per mission, full validation, then an
  index upsert + removal of entries whose missions left the repo.
  Missions with unparseable `mission.json` are reported in the sync summary
  but not indexed; parseable-but-invalid missions are indexed with
  `is_valid=false` and their errors stored.
- **Reads are cache-first**: list/search/view never touch GitHub, so they
  keep working during a GitHub outage. Every listing shows "index last
  synced <relative time>" so staleness is visible.
- **Live operations**: `/mission brief` and `/mission validate` always fetch
  current repository content (a mission maker validating their just-pushed
  fix must see the truth, not the cache).
- The index is disposable — GitHub remains the single source of truth, and
  a sync fully reconciles the index against it.

## 7. Validation

One implementation: `app.missions.validation.validate_mission_files()`,
operating on file *content* so it is transport-agnostic. Consumers:

1. `/mission validate <id>` — content fetched from GitHub
2. `/mission sync` — validates every mission while indexing
3. `python -m tools.validate_mission <dir>` — content read from a local clone

Checks: required files present (mission.json, brief.md, objectives.json,
slots.json), JSON parses, schema-valid (including enum values, player-range
sanity, semver, duplicate objective IDs, duplicate slot categories), plus
cross-file checks. **Errors** fail validation; **warnings** don't (slot total
≠ maximum_players, directory name not starting with the mission ID,
status/location mismatch, very short brief, no primary objective).

## 8. Discord commands

| Command | Access | Data source |
| --- | --- | --- |
| `/help` | public | command tree (built dynamically) |
| `/mission list [status] [map] [type]` | member | index |
| `/mission view <id>` (+ View Brief / View Objectives buttons) | member | index (+ live fetch on buttons) |
| `/mission brief <id>` | member | live |
| `/mission validate <id>` | member | live |
| `/mission search <query>` | member | index |
| `/mission sync` | staff (Manage Server) | GitHub → index |
| `/ping`, `/about`, `/status` | public | — |
| `/config setup`, `/config view` | admin | database |

Every command and parameter carries a description shown in Discord's UI;
a registry test (`tests/test_command_registry.py`) fails the build if a
command is added without one. `/help` builds its output from the command
tree at runtime, so new commands appear in it automatically, tagged with
their permission level (via `require()` metadata).

Mission ID parameters autocomplete from the index. Long briefings are sent
as a preview + attached `.md` file (Discord's 4096-char embed limit).
Buttons expire after 10 minutes or a bot restart (non-persistent views).

## 9. Environment variables

Everything from Phase 1, plus:

| Variable | Required | Purpose |
| --- | --- | --- |
| `GITHUB_MISSIONS_OWNER` | for /mission | GitHub user/org owning the missions repo |
| `GITHUB_MISSIONS_REPOSITORY` | for /mission | Missions repository name |
| `GITHUB_MISSIONS_BRANCH` | no (default `main`) | Branch to read |
| `GITHUB_TOKEN` | private repos | Fine-grained PAT, contents read-only |

When unset, the bot starts normally and `/mission` commands explain what an
administrator must configure.

## 10. Mission-maker workflow

Documented for makers in the missions repo's `MISSION_MAKER.md`. Summary:
clone → copy `templates/mission-template/` to `active/OP-xxx-name/` → edit
in VS Code (live schema IntelliSense) → validate (local CLI or push +
`/mission validate`) → commit/push → staff run `/mission sync`.

## 11. Known limitations

- **Manual sync**: changes appear only after `/mission sync` (webhook design
  below is the planned fix). The index shows its age in listings.
- Search is in-Python substring matching over the index — fine for a unit's
  mission count (tens to low hundreds), not for thousands.
- `/mission view` buttons are non-persistent (die on restart/timeout).
- Local CLI validation requires the platform repo checked out; makers
  without it use `/mission validate` in Discord instead (same checks).
- Unauthenticated GitHub access is limited to 60 requests/hour — set
  GITHUB_TOKEN even for public repos.
- Images in mission folders are ignored by the bot for now.

## 12. Webhooks (deferred by design)

Recommended future design: GitHub push webhook → `POST /webhooks/github` on
the existing FastAPI app (HMAC signature verification with a shared secret)
→ debounce a few seconds → run the same `MissionService.sync()` →
announce changed missions in a configured Discord channel. Deferred because
it requires a publicly reachable HTTPS endpoint, which the current
laptop/Docker deployment doesn't have; `/mission sync` covers the need until
the bot moves to a VPS.

## 13. Recommended next phase (Phase 3)

Operation scheduling on top of the mission index:

- `operations` table referencing `mission_id` (never duplicating mission
  content) + scheduled datetime, host, state machine (announced → locked →
  completed/cancelled)
- `/operation schedule <mission_id> <datetime>` (staff), `/operation list`
- Automated announcement posts in a configured channel, built from the
  mission index + brief
- Guild configuration extension: announcement channel ID, staff role ID
  (replacing the Manage-Server-permission heuristic in `PermissionLevel`)
- Groundwork for signups (Phase 4): stable operation IDs and announcement
  message references

## 14. Project structure (delta from Phase 1)

```
app/
├── missions/              # NEW: domain — schema models + single validation impl
├── bot/commands/missions.py   # NEW: /mission command group
├── services/missions.py       # NEW: sync/list/search/brief/validate logic
├── database/models/mission.py         # NEW: mission index table
├── database/repositories/missions.py  # NEW
├── integrations/github/client.py      # now a real httpx client (was stub)
tools/
├── validate_mission.py    # NEW: local CLI validator (same validation impl)
└── export_mission_schema.py  # NEW: regenerates JSON Schemas from models
missions-repo-template/    # NEW: push this to a new GitHub repo (see README)
migrations/versions/0002_mission_index.py  # NEW
```
