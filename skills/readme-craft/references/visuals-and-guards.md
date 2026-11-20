# Visual Screenshot Audit and Mechanical Anti-Rot Guards

Read this reference when reviewing README screenshots or adding automated checks to prevent README drift.

## Visual screenshot audit checklist

Always inspect the actual image files before signing off on a README:

1. **First-screen honesty**: does the hero image demonstrate the core promise?
   - *Fail*: claiming "interactive UI" while showing a static 3-row table; claiming "prompt history rail and recovery" while showing a single-turn chat with no rail.
   - *Pass*: hero shows the defining interaction in a live state (e.g. an active segmented control, hovered history tick, or real populated panel).
2. **Data and chart plausibility**: check rendered charts, KPIs, and thumbnails for model/fixture artifacts (flat trend lines contradicting a headline peak KPI, placeholder `Lorem ipsum`, or zeroed counters).
3. **Bento grid consistency**:
   - All tiles in a multi-panel grid share a coherent scale (avoid 2× zoomed panels beside 1× panels).
   - No clipped titles, cut-off keyboard shortcuts (`⌥⌘`), cropped bottom lines, or stray background text fragments peeking from behind popovers.
4. **Surface and framing cleanliness**:
   - No double/triple nested borders around inline blocks.
   - No dark/black solid rectangles from transparent-background SVGs rendered onto dark thumbnail boxes (give demo SVGs an explicit background fill).
   - No floating scroll-to-bottom buttons or unrelated third-party plugin chips leaking into the capture.
5. **Language consistency**: a Chinese README hero should not mix English settings chrome unless clearly documented as a shared English fixture.
6. **Capture provenance**: separate deterministic fixture captures (reproducible via a script) from live-model/real-session captures (documented in `docs/screenshots/*.md` with date, host version, prompt, and crop method).

## Mechanical anti-rot guards

Documentation drifts whenever accuracy depends on human memory. Prefer small, fast scripts wired into `npm run check` / CI:

| Guard | What it catches |
| --- | --- |
| **Local links & anchors** | Broken relative links, missing `#heading-slug` anchors, and broken absolute `blob/main/` links to tracked repo files. |
| **Clone URL parity** | README clone URL drifting from `git config --get remote.origin.url` (normalized to public HTTPS). |
| **Portability lint** | GitHub-only `> [!` alert syntax inside published `README*.md`. |
| **Privacy / hygiene lint** | Personal host paths (`/Users/<name>/`, `/home/<name>/`), LAN IPs, or private service labels leaking into shipped docs. |
| **Tarball boundary lint** | Relative links from shipped `docs/` that resolve outside `package.json` `files`. |
| **Asset manifest check** | Missing image files, orphaned assets in `assets/`, or mismatched language-specific screenshots across `README.md` and `README.<lang>.md`. |
| **Multi-language heading parity** | Heading-level (`#`, `##`, `###`) drift, missing language switchers, or cross-language anchor/link mismatches across `README.md` and every `README.<lang>.md`. |
| **Index budget check** | README ballooning back into a manual (line count ceiling + negative check for sections that belong in `docs/`). |
| **Contextual fact snapshot** | If the README quotes live test/suite/pack counts, validate them *in context* against a single measured JSON snapshot updated only from real command output — never bare numbers. |

### Quick shell checks (POSIX/bash/zsh safe, zero dependencies)

```bash
# Collect existing README.md and README.*.md safely (works in bash and zsh even with a single README.md)
readmes=()
while IFS= read -r f; do readmes+=("$f"); done < <(find . -maxdepth 1 -type f \( -name 'README.md' -o -name 'README.*.md' \) | sort)

# 1. Line budget check
wc -l "${readmes[@]}"

# 2. Multi-language heading-depth parity against README.md
for f in "${readmes[@]}"; do
  [ "$f" = "./README.md" ] && continue
  diff -u <(grep -E '^#{1,3} ' ./README.md | sed 's/[^#].*//') \
          <(grep -E '^#{1,3} ' "$f" | sed 's/[^#].*//') || echo "heading drift: $f"
done

# 3. Portability & personal-path check (for permanent CI guards, skip fenced code blocks)
! grep -nE '^\s*>\s*\[!' "${readmes[@]}"
! grep -rnE '/Users/[A-Za-z0-9._-]+/' "${readmes[@]}" $([ -d docs ] && echo docs)
```
