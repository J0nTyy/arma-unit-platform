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
        │   ├── members_<date>.csv    /unit export output — dated, never
        │   ├── members_<date>.xlsx     overwritten (repeat exports get _2…)
        │   └── latest/*.csv          daily "current state" snapshots
        │                               (regenerated in place)
        └── logs/                     server-scoped logs (generated)
```

Datasets exported: `members`, `operations`, `attendance` (one row per
attendance record — filter/sort friendly), `certifications`, `missions`.
CSVs open directly in Excel/LibreOffice/Google Sheets (UTF-8 with BOM).

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
