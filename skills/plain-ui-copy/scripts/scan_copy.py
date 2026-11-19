#!/usr/bin/env python3
"""Zero-dependency UI copy scanner for plain-ui-copy.

Extracts user-facing string/template literals from JS/TS, Python, JSON, and
C-style source files (stripping comments and import paths) and checks them
against universal STE/plain-English rules plus optional project config rules.

Usage:
  python3 scan_copy.py <file_or_dir> [...]
  python3 scan_copy.py --config plain-ui-copy.json src/copy/
  python3 scan_copy.py --max-words 25 --format json extensions/permissions/copy.ts
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tokenize
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

SUPPORTED_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".py", ".json",
    ".swift", ".go", ".rs", ".java", ".kt",
}

C_LIKE_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".swift", ".go", ".rs", ".java", ".kt",
}

TEMPLATE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}

DEFAULT_RULES: list[dict[str, str]] = [
    {
        "id": "modal-may",
        "name": "may (use can for ability/permission, possibly for chance)",
        "pattern": r"\bmay\b",
        "flags": "i",
    },
    {
        "id": "future-conditional",
        "name": "future/conditional tense (prefer present tense over would/will)",
        "pattern": r"\b(would|will)\b",
        "flags": "i",
    },
    {
        "id": "coined-phrase",
        "name": "coined or unnatural phrase",
        "pattern": r"\b(needs your ok|kept closed|files of passwords|passwords and keys open)\b",
        "flags": "i",
    },
    {
        "id": "garden-path",
        "name": "garden-path phrasing",
        "pattern": r"\b(read before apply|each time keeps)\b",
        "flags": "i",
    },
    {
        "id": "non-native",
        "name": "non-native collocation or literal translation",
        "pattern": r"\b(settings from before|to any place|can be written|needs more than \d+|from nothing|shortened form)\b",
        "flags": "i",
    },
    {
        "id": "phrasal-verb",
        "name": "phrasal verb (prefer a single plain verb)",
        "pattern": r"\b(written over|go back to|come back|sends data out|let in|keep out|go through|came in)\b",
        "flags": "i",
    },
    {
        "id": "jargon",
        "name": "technical jargon",
        "pattern": r"\b(consent|configured|hostname|exempt)\b",
        "flags": "i",
    },
    {
        "id": "semicolon-chain",
        "name": "semicolon joining statements (split into sentences)",
        "pattern": r";",
        "flags": "",
        "prose_only": "true",
    },
    {
        "id": "double-punctuation",
        "name": "double punctuation",
        "pattern": r"(?<!\.)\.\.(?!\.)|\.\)\.|!\.|\?\.",
        "flags": "",
    },
    {
        "id": "repeated-word",
        "name": "repeated consecutive word",
        "pattern": r"\b([A-Za-z]{2,})\s+\1\b",
        "flags": "i",
    },
]

IGNORE_NEXT_RE = re.compile(r"plain-ui-copy:\s*ignore-next-line\b")
IGNORE_START_RE = re.compile(r"plain-ui-copy:\s*ignore-start\b")
IGNORE_END_RE = re.compile(r"plain-ui-copy:\s*ignore-end\b")
IMPORT_LINE_RE = re.compile(
    r"^\s*(?:import|export\s+(?:\*|\{[^}]*\})\s+from)\b[^;\n]*;?\s*$",
    re.MULTILINE,
)
WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")


@dataclass(frozen=True)
class Literal:
    location: str
    line: int
    text: str


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    location: str
    rule_id: str
    rule_name: str
    text: str


def compile_flags(flag_str: str) -> int:
    flags = 0
    if "i" in flag_str:
        flags |= re.IGNORECASE
    if "m" in flag_str:
        flags |= re.MULTILINE
    if "s" in flag_str:
        flags |= re.DOTALL
    return flags


def strip_excluded_blocks(source: str, rel_path: str, exclude_blocks: list[dict[str, Any]]) -> str:
    """Replace excluded ranges with matching newlines so line numbers stay accurate."""
    for block in exclude_blocks:
        target = block.get("file", "")
        if target and not (rel_path == target or rel_path.endswith("/" + target) or rel_path.endswith(target)):
            continue
        start_marker = block.get("start")
        end_marker = block.get("end")
        if not start_marker:
            continue
        start_idx = source.find(start_marker)
        if start_idx == -1:
            continue
        if end_marker:
            end_idx = source.find(end_marker, start_idx + len(start_marker))
            if end_idx == -1:
                end_idx = len(source)
        else:
            end_idx = len(source)
        removed = source[start_idx:end_idx]
        replacement = "\n" * removed.count("\n")
        source = source[:start_idx] + replacement + source[end_idx:]
    return source


def strip_imports_preserve_lines(source: str) -> str:
    def _blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    return IMPORT_LINE_RE.sub(_blank, source)


def extract_c_like_literals(source: str, allow_templates: bool) -> list[Literal]:
    """Extract string and template literals while skipping comments and preserving 1-based line numbers."""
    source = strip_imports_preserve_lines(source)
    literals: list[Literal] = []
    n = len(source)
    i = 0
    line = 1
    ignored = False
    ignore_next_line = -1

    def advance(count: int = 1) -> None:
        nonlocal i, line
        for _ in range(count):
            if i < n:
                if source[i] == "\n":
                    line += 1
                i += 1

    def handle_comment_text(comment: str, comment_end_line: int) -> None:
        nonlocal ignored, ignore_next_line
        if IGNORE_START_RE.search(comment):
            ignored = True
        if IGNORE_END_RE.search(comment):
            ignored = False
        if IGNORE_NEXT_RE.search(comment):
            ignore_next_line = comment_end_line + 1

    def skip_line_comment() -> None:
        start = i
        while i < n and source[i] != "\n":
            advance()
        handle_comment_text(source[start:i], line)

    def skip_block_comment() -> None:
        start = i
        advance(2)
        while i < n and not (source[i] == "*" and i + 1 < n and source[i + 1] == "/"):
            advance()
        advance(2)
        handle_comment_text(source[start:i], line)

    def is_ignored(at_line: int) -> bool:
        return ignored or at_line == ignore_next_line

    def read_quoted(quote: str) -> None:
        start_line = line
        out: list[str] = []
        advance()
        while i < n and source[i] != quote:
            if source[i] == "\\" and i + 1 < n:
                nxt = source[i + 1]
                if nxt == "n":
                    out.append("\n")
                elif nxt == "t":
                    out.append("\t")
                elif nxt == "r":
                    out.append("\r")
                else:
                    out.append(nxt)
                advance(2)
            else:
                out.append(source[i])
                advance()
        if i < n and source[i] == quote:
            advance()
        text = "".join(out)
        if text and not is_ignored(start_line):
            literals.append(Literal(location=f"L{start_line}", line=start_line, text=text))

    def read_template() -> None:
        start_line = line
        chunk: list[str] = []
        chunk_line = line
        advance()
        while i < n and source[i] != "`":
            if source[i] == "\\" and i + 1 < n:
                nxt = source[i + 1]
                if nxt == "n":
                    chunk.append("\n")
                elif nxt == "t":
                    chunk.append("\t")
                elif nxt == "r":
                    chunk.append("\r")
                else:
                    chunk.append(nxt)
                advance(2)
            elif source[i] == "$" and i + 1 < n and source[i + 1] == "{":
                text = "".join(chunk)
                if text and not is_ignored(chunk_line):
                    literals.append(Literal(location=f"L{chunk_line}", line=chunk_line, text=text))
                chunk = []
                advance(2)
                depth = 1
                while i < n and depth > 0:
                    if source[i] == "/" and i + 1 < n and source[i + 1] == "/":
                        skip_line_comment()
                    elif source[i] == "/" and i + 1 < n and source[i + 1] == "*":
                        skip_block_comment()
                    elif source[i] in ("'", '"'):
                        read_quoted(source[i])
                    elif source[i] == "`":
                        read_template()
                    elif source[i] == "{":
                        depth += 1
                        advance()
                    elif source[i] == "}":
                        depth -= 1
                        advance()
                    else:
                        advance()
                chunk_line = line
            else:
                if not chunk:
                    chunk_line = line
                chunk.append(source[i])
                advance()
        text = "".join(chunk)
        if text and not is_ignored(chunk_line):
            literals.append(Literal(location=f"L{chunk_line}", line=chunk_line, text=text))
        if i < n and source[i] == "`":
            advance()

    while i < n:
        ch = source[i]
        if ch == "/" and i + 1 < n and source[i + 1] == "/":
            skip_line_comment()
        elif ch == "/" and i + 1 < n and source[i + 1] == "*":
            skip_block_comment()
        elif ch in ("'", '"'):
            read_quoted(ch)
        elif ch == "`" and allow_templates:
            read_template()
        else:
            advance()

    return literals


def extract_python_literals(source: str) -> list[Literal]:
    literals: list[Literal] = []
    ignored = False
    ignore_next_line = -1
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return literals

    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            if IGNORE_START_RE.search(tok.string):
                ignored = True
            if IGNORE_END_RE.search(tok.string):
                ignored = False
            if IGNORE_NEXT_RE.search(tok.string):
                ignore_next_line = tok.end[0] + 1
        elif tok.type == tokenize.STRING:
            start_line = tok.start[0]
            if ignored or start_line == ignore_next_line:
                continue
            raw = tok.string
            # Strip string prefixes (r, u, f, b) and outer quotes safely without eval.
            prefix_match = re.match(r"^[rRuUbBfF]*", raw)
            body = raw[prefix_match.end() :] if prefix_match else raw
            for q in ('"""', "'''", '"', "'"):
                if body.startswith(q) and body.endswith(q) and len(body) >= 2 * len(q):
                    body = body[len(q) : -len(q)]
                    break
            if body:
                literals.append(Literal(location=f"L{start_line}", line=start_line, text=body))
    return literals


