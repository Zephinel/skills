# Plain UI Copy — Checklist, Before/After Pairs, and Guardrail Blueprint

Use this reference when auditing or rewriting UI strings and when building tests or a text fence to keep wording standards enforced.

## 1. One idea per sentence (no colon/semicolon chains)

Split into two sentences. Use `because` for reasons, and parentheses `(...)` for short qualifiers in status bars, list rows, or completion hints.

| Before | After | Why |
| --- | --- | --- |
| `Nothing to change: your rules already match ${file}.` | `Nothing changed. Your rules already match ${file}.` | Two statements joined by `:`. |
| `Saved: all of this is allowed without asking.` | `Saved. All of this is allowed without asking.` | Colon before a full statement. |
| `the user did not allow ${host}; do not try to reach it another way` | `The user did not allow ${host}. Do not try to reach it another way.` | Semicolon chain + missing capitalization/period. |
| `Added ${path}. But it still cannot work there: ${path} is blocked.` | `Added ${path}. However, it still cannot work there because ${path} is blocked.` | Reason clause uses `because`. |
| `sandbox paused: it cannot enforce your rule for X` | `sandbox paused (cannot enforce rule for X)` | Short status qualifier uses parentheses. |
| `feature off, what it sends changed` | `feature off (what it sends changed)` | Comma splice in a status/value cell. |

## 2. Native phrasing and garden-path avoidance

| Before | After | Why |
| --- | --- | --- |
| `For now, the settings read before apply, or the defaults.` | `For now, the previous settings or the defaults apply.` | Garden-path participle (`before apply` reads as a prepositional phrase). |
| `listed more than once, set differently` | `listed more than once with different values` | Comma-spliced participles. |
| `each time keeps only its date` | `only the date of each entry is kept` | Garden-path (`each time` reads as "whenever"). |
| `Pi only needs the terminal view, because Pi restarts there.` | `“Pi only” needs the terminal view because Pi restarts there.` | Unquoted option name causes garden-path reading. |
| `Later, git or your shell reads this file and does what it says.` | `Git or your shell reads this file to decide what to run.` | Lone sentence-initial adverb (`Later,`). |
| `First, let a model read their code.` | `Let a model read their code first.` | Lone sentence-initial adverb (`First,`). |
| `...change what they do. So a rule cannot cover it.` | `...change what they do, so you cannot add a general rule for it.` | Lone sentence-initial `So`. |
| `the settings file can be written` | `the settings file is writable` | Usual collocation. |
| `needs more than 4 seconds` | `takes over 4 seconds` | Usual collocation. |
| `Nothing is sent to any place.` | `Nothing is sent.` | Translated literalism. |
| `hidden everywhere, also in your message` | `hidden everywhere, including in your message` | Non-native trailing `, also in`. |
| `tokens in the JWT form` | `JWT tokens` | Translated noun phrase. |
| `Folders of earlier sessions of this project` | `Folders from earlier sessions in this project` | `of … of` chain. |
| `The tool set was not changed because the tool sets file could not be changed.` | `The tool set was not changed because the settings file could not be written.` | Tongue-twister (repeated words in one sentence). |
| `Make a tool set, from nothing or based on a preset.` | `Create a tool set, empty or based on a preset.` | Non-native `from nothing`. |

## 3. Single plain verbs (no phrasal verbs or coined phrases)

| Before | After |
| --- | --- |
| `go back to the defaults` | `return to the defaults` |
| `this suggestion can come back after restart` | `this suggestion reappears after restart` |
| `The file is not written over.` | `The file is not overwritten.` |
| `Go through them one by one` | `Review them one by one` |
| `a newer result came in. It shows below.` | `A newer result is ready and shown below.` |
| `Keep them out` / `Choose which to let in` | `Hide all of them` / `Choose which to allow` |
| `sends data out` | `sends data to the network` |
| `To try again, go to Tools.` | `To try again, open /settings → Tools.` |
| `close the files of passwords and keys to commands` | `block commands from password and key files` |
| `run a command with your passwords and keys open` | `run a command with access to your password and key files` |
| `needs your OK` / `kept closed` | Avoid coined idioms completely; use plain verbs (`ask`, `allow`, `block`, `hide`). |

