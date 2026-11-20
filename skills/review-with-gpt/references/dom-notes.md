# DOM Notes & Provider Adaptation

Checked on 2026-10-16 with Chrome 141 on macOS against a live ChatGPT conversation. Sites change their DOM without notice — inspect the live DOM via `run-js.py` whenever a selector stops matching rather than assuming the chat is broken.

## What this Chrome + ChatGPT build exposes

| Thing | Observed behavior |
| --- | --- |
| `execute javascript "…" in tab N` | Not in Chrome's AppleScript dictionary — use `execute (tab N of window W) javascript "…"` |
| `#prompt-textarea` | Absent; the composer is a ProseMirror `[contenteditable="true"]` under `ComposerLayoutInput…` |
| First `[contenteditable="true"]` | Can be a **canvas / writing block** (`writing-block-editor`, `group/writing-block-surface`) — always verify the ancestor chain first |
| `[data-testid="send-button"]` | Absent; the control is `button[aria-label="Send"]`, changing to `button[aria-label="Stop"]` while writing |
| `[data-message-author-role]`, `article[data-testid^="conversation-turn"]` | Absent (0 matches in a live conversation) |
| Turn boundary | `h4.sr-only` (or `[class*="sr-only"]`) reading `"You said:"` / `"ChatGPT said:"` |
| `[data-testid]` anywhere | Only 3 on the page, none for composer, send, or turns — the site uses hashed CSS-module classes |
| Long-prompt paste | Synthetic `ClipboardEvent('paste')` is ignored; `document.execCommand('insertText', …)` works in slices |
| Answer body | Last non-empty `[class*="prose"]` block after the last `"ChatGPT said:"` boundary; a naive label walk climbs into `"You said:"` while the answer is empty |
| Stalled generation | Stop control can stay on with no new prose; treat **6 unchanged polls** (~2 min, default `--stall-polls 6`) with no visible thinking progress as a stall |

## Adapting to Claude, Gemini, or other web chats

`scripts/wait-answer.py` and the default snippets in `SKILL.md` target ChatGPT's DOM. For Claude, Gemini, or another web chat:

1. **Probe composer, send/stop buttons, and answer containers first** with `run-js.py` instead of running `wait-answer.py` blindly:
   ```js
   JSON.stringify({
     editables: [].slice.call(document.querySelectorAll('[contenteditable="true"], textarea')).map(function(e){
       var r = e.getBoundingClientRect();
       return {tag: e.tagName, role: e.getAttribute('role'), label: e.getAttribute('aria-label'),
         cls: String(e.className || '').slice(0, 50), h: Math.round(r.height), top: Math.round(r.top)};
     }),
     buttons: [].slice.call(document.querySelectorAll('button[aria-label]')).map(function(b){
       return b.getAttribute('aria-label');
     }).slice(-15)
   });
   ```
2. **Substitute the three provider-specific pieces** while keeping the same verification and stall rules:
   - Composer selector (`findComposer`)
   - Send / Stop button `aria-label` (or disabled/streaming state)
   - Current assistant turn's answer container (never read an earlier turn or the user's own prompt)
3. **If the provider blocks `execCommand('insertText')` or obscures its DOM**, fall back to [references/input-route.md](input-route.md).
