# Contributing

This repository holds agent skills. A skill is a self-contained folder that an
agent can load and follow; it must stay useful without the rest of the repo.

## Adding or changing a skill

1. Each skill lives in its own top-level directory: `solar/`, `my-skill/`.
2. `SKILL.md` is the entry point. Its frontmatter must have `name` (lowercase,
   hyphenated, identical to the folder name) and a `description` that says what
   the skill does and, explicitly, when to use it.
3. The body should be a procedure: inputs, ordered steps, tool or script calls,
   failure paths, and non-negotiables. Prefer checklists over prose.
4. Use `agents/` for role prompts, `scripts/` for deterministic helpers, and
   `references/` for long-form material that would bloat `SKILL.md`.
5. Reference files with paths relative to the skill directory, never absolute
   paths, so the folder stays relocatable.
6. Ship a `README.md` covering install, usage, configuration, and tests.
7. Scripts must run on Python 3.9+ with the standard library only. No network
   calls at import time, no secrets in the tree.
8. Runtime artifacts belong in a working directory (for solar,
   `solar-runs/<run-id>/`), never inside the skill folder.

## Tests

Any script change needs a test. Run the suite before opening a pull request:

```bash
python3 -m unittest discover -s solar/tests -v
```

## Pull requests

- One skill or one behavior per pull request.
- Explain the trigger you expect: the user phrasing that should load the skill.
- Mention the test command you ran and its result.
- Do not commit run artifacts, `__pycache__`, or editor state — see
  [.gitignore](.gitignore).
