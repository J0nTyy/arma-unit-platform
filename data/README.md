# `data/` — server-generated data

The bot creates one isolated directory per Discord server under
`data/servers/`. Only this README is tracked by Git — everything else here
is generated at runtime, private to your deployment, and never committed.

```
data/
└── servers/
    └── <server-name>_<guild-id>/     e.g. 42nd-Ridgeway_1541469876...
        ├── server.yaml               data format version — don't edit
        ├── config/                   server-specific configuration
        ├── memory/
        │   └── memories.md           assistant memory, readable (regenerated)
        ├── exports/
        │   ├── unit-data_<date>.xlsx /unit export — ONE workbook, one sheet
        │   │                           per dataset; only the newest 10 kept
        │   └── latest/*.csv          "current state" snapshots, regenerated
        │                               in place (daily + on every export)
        └── logs/                     server-scoped logs (generated)
```

Datasets: `members`, `operations`, `attendance` (one row per attendance
record — filter/sort friendly), `certifications`, `missions`. The workbook
keeps dated history for "how it looked that day"; `latest/` is always the
current state as CSVs (UTF-8 with BOM — they open directly in
Excel/LibreOffice/Google Sheets). File count stays bounded: at most 10
workbooks + 5 latest CSVs + memories.md per server.

Rules of the road:

- **The database is canonical** for members, operations, attendance and
  assistant memory. Files under `exports/` and `memory/` are generated,
  human-readable snapshots — safe to open in Excel, safe to delete.
- The directory name always ends with the **guild ID**; renaming the
  Discord server never disconnects its data. The bot resolves directories
  strictly by that ID, so one server can never read another's folder.
- Directories are created automatically when the bot starts or joins a
  server. Nothing here is ever overwritten by the bot's own startup.
- **No secrets live here** — tokens and API keys belong in `.env` only.
