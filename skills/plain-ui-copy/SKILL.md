---
name: plain-ui-copy
description: Audit, rewrite, and lock down user-facing UI copy using STE-inspired plain language, one word per concept, call-site edge-value checks, and automated tests or text fences. Use when reviewing or editing UI strings, prompts, settings, buttons, status bars, CLI help, or chat-visible error/refusal text (e.g. "审查 UI 文案", "规范文案并加文本栅栏", "audit user-facing wording"). Not for marketing copy, calibrated model-only prompts, or verbatim third-party/user data.
---

# Plain UI Copy

Audit, write, and lock down user-facing UI copy so it reads as if a native speaker wrote it for a non-developer, stays true to runtime behavior, and cannot silently regress when new features land.

## Scope and boundaries

Apply this skill to every text a user reads in the interface:

- prompts, confirmations, page titles, section headers, and help lines
- setting rows, option lists, labels, buttons, tooltips, and key hints
- status lines, toast notices, CLI help, and error messages
- refusal or block reasons returned by middleware/tools when the host also displays them in chat or logs

Do **not** rewrite:

- model-only prompts that were empirically calibrated against a model (change those only with fresh measurement)
- verbatim text from user files, external tools, or third-party services (unless filtering out raw OS errors like `ENOENT`)
- code comments or internal developer logs

## Core wording standard

Write about 80% of the way to ASD-STE100, combined with natural native English. For concrete before/after pairs for every rule, read [Checklist and before/after pairs](references/checklist.md).

### 1. Sentence craft (STE-inspired)

1. **One idea per sentence.** Do not join two statements with a colon (`:`) or semicolon (`;`). Split into two sentences, use `because` for a reason, or use parentheses `(...)` in compact lines (status bars, list rows, completion hints).
2. **Short sentences.** Keep instructions to about 20 words and descriptions to about 25 words.
3. **Clear actor boundaries.** Use active voice when the user, the visible product/assistant, or a named feature acts. Internal machinery (an extension, middleware, storage layer, or guardrail) has no actor the user knows: keep it passive and short, and never name the internal module (`This call was blocked.`, not `Blocked by the permission extension.`). Never confuse a component's own settings with the host app's settings (`permission settings`, not bare `your settings`).
4. **Instructions start with the verb.** Write `Open /settings to change this.` or `Make sure that the folder is writable.`
5. **Present tense.** Write `asks`, not `will ask`; `opens`, not `would open`; `lets`, not `would let`.
6. **Keep small words and clear referents.** Keep `that` where it prevents telegraph style (`the folders that you allow`). Repeat the noun in option lists instead of leaving dangling pronouns (`simple ones`, `them`). Do not put two mismatched nouns under one verb (`opens those files and runs those commands`, not `both run`).
7. **No phrasal verbs, idioms, or garden-path participles.** Use single plain verbs (`remove` not `take out`, `return` not `go back`, `reappear` not `come back`, `overwrite` not `write over`, `review` not `go through`, `allow`/`hide` not `let in`/`keep out`). Avoid participle chains or misleading word order (`the previous settings apply`, not `the settings read before apply`; `listed more than once with different values`, not `listed more than once, set differently`; `only the date of each entry is kept`, not `each time keeps only its date`).
8. **`can` for ability or permission only; never `may`.** Do not use `may` (ambiguous between permission and chance) and do not use `can` for chance. Use `possibly` for chance (`The search possibly reads secret files.`).
9. **Native phrasing, not translated word order.** Avoid coined phrases (`needs your OK`, `kept closed`, `files of passwords`), tongue-twisters (the same word twice in one sentence), technical jargon (`consent`, `configured`, `provider`, `hostname`, `exempt`), lone sentence-initial adverbs (`Later,`, `First,`, `Then`, `So`), `of … of` chains, and inanimate subjects acting like people (`Tools appear here`, not `A tool comes here`). Use standard collocations (`is writable`, not `can be written`; `takes over 4 seconds`, not `needs more than 4 seconds`; `even though`, not trailing `though`; `is shown below`, not `it shows below`).

### 2. One word for one thing

Keep one vocabulary table for the whole product and enforce it on every page, dialog, and sub-extension:

