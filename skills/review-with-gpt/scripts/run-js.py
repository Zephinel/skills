#!/usr/bin/env python3
"""Run JavaScript in a Chrome tab, one snippet at a time.

    python3 scripts/run-js.py <tabIndex> < snippet.js

Why this exists: the snippet travels inside an AppleScript string literal, so
every backslash, quote and newline in it would otherwise have to be escaped by
hand — and a real snippet (a range, a class selector, a regex) contains all
three. This does the escaping once, for text of any shape.

The snippet must produce a string, because Chrome hands the result to
AppleScript, which has no object type worth having: end every snippet with
`JSON.stringify(...)`. Errors from Chrome arrive on stderr with a non-zero
exit status.
"""

import subprocess
import sys

if len(sys.argv) != 2:
    sys.exit(__doc__)

tab = sys.argv[1]
js = sys.stdin.read()


def applescript_string(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


# Chrome's dictionary has exactly one form of this command: `execute <tab>
# javascript <text>`. The `execute javascript <text> in tab <n>` spelling that
# circulates in examples is not in the dictionary, and AppleScript fails to
# parse it with `-1723 Can't get "1" in tab 5` — which looks like a permission
# error and is not: `-1723 Access not allowed` is the permission error.
script = (
    'tell application "Google Chrome"\n'
    f"  return execute (tab {tab} of window 1) javascript {applescript_string(js)}\n"
    "end tell\n"
)
result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
sys.stdout.write(result.stdout)
sys.stderr.write(result.stderr)
sys.exit(result.returncode)
