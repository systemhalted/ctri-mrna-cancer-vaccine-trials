#!/usr/bin/env python3
"""Turn a collector sweep into the committed automated report.

`ctri_mrna_trials.py` writes a raw sweep to its --output-dir. This script takes
that sweep and renders the files the repository actually tracks:

    data/automated/sweep.json               all normalised records, sorted
    data/automated/candidates.csv           category A/B/C (verified India site)
    data/automated/manual_verification.csv  category D
    reports/AUTOMATED_SWEEP.md              human-readable summary

It never touches the curated research snapshot in data/raw_results.json or
FINDINGS.md. Those are hand-compiled from browser-accessible registry and
sponsor sources, and a machine sweep is not evidence for them.

Output is deterministic. Nothing in the written files depends on the wall clock:
the `as_of` date only advances when the underlying records change, so an
unchanged sweep rewrites a byte-identical tree and the scheduled workflow has
nothing to commit. The date a check ran with no change is recorded in the
workflow run, not in a heartbeat commit.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import sys
from datetime import date, timezone, datetime
from pathlib import Path
from typing import Any

from ctri_mrna_trials import Trial

FIELDS = list(Trial.__dataclass_fields__.keys())
# `source` and `registry_id` are required on Trial, so they have no default to
# read; a record missing them still has to render as something.
DEFAULTS = {name: ("" if field.default is dataclasses.MISSING else field.default)
            for name, field in Trial.__dataclass_fields__.items()}

CATEGORY_LABELS = {
    "A": "A -- currently recruiting at a verified Indian site",
    "B": "B -- India site verified, not yet recruiting or status uncertain",
    "C": "C -- India site verified, no longer recruiting",
    "D": "D -- needs manual verification (no verified Indian site, or evidence incomplete)",
}

NO_CANDIDATE_NOTE = (
    "No record in this sweep is both classified as a therapeutic mRNA "
    "cancer vaccine and confirmed to have an Indian study site. This is a "
    "conservative \"no verified match found\" result, not proof of absence: "
    "CTRI Advanced Search submission is CAPTCHA-protected and is not automated "
    "by this project, so CTRI-only registrations cannot be swept."
)


def sort_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("category", "")),
        str(record.get("registry_id", "")),
        str(record.get("trial_title", "")),
    )


def load_sweep(path: Path) -> list[dict[str, Any]]:
    """Read the collector's raw_results.json and normalise it for comparison."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON list of records")
    records = [{field: record.get(field, DEFAULTS[field]) for field in FIELDS}
               for record in payload]
    return sorted(records, key=sort_key)


def previous_as_of(path: Path, records: list[dict[str, Any]]) -> str | None:
    """Return the stored as_of date if the stored records are unchanged."""
    if not path.is_file():
        return None
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(stored, dict) or stored.get("results") != records:
        return None
    as_of = stored.get("as_of")
    return as_of if isinstance(as_of, str) and as_of else None


def counts_by_category(records: list[dict[str, Any]]) -> dict[str, int]:
    counts = {key: 0 for key in CATEGORY_LABELS}
    for record in records:
        key = str(record.get("category", "")) or "D"
        counts[key] = counts.get(key, 0) + 1
    return counts


def india_candidates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records
            if r.get("qualifies_mrna_cancer_vaccine") and r.get("has_verified_india_site")]


def cell(value: Any) -> str:
    text = " ".join(str(value or "").split())
    if len(text) > 140:
        text = text[:137].rstrip() + "..."
    return text.replace("|", "\\|") or "--"


def table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> list[str]:
    header = [f"| {' | '.join(title for title, _ in columns)} |",
              f"|{'|'.join('---' for _ in columns)}|"]
    body = [f"| {' | '.join(cell(row.get(key)) for _, key in columns)} |" for row in rows]
    return header + body


CANDIDATE_COLUMNS = [
    ("Registry id", "registry_id"),
    ("Title", "trial_title"),
    ("Phase", "trial_phase"),
    ("Status", "recruitment_status"),
    ("Sponsor", "sponsor"),
    ("Indian sites", "indian_trial_sites"),
    ("Contact", "contact_email"),
]

REVIEW_COLUMNS = [
    ("Registry id", "registry_id"),
    ("Title", "trial_title"),
    ("Status", "recruitment_status"),
    ("Why flagged", "_review_reason"),
]


def review_reason(record: dict[str, Any]) -> str:
    """Why a category D record needs a human look.

    The collector leaves manual_verification_reason empty for a record that
    passes the classifier but has no confirmed Indian site. That is the most
    interesting kind of flag here -- a real mRNA cancer vaccine whose location
    list is the only thing standing between it and category A -- so it gets an
    explicit reason rather than a blank cell.
    """
    stated = " ".join(str(record.get("manual_verification_reason") or "").split())
    if stated:
        return stated
    if record.get("qualifies_mrna_cancer_vaccine") and not record.get("has_verified_india_site"):
        return ("Classified as an mRNA cancer vaccine, but no Indian study site "
                "verified. Re-check the location list.")
    return "Not classified as an mRNA cancer vaccine."


