# Skills

Four reusable agent skills for explaining technical topics, auditing and locking down plain-language UI copy, improving existing skills, and getting a review from a web chat you are already signed into.

| Skill | Purpose |
| --- | --- |
| [explain](skills/explain/SKILL.md) | Explain concepts, mechanisms, procedures, and differences with clear language and focused visuals. |
| [plain-ui-copy](skills/plain-ui-copy/SKILL.md) | Audit, rewrite, and systematically enforce plain-language UI copy with STE-inspired rules, call-site edge checks, and a zero-dependency scanner. |
| [skill-enhance](skills/skill-enhance/SKILL.md) | Improve an existing skill's triggers, scope, workflow, references, scripts, and evaluations. |
| [review-with-gpt](skills/review-with-gpt/SKILL.md) | Send a file, a diff, or a question to a signed-in web chat and read the answer back. |

## Install

Install any of the skills with the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add Zephinel/skills --skill explain --skill plain-ui-copy --skill skill-enhance --skill review-with-gpt
```

To install all four globally for Codex without prompts:

```bash
npx skills add Zephinel/skills \
  --skill explain --skill plain-ui-copy --skill skill-enhance --skill review-with-gpt \
  --agent codex --global --yes
```

Update installed global copies:

```bash
npx skills update explain plain-ui-copy skill-enhance review-with-gpt --global
```

## explain

`explain` combines ASD-STE100-inspired writing principles with the smallest useful visual. It can use prose, pseudocode, call trees, component trees, file trees, Mermaid diagrams, diffs, or a focused HTML page.

The response follows the language of your request unless you explicitly choose another language. Code identifiers and UI labels keep their original spelling. The skill applies selected clarity principles; formal ASD-STE100 compliance requires the applicable rules, dictionary, and verification.

Example prompts using Codex's `$skill-name` syntax:

```text
$explain Explain why a cache can return stale data. Use a small diagram.
$explain Compare these two implementations and show the change as a diff.
$explain Explain this deployment procedure in Chinese.
```

## plain-ui-copy

`plain-ui-copy` audits, rewrites, and locks down user-facing UI copy (prompts, settings pages, help lines, buttons, notices, status lines, CLI help, and chat-visible error/refusal messages). It applies ~80% ASD-STE100 principles, native phrasing, one word per concept, actor boundaries, call-site edge-value checks, and systematic tests or text fences so wording standards do not regress when new features land.

It includes a zero-dependency Python 3 scanner (`scripts/scan_copy.py`) supporting JS/TS, Python, JSON, and C-style source files with project-local config rules, narrow allowlists, and block exclusions.

```text
$plain-ui-copy Audit the user-facing copy files in this repo and rank issues by frequency.
$plain-ui-copy 审查这个扩展的所有用户提示文案，修正问题并加上文本栅栏测试。
$plain-ui-copy Run scan_copy.py on src/copy/ and check edge-value rendering for pluralization and punctuation.
```

## skill-enhance

`skill-enhance` improves a skill that already exists. It can make a focused correction or review the whole skill while preserving its intended scope.

Optional maintenance capabilities require explicit approval:

- An eval package adds acceptance checks and, when requested, comparison with a frozen previous version.
- A self-improve package records evidence inside the target skill and requires the eval package. The user controls acceptance of proposed changes.

Ordinary improvements do not install either package by default. Automated Stage 3 evaluations support Linux and macOS. On Windows, use WSL or another compatible Unix environment.

```text
$skill-enhance Improve the description in ./skills/report-writer so it triggers on the right requests.
$skill-enhance Review all of ./skills/report-writer. Improve its workflow without adding eval or self-improve packages.
$skill-enhance Add acceptance evals to ./skills/report-writer and compare against a frozen copy of its current version.
```

## review-with-gpt

`review-with-gpt` posts a prompt into a chat page the user already has open in Chrome — ChatGPT, Claude, Gemini — and reads the answer back as text. It uses the signed-in browser session, so it needs no API key. It can send a file, a diff, or a question, wait for the turn, and recover from a stalled or truncated answer.

The skill runs on macOS with Google Chrome. The preferred route drives the page through JavaScript from Apple Events, which requires **View → Developer → Allow JavaScript from Apple Events** in Chrome. The fallback route pastes and clicks with compiled Swift helpers; it needs macOS accessibility and screen-recording permission, and it is slower and less reliable.

The prompt leaves the machine under the user's account. Do not put credentials in it.

```text
$review-with-gpt Ask the ChatGPT tab I have open to review this diff.
$review-with-gpt 去 ChatGPT 里问问它这段迁移脚本有什么风险。
$review-with-gpt Pull the latest answer out of the Gemini tab.
```

## Repository layout

```text
.
├── LICENSE
├── README.md
├── .github/workflows/skill-enhance-checks.yml
└── skills/
    ├── explain/
    │   ├── SKILL.md
    │   ├── agents/
    │   └── references/
    ├── plain-ui-copy/
    │   ├── SKILL.md
    │   ├── agents/
    │   ├── references/
    │   └── scripts/
    ├── review-with-gpt/
    │   ├── SKILL.md
    │   └── scripts/
    └── skill-enhance/
        ├── SKILL.md
        ├── assets/
        ├── evals/
        ├── references/
        └── scripts/
```

Each skill includes its own supporting resources. The example skills under `skill-enhance/evals/fixtures/` are test fixtures used by the regression suite.

## Development checks

Run the complete `skill-enhance` regression suite from the repository root with Bash and Python 3 available:

```bash
bash skills/skill-enhance/scripts/test-all.sh
python3 skills/plain-ui-copy/scripts/test_scan_copy.py
```

The suite checks shell and Python syntax, JSON data, evaluation lifecycle, path safety, reference isolation, evidence handling, memory binding, and lock behavior. GitHub Actions runs it on Linux and macOS with Python 3.12.

To check skill discovery without installing anything:

```bash
npx skills add . --list
```

## License

[MIT](LICENSE).
