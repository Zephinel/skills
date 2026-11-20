# Fallback: The Input Route (Mouse & Keyboard)

Use this route only when **Allow JavaScript from Apple Events** is off in Chrome, or when the target chat page's DOM is not addressable.

Because this route sends keystrokes to whichever window has focus, another app or tab stealing focus mid-run will receive your input. Verify every step with a fresh screenshot.

## Prerequisites

1. **Keep the display awake.** A sleeping display makes `screencapture` return pure black and makes accessibility presses silently fail. Hold it for the full 10-minute run cap:
   ```bash
   caffeinate -d -u -t 600 &
   ```
2. **Build the Swift helpers** (resolve `<skill-dir>` to the directory containing `review-with-gpt/SKILL.md`):
   ```bash
   swiftc -O "<skill-dir>/scripts/hotkey.swift" -o /tmp/review-hotkey
   swiftc -O "<skill-dir>/scripts/click.swift"  -o /tmp/review-click
   ```
   `click` takes the same screen coordinates as `screencapture -R`, origin at the top-left of the main display, so a point read off a capture can be clicked directly. macOS Accessibility and Screen Recording permissions are required.

## Step 1 — Put the composer in front of you

```bash
osascript -e 'tell application "Google Chrome" to activate'
osascript -e 'tell application "Google Chrome" to set active tab index of window <W> to <N>'
```

Scroll the conversation to its end — the composer sits at the bottom and may be below the fold. Click into the message area, then press `Page Down` (`/tmp/review-hotkey "" 121`) a few times, or `Cmd+End` (`/tmp/review-hotkey c 119`) once.

**Done when:** a screenshot shows the composer's placeholder text ("Ask ChatGPT" or the provider's equivalent) on screen.

## Step 2 — Locate the composer and record its coordinates

Capture a strip and inspect it. Read the placeholder's screen position and click a little to its **left** (inside the input, away from the send button):

```bash
screencapture -x -R<left>,<top>,<width>,<height> /tmp/review-composer.png
```

**Done when:** a caret is visible in the composer in a fresh screenshot.

## Step 3 — Paste the prompt

```bash
pbcopy < /tmp/prompt.md
/tmp/review-hotkey c 9        # Cmd+V
```

Re-check which tab is active right before pasting: a background tab that takes activation (a dev server, a live-reload page) will receive the keystroke instead. Click twice first when Chrome was not already frontmost — the first click only activates Chrome.

**Done when:** a fresh screenshot shows the prompt arrived. **A long prompt arrives as an attachment, not inline text** — ChatGPT turns it into a "Pasted text" chip above the placeholder, and the placeholder still reads "Ask ChatGPT". Look _above_ the input line, not at it. Keep one chip per paste (remove extras via each chip's ×).

## Step 4 — Send

Re-read the send button's position first: an attachment chip shifts it up by roughly one chip height, and it turns from a filled circle into a stop square while generating.

```bash
/tmp/review-click <x> <y>
```

`Enter` (`/tmp/review-hotkey "" 36`) is a fallback only when focus is confirmed — it does nothing if focus drifted, whereas clicking the send button still works.

**Done when:** one fresh screenshot shows both that the composer is empty **and** the send button has become a stop square.

## Step 5 — Wait for the answer to finish

Poll the Step 2 strip containing the send button every ~20s:

```bash
screencapture -x -R<the Step 2 strip> /tmp/review-state.png
```

**Done when:** the send button is a filled circle again instead of a stop square. Answers worth asking for typically take 1–3 minutes.

If the stop square remains and the strip is pixel-identical for **6 polls** (~2 minutes; check `shasum -a 256 /tmp/review-state.png`), treat it as a stall unless a spinner or answer text is visibly changing. Press Stop once, run Step 6 to copy any partial answer, then follow the recovery steps in `SKILL.md`. Do not wait past the ~10-minute cap.

## Step 6 — Copy the page text out

```bash
for i in $(seq 8); do /tmp/review-click 800 500; /tmp/review-hotkey "" 121; done   # Page Down to the end
/tmp/review-click 800 450        # a point in the message area, well above the composer
/tmp/review-hotkey c 0          # Cmd+A
/tmp/review-hotkey c 8          # Cmd+C
LC_ALL=en_US.UTF-8 pbpaste > /tmp/review-page.txt
```

`(800, 500)` and `(800, 450)` are reference points for a 1920×1080 Chrome window — pick your own from a screenshot so both land inside the message column and well away from the composer (clicking inside the composer makes `Cmd+A` select the draft instead of the page).

`LC_ALL=en_US.UTF-8` is required: without a UTF-8 locale, `pbpaste` converts to ASCII and turns every CJK character into `?`.

**Done when:** `/tmp/review-page.txt` is non-empty and readable. Chrome copies only what is **rendered**, so treat it as the visible tail of the conversation rather than full history.

## Step 7 — Cut the answer out of the dump

The dump includes the sidebar and earlier turns. On ChatGPT, split on the `"Worked for …"` / `"Thought for …"` marker preceding the answer (on Claude/Gemini, inspect the dump and split on that provider's last assistant turn boundary):

```bash
python3 - <<'PY'
import pathlib, re
t = pathlib.Path('/tmp/review-page.txt').read_text(encoding='utf-8')
answer = re.split(r'\n(?:Worked|Thought) for [^\n]*\n', t)[-1].strip()
pathlib.Path('/tmp/review-answer.md').write_text(answer, encoding='utf-8')
print(len(answer), "chars")
print(answer[:400])
PY
```

**Done when:** the head of the extracted text is the answer's opening. If it starts mid-sentence, scroll further and copy again.
