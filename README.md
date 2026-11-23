# Skills

A small, auditable collection of agent skills, organized the way the
[Agent Skills](https://docs.claude.com/en/docs/agents-and-tools/agent-skills)
convention expects: one folder per skill,
each with a `SKILL.md` manifest, a human-readable README, and the scripts and
prompts it needs.

Skills are portable. Nothing here depends on a specific agent runtime: the
instructions are plain Markdown, the helpers are standard-library Python.

## Skills in this repository

| Skill | What it does | Entry point |
|-------|--------------|-------------|
| [solar](solar/) | Runs one customer inquiry through `researcher → writer → checker → logger → notifier`, producing a sourced, fact-checked reply with an audit record and optional Telegram delivery. | [solar/SKILL.md](solar/SKILL.md) |

## How a skill is organized

```
skills/
├── README.md            # this file
├── LICENSE
├── .gitignore
└── <skill-name>/
    ├── SKILL.md         # required manifest: YAML frontmatter + instructions
    ├── README.md        # setup, usage, configuration, troubleshooting
    ├── agents/          # optional: role prompts used as subagent system prompts
    ├── scripts/         # optional: deterministic helpers (stdlib only)
    └── tests/           # optional: unit tests for the helpers
```

`solar/` is the reference layout. A skill folder may add `references/` for
long-form documentation and `assets/` for templates; keep every path inside
`SKILL.md` relative to the skill directory so the folder stays relocatable.

### `SKILL.md` contract

Every skill starts with YAML frontmatter:

```yaml
---
name: solar
description: "What it does and, most importantly, when to use it."
---
```

- `name` is lowercase, hyphenated, and identical to the folder name.
- `description` is the only text an agent sees before loading the skill, so it
  must name both the capability and the triggers ("Use when …").
- The body is the procedure: inputs, ordered steps, tool calls, failure paths,
  and non-negotiables. Agents load it only after the description matches.

### Adding a skill

1. Create `<skill-name>/SKILL.md` with matching frontmatter.
2. Put reusable prompt text in `agents/` and deterministic logic in `scripts/`
   (`python3` standard library only, so a skill never needs a virtualenv).
3. Add `<skill-name>/README.md` covering install, usage, configuration, and tests.
4. Add unit tests under `<skill-name>/tests/` when the skill ships scripts.
5. Add a row to the table above and open a pull request.

If a skill writes files at runtime, write them to a working directory — never
into the skill folder, which should stay read-only and relocatable.

## Development

Run the test suite from the repository root:

```bash
python3 -m unittest discover -s solar/tests -v
```

The same command runs in CI (`.github/workflows/tests.yml`). Python 3.9+ is
required; there are no third-party dependencies.

## License

MIT — see [LICENSE](LICENSE). Individual skills may ship their own attribution
notes; `solar` credits [Sol-O](https://github.com/salmonenjoyer68/Sol-O).
