# Unit Missions Repository

Version-controlled source of truth for all unit missions. The Discord bot
indexes this repository and serves mission information via `/mission`
commands; mission makers work here with Git + VS Code.

**Making a mission? Read [MISSION_MAKER.md](MISSION_MAKER.md).**

## Structure

```
active/                  # missions in rotation or in progress
  OP-001-blackout/
    mission.json         # structured metadata (validated against schema/)
    brief.md             # human-readable briefing
    objectives.json      # structured objectives (telemetry-ready IDs)
    slots.json           # intended player composition
archived/                # retired missions, kept for history
templates/
  mission-template/      # copy this to start a new mission
schema/                  # JSON Schemas (generated — do not edit by hand)
```

## Mission lifecycle (`status` in mission.json)

| Status        | Meaning                                                    |
| ------------- | ---------------------------------------------------------- |
| `draft`       | Idea/skeleton; files may be incomplete; not playable       |
| `development` | Actively being built by the mission maker                  |
| `review`      | Content-complete; awaiting staff review / test session     |
| `ready`       | Approved and playable; can be scheduled as an operation    |
| `archived`    | Retired from rotation; folder moves to `archived/`         |

## Conventions

- Folder names start with the mission ID: `active/OP-001-blackout/`
- Mission IDs are unique forever and never reused
- Structured data in JSON; prose in `brief.md`
- Bump `version` when the mission changes meaningfully

Opening this folder in VS Code gives you live validation of the JSON files
(configured in `.vscode/settings.json` against `schema/`).