def render_report(records: list[dict[str, Any]], as_of: str, source: str,
                  review_limit: int) -> str:
    counts = counts_by_category(records)
    candidates = india_candidates(records)
    lines = [
        "# Automated trial sweep",
        "",
        "<!-- Generated by update_reports.py. Do not edit by hand; edits are",
        "     overwritten by the next scheduled run. The curated research report",
        "     is FINDINGS.md, which this file never modifies. -->",
        "",
        f"- Results as of: **{as_of}**",
        f"- Discovery source: {source}",
        f"- Records normalised: **{len(records)}**",
        "",
        "## Headline",
        "",
    ]

    if candidates:
        lines += [
            f"**{len(candidates)} record(s) classified as a therapeutic mRNA cancer "
            "vaccine with a verified Indian study site.** Every one of these is a "
            "machine classification and must be verified against the primary "
            "registry record before it is acted on or added to `FINDINGS.md`.",
            "",
            *table(candidates, CANDIDATE_COLUMNS),
            "",
        ]
    else:
        lines += [NO_CANDIDATE_NOTE, "", "See `FINDINGS.md` for the curated snapshot "
                  "and the sources behind it.", ""]

    lines += ["## Categories", "", "| Category | Records |", "|---|---|"]
    for key, label in CATEGORY_LABELS.items():
        lines.append(f"| {label} | {counts.get(key, 0)} |")
    lines.append("")

    review = [r for r in records if r.get("category") == "D"]
    lines += ["## Flagged for manual verification", ""]
    if review:
        shown = [dict(r, _review_reason=review_reason(r)) for r in review[:review_limit]]
        lines += table(shown, REVIEW_COLUMNS)
        if len(review) > len(shown):
            lines.append("")
            lines.append(f"{len(review) - len(shown)} further record(s) omitted here; "
                         "the full list is `data/automated/manual_verification.csv`.")
        lines.append("")
    else:
        lines += ["None in this sweep.", ""]

    lines += [
        "## What this sweep does and does not cover",
        "",
        "- Covered: the public ClinicalTrials.gov v2 API, queried once per term in",
        "  `search_terms.txt` with `India` as the location query.",
        "- Not covered: CTRI Advanced Search. Submitting it requires a human-entered",
        "  Security Code, which this project does not automate, solve or bypass.",
        "  CTRI records reach the pipeline only when a person supplies a record URL",
        "  or saved HTML.",
        "- Not covered: WHO ICTRP, which publishes no open search API. Use",
        "  `--print-ictrp-urls` to generate the URLs to check by hand.",
        "- A record here is a *classification*, not an eligibility determination.",
        "  Trial eligibility is determined solely by the trial investigators.",
        "",
    ]
    return "\n".join(lines) + "\n"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_reports(records: list[dict[str, Any]], data_dir: Path, report_path: Path,
                  as_of: str, source: str, review_limit: int) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    (data_dir / "sweep.json").write_text(
        json.dumps({"as_of": as_of, "source": source, "results": records},
                   indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_csv(data_dir / "candidates.csv", india_candidates(records))
    write_csv(data_dir / "manual_verification.csv",
              [r for r in records if r.get("category") == "D"])
    report_path.write_text(
        render_report(records, as_of, source, review_limit), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sweep-json", type=Path, required=True,
                   help="raw_results.json written by ctri_mrna_trials.py --output-dir")
    p.add_argument("--data-dir", type=Path, default=Path("data/automated"),
                   help="where the generated data files go (default: data/automated)")
    p.add_argument("--report", type=Path, default=Path("reports/AUTOMATED_SWEEP.md"),
                   help="where the generated markdown report goes")
    p.add_argument("--as-of", default="",
                   help="date to stamp on changed results (default: today, UTC)")
    p.add_argument("--source", default="ClinicalTrials.gov v2 API (India location query)",
                   help="how the sweep was collected, recorded in the report")
    p.add_argument("--min-records", type=int, default=1,
                   help="fail without writing anything if the sweep has fewer records "
                        "than this; guards against a registry outage emptying the report")
    p.add_argument("--review-limit", type=int, default=25,
                   help="how many category D records to list in the markdown report")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    today = args.as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        date.fromisoformat(today)
    except ValueError:
        print(f"error: --as-of must be an ISO date (YYYY-MM-DD), got {today!r}",
              file=sys.stderr)
        return 2

    try:
        records = load_sweep(args.sweep_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if len(records) < args.min_records:
        print(f"error: sweep has {len(records)} record(s), expected at least "
              f"{args.min_records}; refusing to overwrite the reports. A sudden drop "
              "usually means the registry API failed or changed, not that the trials "
              "disappeared.", file=sys.stderr)
        return 3

    sweep_path = args.data_dir / "sweep.json"
    unchanged_as_of = previous_as_of(sweep_path, records)
    as_of = unchanged_as_of or today

    write_reports(records, args.data_dir, args.report, as_of,
                  args.source, args.review_limit)

    candidates = india_candidates(records)
    print(json.dumps({
        "records": len(records),
        "categories": counts_by_category(records),
        "india_candidates": len(candidates),
        "india_candidate_ids": [r.get("registry_id", "") for r in candidates],
        "as_of": as_of,
        "last_checked": today,
        "results_changed": unchanged_as_of is None,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
