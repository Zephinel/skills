# Templates, Portability, and Multi-language Architecture

Read this reference when drafting sections from scratch, handling multi-surface publishing (GitHub + npm/PyPI/plugin stores), or creating/syncing multi-language READMEs.

## Canonical section order (adapt to project archetype)

Include only sections that carry real information. Keep the README an index and link out to `docs/` once any setup or reference block grows past ~15–20 lines.

1. **Header + One-liner**
   - Project logo/icon (`align="right"` or centered), single `# Project Name`, language switcher (`English | [中文](README.zh.md)`) when multi-language.
   - 3–6 objective badges (published version, license, CI, supported host/runtime).
   - Bold one-sentence value proposition + compact jump bar (4–6 core anchors, not 12).
2. **Immediate proof (Demo / Hero visual / Minimal snippet)**
   - **UI / Plugin / App**: hero screenshot or bento proving the headline capability, plus a 1–2 sentence caption.
   - **Library / CLI**: a 5–10 line copy-pasteable code or shell example with expected output *before* long setup prose.
3. **Current status (when published ≠ `main` or pre-1.0)**
   - One portable blockquote separating published stable behavior from unreleased `main` features and naming the exact verified host/runtime version.
4. **Install & Quick Start**
   - Zero-to-running commands with no `$` prompt prefix.
   - If `main` has unreleased headline features, provide both the published install command and the `main` install path, plus what a user sees on first use in each build.
5. **Features at a glance**
   - Prefer a crisp two-column Markdown table (`| Feature | What it adds |`) over walls of bold-prefixed bullets; link each row to its deep doc in `docs/` when present.
6. **Documentation index** (for multi-doc repos)
   - Document-level table (`| Document | What it covers |`) covering usage, limitations, architecture, development, verification, and changelog.
7. **Getting the code, Prerequisites, and Local development**
   - Keep **Getting the code** separate from Prerequisites: exact public HTTPS clone command from `git remote -v`, plus path/submodule/LFS/Codespaces gotchas (for example, cloning repos whose org/project name contains spaces into a plain local folder).
   - **Prerequisites**: list every tool with version + link; when a runtime version is pinned (`.nvmrc`, `volta`, `.tool-versions`, `engines`), explain *why* the pin matters (e.g. native ABI mismatch) and include a verification command (`node --version`).
   - **Local dev vs production**: state the dev command, port/URL, and "it's working" signal separately from `build` / `test` / `deploy`.
8. **Contributing & License**
   - Link to Issues, `CONTRIBUTING.md`, `CHANGELOG.md`, and `LICENSE` — never paste their contents into the README.

## Registry and surface portability

| Surface | Caveats | Safe pattern |
| --- | --- | --- |
| **npmjs / Crates** | GitHub-only alerts (`> [!NOTE]`, `> [!WARNING]`) render literally as `[!NOTE]`; relative images work only if packed in `files`. | Use `> **Note**: …` / `> **Current status**: …`, pack referenced assets in `files` (or use absolute URLs), and use absolute repo URLs for repo-only links. |
| **PyPI** | GitHub-only alerts render literally, and **relative image paths do not render at all** on PyPI project pages. | Use portable bold blockquotes and absolute image/doc URLs (tag-pinned or `raw.githubusercontent.com`) when the README feeds PyPI `long_description`. |
| **Package tarballs (`package.json` `files`)** | Relative links to repo-only files (`docs/usage.md`, `CHANGELOG.md`) break on npmjs when `docs/` is not packed. | Link repo-only files with absolute repository URLs (`https://github.com/<org>/<repo>/blob/main/...`). |
| **Shipped `docs/` inside tarball** | Relative links like `../test/...` or `../.agents/...` break when unpacked from npm. | Convert links pointing outside `files` to absolute repository URLs. |
| **In-app plugin detail pages** | Full GitHub READMEs (badges, clone commands, CI tables) overwhelm a narrow settings/detail pane. | When the host supports a dedicated detail file (e.g. `locale/detail.*.md`), keep the detail page focused on settings/daily use and reserve the README for GitHub/registry discovery. |
| **GitHub-only / private repos** | Public shields.io badges cannot read private repos; GitHub alerts (`> [!NOTE]`) are fine here. | Omit broken public badges on private repos; use GitHub alerts sparingly only when the README never ships to external registries. |
| **Azure Repos** | Renders from the default branch; org/project names with spaces produce URL-encoded paths that break scripts. | Provide `git clone "<url>" plain-folder-name` explicitly. |

## Multi-language README architecture

When a repository maintains two or more README languages (for example `README.md` + `README.en.md`, or `README.md` + `README.zh.md` + `README.ja.md`):

### 1. Primary file and naming
- Keep existing repository conventions first. For a new multi-language setup, put the primary audience's language in `README.md` (usually English for global OSS, or Chinese when the primary users are Chinese-speaking) and use concise BCP-47 tags for siblings: `README.en.md`, `README.zh.md`, `README.ja.md`, `README.ko.md`.
- Only add extra languages when the project actually serves those audiences (for example, the product already ships localized UI like `locale/zh.json`) and can keep them in sync with a parity check.

### 2. Language switcher bar
Place a switcher directly under the H1 in every file, with the current language as plain text and siblings as relative links:

```markdown
<!-- In README.md (English primary) -->
English | [中文](README.zh.md) | [日本語](README.ja.md)

<!-- In README.zh.md -->
[English](README.md) | 中文 | [日本語](README.ja.md)
```

### 3. Structural & factual parity
- **Identical heading depth sequence**: H1/H2/H3 outline matches 1-to-1 across all language files so readers and automated checks stay aligned.
- **Single-pass status sync**: update versions, install paths, published-vs-`main` notices, test/pack counts, and limitations across every language in the same edit.
- **Localized anchors & doc links**: each language's jump bar uses **that language's own heading slugs** (`#安装` in Chinese, `#install` in English), and links to the matching `docs/*.<lang>.md` sibling when localized docs exist.

### 4. Native phrasing & UI fidelity
- Rewrite naturally in each target language rather than translating word-for-word; respect locale punctuation (full-width `，。；（）` in Chinese, half-width in English) and keep code/identifiers verbatim.
- Match in-app UI labels to the target locale's actual dictionary (never leave untranslated button names or stray source-language fragments in a localized README).

### 5. Screenshots & package publishing
- Route language-matched screenshots (`*-zh.webp`, `*-en.webp`) exclusively to their matching README; if a fixture screenshot is single-language, state that honestly in limitations.
- Remember that npm/PyPI only display `README.md` on the registry landing page and do not render relative links to sibling Markdown files: keep relative switcher links for GitHub/fork browsing when siblings ship together, or use absolute repo URLs in `README.md`'s switcher if registry readers are expected to click through to other languages. Include sibling `README.<lang>.md` files in `package.json` `files` if they should ship in the tarball.