- One word per concept — never show a second word as a gloss (`careful: very sure`), and never invent synonyms across pages (e.g., calling the assistant `Pi` in one screen and `the model` in another, or calling environment variables `settings`).
- **Rule outcomes** use one consistent trio (for example `allow`, `ask`, `deny` — never mixing `refuse`, `always ask`, `never allow`, or `needs your approval`).
- **Switches** are setting rows showing current state (`on` / `off`), never action labels (`Turn X off`) that hide the current state.
- **Dialog answers** use `Yes` / `No` or concrete action verbs (`Remove`, `Turn it on`, `Keep my text`), never `on` / `off`.
- **Same situation, same wording** across every surface (for example, always `this session cannot show a question`, never `cannot ask here` on another page).
- **Labels** in aligned blocks are nouns (`Allowed`, `Valid fields`), not verb phrases (`Can be`).
- **Titles that ask** are grammatical questions. **Buttons** state their concrete effect.

### 3. Truth to behavior and user value

- **Promise nothing untrue.** Never write `always` or `never` when a rule, mode, or exception can override it — add `unless …` or state the real condition.
- **Match actual controls.** Warnings, hints, and descriptions may only name buttons or options that actually exist on that screen, using their exact label.
- **State what the user gains** when asking them to turn on a feature, and **give a concrete example** when a rule is abstract.
- **Keep raw system errors off screen.** Map OS error codes (`ENOENT`, `EACCES`, stack traces) to plain recovery instructions; pass through only actionable service messages.
- **Respect layout budgets.** Check fixed-width constraints (such as single-line help rows at 80 columns) so moving the cursor does not jump page height.

## Language boundary

- **Report language:** Write your audit report and explanation in the language of the user's request while quoting UI strings verbatim in the product's UI language.
- **English UI copy:** Apply all 9 sentence-craft rules, one-word-for-one-thing vocabulary, and the bundled scanner (`scripts/scan_copy.py`). Do not claim formal ASD-STE100 compliance or certification without checking against the official standard and dictionary.
- **Chinese (or other non-English) UI copy:** Keep the language-independent principles — one idea per sentence, short sentences, clear actor boundaries (never name the internal extension/middleware), one word per concept, no coined or translated jargon, truthful conditions (`除非…`), matching actual button labels, and full edge-value rendering (0/1/many, punctuation, empty values). Do **not** apply English word counts, English modal rules (`may`/`would`), or English phrasal-verb regexes to non-English text; instead supply language-appropriate `extraRules` and `disableRules` when using the scanner.

## Workflow: auditing existing copy

Do not do a surface-level pass over isolated strings. Follow all four steps:

### Step 1 — Inventory surfaces and bootstrap project vocabulary

Locate every place user-facing copy lives:

- primary and split copy files, shared UI component copy, and loaded sub-extension copy
- chat-visible refusal/error strings returned by gates, middleware, or tools
- non-copy source files (verify no user-facing literals escaped into UI/business code)

If the repository has no existing wording guide or vocabulary table yet, infer the current actor names (product/assistant vs auxiliary models vs internal machinery), recurring terms, and exemptions (calibrated model prompts, verbatim external text) from existing copy and docs. Confirm any ambiguous product-level naming choice with the user before rewriting in bulk.

Record explicitly what is in scope and what is exempted.

### Step 2 — Run the bundled scanner, then read aloud

Run the zero-dependency Python 3 scanner first to catch mechanical defects quickly with exact line numbers (resolve `<skill-dir>` to the directory containing this `SKILL.md`):

```bash
python3 "<skill-dir>/scripts/scan_copy.py" <copy-file-or-dir> [...]
python3 "<skill-dir>/scripts/scan_copy.py" --config plain-ui-copy.json --max-words 25 <copy-file-or-dir> [...]
```

