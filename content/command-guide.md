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
- **Ask anything:** `/ask <question>` or just @mention the bot.

<!-- STAFF-ONLY BELOW -->

# Staff commands

- **First-time setup:** `/unit setup` — pick a setting from the dropdown
  (channels, roles, timezone, reminders, chatter). "Create recommended
  channels" builds the whole channel set with correct permissions after a
  confirmation step. Set the Trainer role here to enable /training grants.
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
  delete anything wrong or stale there.
- **Health check:** `/unit diagnostics`.
