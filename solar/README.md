# Solar

Solar turns one customer inquiry into a sourced, fact-checked reply. It runs a
fixed five-stage pipeline — research, write, check, log, notify — where each
stage only sees the previous stage's artifact, never the orchestrator's
reasoning. Facts enter through the Researcher and nowhere else.

Ported from [Sol-O](https://github.com/salmonenjoyer68/Sol-O); this skill is the
pipeline only. Sol-O's Sun planner, approvals, SQLite store, SSE stream and UI
are not included.

- [How it works](#how-it-works)
- [Install](#install)
- [Use](#use)
- [Output](#output)
- [Configuration](#configuration)
- [Scripts](#scripts)
- [Tests](#tests)
- [Design rules](#design-rules)
- [License](#license)

## How it works

```
inquiry ──▶ researcher ──▶ writer ──▶ checker ──▶ logger ──▶ notifier
              │             │           │            │
        research.json  draft.json  review.json  run.json + index.jsonl
```

| # | Stage | Runs as | Writes |
|---|-------|---------|--------|
| 1 | Researcher | subagent (`agents/researcher.md`) | `research.json` |
| 2 | Writer | subagent (`agents/writer.md`) | `draft.json` |
| 3 | Checker | subagent (`agents/checker.md`) | `review.json` |
| 4 | Logger | `scripts/logger.py` | `run.json`, `index.jsonl` |
| 5 | Notifier | `scripts/notify.py` | Telegram message or dry-run preview |

The Writer may run twice: once from the research, once from the Checker's
issues. Nothing else loops.

- **Researcher** searches the web (2–5 targeted queries), prefers primary
  sources, and reports one claim per finding with a URL and a confidence level.
  Anything unsupported is `unverified` and listed in `gaps`.
- **Writer** drafts the reply using only the findings and any internal context
  supplied by the user. It adds no facts and keeps every caveat.
- **Checker** compares each factual claim in the draft with the research and
  returns `approved` or `needs_changes` with per-issue fixes. It does not
  rewrite.
- **Logger** validates the artifacts, derives the run status, and writes the
  durable record.
- **Notifier** previews the message by default. It never sends a failed or
  clarification run, and it sends only when explicitly enabled.

## Install

Copy the folder into the skills directory your agent scans, for example:

```bash
cp -R solar ~/.claude/skills/solar        # Claude Code
# or the equivalent directory for your runtime
```

No dependencies. Python 3.9+ with the standard library is enough.

## Use

Ask in natural language; the skill's description is what triggers it:

> Run Solar on this customer email and draft a reply. The inquiry is in
> `inbox/acme-refund.txt`.

Optional inputs:

- A `source` key for the conversation (email thread id, chat id; default `cli`).
- Internal context: a file or `kb/` directory. Only the relevant excerpts are
  passed to the Researcher and are cited as `[internal: <path> > <heading>]`,
  never as external sources.

Run artifacts go to `solar-runs/<run-id>/` in the working directory, never into
the skill folder.

## Output

```
solar-runs/
├── index.jsonl                    # one summary line per logged run
└── 20261118T143800Z-a1b2/
    ├── meta.json                  # id, task, source, started_at
    ├── research.json              # findings, conflicts, gaps
    ├── draft.json                 # the deliverable text and facts used
    ├── review.json                # verdict and issues
    ├── run.json                   # validated record + delivery result
    └── failure.json               # only when a stage failed twice
```

`run.json` carries `status` (`complete`, `partial`, `needs_clarification`,
`failed`), the checker's `verdict`, the draft, and the issues. A run is
`complete` only when all three stage artifacts exist and match their role's
output contract.

## Configuration

The notifier is dry-run unless you deliberately turn sending on:

| Variable | Default | Meaning |
|----------|---------|---------|
| `DRY_RUN` | `true` | `false`, `0`, `no` or `off` enables real delivery; unset or true prints a preview. |
| `TELEGRAM_BOT_TOKEN` | — | Bot token, required when `DRY_RUN=false`. |
| `TELEGRAM_CHAT_ID` | — | Target chat, required when `DRY_RUN=false`. |
| `SOLAR_TELEGRAM_ENDPOINT` | Telegram API | Override for local testing. Must be `https`, or `http` on a loopback host. Redirects are never followed. |

Messages over 4000 UTF-16 units are split on paragraph boundaries, then
hard-wrapped. One retry on transient failures; a 429 with a long `retry_after`
is reported instead of waited out.

## Scripts

Both take a run directory and are meant to be run by the skill, not by hand.

```bash
python3 scripts/logger.py --run-dir solar-runs/<run-id>
python3 scripts/notify.py --run-dir solar-runs/<run-id>
```

`logger.py` exits non-zero on a missing `meta.json`, invalid JSON, or an artifact
that violates its output contract. `notify.py` exits non-zero on a delivery
configuration or transport error, and records the outcome under `delivery` in
`run.json`.

To check an artifact by hand:

```bash
python3 -m json.tool solar-runs/<run-id>/research.json >/dev/null
```

## Tests

```bash
python3 -m unittest discover -s solar/tests -v
```

The suite covers message splitting, Telegram delivery (mocked), endpoint
validation, and logger status derivation and artifact validation.

## Design rules

- Facts enter only through the Researcher or supplied internal context. The
  Writer never adds any, the Checker never adds any, and the orchestrator never
  edits the draft.
- Never cite a source that was not actually seen; `unverified` stays
  `unverified`.
- One retry per stage, one Writer revision, no other loops.
- Never send on a failed or clarification run, and never override the
  notifier's dry-run default.
- Stage artifacts are JSON only, so a run can be audited and replayed.

## License

MIT. `solar` is ported from [Sol-O](https://github.com/salmonenjoyer68/Sol-O);
see the repository [LICENSE](../LICENSE).
