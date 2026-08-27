# Arma Unit Platform — Project Documentation

Living architecture document. The [README](README.md) covers quickstart/setup;
this file explains how the system is built and why.

**Version 0.7.0 — Phase 6: the learning assistant & training system.**
Context-aware AI (reads recent chat, quoted messages, reply-to-bot
continuations), server memory (`bot_memories`, AI-curated, staff-pruned via
`/unit memories`), channel-aware answers (real `<#id>` links; staff detail
only in staff channels), opt-in ambient chatter (5–30 min, mood-aware),
`/training` certifications with Discord role sync + trainer role, and a
fully documented editable "brain" in `content/` (see §17).
Phase 5: player profiles, identity & finalized attendance (see §15). Phase 4: AI unit assistant (`/ask`,
provider-switchable OpenAI/Gemini/Claude, tool-based grounding, permission-aware
knowledge base — §13). Phase 3 operation-flow overhaul:
two-field date/time modal (Discord offers bots no calendar/clock widgets), operation names taken from the
mission file, briefings as formatted plain messages with images beneath,
dedicated **#attendance** / **#operation-brief** channels, staff-only
**#operation-logs** archive (completed ops move immediately, cancelled after
24h), @everyone announcements on publish/cancel/reschedule (announcements +
general), and an airier stacked attendance board.

---

## 1. Architecture

```
Discord (commands + buttons/selects/modals)     HTTP clients (future)
   ↓                                                ↓
Bot cogs & persistent UI components             FastAPI app (GET /health)
   ↓                                                ↓
        Application services  (business logic, transactions, typed errors)
             ↓                        ↓
        Repositories             Integrations
             ↓                        ↓
        PostgreSQL               GitHub API   ·   OpenAI (stub)   ·   Arma (stub)
```

Layer rules:

- Cogs and UI views contain no business logic — they call services and render
  results. Services own transactions and typed errors; repositories own queries.
- All GitHub traffic goes through `app/integrations/github/client.py`.
- Domain logic shared across interfaces lives in `app/missions/`.
- Every permission decision is made server-side (`app/bot/permissions.py`),
  including inside button/select callbacks. Discord-side visibility
  (`default_permissions`) is cosmetic only.

## 2. Discord UX philosophy (Phase 3)

Discord should feel like a simple application, not a developer console:

- **Small command vocabulary.** Members: `/missions`, `/operations`,
  `/profile`, `/help` (+ `/mission view`, `/operation view` for deep links).
- **Buttons over commands.** Briefings, objectives, validation, publishing,
  scheduling, attendance, rosters — all buttons on posts, not extra commands.
- **Selects/modals over parameters.** Nothing asks for IDs to be typed:
  mission pickers, channel selects, role selects, date/time modals.
- **No implementation vocabulary.** "sync/index/cache/repository/schema" only
  appear in staff commands (`/unit …`), never in member-facing UI.
- **Persistent buttons.** Attendance/roster/brief/mission buttons are
  discord.py DynamicItems — their state lives in the `custom_id`, so posts
  keep working after bot restarts, forever.

## 3. Command surface

| Command | Access | What it does |
| --- | --- | --- |
| `/help` | everyone | Curated overview; staff sections only shown to staff |
| `/ping`, `/about` | everyone | Liveness / what the bot is |
| `/missions [search] [status]` | member | Browse missions; select menu drills into details |
| `/mission view <mission>` | member | Mission card + Brief · Objectives · (maker: Validate · Publish · Schedule) buttons |
| `/operations` | member | Upcoming operations; select menu drills in (with attend buttons) |
| `/operation view <operation>` | member | One operation card with live attendance buttons |
| `/profile` | member | Upcoming ops + attendance record |
| `/ask <question>` | member | AI unit assistant (grounded in unit data/docs) |
| `/mission publish <mission>` | mission maker | Guided publish: preview → channel → publish/update |
| `/operation create [mission]` | mission maker | Guided scheduling: picker → modal → preview → publish |
| `/operation manage` | staff | Panel: lock/reopen, activate, complete, reschedule, repost, cancel |
| `/unit setup` | admin | Central config hub: channels, roles, timezone, unit name, reminders + channel creation |
| `/unit sync` | staff | Refresh mission index from GitHub + update published posts |
| `/unit diagnostics` | staff | Bot/database/repository/config health |

