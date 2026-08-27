# Unit lore

Put your unit's canonical lore here as Markdown files. The bot indexes this
folder (run `/unit sync` after editing) and the AI assistant treats it as
established fact — it will answer lore questions from these files and say
so plainly when something isn't recorded, instead of inventing canon.

Each file needs a small frontmatter header:

```markdown
---
title: How the unit was founded
visibility: public
tags: lore, history
---

# How the unit was founded

## The short version

Write your lore under normal Markdown headings...
```

- `visibility` is one of `public`, `member`, `staff` — who the assistant may
  show this document to.
- Use `## headings` to split long documents; the assistant retrieves the
  best-matching sections, not whole files.
- This folder is **private to your deployment** and ignored by Git.
- `README.md` files are never indexed.
