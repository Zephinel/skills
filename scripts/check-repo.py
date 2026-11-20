#!/usr/bin/env python3
"""Zero-dependency repository validation for all skills and docs.

Checks:
1. Every skills/<name>/SKILL.md has valid frontmatter (`name` == folder,
   non-empty `description` <= 1024 chars).
2. Every skill includes agents/openai.yaml with display_name, short_description,
   and default_prompt.
3. All relative Markdown links in README.md, skills/*/SKILL.md, and
   skills/*/references/*.md (outside fenced code blocks) resolve to existing files.
4. All Python files under scripts/ and skills/*/scripts/ compile cleanly.
5. All JSON files under skills/ parse as strict JSON (no NaN/Infinity).
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")


def parse_frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing opening '---' on line 1")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("missing closing '---' for frontmatter")

    data: dict[str, str] = {}
    i = 1
    while i < end_idx:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if not match:
            raise ValueError(f"malformed frontmatter line {i + 1}: {line!r}")
        key, raw_val = match.group(1), match.group(2).strip()
        if raw_val in (">", "|", ">-", "|-"):
            block: list[str] = []
            i += 1
            while i < end_idx and (lines[i].startswith("  ") or not lines[i].strip()):
                block.append(lines[i].strip())
                i += 1
            val = " ".join(part for part in block if part)
            data[key] = val
            continue
        if len(raw_val) >= 2 and raw_val[0] == raw_val[-1] and raw_val[0] in ('"', "'"):
            raw_val = raw_val[1:-1]
        data[key] = raw_val
        i += 1
    return data


def strip_fenced_blocks(text: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        m = FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if not in_fence:
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                continue
            if marker[0] == fence_char and len(marker) >= fence_len:
                in_fence = False
                continue
        if not in_fence:
            out.append((lineno, line))
    return out


def check_markdown_links(md_path: Path, errors: list[str]) -> None:
    text = md_path.read_text(encoding="utf-8")
    for lineno, line in strip_fenced_blocks(text):
        # Ignore inline code spans so example markdown syntax isn't treated as a link.
        scrubbed = re.sub(r"`[^`]*`", "", line)
        for match in LINK_RE.finditer(scrubbed):
            raw_target = match.group(1).strip()
            if not raw_target:
                continue
            target = raw_target.split()[0].strip("<>")
            if target.startswith(("#", "http://", "https://", "mailto:")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            decoded = urllib.parse.unquote(path_part)
            resolved = (md_path.parent / decoded).resolve()
            if not resolved.exists():
                rel = md_path.relative_to(REPO_ROOT).as_posix()
                errors.append(f"{rel}:{lineno}: broken relative link -> {raw_target}")


def check_openai_yaml(skill_dir: Path, errors: list[str]) -> None:
    yaml_path = skill_dir / "agents" / "openai.yaml"
    rel = yaml_path.relative_to(REPO_ROOT).as_posix()
    if not yaml_path.is_file():
        errors.append(f"{rel}: missing agents/openai.yaml")
        return
    content = yaml_path.read_text(encoding="utf-8")
    for field in ("display_name:", "short_description:", "default_prompt:"):
        if field not in content:
            errors.append(f"{rel}: missing required field '{field[:-1]}'")


def check_skills(errors: list[str]) -> None:
    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    if not skill_dirs:
        errors.append("skills/: no skill directories found")
        return

    for skill_dir in skill_dirs:
        skill_md = skill_dir / "SKILL.md"
        rel = skill_md.relative_to(REPO_ROOT).as_posix()
        if not skill_md.is_file():
            errors.append(f"{rel}: missing SKILL.md")
            continue
        try:
            fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        except ValueError as exc:
            errors.append(f"{rel}: {exc}")
            continue

        name = fm.get("name", "")
        desc = fm.get("description", "")
        if name != skill_dir.name:
            errors.append(f"{rel}: frontmatter name {name!r} != directory {skill_dir.name!r}")
        if not desc:
            errors.append(f"{rel}: empty description")
        elif len(desc) > 1024:
            errors.append(f"{rel}: description length {len(desc)} exceeds 1024 chars")

        check_openai_yaml(skill_dir, errors)
        check_markdown_links(skill_md, errors)

        ref_dir = skill_dir / "references"
        if ref_dir.is_dir():
            for ref_md in sorted(ref_dir.glob("*.md")):
                check_markdown_links(ref_md, errors)


def check_python_syntax(errors: list[str]) -> None:
    py_files: list[Path] = []
    repo_scripts = REPO_ROOT / "scripts"
    if repo_scripts.is_dir():
        py_files.extend(sorted(repo_scripts.glob("*.py")))
    for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        sdir = skill_dir / "scripts"
        if sdir.is_dir():
            py_files.extend(sorted(sdir.glob("*.py")))

    with tempfile.TemporaryDirectory() as tmp:
        for py_file in py_files:
            cfile = os.path.join(tmp, f"{py_file.stem}.pyc")
            try:
                py_compile.compile(str(py_file), cfile=cfile, doraise=True)
            except py_compile.PyCompileError as exc:
                rel = py_file.relative_to(REPO_ROOT).as_posix()
                errors.append(f"{rel}: python syntax error: {exc.msg}")


def check_json_files(errors: list[str]) -> None:
    def reject_constant(val: str) -> None:
        raise ValueError(f"non-finite JSON constant: {val}")

    for json_file in sorted(SKILLS_DIR.rglob("*.json")):
        try:
            json.loads(json_file.read_text(encoding="utf-8"), parse_constant=reject_constant)
        except (ValueError, json.JSONDecodeError) as exc:
            rel = json_file.relative_to(REPO_ROOT).as_posix()
            errors.append(f"{rel}: invalid JSON: {exc}")


def main() -> int:
    errors: list[str] = []
    readme = REPO_ROOT / "README.md"
    if readme.is_file():
        check_markdown_links(readme, errors)
    check_skills(errors)
    check_python_syntax(errors)
    check_json_files(errors)

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(f"\nRepo check failed with {len(errors)} error(s).", file=sys.stderr)
        return 1

    skill_count = len([p for p in SKILLS_DIR.iterdir() if p.is_dir()])
    print(f"OK: {skill_count} skills, README links, Python syntax, and JSON files passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
