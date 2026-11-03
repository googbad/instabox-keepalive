#!/usr/bin/env python3
"""Read-only InstaBox status monitor for GitHub Actions.

Only calls GET /v1/machines. It never executes commands or changes machine state.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.instabox.sh/v1/machines"
MAX_RUN_MINUTES = 480


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def duration_text(seconds):
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def request_machines(api_key, attempts=3):
    req = urllib.request.Request(
        API_URL,
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
        },
        method="GET",
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if not isinstance(payload.get("machines"), list):
                    raise RuntimeError("API response does not contain a machines list")
                return payload
        except urllib.error.HTTPError as exc:
            # Retry only transient rate-limit/server errors.
            if exc.code not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                detail = exc.read().decode("utf-8", "replace")[:500]
                raise RuntimeError(f"InstaBox API returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f"InstaBox API network error: {exc}") from exc
        time.sleep(min(2 ** attempt, 8))
    raise RuntimeError("InstaBox API request failed")


def summarize(machine, now):
    state = machine.get("state", "unknown")
    started = parse_time(machine.get("runStartedAt"))
    cooldown = parse_time(machine.get("cooldownUntil"))
    elapsed = None
    remaining = None
    if started and state == "running":
        elapsed = max(0, (now - started).total_seconds())
        remaining = max(0, MAX_RUN_MINUTES * 60 - elapsed)
    return {
        "id": machine.get("id"),
        "name": machine.get("name") or machine.get("id") or "unnamed",
        "state": state,
        "desiredState": machine.get("desiredState"),
        "ready": machine.get("runtime", {}).get("ready"),
        "persistentStorageSynced": machine.get("storage", {}).get("synced"),
        "runStartedAt": machine.get("runStartedAt"),
        "elapsed": duration_text(elapsed) if elapsed is not None else None,
        "maxRunRemaining": duration_text(remaining) if remaining is not None else None,
        "cooldownUntil": machine.get("cooldownUntil"),
        "free": machine.get("free"),
    }


def main():
    api_key = os.environ.get("INSTABOX_API_KEY", "")
    if not api_key:
        print("::error::INSTABOX_API_KEY secret is missing", file=sys.stderr)
        return 1

    try:
        payload = request_machines(api_key)
    except Exception as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    now = datetime.now(timezone.utc)
    report = {
        "checkedAt": now.isoformat(),
        "readOnly": True,
        "machines": [summarize(machine, now) for machine in payload["machines"]],
        "nextCursor": payload.get("nextCursor"),
    }
    output = os.environ.get("STATUS_OUTPUT", "machines-status.json")
    with open(output, "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## InstaBox read-only status\\n\\n")
            summary.write(f"Checked: {report['checkedAt']} (UTC)\\n\\n")
            if not report["machines"]:
                summary.write("No machines returned.\\n")
            else:
                summary.write("| Machine | State | Ready | Runtime | 480-min remaining | Cooldown | Storage synced |\\n")
                summary.write("|---|---|---:|---:|---:|---|---:|\\n")
                for item in report["machines"]:
                    summary.write(
                        f"| {item['name']} | {item['state']} | {item['ready']} | "
                        f"{item['elapsed'] or '—'} | {item['maxRunRemaining'] or '—'} | "
                        f"{item['cooldownUntil'] or '—'} | {item['persistentStorageSynced']} |\\n"
                    )
            summary.write("\\n> Read-only: this workflow does not execute commands or change machine state.\\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
