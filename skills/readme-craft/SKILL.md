---
name: readme-craft
description: Draft, audit, localize, and optimize repository README files as concise, truthful landing pages and indexes for users, developers, contributors, and AI coding agents. Use when asked to create, review, slim down, rewrite, translate, or sync README files, check README links/screenshots, or enforce registry portability (e.g. "起草 README", "优化 README", "审查 README", "补充中英文 README"). Not for full API manuals, changelogs, or in-app UI copy.
---

# README Craft

Turn a repository README into a **truthful landing page and index**: a reader decides whether to keep reading in 3–5 seconds, gets running with zero guesswork, and reaches deep docs through verified links rather than scrolling through a bloated manual.

## Modes

| Request | Mode | Output |
| --- | --- | --- |
| Missing or stub README | **Create** | Drafted `README.md` derived strictly from repo evidence |
| "Review / audit this README" | **Audit** | Prioritized P0/P1/P2 report + verdict (no edits unless asked) |
| "Improve / optimize / slim / rewrite" | **Optimize** | Targeted audit → in-place edits (+ `docs/` split if requested) + verification summary |
| "Add / translate / sync README.<lang>.md" | **Localize** | Add or sync multi-language READMEs with heading parity, localized anchors/links, and language switchers |

Match the user's language for reports. Keep the README in the repository's own language(s).

## Step 1 — Ground in repository truth (before writing a line)

Inspect the actual repository first; never guess commands, remotes, versions, or counts:

1. **Manifests & scripts**: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `Makefile`, CI workflows, `.devcontainer/`, `Dockerfile`.
2. **Remote & version state**: `git remote -v` (normalize SSH to public HTTPS clone URL), latest published version/tag vs unreleased `main` features (`CHANGELOG.md` `## [Unreleased]`), and runtime version pins (`.nvmrc`, `volta`, `.tool-versions`, `engines`).
3. **Packaging boundary**: check `files` / `.npmignore` / manifest rules to know which files ship in the published tarball and which stay repo-only.
4. **Existing docs & visuals**: `docs/`, `CONTRIBUTING.md`, `LICENSE`, `AGENTS.md`, language pairs (`README.en.md` / `README.zh.md`), and every image referenced by the README.

**Completion criterion:** every command, URL, version number, and file path you plan to write is backed by a file or command output you just read.

## Step 2 — Apply the core contract

### 1. Index, not manual
- **First screen earns the rest**: bold one-liner stating concrete value (no "A tool that…", no throat-clearing, no AI hype like *seamless / robust / comprehensive / cutting-edge / blazing fast*), 3–6 objective badges (version, license, CI, runtime), and an immediate working example or real screenshot **before** deep setup prose.
- **Line budget**: aim for **~100–240 lines** for a mature project. Push multi-step runbooks, full option catalogs, architecture deep-dives, FAQ walls, and historical verification logs into `docs/` and replace them with a compact documentation index table.
- **Four audiences**: serve **Users** (quickest path to value), **Developers** (get the code, prerequisites with *why* version pins matter, dev mode vs production build), **Contributors** (link `CONTRIBUTING.md` / `LICENSE` / `CHANGELOG.md`, never paste them), and **AI coding agents** (copy-pasteable commands without `$` prefixes, unambiguous paths, `AGENTS.md` pointer if present).

### 2. Truth to shipped reality
- **Separate stable vs unreleased `main`**: when a headline feature lives on `main` but is not yet in the published package (`npm`, `PyPI`, marketplace), state both install paths and what each build actually does on first use.
- **Honest verification claims**: name the exact runtime/host version verified; never claim unverified compatibility or extrapolate counts by arithmetic.
- **Commands run as written**: copy exact script names from manifests; omit placeholder tokens the reader must invent unless explicitly explained.

### 3. Portability & hygiene
- **Cross-surface Markdown**: if the README renders outside GitHub (npm, PyPI, plugin registries), use portable bold blockquotes (`> **Note**: …`) instead of GitHub-only `> [!NOTE]` alerts, which render literally there.
- **Tarball-safe links**: links from a published README to repo-only files (`docs/`, `CHANGELOG.md` excluded from the package) use absolute repository URLs (`https://github.com/<org>/<repo>/blob/main/...`). Links inside shipped `docs/` stay within the tarball or use absolute URLs.
- **Zero private leaks**: strip personal host paths (`/Users/<name>/`), LAN IPs, private launchd/service labels, and credentials from public READMEs and shipped docs.

### 4. Multi-language READMEs
- **Structure & switchers**: keep `README.md` and every `README.<lang>.md` sibling locked to the same heading-depth sequence, section order, and version/status facts, with a working language switcher directly under H1 in every file.
- **Native localization**: write naturally in each target language (matching target-locale UI labels verbatim, proper locale punctuation, localized jump-bar anchors, and links to matching `docs/*.<lang>.md` siblings) rather than word-for-word translation.
- **Asset & packaging alignment**: pair language-specific screenshots (`*-zh.webp` / `*-en.webp`) to their matching README, state honestly if any fixture is single-language, and include all shipped READMEs in package manifests (`files`) when publishing.

For section templates, project-type variants (app / library / CLI / plugin), registry edge cases, and full multi-language rules, read [references/templates-and-portability.md](references/templates-and-portability.md).

## Step 3 — Audit screenshots and visuals (whenever the README shows UI)

Never trust an image filename — inspect the actual rendered images on disk:

- **Headline match**: the hero image must prove the lead claim (e.g. an interactive widget if the hook promises interactive UI, not a static table; multi-turn UI if the copy promises history).
- **Composition & crop**: check for clipped text/shortcuts, mismatched tile scaling in bento grids, broken/black thumbnails (especially transparent-background SVGs), double borders, language mixing inside a localized README, or unrelated third-party plugins leaking into the frame.
- **Provenance**: for non-deterministic live-session captures, keep a brief provenance note under `docs/screenshots/` recording environment, prompt, and crop boundaries.

For the full visual audit checklist and mechanical anti-rot guards, read [references/visuals-and-guards.md](references/visuals-and-guards.md).

## Step 4 — Execute and verify

### When auditing (Audit mode)
Output a concise report ordered by severity (**P0** factual/broken/leaked → **P1** stale/bloated/unportable → **P2** polish):

```markdown
## README Audit: <repo>

### Summary
1–2 sentences on overall quality and primary gap.

### Findings
| Priority | Area | Issue | Fix |
| --- | --- | --- | --- |

### Visuals (if applicable)
Per-image verdict and defects.

### Verdict
Ready / Needs targeted edits / Needs restructure
```

### When creating, optimizing, or localizing (Create / Optimize / Localize mode)
1. Preserve every verified fact; fix structure, opening hook, truthfulness, portability, and broken links. When slimming a long README, never silently discard unique setup or troubleshooting facts — link to existing `docs/` files, or move long sections into `docs/` with links (confirm with the user before creating new doc files if the edit scope was README-only).
2. Keep `README.md` and every `README.<lang>.md` sibling locked to the same heading depth sequence, section order, language switchers, and status facts.
3. Run the repo's existing doc/link/manifest checks (or verify every local link, anchor, image path, and clone URL before finishing).
4. If the repo lacks automated README guards and the user is optimizing a maintained project, suggest or add lightweight checks from [references/visuals-and-guards.md](references/visuals-and-guards.md).

**Completion criterion:** every command matches the codebase, every local link/anchor/asset exists on disk, published-vs-`main` boundaries are explicit, all multi-language READMEs match in structure and language switchers, and zero personal paths or unportable alerts remain in registry-published READMEs.
