#!/usr/bin/env python3
"""Solar logger stage: assemble run.json and index.jsonl from stage artifacts."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

STAGE_FILES = (
    ("research", "research.json"),
    ("writer", "draft.json"),
    ("checker", "review.json"),
)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise SystemExit(f"logger: invalid JSON in {path.name}: {exc}")


def parse_started(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def derive_status(outputs: dict) -> str:
    draft = ((outputs.get("writer") or {}).get("draft") or "").strip()
    needs_clarification = any(
        (output or {}).get("status") == "needs_clarification"
        for output in outputs.values()
    )
    if not draft:
        return "needs_clarification" if needs_clarification else "failed"
    if needs_clarification:
        return "needs_clarification"
    if any((output or {}).get("status") == "partial" for output in outputs.values()):
        return "partial"
    return "complete"


def build_record(run_dir: Path) -> dict:
    meta = read_json(run_dir / "meta.json")
    if meta is None:
        raise SystemExit(f"logger: missing {run_dir / 'meta.json'}")
    outputs = {}
    for name, filename in STAGE_FILES:
        output = read_json(run_dir / filename)
        if output is not None:
            outputs[name] = output
    failure = read_json(run_dir / "failure.json")
    review = outputs.get("checker") or {}
    writer = outputs.get("writer") or {}
    now = datetime.now(timezone.utc)
    started = parse_started(meta.get("started_at", ""))
    previous = read_json(run_dir / "run.json")

    record = {
        "id": meta.get("id") or run_dir.name,
        "created_at": now.isoformat(timespec="seconds"),
        "started_at": meta.get("started_at"),
        "duration_seconds": max(0.0, round((now - started).total_seconds(), 2)) if started else 0.0,
        "task": meta.get("task", ""),
        "source": meta.get("source", "cli"),
        "status": "failed" if failure else derive_status(outputs),
        "verdict": review.get("verdict"),
        "draft": writer.get("draft", ""),
        "issues": review.get("issues", []),
        "outputs": outputs,
    }
    if failure:
        record["failure"] = failure
    if previous and "delivery" in previous:
        record["delivery"] = previous["delivery"]
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Log a Solar run from its stage artifacts.")
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()

    record = build_record(args.run_dir)
    (args.run_dir / "run.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    index_line = {
        key: record[key]
        for key in ("id", "created_at", "task", "status", "verdict", "duration_seconds")
    }
    with (args.run_dir.parent / "index.jsonl").open("a", encoding="utf-8") as index:
        index.write(json.dumps(index_line, ensure_ascii=False) + "\n")
    print(
        f"logger: wrote {args.run_dir / 'run.json'} "
        f"status={record['status']} verdict={record['verdict']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
