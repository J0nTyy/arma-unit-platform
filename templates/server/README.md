# Server data directory

This folder belongs to **one Discord server** and was created automatically
by the bot. The folder name always ends with the Discord guild ID, so
renaming the server never disconnects its data.

| Folder            | Contents                                                        |
| ----------------- | --------------------------------------------------------------- |
| `config/`         | Server-specific configuration files                             |
| `memory/`         | `memories.md` — readable assistant memory snapshot (generated)  |
| `exports/`        | Dated CSV/XLSX from `/unit export` — never overwritten          |
| `exports/latest/` | Daily "current state" CSV snapshots — regenerated in place      |
| `logs/`           | Server-scoped log output (generated)                            |

- `server.yaml` records the data format version — don't edit it.
- Generated files are safe to delete; the database remains the canonical
  store for members, operations and attendance.
- This directory is private to your deployment and ignored by Git.
