#!/usr/bin/env python3
"""Unit tests for review-with-gpt helper scripts (Python stdlib unittest only)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import pathlib
import tempfile
import unittest
from unittest import mock

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run_js = load_module("run_js", "run-js.py")
wait_answer = load_module("wait_answer", "wait-answer.py")


class RunJsTests(unittest.TestCase):
    def test_applescript_string_escapes_quotes_backslashes_and_newlines(self) -> None:
        raw = 'var s = "a\\b";\r\nreturn s;'
        self.assertEqual(
            run_js.applescript_string(raw),
            '"var s = \\"a\\\\b\\";\\r\\nreturn s;"',
        )

    def test_build_applescript_uses_tab_and_window(self) -> None:
        script = run_js.build_applescript(3, "JSON.stringify(1)", window=2)
        self.assertIn("execute (tab 3 of window 2) javascript", script)

    def test_rejects_non_numeric_or_zero_tab(self) -> None:
        for bad in ("0", "-1", "1) of window 2 --"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_js.main([bad])


class WaitAnswerTests(unittest.TestCase):
    def _reading(
        self,
        text: str,
        *,
        stop: bool = False,
        current: bool = True,
        chunks: int = 1,
    ) -> dict:
        return {
            "stop": stop,
            "current": current,
            "chunks": chunks,
            "chars": len(text),
            "head": text[:120],
            "text": text,
        }

    def test_requires_equal_readings_when_chars_still_grow_after_stop(self) -> None:
        readings = [
            self._reading("Partial answer", stop=False),
            self._reading("Partial answer still growing", stop=False),
            self._reading("Partial answer still growing", stop=False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "answer.md"
            with mock.patch.object(wait_answer, "poll", side_effect=readings) as poll_mock, \
                 mock.patch.object(wait_answer.time, "sleep"):
                rc = wait_answer.main(["2", "--out", str(out), "--poll", "0", "--stable", "2"])
            self.assertEqual(rc, 0)
            self.assertEqual(poll_mock.call_count, 3)
            self.assertEqual(out.read_text(encoding="utf-8"), "Partial answer still growing")

    def test_requires_two_readings_after_stop_clears_even_if_chars_unchanged(self) -> None:
        readings = [
            self._reading("Final text", stop=True),
            self._reading("Final text", stop=False),
            self._reading("Final text", stop=False),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "answer.md"
            with mock.patch.object(wait_answer, "poll", side_effect=readings) as poll_mock, \
                 mock.patch.object(wait_answer.time, "sleep"):
                rc = wait_answer.main(["1", "--out", str(out), "--poll", "0", "--stable", "2"])
            self.assertEqual(rc, 0)
            self.assertEqual(poll_mock.call_count, 3)
            self.assertEqual(out.read_text(encoding="utf-8"), "Final text")

    def test_detects_stall_and_saves_partial_answer(self) -> None:
        readings = [self._reading("Halfway done", stop=True)] * 4
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "answer.md"
            with mock.patch.object(wait_answer, "poll", side_effect=readings), \
                 mock.patch.object(wait_answer.time, "sleep"):
                rc = wait_answer.main(
                    ["1", "--out", str(out), "--poll", "0", "--stall-polls", "3"]
                )
            self.assertEqual(rc, 3)
            self.assertEqual(out.read_text(encoding="utf-8"), "Halfway done")

    def test_rejects_prompt_echo_and_does_not_overwrite_with_stale_file(self) -> None:
        readings = [self._reading("You said: please review this", stop=False)] * 3
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "answer.md"
            out.write_text("stale answer from earlier run", encoding="utf-8")
            with mock.patch.object(wait_answer, "poll", side_effect=readings), \
                 mock.patch.object(wait_answer.time, "sleep"):
                rc = wait_answer.main(
                    ["1", "--out", str(out), "--poll", "0", "--stall-polls", "2"]
                )
            self.assertEqual(rc, 2)
            self.assertFalse(out.exists())

    def test_passes_window_flag_to_poll(self) -> None:
        readings = [self._reading("Answer", stop=False)]
        with tempfile.TemporaryDirectory() as tmp:
            out = pathlib.Path(tmp) / "answer.md"
            with mock.patch.object(wait_answer, "poll", side_effect=readings) as poll_mock, \
                 mock.patch.object(wait_answer.time, "sleep"):
                rc = wait_answer.main(
                    ["4", "--window", "2", "--out", str(out), "--poll", "0", "--stable", "1"]
                )
            self.assertEqual(rc, 0)
            poll_mock.assert_called_once_with(4, window=2)


if __name__ == "__main__":
    unittest.main()
