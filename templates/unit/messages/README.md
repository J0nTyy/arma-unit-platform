# Per-unit message overrides

The bot's varied messages (greetings, announcement flavor lines, cert
congratulations) ship with defaults in `content/messages/*.yaml`. To
re-voice any of them for your unit, create a YAML file **here** with the
same key — your version fully replaces the shipped one.

Example — `greetings.yaml`:

```yaml
member_greeting:
  variants:
    - |-
      Welcome to **{unit_name}**, {member}!
      {channels}
      Start with /profile, then sign up for an operation.
  witty:
    - |-
      {member}, welcome aboard. Your paperwork survived processing —
      that was the hard part.
      {channels}
```

Rules of the system:

- `variants` are always eligible; `witty` ones only when
  `personality.humour` in `unit/config/unit.yaml` is `medium` or `high`.
- The bot never picks the same variant twice in a row.
- Keep the `{placeholders}` from the original key — they're filled in
  automatically.
- Serious messages (errors, permission denials) are deterministic on
  purpose and can't be varied here.
- Changes apply after a bot restart.

Shipped keys to override: see `content/messages/*.yaml` in the repository.
