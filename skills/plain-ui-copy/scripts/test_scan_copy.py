#!/usr/bin/env python3
"""Self-tests for scan_copy.py (Python stdlib unittest only)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import scan_copy  # noqa: E402


class ScanCopyTests(unittest.TestCase):
    def write(self, root: Path, rel: str, content: str) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_ts_comments_imports_and_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.write(
                root,
                "copy.ts",
                "\n".join([
                    'import { x } from "../shared/copy.ts";',
                    "// may would will; comment is ignored",
                    "/* kept closed; block comment ignored */",
                    'export const ok = "Nothing changed. Your settings are saved.";',
                    'export const bad = `The search may read ${count === 1 ? "1 file" : `${count} files`}.`;',
                    'export const semi = "First statement; second statement.";',
                ]),
            )
            findings = scan_copy.scan_files([str(target)])
            pairs = [(f.line, f.rule_id) for f in findings]
            self.assertEqual(pairs, [(5, "modal-may"), (6, "semicolon-chain")])

    def test_ignore_directives_and_narrow_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.write(
                root,
                "copy.ts",
                "\n".join([
                    "// plain-ui-copy: ignore-next-line",
                    'export const exempted = "This may happen in a calibrated prompt.";',
                    "/* plain-ui-copy: ignore-start */",
                    'export const block = "It will also be skipped.";',
                    "/* plain-ui-copy: ignore-end */",
                    'export const mode = "The mode is You Shall Pass.";',
                    'export const caught = "This will still be caught.";',
                ]),
            )
            config = {
                "extraRules": [{"id": "no-you", "name": "no second person", "pattern": r"\byou\b", "flags": "i"}],
                "allow": ["You Shall Pass"],
            }
            findings = scan_copy.scan_files([str(target)], config=config)
            self.assertEqual([(f.line, f.rule_id) for f in findings], [(7, "future-conditional")])

    def test_exclude_blocks_preserves_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.write(
                root,
                "model-copy.ts",
                "\n".join([
                    'export const visible = "This call was blocked.";',
                    "export const calibrated = {",
                    '  q1: "Does it do something that would fail?",',
                    "};",
                    'export const after = "This path may fail.";',
                ]),
            )
            config = {
                "excludeBlocks": [{"file": "model-copy.ts", "start": "export const calibrated =", "end": "};"}],
            }
            findings = scan_copy.scan_files([str(target)], config=config)
            self.assertEqual([(f.line, f.rule_id) for f in findings], [(5, "modal-may")])

    def test_json_and_python_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jf = self.write(
                root,
                "en.json",
                json.dumps({"dialog": {"ok": "Save changes", "bad": "This can be written later."}}),
            )
            pf = self.write(
                root,
                "messages.py",
                "\n".join([
                    "# may is fine in comments",
                    'MSG = "Go back to the previous page."',
                ]),
            )
            findings = scan_copy.scan_files([str(jf), str(pf)])
            self.assertEqual(
                [(Path(f.file).name, f.location, f.rule_id) for f in findings],
                [("en.json", "dialog.bad", "non-native"), ("messages.py", "L2", "phrasal-verb")],
            )

    def test_double_punctuation_and_long_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = self.write(
                root,
                "copy.ts",
                "\n".join([
                    'export const ellipsis = "Loading…";',
                    'export const threeDots = "Loading...";',
                    'export const broken = "Not available (macOS only.).";',
                    'export const longOne = "One two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen.";',
                ]),
            )
            findings = scan_copy.scan_files([str(target)], max_words=12)
            self.assertEqual([(f.line, f.rule_id) for f in findings], [(3, "double-punctuation"), (4, "long-sentence")])


if __name__ == "__main__":
    unittest.main()
