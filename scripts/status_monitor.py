
#!/usr/bin/env python3

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API_URL = "https://api.instabox.sh/v1/machines"
API_KEY = os.environ.get("INSTABOX_API_KEY", "")
OUTPUT_FILE = Path(os.environ.get("STATUS_OUTPUT", "machines-status.json"))

RETRIES = 3
RETRY_DELAY = 3
WARNING_MINUTES = 470


def parse_time(value):
    if not value:
        return None

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None


def format_duration(seconds):
    if seconds is None:
        return "Unknown"

    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours}h {minutes}m {seconds}s"


def fetch_machines():
    if not API_KEY:
        raise RuntimeError("INSTABOX_API_KEY is missing")

    headers = {
        "X-API-Key": API_KEY,
        "Accept": "application/json",
        "User-Agent": "InstaBox-GitHub-Actions-Monitor",
    }

    request = urllib.request.Request(
        API_URL,
        headers=headers,
        method="GET",
    )

    last_error = None

    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(
                request,
                timeout=20,
            ) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as error:
            last_error = error

            if error.code not in (429, 500, 502, 503, 504):
                raise

        except (urllib.error.URLError, TimeoutError) as error:
            last_error = error

        if attempt < RETRIES - 1:
            time.sleep(RETRY_DELAY * (attempt + 1))

    raise RuntimeError(
        f"InstaBox API request failed after {RETRIES} attempts: "
        f"{last_error}"
    )


def summarize_machine(machine):
    now = datetime.now(timezone.utc)

    state = machine.get("state", "unknown")
    desired_state = machine.get("desiredState", "unknown")

    started_at = parse_time(machine.get("runStartedAt"))
    cooldown_until = parse_time(machine.get("cooldownUntil"))

    elapsed_seconds = None
    remaining_seconds = None
    warning = False

    max_run_minutes = machine.get("maxRunMinutes", 480)

    try:
        max_run_seconds = int(max_run_minutes) * 60
    except (ValueError, TypeError):
        max_run_seconds = 480 * 60

    if started_at:
        elapsed_seconds = max(
            0,
            int((now - started_at).total_seconds()),
        )

        remaining_seconds = max(
            0,
            max_run_seconds - elapsed_seconds,
        )

        warning = (
            state == "running"
            and elapsed_seconds >= WARNING_MINUTES * 60
        )

    return {
        "id": machine.get("id"),
        "name": machine.get("name", "unnamed"),
        "state": state,
        "desiredState": desired_state,
        "runtimeReady": machine.get("runtime", {}).get("ready"),
        "storageSynced": machine.get("storage", {}).get("synced"),
        "runStartedAt": machine.get("runStartedAt"),
        "elapsed": format_duration(elapsed_seconds),
        "elapsedSeconds": elapsed_seconds,
        "maxRunMinutes": max_run_minutes,
        "maxRunRemaining": format_duration(remaining_seconds),
        "maxRunRemainingSeconds": remaining_seconds,
        "cooldownUntil": machine.get("cooldownUntil"),
        "cooldownActive": bool(
            cooldown_until and cooldown_until > now
        ),
        "free": machine.get("free"),
        "warning470": warning,
    }


def write_summary(machines):
    lines = [
        "# InstaBox Status Monitor",
        "",
        f"Checked at: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Machine | State | Elapsed | Max runtime remaining | 470-min warning |",
        "|---|---|---:|---:|---|",
    ]

    for machine in machines:
        warning = (
            "WARNING"
            if machine["warning470"]
            else "No"
        )

        lines.append(
            f"| {machine['name']} "
            f"| {machine['state']} "
            f"| {machine['elapsed']} "
            f"| {machine['maxRunRemaining']} "
            f"| {warning} |"
        )

    lines.extend([
        "",
        "## Monitoring policy",
        "",
        "- Scheduled read-only status checks every 20 minutes.",
        "- 470-minute runtime warning based on runStartedAt.",
        "- No remote exec, start, stop, suspend or resume actions.",
        "- GitHub Actions scheduling is not guaranteed to run at exact times.",
    ])

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n")

    print("\n".join(lines))


def main():
    try:
        response = fetch_machines()

        if isinstance(response, dict):
            raw_machines = response.get("machines", [])
        elif isinstance(response, list):
            raw_machines = response
        else:
            raise RuntimeError("Unexpected API response format")

        machines = [
            summarize_machine(machine)
            for machine in raw_machines
        ]

        result = {
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "machineCount": len(machines),
            "machines": machines,
        }

        OUTPUT_FILE.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        write_summary(machines)

        for machine in machines:
            if machine["warning470"]:
                print(
                    f"::warning title=470-minute runtime warning::"
                    f"{machine['name']} has reached 470 minutes."
                )

        return 0

    except Exception as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
