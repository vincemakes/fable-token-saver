from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

REQUIRED_OUTCOMES = {
    "authority-main-lite": ("lite", "ok"),
    "balanced-main-distinct-reviewer-max": ("max", "ok"),
    "alias-collision": ("max", "reviewer_unavailable"),
    "reviewer-unavailable": ("max", "reviewer_unavailable"),
    "revise-loop": ("max", "ok"),
    "revision-limit": ("max", "review_revise"),
    "approval-stale": ("max", "approval_stale"),
    "sandbox-unavailable": ("max", "sandbox_unavailable"),
}

INPUT_KEYS = {"host", "main_loop", "explicit_mode", "routes", "events"}
EXPECTED_KEYS = {"mode", "status", "authority", "worker", "states", "evidence"}


class RoutingEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(
            (ROOT / "evals" / "routing-evals.json").read_text(encoding="utf-8")
        )
        cls.cases = cls.data["cases"]
        cls.by_id = {case["id"]: case for case in cls.cases}

    def test_top_level_shape_and_unique_ids(self) -> None:
        self.assertEqual(set(self.data), {"version", "cases"})
        self.assertEqual(self.data["version"], 1)
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), set(REQUIRED_OUTCOMES))

    def test_case_shapes_and_fingerprints(self) -> None:
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertEqual(set(case), {"id", "input", "expected"})
                self.assertEqual(set(case["input"]), INPUT_KEYS)
                self.assertEqual(set(case["expected"]), EXPECTED_KEYS)
                self.assertEqual(len(case["input"]["main_loop"].split(":")), 3)
                self.assertIsInstance(case["expected"]["evidence"], dict)
                self.assertTrue(case["expected"]["evidence"])

    def test_required_mode_and_status_outcomes(self) -> None:
        for case_id, expected in REQUIRED_OUTCOMES.items():
            case = self.by_id[case_id]["expected"]
            with self.subTest(case=case_id):
                self.assertEqual((case["mode"], case["status"]), expected)

    def test_lite_authority_is_inline(self) -> None:
        self.assertEqual(
            self.by_id["authority-main-lite"]["expected"]["authority"], "inline"
        )

    def test_successful_max_checkpoint_order(self) -> None:
        for case_id in (
            "balanced-main-distinct-reviewer-max",
            "revise-loop",
        ):
            states = self.by_id[case_id]["expected"]["states"]
            with self.subTest(case=case_id):
                self.assertLess(states.index("AUTHORITY_PLAN_CHECK"), states.index("DISPATCH"))
                self.assertLess(
                    len(states) - 1 - states[::-1].index("AUTHORITY_FINAL_CHECK"),
                    states.index("INTEGRATE"),
                )

    def test_revise_loop_repeats_exactly_twice_then_integrates(self) -> None:
        case = self.by_id["revise-loop"]
        self.assertEqual(case["input"]["events"].count("revise"), 2)
        states = case["expected"]["states"]
        for state in (
            "DISPATCH",
            "GATE",
            "PATCH_AUDIT",
            "MAIN_LOOP_REVIEW",
            "AUTHORITY_FINAL_CHECK",
        ):
            self.assertEqual(states.count(state), 3)
        self.assertEqual(states[-1], "INTEGRATE")

    def test_revision_limit_stops_on_third_revise(self) -> None:
        case = self.by_id["revision-limit"]
        self.assertEqual(case["input"]["events"].count("revise"), 3)
        self.assertEqual(case["expected"]["status"], "review_revise")
        self.assertNotIn("INTEGRATE", case["expected"]["states"])
        self.assertIn("revision_rounds", case["expected"]["evidence"])

    def test_blocking_cases_never_integrate(self) -> None:
        for case_id in (
            "alias-collision",
            "reviewer-unavailable",
            "revision-limit",
            "approval-stale",
            "sandbox-unavailable",
        ):
            with self.subTest(case=case_id):
                self.assertNotIn("INTEGRATE", self.by_id[case_id]["expected"]["states"])


if __name__ == "__main__":
    unittest.main()
