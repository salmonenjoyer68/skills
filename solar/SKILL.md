---
name: solar
description: "Answer a customer inquiry through the Solar pipeline: researcher → writer → checker → logger → notifier. Use when the user wants a researched, fact-checked reply or email to a customer, asks to run Solar or the researcher-writer-checker pipeline, or wants an audited answer with optional Telegram delivery. Works on web evidence plus any internal context the user supplies."
---

# Solar

Solar turns one customer inquiry into a sourced, fact-checked reply: research first, a draft written only from that research, an independent checker, a durable run record, then delivery. Ported from [Sol-O](https://github.com/salmonenjoyer68/Sol-O).

Stages are fixed. Never add, drop, or reorder them:

| # | Stage | Kind | Artifact |
|---|-------|------|----------|
| 1 | researcher | subagent | `research.json` |
| 2 | writer | subagent | `draft.json` |
| 3 | checker | subagent | `review.json` |
| 4 | logger | `scripts/logger.py` | `run.json`, `index.jsonl` |
| 5 | notifier | `scripts/notify.py` | Telegram message / preview |

The writer may run twice: once from research, once from checker issues. Nothing else loops.

## Inputs

- The inquiry text. Read the file the user points at.
- Optional `source` conversation key (email thread, chat id). Default `cli`.
- Optional internal context: files or a `kb/` directory the user names. Pass only the relevant excerpts to the researcher; treat them as internal evidence, not citations.
- Web access for the researcher. Without it, supplied internal context can still support a finding (marked `[internal: …]`); anything neither source supports is `unverified`.

## Run directory

Create `solar-runs/<run-id>/` in the working directory, where `<run-id>` is UTC `YYYYMMDDTHHMMSSZ` plus `-` and 4 random hex characters (for example `20261118T143800Z-a1b2`). Write `meta.json` first with your file-write tool:

```json
{"id":"<run-id>","task":"<inquiry>","source":"cli","started_at":"<UTC ISO-8601>"}
```

All stage artifacts go in this directory. Never write run artifacts into the skill directory.

## 1. Researcher

Read `agents/researcher.md` and run it as a fresh subagent (Task tool, `task`, or the platform equivalent), with the role text as its system prompt. Give it only the inquiry and the internal context. Do not give it your own analysis.

- Save its JSON output as `research.json`. Validate with `python3 -m json.tool solar-runs/<run-id>/research.json >/dev/null`.
- Invalid JSON or a missing report: re-run the stage once, quoting the validation error. On a second failure, write `failure.json` (`{"stage":"researcher","error":"..."}`) and go to Logger.
- `status: needs_clarification`: save the artifact, go to Logger, then ask the user its single question.

If you cannot spawn subagents, adopt the role yourself: read only the role file and the stage inputs, not your earlier reasoning, and write the JSON before continuing.

## 2. Writer

Fresh subagent with `agents/writer.md`, the inquiry, and `research.json`. Save as `draft.json`; same validation and retry. The writer never sees your analysis, only the inputs.

- `status: needs_clarification` or an empty `draft`: go to Logger, then ask the user its single question; do not run the Checker.

If the researcher returned nothing usable, do not let the writer invent facts: carry the limitation through to the final reply.

## 3. Checker

Fresh subagent with `agents/checker.md`, the inquiry, `research.json`, and `draft.json`. Save as `review.json`; same validation and retry. The checker never sees the writer's reasoning, only its output.

- `approved`: continue.
- `needs_changes`: run the writer once more with the checker's `issues` and the previous draft. Overwrite `draft.json`, then re-run the checker on the revised draft, telling it this is a re-review of the previously reported issues. Overwrite `review.json`; do not loop again.
- `needs_clarification` or no usable draft: go to Logger.

## 4. Logger

```bash
python3 <skill-dir>/scripts/logger.py --run-dir solar-runs/<run-id>
```

It reads `meta.json` and the stage artifacts and writes `run.json`, appending one line to `solar-runs/index.jsonl`. It derives `status` (`complete`, `partial`, `needs_clarification`, `failed`) and carries the checker's `verdict` and `issues`; a run is `complete` only when all three stage artifacts exist and match their role's output contract (valid `status`, plus `findings`, `draft`, and `verdict`/`issues` respectively). An artifact that fails validation exits non-zero. On a non-zero exit, report it and do not notify.

## 5. Notifier

```bash
python3 <skill-dir>/scripts/notify.py --run-dir solar-runs/<run-id>
```

- Skips failed and clarification runs; nothing is sent without a draft.
- Dry run by default (`DRY_RUN` unset or true): prints the message and records `delivery.dry_run`.
- Sends only when `DRY_RUN=false` and `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` are set. Messages over 4000 characters are split; one retry on transient failures.
- `SOLAR_TELEGRAM_ENDPOINT` overrides the Telegram URL, for local testing: https, or http on a loopback host. Redirects are never followed.

## Final reply

Give the user, in order:

1. The draft text, labeled ready to send only when the final verdict is `approved` (an approved partial run counts); otherwise show it labeled unresolved with the open issues.
2. One short status block: run id, verdict, unresolved issues, run directory, delivery result.
3. If clarification is needed, ask exactly the stage's one question and stop.

## Non-negotiables

- Facts enter only through the researcher or supplied internal context. The writer never adds any, the checker never adds any, and you never edit the draft.
- Never cite a source that was not actually seen. `unverified` stays `unverified`.
- One retry per stage, one writer revision, no other loops.
- Never send on a failed or clarification run, and never override the notifier's dry-run default.

This skill is the pipeline only: Sol-O's Sun planner, approvals, SQLite store, SSE stream and UI are not included.
