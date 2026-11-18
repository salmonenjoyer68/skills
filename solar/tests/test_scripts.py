import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(
        f"solar_{name}", ROOT / "scripts" / f"{name}.py"
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

    def test_emoji_are_split_by_utf16_units(self):
        parts = notify.split_message("😀" * 5, 9)
        self.assertEqual(parts, ["😀" * 4, "😀"])
        self.assertLessEqual(max(notify.utf16_units(part) for part in parts), 9)


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

    def test_missing_checker_is_failed(self):
        record = self.record(
            {
                "research.json": {"status": "complete"},
                "draft.json": {"status": "complete", "draft": "reply"},
            }
        )
        self.assertEqual(record["status"], "failed")


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


class RetryTest(unittest.TestCase):
    def test_429_is_retried_once(self):
        calls = []

        class Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 429, "Too Many Requests", {}, None
                )
            return Response()

        with (
            mock.patch.object(notify.urllib.request, "urlopen", fake_urlopen),
            mock.patch.object(notify.time, "sleep", lambda _: None),
        ):
            notify.send_part("https://example.test/botTOKEN/sendMessage", "1", "hi", "TOKEN")
        self.assertEqual(len(calls), 2)


class NotifySkipTest(unittest.TestCase):
    def test_failed_run_is_skipped_without_sending(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_path = Path(tmp) / "run.json"
            run_path.write_text(json.dumps({"id": "r", "status": "failed", "draft": "x"}))
            with (
                mock.patch.object(sys, "argv", ["notify.py", "--run-dir", tmp]),
                mock.patch.dict(
                    os.environ,
                    {
                        "DRY_RUN": "false",
                        "TELEGRAM_BOT_TOKEN": "t",
                        "TELEGRAM_CHAT_ID": "1",
                    },
                ),
                mock.patch.object(
                    notify.urllib.request,
                    "urlopen",
                    side_effect=AssertionError("must not send"),
                ),
            ):
                self.assertEqual(notify.main(), 0)
            delivery = json.loads(run_path.read_text(encoding="utf-8"))["delivery"]
            self.assertTrue(delivery["skipped"])
            self.assertFalse(delivery["delivered"])


if __name__ == "__main__":
    unittest.main()
