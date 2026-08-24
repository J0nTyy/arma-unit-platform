# Arma Unit Platform — Project Documentation

Living architecture document. The [README](README.md) covers quickstart/setup;
this file explains how the system is built and why.

**Version 0.4.0 — Phase 3 complete, plus operation-flow overhaul:**
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

## 12. Phase 1–2 reference (unchanged)

GitHub client (Contents + Trees API, typed errors), mission schema (single
pydantic source of truth generating the JSON Schemas), ONE validation
implementation shared by bot/sync/CLI (`python -m tools.validate_mission`),
sync/caching model (index = disposable cache; GitHub = source of truth),
mission-maker workflow docs in the missions repo (`MISSION_MAKER.md`).
