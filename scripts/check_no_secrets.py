#!/usr/bin/env python3
"""Fail if any tracked file contains a New Relic key-shaped string.

A backstop against committing a real credential. Runs in CI over all git-tracked
files. The key formats appear here only as regex fragments, which do not match
themselves, so no file is exempted (a real key anywhere, including in docs, must
fail).
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "New Relic user key (NRAK)": re.compile(r"NRAK-[A-Za-z0-9]{20,}"),
    "New Relic ingest/browser key": re.compile(r"NR(II|JS|BR)-[A-Za-z0-9]{20,}"),
    "New Relic license key": re.compile(r"\b[A-Fa-f0-9]{36}NRAL\b"),
}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], capture_output=True, text=True, check=True
    ).stdout
    return [line for line in out.splitlines() if line]


def scan() -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for path in tracked_files():
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                text = fh.read()
        except OSError:
            continue
        for label, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append((path, label))
    return findings


def main() -> int:
    findings = scan()
    if findings:
        print("Potential committed credentials found:")
        for path, label in findings:
            print(f"  {path}: {label}")
        print("\nRemove the secret and rotate it. Secrets belong in the credential backend.")
        return 1
    print("No New Relic key-shaped strings found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
