#!/usr/bin/env python3
"""Small Bark notifier shared by InstaBox GitHub Actions jobs.

BARK_URL is the complete Bark push URL stored as a GitHub Actions secret.
The URL and device key are never printed to logs.
"""

import json
import os
import urllib.error
import urllib.request


def send_bark(title, body, *, url=None, timeout=20):
    """Send one Bark notification. Return True only for Bark code == 200."""
    target = (url if url is not None else os.environ.get("BARK_URL", "")).strip().rstrip("/")
    if not target:
        print("Bark notification skipped: BARK_URL is not configured.")
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "group": "InstaBox",
    }).encode("utf-8")

    request = urllib.request.Request(
        target,
        data=payload,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": "InstaBox-GitHub-Actions",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
        if isinstance(result, dict) and result.get("code") == 200:
            print("Bark notification sent.")
            return True
        print("Bark notification failed: Bark did not return code 200.")
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as error:
        # Do not include request URL: it contains the private Bark device key.
        print(f"Bark notification error: {type(error).__name__}")
    return False
