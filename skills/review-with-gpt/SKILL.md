---
name: review-with-gpt
description: Send a file, diff, or question to a web chat the user already has open in Google Chrome on macOS (built-in scripts target ChatGPT; Claude, Gemini, and other chats work via DOM probing or input fallback) and read the reply back as text. Use on macOS when the user says "review with GPT", "让 ChatGPT review 一下", "ask the ChatGPT I have open", "去 ChatGPT 里看看它怎么说", "get a second opinion from Gemini/Claude", or asks to pull the latest answer out of an open Chrome chat tab. Needs no API key; not for non-macOS environments or API-based model calls.
---

# review-with-gpt — drive a chat the user is already signed into

Sends a prompt into a Google Chrome chat tab on macOS and reads the answer back using the user's signed-in session. No API key or account setup is required.

**What leaves the machine.** The prompt is posted to that service under the user's account. For private material, tell the user plainly before sending, and keep credentials out of the prompt.

**Script paths.** All commands below refer to `<skill-dir>/scripts/...` — resolve `<skill-dir>` to the directory containing this `SKILL.md` rather than assuming the shell working directory is inside the skill.

## Before you start

1. **Find the window and tab.** Never assume `window 1` or a tab index — list every Chrome window and tab:
   ```bash
   osascript -e 'tell application "Google Chrome"
     set out to ""
     repeat with w from 1 to count of windows
       repeat with t from 1 to count of tabs of window w
         set out to out & w & ":" & t & " " & (URL of tab t of window w) & linefeed
       end repeat
     end repeat
     return out
   end tell'
   ```
   Match on URL (or title). If no matching tab exists, ask the user to open the chat rather than opening one yourself (they may have multiple accounts signed in).

