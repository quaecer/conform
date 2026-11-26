# SPDX-License-Identifier: Apache-2.0
"""Test comparison modes and subprocess outcomes end to end."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from quaecer.conform.suite import Case, load_suite, matches, report, run_case, summary


class SuiteTest(unittest.TestCase):
    def test_comparison_modes(self) -> None:
        self.assertTrue(matches({"a": 1.0}, {"a": 1}, "canonical-equal"))
        self.assertFalse(matches({"a": 1}, {"a": True}, "canonical-equal"))
        self.assertTrue(matches({"a": {"b": 1}}, {"a": {"b": 1, "d": 2}}, "subset"))
        self.assertFalse(matches([{"a": 1}], [{"a": 1, "b": 2}], "subset"))
        mode = "set-equal-on:/a~1b/0/~0"
        self.assertTrue(matches({"a/b": [{"~": [1, 2]}]}, {"a/b": [{"~": [2, 1, 1]}]}, mode))
        self.assertFalse(matches({"a/b": [{"~": [1]}]}, {"a/b": [{"~": None}]}, mode))
        with self.assertRaises(ValueError):
            matches([], [], "set-equal-on:/~3")

    def test_case_process_classifies_unavailable_output(self) -> None:
        case = Case("case-1", {"given": 3}, {"given": 3}, "canonical-equal")
        examples = [
            ("import sys; print(sys.stdin.read())", "passed", "matched"),
            ('print("{}")', "failed", "different"),
            ("raise SystemExit(8)", "cantTell", "exit_error"),
            ('print("true"); print("false")', "cantTell", "invalid_response"),
            ('print(\'{"given":3,"given":4}\')', "cantTell", "invalid_response"),
            ('print("9e999")', "cantTell", "invalid_response"),
            ('print(" " * (2 * 1024 * 1024 + 1))', "cantTell", "invalid_response"),
        ]
        for code, status, reason in examples:
            with self.subTest(code=code):
                result = run_case(case, [sys.executable, "-c", code], timeout=5)
                self.assertEqual((result.outcome, result.reason), (status, reason))
        absent = run_case(case, ["missing-executable-for-test"], timeout=5)
        self.assertEqual(absent.reason, "startup_error")
        expired = run_case(case, [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.05)
        self.assertEqual(expired.reason, "timeout")

    def test_suite_refuses_missing_and_duplicate_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = root / "case-1"
            case.mkdir()
            (case / "input.json").write_text("null")
            (case / "expected.json").write_text("null")
            metadata = {
                "id": "case-1",
                "description": "values agree",
                "requirements": ["rule-1"],
                "comparison": "canonical-equal",
            }
            (case / "case.json").write_text(json.dumps(metadata))
            self.assertEqual(load_suite(root), (Case("case-1", None, None, "canonical-equal"),))
            for links in ([], ["rule-1", "rule-1"]):
                (case / "case.json").write_text(json.dumps(dict(metadata, requirements=links)))
                with self.assertRaisesRegex(ValueError, "requirement links"):
                    load_suite(root)

    def test_reports_keep_execution_errors_separate(self) -> None:
        case = Case("case-1", None, None, "canonical-equal")
        observed = (run_case(case, [sys.executable, "-c", 'print("null")'], timeout=3),)
        self.assertIn("earl:outcome earl:passed", report(observed))
        self.assertEqual(
            json.loads(summary(observed))["counts"],
            {
                "passed": 1,
                "failed": 0,
                "cantTell": 0,
            },
        )
