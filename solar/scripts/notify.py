#!/usr/bin/env python3
"""Solar notifier stage: deliver a finished run to Telegram (dry-run by default)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TELEGRAM_LIMIT = 4000
FALSE_VALUES = {"false", "0", "no", "off"}
MAX_RETRY_WAIT = 10  # seconds we are willing to block a CLI run for a 429


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # a redirect is never a Telegram success


_opener = urllib.request.build_opener(_NoRedirect)


def open_url(request):
    return _opener.open(request, timeout=30)


def retry_after(exc: urllib.error.HTTPError) -> int | None:
    try:
        value = json.loads(exc.read() or b"{}").get("parameters", {}).get("retry_after")
        return int(value) if value is not None else None
    except (AttributeError, TypeError, ValueError, OSError):
        return None


def utf16_units(text: str) -> int:
    # Telegram counts UTF-16 code units, so an emoji costs 2.
    return len(text.encode("utf-16-le")) // 2


def fit_prefix(text: str, limit: int) -> int:
    """Length of the longest prefix within limit UTF-16 units; always at least 1 char."""
    total = 0
    for index, char in enumerate(text):
        total += 2 if ord(char) > 0xFFFF else 1
        if total > limit:
            return index or 1
    return len(text)


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on paragraph boundaries, then hard-wrap, never over limit UTF-16 units."""
    if utf16_units(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if utf16_units(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = ""
        rest = paragraph
        while utf16_units(rest) > limit:
            cut = fit_prefix(rest, limit)
            chunks.append(rest[:cut])
            rest = rest[cut:]
        current = rest
    if current:
        chunks.append(current)
    return chunks


def build_message(run: dict) -> str:
    verdict = run.get("verdict")
    header = f"Solar run {run.get('id', '?')}\nStatus: {run.get('status', 'unknown')}"
    if verdict:
        header += f" | Verdict: {verdict}"
    lines = [header, "", f"Task: {run.get('task', '')}", "", "Draft:", run.get("draft", "")]
    issues = run.get("issues") or []
    if issues:
        lines += ["", "Checker issues:"]
        for issue in issues:
            if isinstance(issue, dict):
                detail = f"- {issue.get('problem', '')}"
                if issue.get("location"):
                    detail += f" ({issue['location']})"
                if issue.get("suggestion"):
                    detail += f" — {issue['suggestion']}"
                lines.append(detail)
            else:
                lines.append(f"- {issue}")
    return "\n".join(lines)


def dry_run_enabled() -> bool:
    # Unset or true is a preview; only an explicit false value sends.
    return os.environ.get("DRY_RUN", "").strip().lower() not in FALSE_VALUES


def send_part(url: str, chat_id: str, text: str, token: str) -> None:
    body = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    last_error = ""
    delay = 1
    for attempt in (1, 2):
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with open_url(request) as response:
                if not 200 <= response.status < 300:
                    last_error = f"HTTP {response.status}"
                else:
                    try:
                        payload = json.loads(response.read() or b"{}")
                    except ValueError:
                        payload = {}
                    if payload.get("ok") is True:
                        return
                    last_error = f"not ok: {payload.get('description', 'invalid response')}"
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code == 429:
                wait = retry_after(exc)
                if wait is not None and wait > MAX_RETRY_WAIT:
                    last_error += f" rate limited; retry after {wait}s"
                    break
                delay = wait or 1
            elif exc.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt == 1:
            time.sleep(delay)
    raise RuntimeError(last_error.replace(token, "***"))


def write_delivery(run_path: Path, run: dict, delivery: dict) -> None:
    run["delivery"] = delivery
    tmp = run_path.with_suffix(".tmp")
    try:
        tmp.write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(tmp, run_path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Notify Telegram about a logged Solar run.")
    parser.add_argument("--run-dir", required=True, type=Path)
    args = parser.parse_args()

    run_path = args.run_dir / "run.json"
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise SystemExit(f"notifier: missing {run_path}; run logger first")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"notifier: invalid {run_path.name}: {exc}")

    status = run.get("status")
    draft = (run.get("draft") or "").strip()
    if status not in {"complete", "partial"} or not draft:
        reason = "empty draft" if not draft else f"status={status}"
        write_delivery(
            run_path,
            run,
            {"dry_run": None, "delivered": False, "skipped": True, "reason": reason},
        )
        print(f"notifier: skipped ({reason})")
        return 0

    message = build_message(run)
    parts = split_message(message)
    if dry_run_enabled():
        print("--- DRY_RUN telegram message ---")
        for index, part in enumerate(parts, start=1):
            print(f"[part {index}/{len(parts)}] {part}")
        print("--- end telegram message ---")
        write_delivery(
            run_path, run, {"dry_run": True, "delivered": False, "parts": len(parts)}
        )
        print(f"notifier: dry run, {len(parts)} part(s); set DRY_RUN=false to send")
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        error = "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set when DRY_RUN=false"
        write_delivery(
            run_path, run, {"dry_run": False, "delivered": False, "error": error}
        )
        print(f"notifier: {error}", file=sys.stderr)
        return 1

    url = os.environ.get("SOLAR_TELEGRAM_ENDPOINT", "").strip() or (
        f"https://api.telegram.org/bot{token}/sendMessage"
    )
    parsed = urllib.parse.urlsplit(url)
    loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if not parsed.scheme:
        error = "SOLAR_TELEGRAM_ENDPOINT is missing a URL scheme"
    elif parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        error = "SOLAR_TELEGRAM_ENDPOINT must use https (http only for loopback)"
    else:
        error = ""
    if error:
        write_delivery(
            run_path, run, {"dry_run": False, "delivered": False, "error": error}
        )
        print(f"notifier: {error}", file=sys.stderr)
        return 1
    try:
        for part in parts:
            send_part(url, chat_id, part, token)
    except RuntimeError as exc:
        write_delivery(
            run_path,
            run,
            {
                "dry_run": False,
                "delivered": False,
                "parts": len(parts),
                "error": str(exc),
            },
        )
        print(f"notifier: send failed: {exc}", file=sys.stderr)
        return 1
    write_delivery(
        run_path, run, {"dry_run": False, "delivered": True, "parts": len(parts)}
    )
    print(f"notifier: sent {len(parts)} part(s) to Telegram")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
