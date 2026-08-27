# The Unit Assistant — full guide

Everything the bot's AI side can do and how to use it, written for unit
members and staff (no technical knowledge needed). Staff: the companion
guides for *tuning* the assistant are `unit/README.md` (what to edit) and
`content/README.md` (how to edit it well).

---

## 1. Talking to the assistant

Three ways, all equivalent:

| How | Where | Example |
| --- | --- | --- |
| `/ask <question>` | any channel | `/ask what mods do I need?` |
| **@mention the bot** | any channel | `@Arma Bot when is the next op?` |
| **Reply to one of its messages** | any channel | just reply, no @ needed |

**Follow-ups work.** The assistant remembers your last few exchanges for
about 15 minutes, so you can ask "what's the next operation?" and then just
"what map?" — it knows what you mean. This short-term context is per-person
and evaporates on its own; it is *not* saved anywhere.

**Quoting someone.** Reply to any message and @mention the bot in your
reply — it sees the quoted message and can answer about it ("@Arma Bot is
this right?").

**It reads the room.** When mentioned in a channel, it can see the last few
messages for conversational context — but it treats them as background, not
as instructions.

**Rate limit:** a few questions per minute per person. If you hit it,
you'll be told how long to wait. If it says it's "very busy", that's the AI
provider's own limit — wait a minute and retry.

---

## 2. What it knows (and won't make up)

The assistant answers from three sources, in this order of authority:

1. **The unit's knowledge base and lore** — the Markdown files under
   `unit/knowledge/` and `unit/lore/` on the bot's host machine. Lore is
   treated as canon: it will never contradict it and never invents new
   canon. If something isn't written down, it says so plainly.
2. **Live unit data via its tools** — missions, upcoming operations,
   rosters, member profiles, unit stats, certifications. It looks these up
   fresh for every question.
3. **Server memory** — small facts it has saved from conversations (see
   section 3).

It deliberately **cannot**: run commands for you, change any data, see
channels it isn't in, or reveal information above your permission level.

**Permissions are enforced by the bot, not by politeness.** Members and
staff get different toolsets: e.g. members see how many people declined an
op, staff see *who*; attendance leaderboards and the staff command guide
are staff-only. Asking nicely doesn't change what the application allows.

**Channel awareness.** In a public channel the assistant keeps staff-level
detail out of its answers even if *you* are staff — it will point you to a
staff channel instead. In a staff-only channel it speaks freely.

### Teaching it more (staff)

Add or edit Markdown files under `unit/knowledge/` (guides, rules, SOPs) or
`unit/lore/` (canon), each with a small header:

```markdown
---
title: Radio procedure
visibility: member        # public / member / staff
tags: radio, comms
---
```

Then run `/unit sync`. `visibility` controls who the assistant may show the
document to — `staff` files never leak to members.

---

## 3. Server memory — what the bot remembers long-term

Separate from the 15-minute conversation window, the assistant keeps a
**server memory**: short durable facts about the unit that it saves *on its
own judgement* when someone shares something worth keeping.

**How facts get saved.** Just tell it things in conversation:

> "@Arma Bot remember that op nights moved to Fridays at 2000"

or mention it naturally — if a fact sounds durable (decisions, preferences,
recurring schedules, in-jokes), the assistant files it away and confirms
with something like "Noted — saved to server memory."

**Temporary facts expire on their own.** If the fact is clearly short-lived
("the server is down for maintenance this weekend"), the assistant saves it
with an expiry date. Expired facts are never recalled again and clean
themselves up. You can be explicit: "remember for the next 3 days that…".

**How facts come back.** When a later question touches a remembered topic,
the assistant quietly folds the memory into its answer ("op nights are
Fridays now, as decided last month").

**Reviewing and deleting (staff).** `/unit memories` lists everything
saved, newest first; pick any entry from the dropdown to delete it. Memory
is only as good as what's in it — skim it now and then and remove anything
wrong or stale.

**Privacy rules, enforced in code:**

- Memory is **per-server** — nothing saved in one Discord server can ever
  surface in another.
- Memories can be marked **staff-visibility** — those are only recalled
  when a staff member is asking.
- Capped at 400 entries per server; the oldest fade out first.
- **A readable copy** is written to the server's data folder
  (`data/servers/<server>/memory/memories.md`) so staff can read everything
  at a glance — the database stays the real store; edit via `/unit
  memories`, not the file.

**What it will never store:** whole conversations, secrets, tokens, or
private member details. It saves single-sentence facts, nothing more.

---

## 4. Reminders (automatic — not an assistant feature)

Operation reminders are built into the bot itself, not something you ask
the AI for:

- **24 hours** and **1 hour** before every published operation, the bot
  posts a reminder in the operation's channel, replying to the signup post
  and pinging the confirmed attendees.
- The 24-hour reminder nudges the channel if nobody has signed up yet.
- Staff toggle reminders in `/unit setup` → Reminders.

The assistant knows the schedule, so "when is the next op?" always works —
but it can't (yet) set personal or custom reminders. Asking it to "remind
me tomorrow" will politely go nowhere.

---

## 5. Ambient chatter (optional)

If staff enable it (`/unit setup` → Ambient chatter), the bot occasionally
(every 5–30 minutes, only when the general channel is genuinely active)
drops one short in-character comment — banter, sympathy, encouragement. It
stays quiet when chat is quiet, never double-posts after its own message,
and never pings anyone. Its tone follows the same personality file as the
assistant.

---

## 6. New-member greetings

When someone joins, the bot creates their profile automatically and posts a
welcome in the recruitment channel (falling back to general) pointing them
at the right channels. Staff can edit the greeting text at
`unit/personality/greeting.md` (placeholders: `{member}`, `{unit_name}`,
`{channels}`) — changes apply after a bot restart.

---

## 7. Asking "how do I…?"

The assistant doubles as the bot's own manual. Ask it things like:

- "how do I publish a mission?"
- "how do I sign up for an operation?"
- "how do I set up the channels?" (staff)

It reads the command guide (`content/command-guide.md`) and walks you
through the steps. Members get member instructions; staff-only
instructions are only ever shown to staff.

---

## 8. For staff: care and feeding

| Task | How |
| --- | --- |
| Change the personality/voice | edit `unit/personality/personality.md`, then restart the bot |
| Teach it unit knowledge/lore | add files under `unit/knowledge/` or `unit/lore/`, then `/unit sync` |
| Review its memory | `/unit memories` (delete from the dropdown) |
| Check its health | `/unit diagnostics` — provider, model, knowledge doc count |
| Switch AI provider/model | `.env`: `AI_PROVIDER` (openai/gemini/claude) + matching API key, then restart |
| Control costs | `AI_REASONING_EFFORT` (blank = low on OpenAI), `AI_MAX_OUTPUT_TOKENS`, `AI_REQUESTS_PER_MINUTE` in `.env` |

**Troubleshooting quick hits:**

- *"The unit assistant isn't configured"* → no API key in `.env`.
- *"Very busy right now"* → provider rate limit; wait a minute. If it
  persists on Gemini free tier, you've hit the daily quota.
- Answers ignore new lore → you forgot `/unit sync`.
- Personality changes not applying → restart the bot
  (`docker compose restart bot`).