## 4. Actor boundaries and no code-internal view

| Before | After | Why |
| --- | --- | --- |
| `Blocked by the permission extension. ...` | `This call was blocked. ...` | Never name the internal extension/middleware. |
| `App could not close secret files to commands.` | `Commands could not be blocked from password and key files.` | Internal guardrail work has no user-facing actor; keep passive. |
| `Make sure that App can write to its settings folder.` | `Make sure that the permission settings folder is writable.` | App is not the extension; qualify which settings folder. |
| `how strict your settings are` | `how strict your permission settings are` | Distinguish component settings from host app settings. |
| `For both, secrets are hidden again.` | `For both, secrets are hidden.` | "again" leaks an internal two-pass implementation detail. |
| `these entries count as one, as they do when the rules apply` | `these duplicate entries are combined` | Describe the visible result, not internal layering. |
| `A tool comes here when you set it.` | `Tools appear here once you set them to allow, ask or deny.` | Inanimate objects do not act like people. |
| `Your choice saves the file on this computer at once.` | `Once you choose, the file is saved on this computer.` | Avoid inanimate agent (`Your choice saves`). |

## 5. One word for one thing

Define a project vocabulary table and enforce it everywhere:

| Concept | Prefer | Avoid |
| --- | --- | --- |
| Rule decisions | `allow`, `ask`, `deny` | `refuse`, `always ask`, `never allow`, `ask first`, `never run`, `needs your approval` |
| Logged outcomes | `allowed`, `blocked` | mixing `refused` / `denied` / `stopped` for the same column |
| Switches (setting rows) | `on`, `off` | `yes`, `no`, or action labels like `Turn X off` |
| Dialog answers | `Yes`, `No`, or concrete verb (`Remove`, `Turn it on`) | `on`, `off` |
| Removal | `Remove` | `Forget`, `Take out`, `Stop allowing` |
| Environment variables | `environment variable`, `variable` | `setting`, `lines of settings` |
| No interactive screen | `this session cannot show a question` | mixing `cannot ask here` / `cannot ask the user` |
| Assistant vs auxiliary model | One fixed name for the assistant, `a model` for auxiliary reviewers/classifiers | calling the assistant `the model` in one sub-extension and its product name elsewhere |
| Aligned block labels | Nouns (`Allowed`, `Valid fields`) | Verb phrases (`Can be`, `Known here`) |

## 6. Truth to behavior, modals, and referents

- **No `may`:** `The search may read secret files.` → `The search possibly reads secret files.`
- **No `can` for chance:** `The service can charge for each question.` → `The service possibly charges for each question.`
- **Present tense:** `cannot be checked as App would open it` → `cannot be checked as App opens it`
- **No false absolutes:** `Passwords and keys: files never opened` → `Passwords and keys` (when an exception or bypass mode exists).
- **Repeat nouns in options:** `Relaxed: run simple ones` → `Relaxed: run simple commands in the allowed folders`.
- **Keep referents unambiguous:** `Package tools keep downloaded files in these folders. When commands can change them…` → `When commands can change these folders…`
- **Match actual controls:** If a prompt omits `Always allow` (for dangerous or once-only calls), the warning and habit hint must not mention `“Always allow”`.

## 7. Edge-value composition checks

Always test parameterized strings with these inputs:

1. **Zero / one / two / three-plus items:**
   - `0`: empty string or explicit `none` (no trailing colon or dangling separator).
   - `1`: singular verbs and pronouns (`Read it` / `it is too broad`), not plural (`they are`).
   - `2`: `A and B`.
   - `3+`: `A, B and C`, never `A and B and C`.
2. **Flags that omit a prefix sentence:**
   - `added ? "Added X. However, ..." : "Cannot work in X ..."` — never render a standalone `"However, ..."` with no preceding sentence.
3. **Punctuation from external reasons or fragments:**
   - Strip trailing `.` before placing a reason inside `(...)`: `trimDot(why)` prevents `(Works only on macOS.).`.
   - Avoid adding a second `.` when an external message already ends with `.` / `!` / `?`: `endPeriod(reason)` prevents `Rate limit exceeded..`.
