#!/usr/bin/env python3
"""Run JavaScript in a Chrome tab, one snippet at a time.

    python3 scripts/run-js.py <tabIndex> [--window 1] < snippet.js

Why this exists: the snippet travels inside an AppleScript string literal, so
every backslash, quote and newline in it would otherwise have to be escaped by
hand — and a real snippet (a range, a class selector, a regex) contains all
three. This does the escaping once, for text of any shape.

The snippet must produce a string, because Chrome hands the result to
AppleScript, which has no object type worth having: end every snippet with
`JSON.stringify(...)`. Errors from Chrome arrive on stderr with a non-zero
exit status.
"""

import argparse
import subprocess
import sys


def positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value!r}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {parsed}")
    return parsed


def applescript_string(s: str) -> str:
    escaped = (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return '"' + escaped + '"'


def build_applescript(tab: int, js: str, window: int = 1) -> str:
    # Chrome's dictionary has exactly one form of this command: `execute <tab>
    # javascript <text>`. The `execute javascript <text> in tab <n>` spelling that
    # circulates in examples is not in the dictionary, and AppleScript fails to
    # parse it with `-1723 Can't get "1" in tab 5` — which looks like a permission
    # error and is not: `-1723 Access not allowed` is the permission error.
    return (
        'tell application "Google Chrome"\n'
        f"  return execute (tab {tab} of window {window}) javascript {applescript_string(js)}\n"
        "end tell\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run JavaScript from stdin in a Google Chrome tab via Apple Events."
    )
    parser.add_argument("tab", type=positive_int, help="1-based Chrome tab index")
    parser.add_argument(
        "--window",
        type=positive_int,
        default=1,
        help="1-based Chrome window index (default: 1)",
    )
    args = parser.parse_args(argv)

    js = sys.stdin.read()
    script = build_applescript(args.tab, js, window=args.window)
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
