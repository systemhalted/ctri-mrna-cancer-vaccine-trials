import contextlib
import io
import json
import pathlib
import tempfile
import unittest

from update_reports import (
    NO_CANDIDATE_NOTE,
    cell,
    counts_by_category,
    india_candidates,
    load_sweep,
    main,
    render_report,
    review_reason,
)

QUALIFYING = {
    "registry_id": "NCT09999001",
    "trial_title": "Neoantigen mRNA vaccine in melanoma",
    "trial_phase": "PHASE2",
    "recruitment_status": "RECRUITING",
    "sponsor": "Example Biopharma",
    "indian_trial_sites": "Example Cancer Centre, Mumbai, India",
    "contact_email": "ctdesk@example.invalid",
    "category": "A",
    "qualifies_mrna_cancer_vaccine": True,
    "has_verified_india_site": True,
}

NO_INDIA_SITE = {
    "registry_id": "NCT09999004",
    "trial_title": "mRNA neoantigen therapy, no India site",
    "recruitment_status": "RECRUITING",
    "category": "D",
    "qualifies_mrna_cancer_vaccine": True,
    "has_verified_india_site": False,
    "manual_verification_reason": "",
}

NOT_A_VACCINE = {
    "registry_id": "NCT09999003",
    "trial_title": "CAR-T in lymphoma",
    "recruitment_status": "RECRUITING",
    "category": "D",
    "qualifies_mrna_cancer_vaccine": False,
    "has_verified_india_site": False,
    "manual_verification_reason": "Missing required evidence: mRNA platform.",
}


def write_sweep(directory: pathlib.Path, records: list[dict]) -> pathlib.Path:
    path = directory / "raw_results.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