def extract_json_literals(source: str) -> list[Literal]:
    data = json.loads(source)
    literals: list[Literal] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(node, list):
            for idx, v in enumerate(node):
                walk(v, f"{path}[{idx}]")
        elif isinstance(node, str):
            literals.append(Literal(location=path or "$", line=1, text=node))

    walk(data, "")
    return literals


def is_prose_like(text: str) -> bool:
    """True if text looks like human-readable prose rather than a bare identifier, path, or glob."""
    stripped = text.strip()
    if not stripped or not re.search(r"[A-Za-z]", stripped):
        return False
    # Skip relative file paths and glob patterns like ../foo or **/*.env
    if stripped.startswith(("./", "../", "**/")) and " " not in stripped:
        return False
    return True


def check_literals(
    file_label: str,
    literals: Iterable[Literal],
    rules: list[dict[str, Any]],
    allow: list[str],
    max_words: int | None,
) -> list[Finding]:
    compiled = [
        (
            r["id"],
            r["name"],
            re.compile(r["pattern"], compile_flags(r.get("flags", ""))),
            r.get("prose_only") in (True, "true"),
        )
        for r in rules
    ]
    findings: list[Finding] = []
    for lit in literals:
        if not is_prose_like(lit.text):
            continue
        cleaned = lit.text
        for phrase in allow:
            if phrase:
                cleaned = cleaned.replace(phrase, "")
        for rule_id, rule_name, regex, prose_only in compiled:
            if prose_only and " " not in cleaned.strip():
                continue
            if regex.search(cleaned):
                findings.append(
                    Finding(
                        file=file_label,
                        line=lit.line,
                        location=lit.location,
                        rule_id=rule_id,
                        rule_name=rule_name,
                        text=lit.text.replace("\n", "\\n"),
                    )
                )
        if max_words is not None and max_words > 0:
            for sentence in re.split(r"(?<=[.!?])\s+|\n+", cleaned):
                words = WORD_RE.findall(sentence)
                if len(words) > max_words:
                    findings.append(
                        Finding(
                            file=file_label,
                            line=lit.line,
                            location=lit.location,
                            rule_id="long-sentence",
                            rule_name=f"sentence has {len(words)} words (limit {max_words})",
                            text=sentence.strip(),
                        )
                    )
    return findings