Removed/renamed from Phase 2: `/mission list|search` → `/missions`;
`/mission brief|validate` → buttons; `/mission sync` → `/unit sync`;
`/status` → `/unit diagnostics`; `/config …` → `/unit setup`.

## 4. Permissions

Five levels, resolved server-side on every command *and* button click
(`resolve_level` is pure and unit-tested):

- `PUBLIC` → anyone
- `MEMBER` → any guild member
- `MISSION_MAKER` → configured Mission Maker role (or anything below)
- `STAFF` → configured Staff role, falling back to Discord's **Manage
  Server** permission when no role is configured
- `ADMIN` → Discord Administrator

Roles are configured in `/unit setup` and stored per guild. `/help` shows
each user only the sections they can use; `default_permissions` additionally
hides `/unit` from non-staff in the Discord UI (cosmetic layer).

## 5. Channel configuration

`GuildConfiguration` stores per-guild channel IDs (operations, missions,
announcements, logs, recruitment, AAR, staff), role IDs, timezone, unit name
and the reminders toggle. Everything is set through `/unit setup` with
Discord's native channel/role select menus — admins never type IDs.

**Create recommended channels**: the setup hub can create the full channel
set after showing a plan and asking for confirmation. Channels that already
exist (by configured ID or by default name) are reused, never duplicated.
Each created channel gets a topic explaining its purpose. Requires the bot
to have Manage Channels + Manage Roles (the setup flow surfaces a re-invite
URL if missing).

| Channel | Purpose | Who can post | What the bot does there |
| --- | --- | --- | --- |
| `#attendance` | Signup posts | bot (members read) | The signup post with attendance buttons, reminders, waitlist promotions; cleaned up after archiving |
| `#operation-brief` | Briefings | bot (members read) | Formatted briefing messages + mission images for posted operations |
| `#operation-logs` | Staff archive | staff only | Final attendance board of completed/cancelled operations |
| `#operations` | Ops chatter | everyone reads, members chat | Nothing automated — kept free for discussion |
| `#missions` | Mission library | bot (members read) | Published mission cards with Brief/Objectives/Schedule buttons, refreshed on `/unit sync` |
| `#announcements` | Unit-wide announcements | bot + staff | @everyone notices when operations are posted/cancelled/rescheduled |
| General (existing chat) | Server general | everyone | Mirror of operation announcements (configured in setup; falls back to the system channel) |
| `#recruitment` | New-player info | everyone | Reserved for future onboarding features |
| `#after-action-reports` | AARs for completed ops | bot (members read) | Reserved for the future AAR system |
| `#bot-logs` | Bot activity log | staff only | Reserved for staff-visible bot event logging |
| `#staff` | Staff coordination | staff only | Reserved for staff notifications (e.g. review requests) |

## 6. Operations & attendance model

```
GitHub mission  →  mission index row  →  Operation (scheduled instance)
                                             ↓
                                        OperationAttendance (per member)
                                             ↓
                                        Discord post (channel_id/message_id)
```

- `operations`: guild, mission_id (content never duplicated), name, UTC
  `scheduled_at` + the IANA timezone it was scheduled in, server name,
  `max_players`, status, creator, post reference, an objectives snapshot
  (rendered at creation so posts rebuild without GitHub calls), and reminder
  bookkeeping.
- `operation_attendance`: one row per member per operation
  (unique constraint), status `attending / maybe / declined / waitlist`,
  display name captured at click time, waitlist entry timestamp.
- `mission_publications`: which mission is published as which message
  (unique per guild+mission+channel) so publishing updates instead of
  duplicating.

### Lifecycle

`draft → scheduled → open ⇄ locked → active → completed`, with `cancelled`
reachable from every non-terminal state. Transitions are validated by a
whitelist in the service layer — `completed → open`, `cancelled → active`
etc. are impossible. Operations auto-flip to `active` at start time (via the
scheduler). Archived missions can't be scheduled unless staff explicitly
allow it.

### Attendance & waitlist

Buttons, not reactions. Clicking Attend/Maybe/Can't-Attend upserts the
member's single row, then the post's embed is rebuilt in place (never a new
message). The post shows a **three-column attendance board** — Attending /
Maybe / Can't attend — listing each respondent as a mention.

Operations have **no member limit by default** (`max_players` is NULL). The
FIFO waitlist-and-promotion rules stay implemented in the service layer and
engage automatically if a capacity is ever set again. All rules live in
`OperationService.set_attendance` + `_reconcile_waitlist`, so the policy can
change without touching UI code.

