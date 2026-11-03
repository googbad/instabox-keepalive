#!/usr/bin/env python3
"""GitHub Actions controller for InstaBox keepalive.

Each scheduled invocation:
- reads the machine list and runStartedAt from InstaBox;
- runs one lightweight exec on each running machine before the 450-minute rotation point;
- at/after 450 minutes, performs suspend -> wait suspended -> resume -> wait running;
- verifies runStartedAt advanced before reporting a successful rotation;
- sends one Bark notification for each completed/failed rotation.

No local persistent state is required: InstaBox runStartedAt is authoritative.
"""

import json
import os
import sys
import time
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE_URL = "https://api.instabox.sh"
API_KEY = os.environ.get("INSTABOX_API_KEY", "").strip()
ROTATE_AFTER_SECONDS = 450 * 60
EXEC_COMMAND = (
    "if [ -x /data/watchdog.sh ]; then "
    "sudo /data/watchdog.sh; else date; fi"
)
POLL_INTERVAL = 3
POLL_TIMEOUT = 120


class InstaBoxError(RuntimeError):
    pass


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return None


def api_request(method, path, payload=None, timeout=30):
    if not API_KEY:
        raise InstaBoxError("INSTABOX_API_KEY secret is missing")

    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")

    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
        "User-Agent": "InstaBox-GitHub-Actions-Keepalive",
    }
    if data is not None:
        headers["Content-Type"] = "application/json"
    if path.endswith(("/suspend", "/resume", "/start", "/stop")):
        headers["Idempotency-Key"] = str(uuid.uuid4())

    request = urllib.request.Request(
        BASE_URL + path,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as error:
        # API response body is useful; no request headers or API key are logged.
        detail = error.read().decode("utf-8", "replace")[:500]
        raise InstaBoxError(f"{method} {path} returned HTTP {error.code}: {detail}") from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise InstaBoxError(f"{method} {path} network error: {type(error).__name__}") from error
    except json.JSONDecodeError as error:
        raise InstaBoxError(f"{method} {path} returned invalid JSON") from error


def send_bark(title, body):
    url = os.environ.get("BARK_URL", "").strip().rstrip("/")
    if not url:
        print("::warning::BARK_URL is not configured; notification skipped.")
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "group": "InstaBox",
    }).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "InstaBox-GitHub-Actions",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8", "replace"))
        if isinstance(result, dict) and result.get("code") == 200:
            print("Bark notification sent.")
            return True
        print("::warning::Bark did not return code 200.")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        # Never print the URL: it contains the Bark device key.
        print(f"::warning::Bark notification error: {type(error).__name__}")
    return False


def fetch_machine(mid):
    return api_request("GET", f"/v1/machines/{mid}")


def wait_for_state(mid, expected):
    deadline = time.monotonic() + POLL_TIMEOUT
    last_state = "unknown"
    while time.monotonic() < deadline:
        try:
            machine = fetch_machine(mid)
            last_state = machine.get("state", "unknown")
            if last_state == expected:
                return machine
        except InstaBoxError as error:
            print(f"State poll transient error: {error}")
        time.sleep(POLL_INTERVAL)
    raise InstaBoxError(
        f"machine {mid} did not reach state={expected} within {POLL_TIMEOUT}s "
        f"(last state={last_state})"
    )


def perform_rotation(machine):
    mid = machine["id"]
    name = machine.get("name") or mid
    previous_started = parse_time(machine.get("runStartedAt"))
    if previous_started is None:
        raise InstaBoxError(f"{name}: runStartedAt is missing or invalid; refusing lifecycle action")

    print(f"{name}: runtime reached 450 minutes; starting suspend -> resume.")
    api_request("POST", f"/v1/machines/{mid}/suspend")
    wait_for_state(mid, "suspended")
    api_request("POST", f"/v1/machines/{mid}/resume")
    resumed = wait_for_state(mid, "running")

    # The platform's runStartedAt is the authoritative timer. Poll until it advances.
    deadline = time.monotonic() + POLL_TIMEOUT
    refreshed_started = parse_time(resumed.get("runStartedAt"))
    while (refreshed_started is None or refreshed_started <= previous_started) and time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        resumed = fetch_machine(mid)
        if resumed.get("state") != "running":
            raise InstaBoxError(f"{name}: machine left running state after resume")
        refreshed_started = parse_time(resumed.get("runStartedAt"))

    if refreshed_started is None or refreshed_started <= previous_started:
        raise InstaBoxError(
            f"{name}: resumed and running, but runStartedAt did not advance; "
            "rotation cannot be confirmed"
        )

    elapsed = datetime.now(timezone.utc) - previous_started
    minutes = max(0, int(elapsed.total_seconds() // 60))
    message = (
        f"机器：{name}\n"
        f"操作：suspend → resume\n"
        f"结果：已恢复 running\n"
        f"轮换前运行：约 {minutes} 分钟\n"
        f"新 runStartedAt：{refreshed_started.isoformat()}"
    )
    send_bark("InstaBox 450 分钟轮换成功", message)
    print(f"{name}: rotation confirmed; runStartedAt advanced to {refreshed_started.isoformat()}.")


def keepalive_exec(machine):
    mid = machine["id"]
    name = machine.get("name") or mid
    result = api_request(
        "POST",
        f"/v1/machines/{mid}/exec",
        {"cmd": EXEC_COMMAND, "timeoutSeconds": 120},
        timeout=150,
    )
    if result.get("exitCode") != 0:
        raise InstaBoxError(
            f"{name}: exec failed with exitCode={result.get('exitCode')}; "
            f"stderr={str(result.get('stderr', ''))[:300]}"
        )
    print(f"{name}: keepalive exec succeeded.")


def main():
    try:
        response = api_request("GET", "/v1/machines")
        if isinstance(response, list):
            machines = response
        elif isinstance(response, dict) and isinstance(response.get("machines"), list):
            machines = response["machines"]
        else:
            raise InstaBoxError("Unexpected /v1/machines response shape")

        if not machines:
            print("No InstaBox machines were returned; nothing to do.")
            return 0

        failures = []
        now = datetime.now(timezone.utc)
        for machine in machines:
            mid = machine.get("id")
            name = machine.get("name") or mid or "unnamed"
            if not mid:
                failures.append(f"{name}: machine id missing")
                continue

            state = machine.get("state")
            if state != "running":
                print(f"{name}: state={state}; no automatic wake action is configured.")
                continue

            started = parse_time(machine.get("runStartedAt"))
            if started is None:
                failures.append(f"{name}: runStartedAt missing/invalid; skipped")
                continue

            elapsed = (now - started).total_seconds()
            try:
                if elapsed >= ROTATE_AFTER_SECONDS:
                    perform_rotation(machine)
                else:
                    keepalive_exec(machine)
            except Exception as error:
                detail = f"{name}: {error}"
                print(f"::error::{detail}", file=sys.stderr)
                failures.append(detail)
                # A rotation/exec failure is user-actionable; notify once in this invocation.
                send_bark("InstaBox 自动保活失败", detail)

        if failures:
            print(f"{len(failures)} machine operation(s) failed.", file=sys.stderr)
            return 1
        return 0

    except Exception as error:
        detail = f"InstaBox controller failed: {error}"
        print(f"::error::{detail}", file=sys.stderr)
        send_bark("InstaBox 自动保活任务失败", detail)
        return 1


if __name__ == "__main__":
    sys.exit(main())