def iter_files(targets: list[str]) -> list[Path]:
    found: list[Path] = []
    for target in targets:
        p = Path(target)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {target}")
        if p.is_file():
            found.append(p)
        else:
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in {"node_modules", ".git", "dist", "build", "__pycache__"})
                for name in sorted(files):
                    fp = Path(root) / name
                    if fp.suffix.lower() in SUPPORTED_EXTS:
                        found.append(fp)
    return found


def load_config(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Config file must contain a JSON object.")
    return data


def scan_files(
    targets: list[str],
    config: dict[str, Any] | None = None,
    max_words: int | None = None,
) -> list[Finding]:
    cfg = config or {}
    disabled = set(cfg.get("disableRules", []))
    rules = [r for r in DEFAULT_RULES if r["id"] not in disabled]
    for extra in cfg.get("extraRules", []):
        rules.append(extra)
    allow = list(cfg.get("allow", []))
    exclude_blocks = list(cfg.get("excludeBlocks", []))
    effective_max_words = max_words if max_words is not None else cfg.get("maxWords")

    all_findings: list[Finding] = []
    for fp in iter_files(targets):
        rel = fp.as_posix()
        source = fp.read_text(encoding="utf-8")
        source = strip_excluded_blocks(source, rel, exclude_blocks)
        ext = fp.suffix.lower()
        if ext == ".json":
            lits = extract_json_literals(source)
        elif ext == ".py":
            lits = extract_python_literals(source)
        elif ext in C_LIKE_EXTS:
            lits = extract_c_like_literals(source, allow_templates=(ext in TEMPLATE_EXTS))
        else:
            lits = [
                Literal(location=f"L{idx}", line=idx, text=ln)
                for idx, ln in enumerate(source.splitlines(), start=1)
                if ln.strip()
            ]
        all_findings.extend(check_literals(rel, lits, rules, allow, effective_max_words))
    return all_findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan user-facing UI copy files against plain-language STE rules.")
    parser.add_argument("targets", nargs="+", help="Files or directories to scan.")
    parser.add_argument("--config", help="Optional JSON config with extraRules, disableRules, allow, excludeBlocks, maxWords.")
    parser.add_argument("--max-words", type=int, default=None, help="Flag sentences exceeding N words (e.g. 25).")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format (default: text).")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
        findings = scan_files(args.targets, config=config, max_words=args.max_words)
    except (OSError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps([asdict(f) for f in findings], indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f.file}:{f.location} [{f.rule_id}] {f.rule_name}")
            print(f"  {f.text}")
        if not findings:
            print("OK: 0 findings.")
        else:
            print(f"\nFound {len(findings)} issue(s).")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
