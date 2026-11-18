import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        f"sol_o_{name}", ROOT / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


logger = load("logger")
notify = load("notify")


class SplitMessageTest(unittest.TestCase):
    def test_short_message_is_one_part(self):
        self.assertEqual(notify.split_message("hello", 10), ["hello"])

    def test_long_paragraph_is_hard_wrapped(self):
        self.assertEqual(
            notify.split_message("x" * 25, 10), ["x" * 10, "x" * 10, "x" * 5]
        )

    def test_paragraphs_pack_greedily(self):
        self.assertEqual(
            notify.split_message("aaaa\n\nbbbb\n\ncccccccccccc", 10),
            ["aaaa\n\nbbbb", "cccccccccc", "cc"],
        )


class LoggerTest(unittest.TestCase):
    def record(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run-1"
            run_dir.mkdir()
            meta = {
                "id": "run-1",
                "task": "q",
                "source": "cli",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            (run_dir / "meta.json").write_text(json.dumps(meta))
            for name, value in files.items():
                (run_dir / name).write_text(json.dumps(value))
            return logger.build_record(run_dir)

    def test_approved_run_is_complete(self):
        record = self.record(
            {
                "research.json": {"status": "complete"},
                "draft.json": {"status": "complete", "draft": "reply"},
                "review.json": {"status": "complete", "verdict": "approved", "issues": []},
            }
        )
        self.assertEqual(
            (record["status"], record["verdict"], record["draft"]),
            ("complete", "approved", "reply"),
        )

    def test_partial_stage_makes_run_partial(self):
        record = self.record(
            {
                "research.json": {"status": "partial"},
                "draft.json": {"status": "complete", "draft": "reply"},
                "review.json": {"status": "complete", "verdict": "approved", "issues": []},
            }
        )
        self.assertEqual(record["status"], "partial")

    def test_missing_draft_is_failed_unless_clarification(self):
        self.assertEqual(
            self.record({"research.json": {"status": "complete"}})["status"], "failed"
        )
        self.assertEqual(
            self.record({"research.json": {"status": "needs_clarification"}})["status"],
            "needs_clarification",
        )


class MessageTest(unittest.TestCase):
    def test_issues_are_included(self):
        message = notify.build_message(
            {
                "id": "r1",
                "status": "complete",
                "verdict": "needs_changes",
                "task": "q",
                "draft": "d",
                "issues": [
                    {
                        "problem": "unsupported price",
                        "location": "prices",
                        "suggestion": "cite the researcher's finding",
                    }
                ],
            }
        )
        self.assertIn("unsupported price", message)
        self.assertIn("prices", message)


if __name__ == "__main__":
    unittest.main()