4. **Missing or invalid fields:**
   - Invalid timestamps or missing model names must not leave leading spaces (` 12:30 · allowed`) or dangling slashes (`no model/`).

## Systematic guardrail blueprint

Use these four layers together so wording standards hold as new features are added:

1. **Type-level separation for fragments vs sentences:**
   - Keep standalone toast/page notices as plain `string`.
   - Keep embedded reason fragments as a distinct branded type (for example `Told`, lowercase, no trailing period). Passing a full-sentence toast into a parenthetical reason slot then fails typecheck.
2. **Dynamic exhaustive iteration over closed enums/maps:**
   - Export `WHY`, `BECAUSE`, `FLAGGED`, or equivalent `Record<Reason, string>` maps.
   - Assert key parity (`Object.keys(WHY).sort()` vs `Object.keys(BECAUSE).sort()`) and run wording checks over every entry dynamically — never copy enum values into a static test array that goes stale.
3. **Behavioral + edge-value tests:**
   - Call every parameterized formatter across `0 / 1 / 2 / 3+`, missing values, and period-terminated external errors.
   - Invoke the real prompt builder for every category (standard, dangerous, once-only, ask-rule) and assert that every quoted button name in `warning` or `habit` exists verbatim in `request.options`.
4. **Comment-stripped text fence over all user-facing copy files:**
   - Parse string and template literals from every user-facing copy file (stripping `//` and `/* */` comments, `import` lines, and explicitly excluded calibrated model-only blocks).
   - Run a shared list of banned regexes (modals, wrong tenses, coined phrases, internal module names, banned synonyms, invalid actor-verb pairs, technical jargon, semicolons, double punctuation) over every extracted literal.
   - Keep the fence fast (< 100 ms) so it runs on every normal test invocation; skip only the source-reading test under mutation testing if the repo mutates source files in place.

## Chinese UI copy adaptation

When the target product's UI is in Chinese, keep the structural and product principles unchanged and adapt the prose rules:

- **One idea per sentence:** Split comma-spliced or semicolon-chained statements into short sentences; put the condition before the result (`如果……，……`) and name the recovery action (`要修改，请打开……`).
- **One word for one thing:** Pick one term per concept across every screen (e.g., `允许 / 询问 / 拒绝`, `开启 / 关闭`, `移除`, `环境变量`), and do not mix synonyms (`禁止` / `拦截` / `驳回` for the same rule decision).
- **Clear actor boundaries:** Never blame internal modules (`权限扩展拦截了此调用` → `此调用已被拦截`), and never conflate a component's settings with host app settings (`权限设置` vs `设置`).
- **Natural Chinese, not translated English:** Avoid stiff passive chains (`被……所……`), redundant `的` chains, and English word-order calques.
- **Same call-site and edge-value rigor:** Check `0 / 1 / 多个`, punctuation inside parentheses (full-width `（）` vs half-width, no `。）。`), and verify warnings only name buttons actually rendered on that dialog.

## Sample scanner config

Use a project-local JSON file with `python3 scripts/scan_copy.py --config plain-ui-copy.json <targets>` to add repository-specific vocabulary rules and narrow exemptions without modifying the shared script:

```json
{
  "extraRules": [
    {
      "id": "no-internal-module",
      "name": "do not name the internal extension",
      "pattern": "\\bthe permission extension\\b",
      "flags": "i"
    },
    {
      "id": "banned-synonyms",
      "name": "banned rule synonyms (use allow / ask / deny / blocked)",
      "pattern": "\\b(always ask|refuse[ds]?|needs your approval|stop allowing)\\b",
      "flags": "i"
    },
    {
      "id": "bare-settings",
      "name": "qualify component settings (use 'permission settings')",
      "pattern": "\\byour settings\\b",
      "flags": "i"
    }
  ],
  "disableRules": [],
  "allow": [
    "You Shall Pass",
    "cloud providers"
  ],
  "excludeBlocks": [
    {
      "file": "model-copy.ts",
      "start": "  investigation:",
      "end": null
    }
  ],
  "maxWords": 25
}
```
