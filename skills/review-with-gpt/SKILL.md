---
name: review-with-gpt
description: Get a review, a critique or a second opinion from a web chat the user is already signed into (ChatGPT, Claude, Gemini, …) — hand it a file, a diff or a question, and read the reply back as text. Use when the user says "review with GPT", "让 ChatGPT review 一下", "ask the ChatGPT I have open", "去 ChatGPT 里看看它怎么说", "get a second opinion from Gemini", or asks you to pull the latest answer out of a chat page. Goes through the user's logged-in browser session, so it needs no API key and reaches whichever models they have open.
---

# review-with-gpt — drive a chat the user is already signed into

Sends a prompt into a browser chat and reads the answer back, using the user's own session. It reaches models the user has open, with no key and no account setup.

**What leaves the machine.** The prompt is posted to that service under the user's account. For private material, say plainly that you are sending it there, and keep credentials out of the prompt.

## Before you start

- **Find the tab.** Never assume which tab is the target — list them:
  ```
  osascript -e 'tell application "Google Chrome" to get URL of every tab of window 1'
  ```
  Match on URL or title. If there is no matching tab, ask the user to open the chat rather than opening one yourself (they may have several accounts signed in).

- **Probe the JS route.** Chrome's dictionary has exactly one spelling of this command — `execute <tab> javascript <text>`:
  ```
  osascript -e 'tell application "Google Chrome" to execute (tab <N> of window 1) javascript "1"'
  ```
  A value back → take [the JS route](#the-js-route-preferred). `-1723 Access not allowed` → JavaScript from Apple Events is off: ask for **View → Developer → Allow JavaScript from Apple Events**, and take the input route meanwhile.

- **Build the helpers** — `scripts/run-js.py` and `scripts/wait-answer.py` for the JS route; `scripts/hotkey.swift` and `scripts/click.swift` for the input route:
  ```
  swiftc -O scripts/hotkey.swift -o /tmp/review-hotkey
  swiftc -O scripts/click.swift  -o /tmp/review-click
  ```
  `click` takes the same screen coordinates as `screencapture -R`, origin at the top-left of the main display, so a point you read off a capture can be clicked directly.

## Choosing a route

| | JS route | input route |
|---|---|---|
| Needs | Allow JavaScript from Apple Events | nothing but the helpers |
| Drives | the page's own DOM, by selector | the mouse and keyboard |
| Survives another tab stealing focus | yes | no |
| Give it | a long prompt, a scripted hand-off | a page whose DOM you cannot address |

The input route sends keystrokes to whatever has focus, and something else can take focus mid-run (see Traps). Prefer the JS route whenever the probe returns a value.

## The JS route (preferred)

`run-js.py` runs one snippet in the tab and prints what the snippet returns. Every snippet must return `JSON.stringify(...)` — Chrome passes the value to AppleScript, which has no object type.

**Done when, for all five steps:** the printed value says what the step expects. Read it; do not chain two steps on one assumption.

### Step 1 — Find the composer, and check what you found

The first `[contenteditable="true"]` is **not** necessarily the composer. A conversation can hold a canvas / writing block, which mounts before the composer and takes that slot: writing to it silently edits the user's document. Identify by structure, and print the ancestor chain before writing anything:

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

**Done when:** the chain names the composer (and the length matches the draft you expect — `0` for an empty one).

### Step 2 — Put the prompt in

Two dead ends first, both verified: a synthetic `ClipboardEvent('paste')` is accepted and ignored — the handler calls `preventDefault` and never reads untrusted `clipboardData` — and the site's paste path (a "Pasted text" chip) belongs to real keystrokes only. `document.execCommand('insertText', …)` is the one that lands, because the editor's own state updates.

Carry the text in as base64, which is all ASCII and so survives the AppleScript string whole:

```
python3 - <<'PY'
import base64, subprocess, sys
b64 = base64.b64encode(open('/tmp/prompt.md','rb').read()).decode()
for i in range(0, len(b64), 60000):
    js = "window.__b64 = (window.__b64 || '') + '%s'; 'ok ' + window.__b64.length;" % b64[i:i+60000]
    print(subprocess.run([sys.executable, 'scripts/run-js.py', '<N>'], input=js,
                         capture_output=True, text=True).stdout.strip())
PY
```

Then decode once, and insert in slices, checking the length after every one:

```js
// once
var bin = atob(window.__b64), bytes = new Uint8Array(bin.length);
for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
window.__p = new TextDecoder('utf-8').decode(bytes); window.__i = 0;
JSON.stringify({chars: window.__p.length});
```

```js
// per slice, until window.__i == window.__p.length
var el = findComposer(); el.focus();                       // findComposer as in Step 1
var r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
var s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
var slice = window.__p.slice(window.__i, window.__i + 9000);
var ok = document.execCommand('insertText', false, slice);
window.__i += slice.length;
JSON.stringify({ok: ok, at: window.__i, total: window.__p.length, composerLen: el.innerText.length});
```

`insertText` is slow — seconds per 9k slice, so a 74KB prompt is a couple of minutes of slices. Expect no chip: the text goes in inline, and the composer grows tall while it does.

**Done when:** `at == total` and `composerLen` is in the same range as `total` (the rendered text runs a little longer: markdown headings and list items become their own blocks).

### Step 3 — Send

```js
JSON.stringify({composerChars: findComposer().innerText.length,
  send: !!document.querySelector('button[aria-label="Send"]')});
```

```js
document.querySelector('button[aria-label="Send"]').click();
```

A click through the DOM is enough — no focus, no coordinates. (If the button is missing, the composer is empty as far as the page is concerned: go back to Step 2 rather than clicking harder.)

**Done when:** two readings agree — the composer is empty **and** a stop control exists (`button[aria-label="Stop"]`, or "ChatGPT is responding" on the page).

### Step 4 — Wait, and detect a stall

Measure the **answer itself**, not the stop button. The button can stay on while the model is thinking, and it can also stay on after the model has stopped producing anything.

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
JSON.stringify({
  stop: !!document.querySelector('button[aria-label="Stop"]'),
  blocks: blocks.length,
  current: current,
  chars: text.length,
  head: text.slice(0, 120)
});
```

The ready-made poller runs this check and saves the answer:

```
python3 scripts/wait-answer.py <N> --out /tmp/review-answer.md
```

It watches the **current turn's** prose block, not only the Stop button. Exit `0` = answer saved; `2` = no usable answer in this turn; `3` = stalled (Stop on, no growth for `--stall-polls`); `4` = hard cap. Exit `3` is a signal to inspect the page, not permission to click Stop. The snippet is the same check when you need to diagnose a poll by hand.

Poll every ~20s in a background job rather than blocking. A new turn starts the length from near zero, so require **no stop control and two equal readings in a row** before reading the answer.

**Done when:** the stop control is gone and the answer length has held still across two polls.

**Do not wait forever.** If the stop control is still on and both `chars` and the visible progress have not changed for six polls (about two minutes; `--stall-polls` changes it), read [When the answer stops early](#when-the-answer-stops-early). If the page is visibly thinking or writing, keep waiting up to the ~10-minute cap; the recovery section distinguishes that from a stall.

### Step 5 — Read the answer

Read the **last non-empty prose block**. That is the answer container in this build, and it works even while the assistant turn has no label body yet. For another provider, substitute that page's answer container; the turn/stall rules below are the same.

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

Reject these, and keep waiting or go to the recovery section:

- `current` is false — the block belongs to an **earlier turn**.
- `head` starts with `You said:` — that is the **user prompt**, not the answer. It happens when the assistant body is still empty and a label-based walk climbs into the conversation container.
- `chars` equals the prompt's length and the head is the prompt's first line.
- `chars` is 0 while the stop control is on.

Only if `[class*="prose"]` is absent, fall back to the turn labels. Use the **last** `ChatGPT said:` label and stop at the first ancestor with a real answer body; if the walk reaches a container that includes `You said:`, the answer is not ready:

```js
var labels = [].slice.call(document.querySelectorAll('[class*="sr-only"]'))
  .filter(function(e){ return /^ChatGPT said/.test((e.innerText || '').trim()); });
var n = labels[labels.length - 1];
while (n && (n.innerText || '').length < 50) n = n.parentElement;
var text = n ? n.innerText.replace(/^ChatGPT said:?/, '').trim() : '';
JSON.stringify({turns: labels.length, chars: text.length,
  head: text.slice(0, 120), userPrompt: /^You said:/.test(text)});
```

The body includes the turn's own chrome (a "Thought for …"/"Worked for …" summary above the answer). Split it off, or keep it: the answer itself starts after that line.

**Done when:** the head is the answer's opening, and it is not the prompt or the conversation history. Save the text where the work needs it, and report it in the reply rather than only in a file.

## When the answer stops early

A web chat can stall in three different ways. They need different responses.

| What you see | What it is | What to do |
|---|---|---|
| Stop on, answer `chars` unchanged for 6 polls (~2 min), **and** the page shows no thinking/progress change | **Stalled** generation | Stop once, read the partial, continue or shrink the prompt |
| Stop off, answer ends mid-sentence or with an open code fence | **Truncated** answer | Send a short continuation prompt |
| Stop on for minutes, but `head`/`chars` is the prompt or `You said:` | **False answer** — extraction walked into the user turn | Do not treat it as output; keep reading the answer container, or stop and use the recovery prompt |

Do not confuse a stall with legitimate long reasoning. A reasoning model may show `Thinking` / `Working` for several minutes before the first prose block. If the page is visibly thinking, or the turn's status line is still changing, it is not a stall yet: wait. Apply the 6-poll rule only when both the answer and the visible progress have stopped changing. Give the whole turn a hard cap (about 10 minutes) and watch for **new prose content**, not just the stop button.

### Recover a stalled or truncated answer

1. **Stop once.** Click the stop control only when the stall criteria hold. Wait two seconds; read the last non-empty prose block as `partial` **only if `current` is true**. If `current` is false, there is no partial answer from this turn to continue — go to step 3.
2. **If `partial` is real content** (the head is the review, not `You said:`), continue in the same thread:
   ```
   你刚才的回答在下面这里中断了。请从断点继续，只输出剩余部分，不要重复已经输出的内容，也不要重新审查全文。
   断点前的最后一句/标题：
   <last 2–3 lines of partial>
   ```

   In an English chat:

   ```
   Your previous answer stopped at the point below. Continue from there and output only the remainder. Do not repeat what you already wrote and do not restart the review.
   Last line/heading before the stop:
   <last 2–3 lines of partial>
   ```

   Send it as a normal new turn. Verify a new stop control appears and the answer grows; then run Step 4 again.
3. **If `partial` is empty, is only the prompt echo, or the model keeps stalling**, do not keep poking it. Build a **smaller** prompt: keep the question, the changed functions and the tests; drop the full-file dumps. A 70–80KB review prompt is a stall risk; 20–40KB is more reliable. Resend the smaller prompt as a new turn and say once that it replaces the earlier attempt.
4. **If the answer is truncated at the end** (no stop control, text stops mid-word, code fence unclosed), the same continuation prompt works. If the thread has already produced most of the review, ask only for the missing sections, not the whole answer again.
5. **Never** treat a stopped answer as complete just because the stop button is gone. Check the tail: a usable review ends with a verdict or a natural sentence, not mid-sentence.

Long prompts also make the model slower and more likely to wander. Prefer one focused brief plus follow-up turns over one 70KB dump. If the provider has a thinking-level selector, a lower level is often enough for a structured code review.

---

## The input route

Take this when JavaScript from Apple Events is off, or when the page's DOM is not addressable.

### Step 1 — Put the composer in front of you

```
osascript -e 'tell application "Google Chrome" to activate'
osascript -e 'tell application "Google Chrome" to set active tab index of window 1 to <N>'
```

Then scroll the conversation to its end — the composer sits at the bottom and may be below the fold. Click into the message area, then press `Page Down` (`/tmp/review-hotkey "" 121`) a few times, or `Cmd+End` (`/tmp/review-hotkey c 119`) once.

**Done when:** a screenshot shows the composer's placeholder text ("Ask ChatGPT" and friends) somewhere on screen.

### Step 2 — Locate the composer, and write the position down

Capture a strip and look at it. Take the placeholder's screen position, and click a little to its **left** (inside the input, away from the send button).

```
screencapture -x -R<left>,<top>,<width>,<height> /tmp/review-composer.png
```

**Done when:** a caret is visible in the composer in a fresh screenshot.

### Step 3 — Paste the prompt

```
pbcopy < /tmp/prompt.md
/tmp/review-hotkey c 9        # Cmd+V
```

Re-check which tab is active in the moment before the paste: the keystroke goes to whatever has focus, and a background tab that takes activation (a dev server, a live-reload page) will receive it instead. Click twice first when Chrome was not already frontmost — the first click is spent activating it.

**Done when:** a fresh screenshot shows the prompt arrived. **A long prompt arrives as an attachment, not as text** — ChatGPT turns it into a "Pasted text" chip above the placeholder, and the placeholder still reads "Ask ChatGPT". Look _above_ the input line, not at it. One chip per paste: remove the extras (each chip's ×), or they all get sent.

### Step 4 — Send

Re-read the send button's position first: a chip shifts it up by roughly one chip height, and it turns from a filled blue circle into a stop square once it is generating.

```
/tmp/review-click <x> <y>
```

`Enter` (`/tmp/review-hotkey "" 36`) is the fallback: it does nothing when focus drifted, where the send button does.

**Done when:** the composer is empty **and** the button has become a stop square. Both, checked in one screenshot.

### Step 5 — Wait for the answer to finish

Poll the strip from Step 2, which contains the send button:

```
screencapture -x -R<the Step 2 strip> /tmp/review-state.png
```

**Done when:** the send button is a filled circle again instead of a stop square. Answers worth asking for take one to three minutes.

If the stop square remains and the strip is pixel-identical for six polls (check `shasum -a 256 /tmp/review-state.png`), treat it as a stall unless a spinner or the answer text is visibly changing. Press Stop once, run Step 6 to copy the partial, then use the continuation prompt from [When the answer stops early](#when-the-answer-stops-early). Do not wait past the ~10-minute cap.

### Step 6 — Copy the page text out

```
for i in $(seq 8); do /tmp/review-click 800 500; /tmp/review-hotkey "" 121; done   # Page Down to the end
/tmp/review-click 800 450        # a point in the message area, well above the composer
/tmp/review-hotkey c 0          # Cmd+A
/tmp/review-hotkey c 8          # Cmd+C
LC_ALL=en_US.UTF-8 pbpaste > /tmp/review-page.txt
```

The two x/y pairs are the ones used on a 1920×1080 Chrome window: `(800, 500)` to focus the message column, `(800, 450)` to select inside it. Pick your own from a screenshot — what matters is that both are in the message area and nowhere near the composer, since a click that lands in the composer makes `Cmd+A` select the draft instead of the page.

`LC_ALL=en_US.UTF-8` is required: without a locale, `pbpaste` converts to ASCII and every CJK character becomes `?`.

**Done when:** `/tmp/review-page.txt` is non-empty and readable. Chrome copies only what is **rendered**, so treat this as the visible tail of the conversation, not its whole history.

### Step 7 — Cut the answer out of the dump

The dump includes the sidebar and earlier turns. Split on the "Worked for …" marker that precedes the answer:

```
python3 - <<'PY'
import pathlib, re
t = pathlib.Path('/tmp/review-page.txt').read_text()
answer = re.split(r'\nWorked for [^\n]*\n', t)[-1].strip()
pathlib.Path('/tmp/review-answer.md').write_text(answer)
print(len(answer), "chars");  print(answer[:400])
PY
```

**Done when:** the head of the extracted text is the answer's own opening. If it opens mid-sentence, the answer is longer than what Chrome copied — scroll further and copy again.

---

## Traps

**Keep the display awake while you drive the page.** A sleeping display makes `screencapture` return pure black and makes accessibility presses look like they do nothing — the app is fine, the screen is off, and both symptoms read as bugs. Hold it for the run:

```
caffeinate -d -u -t 300 &
```

**Verify every step, in the currency of the route.** The failures here are silent: a JS write into the wrong element, a paste that landed nowhere, a click that only activated the window, an `Enter` that went to another app. The JS route returns values — read them. The input route returns nothing — screenshot it.

**A canvas is not the composer.** Before writing, print the target's ancestor chain (Step 1). If a canvas did get written to, its own toolbar has an **Undo last edit** button; press it until the canvas's length is back to what it was before (the dump you took first is the reference).

**When unsure whether it sent, look before sending again.** Step 3's criterion answers it. Sending twice puts the same prompt in the thread twice, and the user sees it.

**`sr-only` labels are boundaries, not answer bodies.** When the assistant turn is still empty, walking up from `ChatGPT said:` can reach a container that starts with `You said:` and contains the prompt. That is the false-answer trap. Prefer the last non-empty `[class*="prose"]` block, and reject any head that starts with `You said:`.

**Stop on is not progress.** A stalled generation can leave the stop control on with no new prose. Poll the answer length, not only the button; use the stall rules in [When the answer stops early](#when-the-answer-stops-early).

**The model picker is part of the page.** If the user cares which model or thinking level answers, that selector sits next to the send button and has to be set deliberately — the default is whatever they last chose by hand, which may not be what they expect for this request.

## Appendix: what this Chrome + ChatGPT build exposes

Checked on 2026-10-16, Chrome 141 on macOS, with a live conversation. The site owns these; re-read the DOM when one stops matching rather than concluding the chat is broken.

| Thing | This build |
|---|---|
| `execute javascript "…" in tab N` | not in the dictionary — use `execute (tab N of window 1) javascript "…"` |
| `#prompt-textarea` | absent; the composer is a ProseMirror `[contenteditable="true"]` under `ComposerLayoutInput…` |
| first `[contenteditable="true"]` | can be a **canvas / writing block** (`writing-block-editor`, `group/writing-block-surface`) |
| `[data-testid="send-button"]` | absent; the control is `button[aria-label="Send"]`, and it becomes `button[aria-label="Stop"]` while writing |
| `[data-message-author-role]`, `article[data-testid^="conversation-turn"]` | absent (0 matches in a conversation with turns) |
| turn boundary | `h4.sr-only` (or any `[class*="sr-only"]`) reading "You said:" / "ChatGPT said:" |
| `[data-testid]` anywhere | 3 in total, none of them composer, send or turns — the site uses hashed CSS-module classes |
| long-prompt paste | synthetic paste events are ignored; `execCommand('insertText')` works, in slices |
| answer body | last non-empty `[class*="prose"]` block; `ChatGPT said:` labels are turn boundaries, and a label walk can fall into the user prompt while the answer is empty |
| stalled generation | stop control can stay on with no new prose; treat three unchanged polls as a stall and use [When the answer stops early](#when-the-answer-stops-early) |