Supported file types: `.ts`, `.tsx`, `.js`, `.jsx`, `.mjs`, `.cjs`, `.py`, `.json`, `.swift`, `.go`, `.rs`, `.java`, `.kt`. The scanner strips comments and `import`/`export ... from` lines automatically, supports `--format json`, inline ignore comments (`plain-ui-copy: ignore-next-line`, `ignore-start`/`ignore-end`), and a project JSON config (`extraRules`, `disableRules`, `allow`, `excludeBlocks`, `maxWords`). See [Sample config](references/checklist.md#sample-scanner-config).

The scanner catches mechanical patterns only — still read every string aloud as a user who does not know the implementation to catch:

- awkward/translated phrasing, coined terms, tongue-twisters, and abstract sentences missing examples
- vocabulary drift across files or sub-extensions
- internal concepts leaking onto the screen (`the extension`, internal stages, implementation mechanisms)
- dead/unused copy left behind after refactors (delete superseded copy rather than keeping it around)

### Step 3 — Trace call sites and render edge values

Inspect how parameterized copy functions are actually called and composed. Render every formatter with edge values:

- counts: `0`, `1`, `2`, `3+` (singular/plural agreement, `A, B and C` vs `A and B and C`)
- missing, empty, or invalid values (no dangling separators, slashes, or leading spaces)
- boolean flags (for example, `added = false` must not leave a sentence starting with `However,`)
- external reasons that already end with `.` composed into parentheses or sentences (no `..` or `.).`)
- prompt warnings and hints checked against the exact `options` array built at the call site

### Step 4 — Report clearly before or alongside fixes

1. Rank findings by how often the user sees them (high-frequency chat/prompt copy first, rare edge cases last).
2. For each finding, give: exact file + line, current text, rule broken, and suggested replacement.
3. Explicitly state whether a proposed fix is a **patch** (editing strings only) or a **systematic fix** (preventing the whole class from returning), before being asked.
4. State clearly what was checked and what was not checked.

## Workflow: fixing copy systematically

Editing strings one by one is a patch. Whenever auditing reveals recurring or post-review regressions, combine the copy edits with structural and test guardrails. See [Systematic guardrail blueprint](references/checklist.md#systematic-guardrail-blueprint) for concrete patterns.

1. **Fix the root mechanism by construction where possible:**
   - Separate standalone notice sentences (`string`) from embedded reason fragments (a branded/typed fragment such as `Told`, lowercase with no trailing period) so a full sentence cannot slip into a `(...)` slot.
   - Pass the real rendered button label (or `undefined` when absent) from the prompt builder into warning and hint formatters instead of hardcoding button names.
   - Normalize trailing punctuation in shared helpers (`trimDot` for parenthetical inserts, `endPeriod` for external messages).
   - Delete dead copy and remove superseded per-case workarounds.

2. **Add dynamic exhaustive tests (no hardcoded key lists):**
   - Export closed reason/concern maps (`Record<Reason, string>`) and iterate `Object.keys(...)` dynamically so any newly added reason is checked automatically.
   - Assert 1:1 key parity when two tables describe the same domain (for example, user-facing reasons and chat/model-facing reasons).

3. **Add edge-value and behavioral truth tests:**
   - Render every parameterized copy function across `0 / 1 / 2 / 3+`, missing/invalid inputs, flags, and period-terminated external errors.
   - Construct real prompts across modes/categories (normal, dangerous, once-only, ask-rule) and assert that warnings/hints only quote button labels present in `options`.

4. **Add a text fence across all user-facing copy files:**
   - When future features can add new keys before dedicated behavioral tests exist, add a test that extracts string/template literals (stripping comments and `import` paths, and scoping out exempted model-only prompts) across all user-facing copy files.
   - Fail on banned modals (`may`), wrong tenses (`would`/`will`), internal-module names, coined phrases, banned synonyms, invalid actor-verb pairs, inconsistent terms, semicolons, and double punctuation.
   - If the project uses mutation testing, mark only the source-reading fence test to skip under mutation runs while keeping rendered/behavioral wording tests active.

5. **Verify completely:**
   - **Grep tests for changed button/prompt strings before running long suites:** interactive or TUI walker tests that wait for an old button label (such as `Read it with` after pluralizing to `Read them with`) can hang until timeout instead of failing fast.
   - Update existing test assertions that matched the old wording.
   - Run the project's full test suite, typecheck, diff check, and (if applicable) changed-line mutation check.
   - Confirm no background test processes remain running.

## Traps

- **False positives in text fences:** Relative `import "../..."` paths trigger double-punctuation rules (`..`), and proper nouns or established phrases (such as `You Shall Pass` vs `\byou\b`, or `cloud providers` vs `provider`) can collide with generic rules. Strip `import` lines and add narrow `allow` entries (or lookbehinds) rather than weakening the rule globally.
- **Hardcoded enum lists in wording tests:** A static array of reason codes silently misses newly added reasons. Always export the closed map and iterate its keys dynamically.
- **Reusing a standalone notice in an embedded fragment slot:** Passing a capitalized, period-terminated toast sentence into `(${reason})` produces `(Sentence.).`. Separate the two shapes by type or naming convention.
- **Rewriting calibrated model prompts:** Do not fold empirically tuned classifier/judge prompts into the UI wording fence unless the user explicitly plans a fresh measurement pass.