class LoadSweepTests(unittest.TestCase):
    def test_missing_fields_are_filled_with_dataclass_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sweep(pathlib.Path(tmp), [{"registry_id": "NCT1"}])
            record = load_sweep(path)[0]
        self.assertEqual(record["trial_title"], "")
        self.assertFalse(record["qualifies_mrna_cancer_vaccine"])

    def test_records_are_sorted_so_diffs_stay_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_sweep(pathlib.Path(tmp), [NO_INDIA_SITE, QUALIFYING])
            ids = [r["registry_id"] for r in load_sweep(path)]
        self.assertEqual(ids, ["NCT09999001", "NCT09999004"])

    def test_a_json_object_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "raw_results.json"
            path.write_text('{"results": []}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_sweep(path)


class ReviewReasonTests(unittest.TestCase):
    def test_stated_reason_is_kept(self):
        self.assertIn("mRNA platform", review_reason(NOT_A_VACCINE))

    def test_qualifying_record_without_india_site_gets_an_explicit_reason(self):
        self.assertIn("no Indian study site", review_reason(NO_INDIA_SITE))


class CellTests(unittest.TestCase):
    def test_pipes_are_escaped_so_the_table_survives(self):
        self.assertEqual(cell("a | b"), "a \\| b")

    def test_empty_value_renders_a_dash(self):
        self.assertEqual(cell(""), "--")

    def test_long_values_are_truncated(self):
        self.assertEqual(len(cell("x" * 400)), 140)


class ReportTests(unittest.TestCase):
    def test_no_candidate_run_states_the_conservative_result(self):
        report = render_report([NOT_A_VACCINE], "2026-08-23", "test", 25)
        self.assertIn(NO_CANDIDATE_NOTE, report)
        self.assertIn("CAR-T in lymphoma", report)

    def test_candidate_run_lists_the_candidate_and_its_contact(self):
        report = render_report([QUALIFYING, NO_INDIA_SITE], "2026-08-23", "test", 25)
        self.assertNotIn(NO_CANDIDATE_NOTE, report)
        self.assertIn("ctdesk@example.invalid", report)
        self.assertIn("must be verified against the primary", report)

    def test_review_list_is_capped_and_says_how_many_were_omitted(self):
        records = [dict(NOT_A_VACCINE, registry_id=f"NCT{i:07d}") for i in range(30)]
        report = render_report(records, "2026-08-23", "test", 5)
        self.assertIn("25 further record(s) omitted", report)

    def test_ctri_captcha_limitation_is_always_stated(self):
        report = render_report([QUALIFYING], "2026-08-23", "test", 25)
        self.assertIn("Security Code", report)

    def test_counts_cover_every_category_even_when_empty(self):
        self.assertEqual(counts_by_category([QUALIFYING]),
                         {"A": 1, "B": 0, "C": 0, "D": 0})

    def test_only_india_verified_records_are_candidates(self):
        found = india_candidates([QUALIFYING, NO_INDIA_SITE, NOT_A_VACCINE])
        self.assertEqual([r["registry_id"] for r in found], ["NCT09999001"])


class MainTests(unittest.TestCase):
    def run_main(self, tmp: str, records: list[dict], *extra: str) -> int:
        root = pathlib.Path(tmp)
        argv = [
            "--sweep-json", str(write_sweep(root, records)),
            "--data-dir", str(root / "data"),
            "--report", str(root / "report.md"),
            *extra,
        ]
        # main() prints a JSON summary for the workflow to read and guard
        # failures to stderr; keep both out of the test output.
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            return main(argv)

    def test_writes_every_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main(tmp, [QUALIFYING, NOT_A_VACCINE],
                                          "--as-of", "2026-08-23"), 0)
            root = pathlib.Path(tmp)
            self.assertTrue((root / "report.md").is_file())
            sweep = json.loads((root / "data" / "sweep.json").read_text())
            self.assertEqual(sweep["as_of"], "2026-08-23")
            self.assertEqual(len(sweep["results"]), 2)
            candidates = (root / "data" / "candidates.csv").read_text()
            self.assertIn("NCT09999001", candidates)
            self.assertNotIn("NCT09999003", candidates)
            self.assertIn("NCT09999003",
                          (root / "data" / "manual_verification.csv").read_text())

    def test_an_unchanged_sweep_rewrites_a_byte_identical_tree(self):
        """A re-run on a later date must leave nothing for the workflow to commit."""
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            self.run_main(tmp, [QUALIFYING], "--as-of", "2026-08-23")
            before = {path.name: path.read_bytes()
                      for path in sorted(root.rglob("*")) if path.is_file()
                      and path.name != "raw_results.json"}
            self.assertEqual(self.run_main(tmp, [QUALIFYING], "--as-of", "2027-01-01"), 0)
            after = {path.name: path.read_bytes()
                     for path in sorted(root.rglob("*")) if path.is_file()
                     and path.name != "raw_results.json"}
            as_of = json.loads((root / "data" / "sweep.json").read_text())["as_of"]
        self.assertEqual(before, after)
        self.assertEqual(as_of, "2026-08-23")

    def test_changed_results_advance_the_as_of_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_main(tmp, [QUALIFYING], "--as-of", "2026-08-23")
            self.run_main(tmp, [QUALIFYING, NOT_A_VACCINE], "--as-of", "2027-01-01")
            sweep = json.loads((pathlib.Path(tmp) / "data" / "sweep.json").read_text())
        self.assertEqual(sweep["as_of"], "2027-01-01")

    def test_an_empty_sweep_does_not_overwrite_existing_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_main(tmp, [QUALIFYING], "--as-of", "2026-08-23")
            before = (pathlib.Path(tmp) / "data" / "sweep.json").read_text()
            self.assertEqual(self.run_main(tmp, []), 3)
            after = (pathlib.Path(tmp) / "data" / "sweep.json").read_text()
        self.assertEqual(before, after)

    def test_min_records_threshold_is_configurable(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main(tmp, [QUALIFYING], "--min-records", "5"), 3)

    def test_a_malformed_as_of_date_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_main(tmp, [QUALIFYING], "--as-of", "last tuesday"), 2)

    def test_a_missing_sweep_file_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                exit_code = main(["--sweep-json", str(pathlib.Path(tmp) / "nope.json"),
                                  "--data-dir", tmp, "--report", tmp + "/r.md"])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