### Operation publishing layout

Scheduling: mission select → a **two-field modal** (date + time — Discord's
bot API has no calendar or clock widgets, and a button-built calendar is
impossible at 5 buttons per row) → preview → publish. The operation name
always comes from the mission file on GitHub.

Publishing then posts to **two channels**: the full briefing goes to
`#operation-brief` as formatted plain messages (Discord renders the
headings; sections get themed emoji; *Notes for Mission Makers* is omitted)
with `images/` files attached beneath, and the signup post goes to
`#attendance`. An @everyone announcement lands in the announcements channel
and the configured general channel. Cancel/reschedule announce the same way.

### Post archiving

Signup and briefing posts don't pile up: when an operation is **completed**
its posts are immediately re-logged to the staff-only `#operation-logs`
(final attendance board) and deleted from the live channels; **cancelled**
operations stay visible for 24 hours first. Reschedules edit the existing
post in place, so there is nothing stale to archive. Archiving is driven by
the same database-backed scheduler as reminders and survives restarts.

## 7. Reminders

Database-driven, restart-proof: each operation stores
`reminder_24h_sent_at` / `reminder_1h_sent_at`. A 60-second scheduler loop
asks the service "what is due now?" — the service marks and returns due
reminders; the cog posts them in the operations channel as replies to the
operation post, mentioning confirmed attendees. Design points:

- Bot down through a window → reminder sends on next tick (still before
  start); bot down past start → skipped, never sent late.
- Operations created inside a window (e.g. 2h before start) skip the stale
  24h reminder but still get the 1h one.
