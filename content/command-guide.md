<!--
  COMMAND GUIDE — the assistant reads this file when someone asks HOW to do
  something with the bot. Edit freely; plain language works best.

  IMPORTANT: everything BELOW the "STAFF-ONLY BELOW" marker is only shown to
  staff. Keep member instructions above it, staff instructions below it.
-->

# Member commands

- **See missions:** `/missions` to browse, `/mission view` for one in detail.
  Buttons on each card open the briefing and objectives.
- **See operations:** `/operations` lists what's coming up. Sign up with the
  🟢 Attend / 🟡 Maybe / 🔴 Can't Attend buttons on the operation post in the
  attendance channel — you can change your answer any time.
- **Your profile:** `/profile`, then the ⚙️ Set up profile button for role
  preferences, timezone, bio and Steam ID.
- **Your certs:** `/training certs` shows what you hold and what you're
  eligible to train for. `/training info` lists all certifications and their
  requirements.
- **Unit stats:** `/stats`.
- **Ask anything:** `/ask <question>`, @mention the bot anywhere, or just
  reply to one of its messages. Follow-up questions work for ~15 minutes
  ("what's the next op?" → "what map?"). Reply to someone's message while
  mentioning the bot and it can answer about that message.
- **Make it remember things:** tell it facts worth keeping — "@mention
  remember op nights moved to Fridays". It saves short durable facts to
  server memory and uses them in later answers. Temporary facts can expire:
  "remember for the next 3 days that the server is down". It never stores
  whole conversations or private details.
- **Operation reminders are automatic** — 24 hours and 1 hour before each
  published operation, posted on the signup post with attendee pings. The
  assistant can tell you the schedule but cannot set personal reminders.

<!-- STAFF-ONLY BELOW -->

# Staff commands

- **First-time setup:** `/unit setup` — pick a setting from the dropdown
  (channels, roles, timezone, reminders, chatter). "Create recommended
  channels" builds the whole channel set with correct permissions, and
  "Create recommended roles" creates Staff / Mission Maker / Trainer /
  Developer roles (no Discord permissions, unassigned) — both after a
  confirmation step. Prefer your own role names? Pick existing roles from
  the dropdown instead. Renaming roles later is always safe: the bot tracks
  IDs, not names. Set the Trainer role to enable /training grants.
- **Content sync:** `/unit sync` after any push to the missions repo —
  refreshes missions, knowledge, and published posts.
- **Publish a mission:** `/mission publish` → pick mission → preview →
  Publish (or Update Existing if it's already posted).
- **Schedule an operation:** `/operation create` → pick mission → enter date
  and time in the popup → preview → Publish. Briefing + images go to the
  brief channel, signup post to attendance, @everyone announcement goes out.
- **Manage an operation:** `/operation manage` → pick it → lock/reopen,
  reschedule, repost, mark active/completed, or cancel. Completed ops
  auto-archive to operation-logs; cancelled ones follow after 24h.
- **Finalize attendance:** `/operation attendance` → pick the operation →
  select each member and press Attended/Absent/Excused, or "All signed-up →
  attended" then fix exceptions. Walk-ons can be added with the user picker.
- **Manage members:** `/members` → pick a member → status, onboarding,
  qualifications. `/members search:<name>` jumps straight to one.
- **Grant certifications:** `/training grant` (needs Trainer role or staff).
- **Bot memory:** `/unit memories` lists what the assistant has remembered;
  delete anything wrong or stale there. A readable copy lives in the
  server's data folder (`memory/memories.md`) — the command is the editor,
  the file is just for reading.
- **Export unit data:** `/unit export` — one Excel workbook (members,
  operations, attendance, certifications, missions as separate sheets),
  attached in Discord and saved on the host. Only the newest 10 exports are
  kept; `exports/latest/` always holds the current state as CSVs.
- **AI spend (developers only):** `/unit usage` — requests, tokens and
  estimated cost for the last 30 days, tracked by the bot itself. Needs the
  Developer role from `/unit setup`; the server owner always has access.
- **Health check:** `/unit diagnostics`.
