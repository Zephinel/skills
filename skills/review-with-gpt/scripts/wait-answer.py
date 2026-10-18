#!/usr/bin/env python3
"""Wait for the current ChatGPT turn and save its answer text.

    python3 scripts/wait-answer.py <tabIndex> [--out /tmp/review-answer.md]

This replaces a hand-rolled polling loop. It watches the answer container
(`[class*="prose"]` inside the current assistant turn), not only the Stop
button, because the button can stay on while the model is thinking and can
also stay on after it has stopped producing text.

Exit codes:
    0  answer complete and saved
    2  no usable answer in the current turn (empty / prompt echo)
    3  stalled: Stop on and the answer did not grow for --stall-polls polls
    4  hard cap reached (default 10 minutes)
    1  a run-js.py call failed

Exit 3 is a signal to *inspect* the page, not permission to click Stop: a
reasoning model can think for minutes without prose. If the page is visibly
thinking or the turn's status line is still changing, wait; otherwise use the
recovery steps in SKILL.md.
"""

import argparse
import json
import pathlib
import subprocess
import sys
import time
from typing import Optional

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
RUN_JS = SCRIPT_DIR / "run-js.py"

SNIPPET = r'''
var labels = [].slice.call(document.querySelectorAll('[class*="sr-only"]'))
  .filter(function(e){ return /^ChatGPT said/.test((e.innerText || '').trim()); });
var turn = labels[labels.length - 1];
var blocks = [].slice.call(document.querySelectorAll('[class*="prose"]'))
  .filter(function(e){ return (e.innerText || '').trim().length > 0; });
var last = blocks[blocks.length - 1];
var current = !turn || !last ||
  !!(turn.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING);
var text = current && last ? last.innerText.trim() : '';
JSON.stringify({
  stop: !!document.querySelector('button[aria-label="Stop"]'),
  current: current,
  chunks: blocks.length,
  chars: text.length,
  head: text.slice(0, 120),
  text: text
});
'''


def poll(tab: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(RUN_JS), tab],
        input=SNIPPET,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:400])
    return json.loads(r.stdout.strip())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tab")
    ap.add_argument("--out", default="/tmp/review-answer.md")
    ap.add_argument("--poll", type=float, default=20.0)
    ap.add_argument("--stable", type=int, default=2,
                    help="equal readings after Stop is gone (default 2)")
    ap.add_argument("--stall-polls", type=int, default=6,
                    help="unchanged polls before declaring a stall (default 6)")
    ap.add_argument("--cap", type=float, default=600.0,
                    help="hard cap in seconds (default 600)")
    args = ap.parse_args()

    # A one-shot poller must not let a previous run's answer masquerade as
    # this run's result. Start from no file; a stall with real partial text
    # will write it back.
    out = pathlib.Path(args.out)
    try:
        out.unlink()
    except FileNotFoundError:
        pass

    started = time.monotonic()
    last_chars = None
    stable = 0
    unchanged = 0
    last = None

    while True:
        elapsed = time.monotonic() - started
        if elapsed > args.cap:
            save(args.out, last)
            print(f"TIMEOUT {elapsed:.0f}s chars={last['chars'] if last else 0} out={args.out}")
            return 4
        try:
            data = poll(args.tab)
        except Exception as e:
            print(f"ERROR {e}")
            return 1
        last = data
        print(
            f"t={elapsed:5.0f}s stop={int(data['stop'])} "
            f"current={int(data['current'])} chunks={data['chunks']} "
            f"chars={data['chars']} head={data['head'][:40]!r}",
            flush=True,
        )

        if data["chars"] == last_chars:
            unchanged += 1
        else:
            unchanged = 0
            last_chars = data["chars"]

        if not data["stop"]:
            usable = (data["current"] and data["chars"] > 0
                      and not (data.get("text") or "").startswith("You said:"))
            if usable:
                if stable + 1 >= args.stable:
                    save(args.out, data)
                    print(f"DONE chars={data['chars']} out={args.out}")
                    return 0
                stable += 1
            else:
                stable = 0
            if unchanged >= args.stall_polls:
                save(args.out, data)
                print(f"EMPTY chars={data['chars']} out={args.out}")
                return 2
        else:
            stable = 0
            if unchanged >= args.stall_polls:
                save(args.out, data)
                print(f"STALLED chars={data['chars']} out={args.out}")
                return 3

        time.sleep(args.poll)


def save(path: str, data: Optional[dict]) -> None:
    if not data:
        return
    text = data.get("text") or ""
    if not text or text.startswith("You said:"):
        # Do not write a prompt echo or an empty current turn.
        return
    pathlib.Path(path).write_text(text)


if __name__ == "__main__":
    sys.exit(main())
