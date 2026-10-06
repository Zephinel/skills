# Skills

Two reusable agent skills for explaining technical topics and improving existing skills.

| Skill | Purpose |
| --- | --- |
| [explain](skills/explain/SKILL.md) | Explain concepts, mechanisms, procedures, and differences with clear language and focused visuals. |
| [skill-enhance](skills/skill-enhance/SKILL.md) | Improve an existing skill's triggers, scope, workflow, references, scripts, and evaluations. |

## Install

Install either or both skills with the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add Zephinel/skills --skill explain --skill skill-enhance
```

To install both globally for Codex without prompts:

```bash
npx skills add Zephinel/skills \
  --skill explain --skill skill-enhance \
  --agent codex --global --yes
```

Update installed global copies:

```bash
npx skills update explain skill-enhance --global
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
```

The suite checks shell and Python syntax, JSON data, evaluation lifecycle, path safety, reference isolation, evidence handling, memory binding, and lock behavior. GitHub Actions runs it on Linux and macOS with Python 3.12.

To check skill discovery without installing anything:

```bash
npx skills add . --list
```

## License

[MIT](LICENSE).