- Rescheduling resets both flags so the new time gets fresh reminders.
- Per-guild toggle in `/unit setup`; timezone is respected (all math in UTC,
  display via Discord's local timestamps).

## 8. Mission publishing

`/mission publish` (or the Publish button on `/mission view`): preview embed
→ optional channel change (defaults to the configured missions channel) →
publish. The message reference is recorded; publishing the same mission
again offers **Update Existing / Publish Another / Cancel**. `/unit sync`
re-renders every published post afterwards, so status changes
(🟡 development → 🟢 ready …) appear on existing posts without new messages.
Published mission posts carry Brief / Objectives / Schedule-Operation
buttons (schedule is maker-gated at click time).

## 9. Database changes (migration 0003)

- 0003: `guild_configurations` + unit_name, timezone, reminders_enabled,
  staff_role_id, mission_maker_role_id, 7 channel ID columns; new
  `operations`, `operation_attendance` (FK, cascade delete),
  `mission_publications`
- 0004: mission player limits and `required_mods` dropped from the index;
  `operations.max_players` becomes nullable (NULL = no member limit)
- 0005: guild channels for attendance/briefing/operation-logs/general;
  operation archiving state (cancelled_at, archived_at, brief message refs)

## 10. Known limitations

- Roster shows flat lists (no squad assignment yet — that's the Phase 4+
  signup/roster system).
- Reminder delivery is channel-post only (chosen design); DMs could be added
  as a per-user preference later.
- The ephemeral flows (setup hub, create flow, manage panel) time out after
  10–15 minutes — re-run the command; only the *persistent* post buttons
  survive restarts by design.
- One operation post per operation; reposting re-points the operation at the
  new message.
- Waitlist promotions announce in-channel but don't DM the promoted member.
- `/operations` hides `scheduled`-but-never-published operations from
  members until published.

## 11. Recommended next phase (Phase 4)

Signup rosters & structured slotting on top of attendance: pick an actual
slot (`Rifleman`, `Medic`, …) from the mission's `slots.json`, squad
assignment view, attendance history → player statistics, and AAR posting
into the configured AAR channel. After that: Arma telemetry ingest via the
existing FastAPI app (objective results keyed to objective IDs).

## 13. AI unit assistant (Phase 4)

### Architecture

```
/ask or @mention → rate limit → permission level resolved by the app
      → AssistantService (personality + short memory)
      → model ⇄ Tool Registry ⇄ Application Services   (bounded loop, ≤4 rounds)
      → grounded answer
```

Never a raw passthrough: the model only sees what approved tools return, run
at the requester's permission level. No SQL, no writes, no secrets — this
phase is strictly read-only.

### Provider switching

Two clients live in `app/integrations/ai/`, both speaking the same interface
(`chat(messages, tools) -> AIResponse`): an OpenAI-compatible one for
`AI_PROVIDER=openai` (OPENAI_API_KEY, default `gpt-5-mini`) and `gemini`
(GEMINI_API_KEY via Google's compatibility endpoint, default
`gemini-flash-latest`), and a Claude one on the official Anthropic SDK for
`AI_PROVIDER=claude` (ANTHROPIC_API_KEY, default `claude-opus-4-8`) — Claude's
wire format differs, so `claude.py` translates the shared OpenAI-style
transcript at the edge. `AI_MODEL`/`AI_BASE_URL` override anything.
Without a key the bot runs normally and `/ask` explains what's missing.

### Tools (all member-level, read-only)

`get_unit_information` · `search_knowledge` · `search_missions` ·
`get_mission` · `get_mission_briefing` · `get_upcoming_operations` ·
`get_operation` · `get_operation_roster`. The registry enforces
authorization per tool and filters knowledge by the caller's tier; e.g.
members get declined *counts* in rosters, staff get names.

### Knowledge base

Local Markdown files under `unit/knowledge/` and `unit/lore/` (private to
the deployment — the missions repo holds mission content only), frontmatter
(`title` / `visibility: public|member|staff` / `tags`), indexed into the
`knowledge_documents` table at startup and by `/unit sync` (validation
failures reported, never fatal). Retrieval is keyword scoring per `##`
section with visibility filtering *before* scoring — an interface a future
vector search can replace without touching the AI service. Staff guides:
the READMEs inside those folders.

### Personality

`content/personality.md` — tone plus non-negotiable grounding rules
(answer from tools only, admit gaps, no invented lore/policies, no
impersonation, no internal details). Editable without code changes;
missing file falls back to a safe built-in.

### Interaction & limits

`/ask <question>` anywhere (member+); **@mention questions work in any
channel** — the bot only ever reacts when explicitly mentioned, never to
ordinary conversation (`#ask-the-unit` remains the suggested home for
longer back-and-forth). The persona ("Sarge", a veteran NCO voice with
Discord-native reply formatting) lives in `content/personality.md`;
the new-member greeting template lives in `content/greeting.md`
(placeholders: `{member}` `{unit_name}` `{channels}`) and posts to the
recruitment channel (fallback: general/system) on member join.
Per-user sliding rate limit (`AI_REQUESTS_PER_MINUTE`, default 4). Short
per-user conversation memory (3 exchanges, 15 min TTL, in-memory only).
Logs record model/duration/tokens/tool names — never question or answer
text. Migration 0006.

### Known limitations

Keyword retrieval (no semantic search yet); memory is per-user, not
per-thread; answers cap at ~3 Discord messages.

## 15. Players, identity & finalized attendance (Phase 5)

### Identity model

A **Player** is the persistent unit profile behind a **Discord member** —
one profile per Discord user per guild (multi-guild safe), with optional
**Steam identity** (SteamID64, format-validated, set by the member in the
setup flow — never auto-trusted). Profiles are created lazily on first
interaction and automatically on server join (requires the **Server Members
Intent** — the bot logs precise instructions if it's missing). When someone
leaves Discord, nothing is deleted: `left_at` is stamped and all operational
history stays intact; rejoin clears it.

### Attendance lifecycle

```
Signup (buttons)  →  Staff finalization (/operation attendance)  →
Attendance record (audited)  →  Statistics (/profile, /stats)
```

Signup rows are never overwritten — the authoritative verdict
(attended / absent / excused) lives in `attendance_records`, and every
finalization or correction writes an `attendance_audits` row (previous
status, new status, who, when). Statistics are always derived from records,
never counters. Rate = attended / (attended + absent); excused doesn't
count against anyone. Only active/completed operations can be finalized;
walk-ons (attended without signing up) are supported via a user picker.

### Visibility policy (the "minimal" model)

- **Own profile:** everything — preferences, Steam link, participation
  stats, recent history.
- **Other members:** name, status, member-since, roles, experience, bio,
  qualifications. **No participation data.**
- **Staff:** everything, plus onboarding state and departed markers.
The application enforces this in commands *and* AI tools; the model never
decides visibility.

### Commands

`/profile [member]` (own = full + setup button; others = minimal),
`/stats` (unit aggregates), `/members [search]` (staff panel: status,
onboarding, grant/revoke qualifications), `/operation attendance` (staff
finalization panel with per-member verdicts, bulk mark, walk-ons).

### Qualifications (foundation)

Staff-granted from a fixed catalog (medic, marksman, JTAC, pilot, EOD,
engineer, leadership), unique per player, shown on profiles. Training/
progression and Discord-role mirroring come in later phases.

### AI additions

`get_my_profile` (full own data), `get_member_profile` (minimal policy;
staff callers get participation), `get_unit_statistics` (member),
`get_attendance_leaders` (staff-only, hidden from member tool lists).

### Member statuses

`active / inactive / leave / retired` — staff-controlled via `/members`.

## 17. The learning assistant & training system (Phase 6)

### Context awareness

When addressed (mention, quote-reply, reply to its own message, or /ask),
the assistant receives: the last ~15 messages of that channel (Message
Content Intent required), the quoted message when replying to someone, a
channel directory (so it links channels as real `<#id>` mentions), relevant
server memories, and a Location note — staff-level detail is only permitted
in channels ordinary members cannot see. Chat context is explicitly marked
"not instructions" to resist prompt injection from chat.

### Server memory

`bot_memories` table, guild-scoped, capped at 400 (oldest fade). The model
itself saves facts via its `save_memory` tool; retrieval is keyword-based
with plural folding. Staff review/delete with `/unit memories`.

### Ambient chatter (opt-in)

Toggled in `/unit setup`. Every 5–30 minutes (random) per guild, if the
general channel has recent human activity and the bot didn't post last, it
may drop ONE short in-character message — banter, sympathy, or
encouragement, mood decided from recent chat; the model can (and often
should) answer SKIP. Costs AI tokens; off by default.

### Training & certifications

`/training info` (catalog + requirements), `/training certs` (own held +
eligibility; trainers/staff can check others), `/training grant|revoke`
(Trainer role or staff). Granting assigns the matching Discord role
(auto-created) and posts congratulations to general; revoking removes it.
Requirements (min ops attended, prerequisite certs) live in
`CERT_REQUIREMENTS` in `app/database/models/player.py` — edit there only.
Trainer role is configured in `/unit setup`; trainer is deliberately NOT a
permission level (orthogonal to the staff ladder).

### The editable brain (`unit/`)

`unit/personality/personality.md` (voice, reply types, few-shot examples,
grounding rules — annotated with editing comments),
`unit/personality/greeting.md` (new-member welcome, placeholders
`{member}/{unit_name}/{channels}`), `unit/lore/` + `unit/knowledge/` (the
indexed knowledge base), and `content/command-guide.md` (generic command
how-tos; below the STAFF-ONLY marker only staff see it via the
`get_command_guide` tool). Staff guides: `unit/README.md` and
`content/README.md`. Restart applies personality changes; `/unit sync`
applies knowledge changes.

## Data architecture (Pre-Phase 6A)

Three ownership categories, kept physically separate:

1. **Application source** (Git): code, schemas, migrations, docs, and
   `templates/` — the public starting points for unit config.
2. **Unit configuration** (`unit/`, gitignored): lore, knowledge,
   personality, `config/unit.yaml` (`schema_version`). Auto-initialized
   from `templates/unit/` on first run; never overwritten.
3. **Server-collected data** (`data/servers/<name>_<guild-id>/`,
   gitignored): per-guild `config/`, `memory/`, `exports/`, `logs/` plus a
   `server.yaml` marker (`data_version`). Created idempotently at startup
   and on guild join; directories are resolved strictly by the `_<guild-id>`
   suffix (`ServerDataService` in `app/services/server_data.py`), so guild
   renames never orphan data and one guild can never read another's folder.

The **database stays canonical** for relational data (players, operations,
attendance, memory); server folders hold configuration and generated
human-readable snapshots/exports. Both `unit/` and `data/` are
volume-mounted in docker-compose so they survive image rebuilds.

## 18. Phase 1–2 reference (unchanged)

GitHub client (Contents + Trees API, typed errors), mission schema (single
pydantic source of truth generating the JSON Schemas), ONE validation
implementation shared by bot/sync/CLI (`python -m tools.validate_mission`),
sync/caching model (index = disposable cache; GitHub = source of truth),
mission-maker workflow docs in the missions repo (`MISSION_MAKER.md`).
