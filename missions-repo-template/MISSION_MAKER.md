# Mission Maker Guide

This repository holds every mission for the unit. You edit files here; the
Discord bot reads them and shows them to everyone with `/mission` commands.
You do **not** need to be a programmer — if you can edit text files, you can
make missions.

## 1. Get the repository

Install [Git](https://git-scm.com/downloads) and [VS Code](https://code.visualstudio.com/),
then in a terminal:

```
git clone <URL of this repository>
```

Open the cloned folder in VS Code (*File → Open Folder*). VS Code will
automatically check your JSON files against the unit's schema as you type —
mistakes get red squiggles.

## 2. Create a mission from the template

Copy the folder `templates/mission-template/` into `active/` and rename it
to your mission ID plus a short name:

```
active/OP-003-thunder-road/
```

The folder name must start with your mission ID.

## 3. Choose a mission ID

Format: 2–6 capital letters, a dash, and a number — e.g. `OP-003`.
Look at the existing folders in `active/` and `archived/` and take the next
free number. IDs must be unique across the whole repository and never reused.

## 4. Edit the metadata (`mission.json`)

Fill in every field. The important rules:

- `status` starts as `draft`, and moves through `development` → `review` →
  `ready` as your mission matures (staff set it to `ready` after review).
  `archived` is for retired missions.
- `difficulty` is one of: `easy`, `standard`, `hard`, `veteran`.
- `description` is one or two sentences — the long story goes in `brief.md`.
- `version` is `major.minor.patch`, e.g. `0.1.0`. Bump it when you change
  the mission meaningfully.

You do **not** list player counts or required mods — the unit has no member
limit and runs a standard modset.

**Don't worry about Discord formatting.** You write plain Markdown and JSON;
the bot turns it into polished Discord posts (sections, emoji, layout) when
a mission is published or scheduled.

## 5. Write the briefing (`brief.md`)

Plain Markdown, starting with `# Your Operation Name`. The template gives
you sections (Situation, Mission, Execution, …) — delete the ones you don't
need. This is the document players actually read, so write for them.

## 6. Define objectives (`objectives.json`)

Each objective needs a stable ID (`OBJ-01`, `OBJ-02`, …), a name, a short
description, a `type` (`primary` / `secondary` / `optional`) and whether it
is `required` for mission success. Every mission should have at least one
primary objective. IDs must be unique within the mission — the Arma server
will later report results against them, so don't rename them after a
mission has been played.

## 7. Define slots (`slots.json`)

Describe the intended player composition: categories (Command, Infantry,
Support, …) containing roles with a count. This is planning information for
players and future signup systems — there is no hard player limit.

## 7b. Add images and files (optional)

Create an `images/` folder inside your mission and drop in anything players
should see with the briefing — AO maps, plans, screenshots:

```
active/OP-003-thunder-road/
    images/
        ao-map.png
        assault-plan.jpg
```

When your mission is scheduled as an operation, the bot posts these files in
Discord together with the briefing, right above the signup post. Keep files
under 8 MB each; the first ~9 files are posted.

## 8. Validate before pushing

If you have the platform repository set up (optional — ask staff), run:

```
python -m tools.validate_mission active/OP-003-thunder-road
```

Otherwise just push (step 9) and run `/mission validate OP-003` in Discord —
it performs exactly the same checks and tells you precisely what to fix.

## 9. Commit and push

```
git add active/OP-003-thunder-road
git commit -m "OP-003 Thunder Road: initial draft"
git push
```

## 10. Make the bot see it

In Discord, ask a staff member to run `/mission sync` (or run it yourself if
you have the Manage Server permission). Your mission then appears in
`/mission list`, and anyone can read it with `/mission view OP-003`.
Run `/mission validate OP-003` and fix anything it flags — a mission must
validate clean before staff will move it to `review`.