2. **Probe the JS route.** Chrome's dictionary has one spelling — `execute (tab <N> of window <W>) javascript <text>`:
   ```bash
   osascript -e 'tell application "Google Chrome" to execute (tab <N> of window <W>) javascript "1"'
   ```
   - Returns `1` → take [the JS route](#the-js-route-preferred) below.
   - Fails with `-1723 Access not allowed` → **View → Developer → Allow JavaScript from Apple Events** is off. Mention that setting to the user and use the fallback in [references/input-route.md](references/input-route.md).

3. **Provider check.** The ready-made snippets and `wait-answer.py` target **ChatGPT's** DOM. For **Claude, Gemini, or another chat**, read [references/dom-notes.md](references/dom-notes.md#adapting-to-claude-gemini-or-other-web-chats) to probe that page's composer, send/stop button, and answer container first.

## Choosing a route

| | JS route (preferred) | Input route ([references/input-route.md](references/input-route.md)) |
| --- | --- | --- |
| Needs | Chrome **Allow JavaScript from Apple Events** | Accessibility + Screen Recording + Swift helpers |
| Drives | The page's DOM via `run-js.py` | Mouse and keyboard |
| Survives focus changes | Yes | No |
| Best for | Long prompts, reliable hand-offs | Apple Events off or non-addressable DOM |

## The JS route (preferred)

`<skill-dir>/scripts/run-js.py <N> [--window <W>]` runs one snippet from stdin in the tab and prints its return value. Every snippet must return `JSON.stringify(...)` because AppleScript has no JS object type.

**Done when (every step):** the printed JSON confirms the expected state. Read it before moving on; never chain two steps on an assumption.

### Step 1 — Find the composer and verify it

The first `[contenteditable="true"]` is **not** necessarily the composer. A conversation can hold a canvas / writing block mounted earlier in the DOM — writing to it silently edits the user's document. Inspect the ancestor chain before writing anything:

```js
function findComposer(){
  var ces = [].slice.call(document.querySelectorAll('[contenteditable="true"]'));
  for (var i = ces.length - 1; i >= 0; i--)
    for (var n = ces[i], k = 0; n && k < 12; n = n.parentElement, k++)
      if (/ComposerLayoutInput/.test(String(n.className || ''))) return ces[i];
  return ces.filter(function(e){ var r = e.getBoundingClientRect();
    return r.height > 0 && r.height < 400 && r.top > 0 && r.top < window.innerHeight; }).pop() || null;
}
var el = findComposer(), path = [];
for (var n = el, k = 0; n && k < 6; k++, n = n.parentElement) path.push(n.tagName + '|' + String(n.className || '').slice(0, 40));
JSON.stringify({found: !!el, path: path, len: el ? el.innerText.length : -1});
```

**Done when:** `path` names the composer (not a canvas/writing block) and `len` matches the expected draft (`0` for empty).

### Step 2 — Put the prompt in

Synthetic `ClipboardEvent('paste')` is ignored by the editor, and the "Pasted text" chip only fires on real keystrokes. Use `document.execCommand('insertText', …)` in slices so the editor's internal state updates.

Carry the prompt in as base64 (pure ASCII survives AppleScript escaping cleanly):

```bash
python3 - "<skill-dir>/scripts/run-js.py" <N> <W> <<'PY'
import base64, subprocess, sys
run_js, tab, win = sys.argv[1], sys.argv[2], sys.argv[3]
b64 = base64.b64encode(open('/tmp/prompt.md', 'rb').read()).decode()
for i in range(0, len(b64), 60000):
    js = "window.__b64 = (window.__b64 || '') + '%s'; 'ok ' + window.__b64.length;" % b64[i:i+60000]
    out = subprocess.run(
        [sys.executable, run_js, tab, '--window', win],
        input=js, capture_output=True, text=True, check=True,
    )
    print(out.stdout.strip())
PY
```

Decode once, then insert in 9k slices, checking the printed length after each slice:

```js
// once
var bin = atob(window.__b64), bytes = new Uint8Array(bin.length);
for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
window.__p = new TextDecoder('utf-8').decode(bytes); window.__i = 0;
JSON.stringify({chars: window.__p.length});
```

```js
// per slice, until window.__i == window.__p.length
var el = findComposer(); el.focus();                       // findComposer from Step 1
var r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
var slice = window.__p.slice(window.__i, window.__i + 9000);
var ok = document.execCommand('insertText', false, slice);
window.__i += slice.length;
JSON.stringify({ok: ok, at: window.__i, total: window.__p.length, composerLen: el.innerText.length});
```

`insertText` takes a few seconds per 9k slice; text goes in inline with no attachment chip.

**Done when:** `at == total` and `composerLen` is in the same range as `total` (rendered blocks run slightly longer).

### Step 3 — Send

```js
JSON.stringify({composerChars: findComposer().innerText.length,
  send: !!document.querySelector('button[aria-label="Send"]')});
```

```js
document.querySelector('button[aria-label="Send"]').click();
```

A DOM `.click()` needs no focus or coordinates. If the Send button is missing, the editor considers the composer empty — go back to Step 2.

**Done when:** the composer is empty **and** a stop control exists (`button[aria-label="Stop"]`, or "ChatGPT is responding" on the page).

### Step 4 — Wait and detect a stall

Measure the **current turn's answer**, not only the Stop button. The Stop button can remain active while thinking or after generation stalls.

On ChatGPT, run the bundled poller (prefer a background job over blocking):

```bash
python3 "<skill-dir>/scripts/wait-answer.py" <N> --window <W> --out /tmp/review-answer.md
```

Exit codes:
- `0` — answer complete (Stop gone + 2 consecutive equal readings) and saved to `--out`
- `2` — no usable answer in this turn (empty or prompt echo)
- `3` — stalled (Stop on and `chars` unchanged for `--stall-polls`, default `6` polls ≈ 2 min). **Exit `3` is a signal to inspect the page, not automatic permission to click Stop.**
- `4` — hard cap reached (default `600s` / 10 min)
- `1` — `run-js.py` call failed

**Done when:** `wait-answer.py` exits `0` (Stop gone and answer length held equal across two polls). If exit is `2`, `3`, or `4`, follow [When the answer stops early](#when-the-answer-stops-early).

### Step 5 — Read and verify the answer

If you ran `wait-answer.py` and it exited `0`, inspect `/tmp/review-answer.md`. To read the ChatGPT DOM directly (or verify a manual poll):

```js
var labels = [].slice.call(document.querySelectorAll('[class*="sr-only"]'))
  .filter(function(e){ return /^ChatGPT said/.test((e.innerText || '').trim()); });
var turn = labels[labels.length - 1];
var blocks = [].slice.call(document.querySelectorAll('[class*="prose"]'))
  .filter(function(e){ return (e.innerText || '').trim().length > 0; });
var last = blocks[blocks.length - 1];
var current = !turn || !last ||
  !!(turn.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING);
var text = current && last ? last.innerText.trim() : '';
JSON.stringify({blocks: blocks.length, chars: text.length, current: current,
  head: text.slice(0, 160), text: text});
```

Reject the reading and keep waiting or recover if:
- `current` is `false` (block belongs to an earlier turn)
- `head` starts with `You said:` (walked into the user prompt)
- `chars` matches the prompt length and `head` is the prompt's opening
- `chars` is `0` while Stop is still on

Fallback only when `[class*="prose"]` is absent: walk up from the last `ChatGPT said:` `sr-only` label until `innerText.length >= 50`, and reject if the result starts with `You said:`.

**Done when:** the head is the answer's real opening (not the prompt or earlier turn), and the tail ends naturally rather than mid-sentence. Report the answer directly in your reply rather than only saving a file.

## When the answer stops early

| What you see | What it is | What to do |
| --- | --- | --- |
| Stop on, `chars` unchanged for 6 polls (~2 min), **and** no visible thinking/progress change | **Stalled** generation | Stop once, read `partial`, continue or shrink prompt |
| Stop off, text ends mid-sentence or with an unclosed code fence | **Truncated** answer | Send a short continuation prompt |
| Stop on for minutes, `head` starts with `You said:` or echoes prompt | **False answer** | Do not treat as output; keep checking the answer container or recover |

Do not confuse a stall with long reasoning. If the page visibly shows active `Thinking` / `Working` status updates, keep waiting up to the ~10-minute cap.

### Recovery steps

1. **Stop once** only after stall criteria hold. Wait 2 seconds, then read the last non-empty prose block as `partial` **only if `current` is `true`**. If `current` is `false`, skip to step 3.
2. **If `partial` is real review content**, send a continuation turn in the same thread (match the chat language):
   - Chinese:
     ```text
     你刚才的回答在下面这里中断了。请从断点继续，只输出剩余部分，不要重复已经输出的内容，也不要重新审查全文。
     断点前的最后一句/标题：
     <last 2–3 lines of partial>
     ```
   - English:
     ```text
     Your previous answer stopped at the point below. Continue from there and output only the remainder. Do not repeat what you already wrote and do not restart the review.
     Last line/heading before the stop:
     <last 2–3 lines of partial>
     ```
   Confirm a new Stop control appears, then wait again (Step 4).
3. **If `partial` is empty, echoes the prompt, or keeps stalling**, stop retrying the huge prompt. Shrink it to 20–40KB (keep the question, changed functions, and tests; drop full-file dumps; 70–80KB prompts stall often) and resend as a new turn, noting once that it replaces the earlier attempt.
4. **If truncated at the end** (no Stop control, mid-sentence/open fence), send the continuation prompt above or ask only for the missing sections.
5. **Always check the tail** before declaring completion — a missing Stop button alone does not prove completeness.

## Traps

- **Verify every step in the currency of the route.** JS returns JSON — read it. Input route returns nothing — screenshot it.
- **A canvas is not the composer.** Check the ancestor chain before inserting (Step 1). If a canvas was edited by mistake, click its **Undo last edit** button until its length returns to the initial reading.
- **Check before sending twice.** Step 3's criterion answers whether it sent; sending twice duplicates the prompt in the user's thread.
- **`sr-only` labels are turn boundaries, not answer bodies.** Walking up from an empty `ChatGPT said:` label lands on `You said:`. Prefer `[class*="prose"]` after the last turn label.
- **The model picker belongs to the page.** If the user cares which model or thinking level answers, verify or set the selector next to the send button rather than assuming the last-used default.

## References

- [references/input-route.md](references/input-route.md) — fallback mouse/keyboard route when Apple Events JS is off or the DOM is not addressable.
- [references/dom-notes.md](references/dom-notes.md) — observed Chrome + ChatGPT DOM facts and how to probe selectors for Claude, Gemini, or other web chats.
