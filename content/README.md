# The bot's brain — how to teach and tune it

Everything that shapes how the bot talks and what it knows lives in plain
text files. No coding needed for any of this.

> **Moved in v0.10:** the private files (personality, greeting, lore,
> knowledge) now live under **`unit/`** — see `unit/README.md`. This folder
> keeps only generic, public app content.

## The three layers (edit in this order of impact)

| What you want to change | Where | Applies |
| --- | --- | --- |
| **Voice & character** — how it talks, jokes, signs off | `unit/personality/personality.md` | after bot restart |
| **Style knobs** — humour level, formality, reply length | `unit/config/unit.yaml` → `personality:` | after bot restart |
| **What it knows about the unit** — rules, lore, guides, SOPs | `unit/knowledge/` and `unit/lore/` | after `/unit sync` |
| **What it remembers from chat** — small facts it picked up | saved automatically; review with `/unit memories` | instantly |

Other editable files:

- `unit/messages/*.yaml` — the varied bot messages (new-member greetings,
  announcement flavor lines, cert congratulations). Shipped defaults live
  in `content/messages/`; putting the same key in `unit/messages/`
  replaces it. `witty` variants only fire at humour `medium`/`high`.
  Serious messages (errors, denials) are deterministic on purpose.
- `content/command-guide.md` (this folder) — the step-by-step command
  instructions the bot gives when someone asks "how do I …". Everything
  below the `<!-- STAFF-ONLY BELOW -->` line is only ever shown to staff.

## Tuning the personality — practical tips

1. **The example exchanges are the strongest lever.** The model imitates
   them heavily. Want shorter answers? Shorten the examples. Want a
   different accent or catchphrase? Write 3–4 examples using it.
2. Change the name/character in "Who you are" freely — call it whatever
   fits your unit. Keep the "never claim to be human" line.
3. "How you write" contains the anti-AI-essay rules. If answers start
   looking like essays again, make these rules stricter, not longer.
4. Be careful in "Grounding rules" — that section is what keeps the bot
   honest (no invented lore, no leaked staff info). Add rules, avoid
   removing them.
5. After editing: `docker compose restart bot` (personality is read at
   startup and per-question).

## Teaching it unit knowledge

Add or edit Markdown files under `unit/knowledge/` (guides, rules, SOPs) or
`unit/lore/` (canonical lore) — each file has a 3-line header
(title / visibility / tags), documented in those folders' READMEs. Then run
`/unit sync`. The bot answers from those files immediately and honestly
says when something isn't written yet.

## Server memory

The bot quietly saves durable facts it hears in conversation ("op nights
moved to Fridays", "Vector is the armor guy"). It recalls them when
relevant. Staff should skim `/unit memories` now and then and delete
anything wrong — memory is only as good as what's in it.

## Ambient chatter

Optional: the bot occasionally (every 5–30 min, only when chat is active)
drops an in-character comment in the general channel — banter, sympathy, or
encouragement based on the conversation. Toggle it in `/unit setup` →
"Ambient chatter". Its tone is governed by `personality.md` too.
