# Unit knowledge base

Put your unit's how-to documents here as Markdown files: onboarding guides,
mod setup, rules of conduct, radio procedures, staff SOPs — anything the AI
assistant should be able to answer questions from. Run `/unit sync` after
editing so the bot re-indexes the folder.

Organize with subfolders (they become the document's category):

```
knowledge/
├── onboarding/getting-started.md
├── rules/conduct.md
└── sop/staff-procedures.md      <- visibility: staff
```

Each file needs a small frontmatter header:

```markdown
---
title: Getting started
visibility: member
tags: onboarding, new-players
---

# Getting started

## First steps

Write the guide under normal Markdown headings...
```

- `visibility` is one of `public`, `member`, `staff` — who the assistant may
  show this document to. Staff-only SOPs are never revealed to members.
- This folder is **private to your deployment** and ignored by Git.
- `README.md` files are never indexed.
