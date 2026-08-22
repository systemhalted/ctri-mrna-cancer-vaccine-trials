#!/usr/bin/env python3
"""Find mRNA therapeutic cancer-vaccine trials relevant to India.

The collector deliberately does not submit CTRI Advanced Search because that form
requires a human-entered Security Code/CAPTCHA. It can parse known public CTRI
record URLs or CTRI HTML files saved manually. Structured discovery uses the
public ClinicalTrials.gov v2 API.

No patient information is collected or submitted.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

import classify as _classify

CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"
CTGOV_STUDY = "https://clinicaltrials.gov/study/{nct_id}"
ICTRP_SEARCH = "https://trialsearch.who.int/"
USER_AGENT = "ctri-mrna-cancer-vaccine-research/1.0 (no CTRI CAPTCHA automation)"

DEFAULT_SEARCH_TERMS = [
    "mRNA", "messenger RNA", "RNA vaccine", "cancer vaccine", "tumor vaccine",
    "therapeutic vaccine", "neoantigen", "personalized neoantigen",
    "personalized cancer vaccine", "individualized vaccine", "tumor-specific antigen",
    "mRNA immunotherapy", "V940", "mRNA-4157", "intismeran autogene", "BNT111",
    "BNT113", "BNT116", "BNT122", "autogene cevumeran", "RO7198457",
    "mRNA-4359", "RNA-LPX", "RNA lipoplex", "FixVac",
]

CATEGORY_A = {"RECRUITING", "ENROLLING_BY_INVITATION"}
CATEGORY_B = {"NOT_YET_RECRUITING", "SUSPENDED", "UNKNOWN"}
CATEGORY_C = {"ACTIVE_NOT_RECRUITING", "COMPLETED", "TERMINATED", "WITHDRAWN"}


@dataclass
class Evidence:
    """Evidence that a record describes an mRNA therapeutic cancer vaccine.

    Populated by classify.classify(). Three axes must all fire and no veto may
    fire. The axes are deliberately narrow: an earlier version matched bare
    terms such as "breast", "lung" and "immunotherapy", which appear in the
    boilerplate eligibility criteria of nearly every trial ("breast feeding",
    "prior immunotherapy"), so cancer and therapeutic evidence fired on records
    that had nothing to do with cancer vaccines.
    """

    cancer: list[str] = field(default_factory=list)
    mrna: list[str] = field(default_factory=list)
    therapeutic: list[str] = field(default_factory=list)
    known_product: list[str] = field(default_factory=list)
    vetoes: list[str] = field(default_factory=list)
    tier: str = ""
    _rationale: str = ""

    @property
    def qualifies(self) -> bool:
        return self.tier in (_classify.TIER_CONFIRMED, _classify.TIER_PROBABLE)

    @property
    def needs_manual_review(self) -> bool:
        return self.tier == _classify.TIER_MANUAL

    def rationale(self) -> str:
        return self._rationale


@dataclass
class Trial:
    source: str
    registry_id: str
    ctri_registration_number: str = ""
    nct_number: str = ""
    trial_title: str = ""
    scientific_title: str = ""
    cancer_type_indication: str = ""
    investigational_treatment: str = ""
    mrna_qualification_rationale: str = ""
    trial_phase: str = ""
    recruitment_status: str = ""
    date_of_registration: str = ""
    study_start_date: str = ""
    sponsor: str = ""
    principal_investigator: str = ""
    indian_trial_sites: str = ""
    participating_hospitals_institutions: str = ""
    contact_person: str = ""
    contact_email: str = ""
    contact_phone: str = ""
    key_inclusion_criteria: str = ""
    key_exclusion_criteria: str = ""
    relevant_age_limits: str = ""
    ctri_url: str = ""
    international_identifiers: str = ""
    clinicaltrials_gov_url: str = ""
    category: str = ""
    qualifies_mrna_cancer_vaccine: bool = False
    has_verified_india_site: bool = False
    manual_verification_reason: str = ""
    classification_tier: str = ""
    classification_vetoes: str = ""



def compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def find_evidence(text: str) -> Evidence:
    """Classify free registry text. See classify.py for the rule and its vetoes."""
    result = _classify.classify({"summary": text})
    return Evidence(
        cancer=result["disease_evidence"],
        mrna=[e for e in result["platform_evidence"] if not e.startswith("named product")],
        therapeutic=result["modality_evidence"],
        known_product=result["named_products"],
        vetoes=result["vetoes"],
        tier=result["tier"],
        _rationale=result["rationale"],
    )


def status_to_enum(status: str) -> str:
    s = status.lower().strip()
    if "not yet" in s or "not started" in s:
        return "NOT_YET_RECRUITING"
    if "open to recruitment" in s or "open for recruitment" in s:
        return "RECRUITING"
    if "active" in s and "not recruiting" in s:
        return "ACTIVE_NOT_RECRUITING"
    if "recruiting" in s and "not" not in s:
        return "RECRUITING"
    if "completed" in s:
        return "COMPLETED"
    if "terminated" in s:
        return "TERMINATED"
    if "withdrawn" in s:
        return "WITHDRAWN"
    if "suspended" in s:
        return "SUSPENDED"
    return "UNKNOWN"


def category(qualifies: bool, has_india: bool, status: str) -> str:
    if not qualifies or not has_india:
        return "D"
    if status in CATEGORY_A:
        return "A"
    if status in CATEGORY_B:
        return "B"
    if status in CATEGORY_C:
        return "C"
    return "D"


def disqualification_reason(evidence: Evidence) -> str:
    """Say why a record was not classified as an mRNA cancer vaccine."""
    if evidence.qualifies:
        return ""
    if evidence.vetoes:
        return "Ruled out: " + "; ".join(evidence.vetoes)
    return evidence.rationale() or "Insufficient evidence for an mRNA therapeutic cancer-vaccine mechanism."


def join(values: Iterable[Any], sep: str = "; ") -> str:
    return sep.join(str(v).strip() for v in values if v is not None and str(v).strip())


def split_eligibility(criteria: str) -> tuple[str, str]:
    if not criteria:
        return "", ""
    m = re.search(r"(?is)\bexclusion\s+criteria\s*:?", criteria)
    if not m:
        return criteria.strip(), ""
    inc = re.sub(r"(?is)^.*?inclusion\s+criteria\s*:?", "", criteria[:m.start()]).strip()
    exc = criteria[m.end():].strip()
    return inc, exc


def normalize_ctgov(study: dict[str, Any]) -> Trial:
    p = study.get("protocolSection", {})
    ident = p.get("identificationModule", {})
    status = p.get("statusModule", {})
    sponsor = p.get("sponsorCollaboratorsModule", {})
    conditions = p.get("conditionsModule", {})
    design = p.get("designModule", {})
    arms = p.get("armsInterventionsModule", {})
    contacts = p.get("contactsLocationsModule", {})
    elig = p.get("eligibilityModule", {})

    nct = str(ident.get("nctId", ""))
    haystack = json.dumps({k: p.get(k, {}) for k in (
        "identificationModule", "descriptionModule", "conditionsModule",
        "armsInterventionsModule", "eligibilityModule")}, ensure_ascii=False)
    evidence = find_evidence(haystack)

    locations = contacts.get("locations", []) or []
    india = [x for x in locations if str(x.get("country", "")).strip().lower() == "india"]
    site_strings = []
    site_contacts = []
    for loc in india:
        bits = [loc.get("facility"), loc.get("city"), loc.get("state"), loc.get("country")]
        text = ", ".join(str(x) for x in bits if x)
        if loc.get("status"):
            text += f" [{loc['status']}]"
        site_strings.append(text)
        site_contacts.extend(loc.get("contacts", []) or [])
    chosen_contacts = site_contacts or contacts.get("centralContacts", []) or []

    interventions = []
    for intervention in arms.get("interventions", []) or []:
        interventions.append(join([
            intervention.get("name", ""),
            " / ".join(intervention.get("otherNames", []) or []),
            intervention.get("description", ""),
        ], " | "))

    criteria = str(elig.get("eligibilityCriteria", ""))
    inc, exc = split_eligibility(criteria)
    officials = contacts.get("overallOfficials", []) or []
    pis = [o.get("name", "") for o in officials if str(o.get("role", "")).upper() in {
        "PRINCIPAL_INVESTIGATOR", "STUDY_CHAIR", "STUDY_DIRECTOR"}]
    overall = str(status.get("overallStatus", "UNKNOWN"))

    return Trial(
        source="ClinicalTrials.gov",
        registry_id=nct,
        nct_number=nct,
        trial_title=str(ident.get("briefTitle", "")),
        scientific_title=str(ident.get("officialTitle", "")),
        cancer_type_indication=join(conditions.get("conditions", []) or []),
        investigational_treatment=join(interventions),
        mrna_qualification_rationale=evidence.rationale(),
        trial_phase=join(design.get("phases", []) or []),
        recruitment_status=overall,
        date_of_registration=str((status.get("studyFirstSubmitDate") or "")),
        study_start_date=str((status.get("startDateStruct") or {}).get("date", "")),
        sponsor=str((sponsor.get("leadSponsor") or {}).get("name", "")),
        principal_investigator=join(pis),
        indian_trial_sites=join(site_strings),
        participating_hospitals_institutions=join(x.get("facility", "") for x in india),
        contact_person=join(c.get("name", "") for c in chosen_contacts),
        contact_email=join(c.get("email", "") for c in chosen_contacts),
        contact_phone=join(c.get("phone", "") for c in chosen_contacts),
        key_inclusion_criteria=inc,
        key_exclusion_criteria=exc,
        relevant_age_limits=join([elig.get("minimumAge", ""), elig.get("maximumAge", "")], " to "),
        international_identifiers=nct,
        clinicaltrials_gov_url=CTGOV_STUDY.format(nct_id=nct),
        category=category(evidence.qualifies, bool(india), overall),
        qualifies_mrna_cancer_vaccine=evidence.qualifies,
        has_verified_india_site=bool(india),
        manual_verification_reason=disqualification_reason(evidence),
        classification_tier=evidence.tier,
        classification_vetoes=join(evidence.vetoes),
    )


def collect_ctgov(search_terms: Iterable[str], sleep_seconds: float = 0.35) -> list[Trial]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    studies: dict[str, dict[str, Any]] = {}
    for term in search_terms:
        token = None
        while True:
            params = {"query.term": term, "query.locn": "India", "pageSize": 100, "format": "json"}
            if token:
                params["pageToken"] = token
            print(f"[ClinicalTrials.gov] {term}", file=sys.stderr)
            response = session.get(CTGOV_API, params=params, timeout=45)
            if response.status_code == 429:
                raise RuntimeError("ClinicalTrials.gov returned HTTP 429; stop and retry later.")
            response.raise_for_status()
            payload = response.json()
            for study in payload.get("studies", []):
                nct = study.get("protocolSection", {}).get("identificationModule", {}).get("nctId")
                if nct:
                    studies[str(nct)] = study
            token = payload.get("nextPageToken")
            if not token:
                break
            time.sleep(max(0.0, sleep_seconds))
        time.sleep(max(0.0, sleep_seconds))
    return [normalize_ctgov(s) for s in studies.values()]


def normalize_nct_ids(nct_ids: Iterable[str]) -> list[str]:
    """Upper-case and validate NCT identifiers, dropping blanks.

    Kept separate from the fetch so the validation can be tested without a
    network call, and so a typo fails before any request is made.
    """
    ids = [x.strip().upper() for x in nct_ids if x and x.strip()]
    invalid = [x for x in ids if not re.fullmatch(r"NCT\d{8}", x)]
    if invalid:
        raise RuntimeError("Not valid NCT identifiers: " + ", ".join(invalid))
    return ids


def fetch_ctgov_ids(nct_ids: Iterable[str], sleep_seconds: float = 0.35) -> list[Trial]:
    """Fetch specific studies by NCT identifier, without running a term search.

    Two uses. First, following a secondary identifier found in a CTRI record
    through to the fuller ClinicalTrials.gov record, which is where sites,
    contacts and eligibility criteria actually live. Second, re-checking the
    location list of a known trial without repeating the whole sweep -- country
    lists change without announcement, and for this research the India answer
    turns entirely on them.
    """
    ids = normalize_nct_ids(nct_ids)
    if not ids:
        return []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    trials: list[Trial] = []
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        print(f"[ClinicalTrials.gov] fetching {len(batch)} id(s)", file=sys.stderr)
        response = session.get(
            CTGOV_API,
            params={"filter.ids": ",".join(batch), "pageSize": len(batch), "format": "json"},
            timeout=45,
        )
        if response.status_code == 429:
            raise RuntimeError("ClinicalTrials.gov returned HTTP 429; stop and retry later.")
        response.raise_for_status()
        returned = set()
        for study in response.json().get("studies", []):
            trial = normalize_ctgov(study)
            returned.add(trial.nct_number)
            trials.append(trial)
        for missing in [x for x in batch if x not in returned]:
            print(f"[ClinicalTrials.gov] no record returned for {missing}", file=sys.stderr)
        time.sleep(max(0.0, sleep_seconds))
    return trials


def ictrp_search_urls(terms: Iterable[str]) -> list[tuple[str, str]]:
    """Build WHO ICTRP search URLs for a human to open.

    ICTRP publishes no open search API, so this cannot be collected
    automatically. It is worth having anyway: ICTRP mirrors CTRI as well as
    ClinicalTrials.gov and 15+ other registries, which makes it the most useful
    fallback when ctri.nic.in is unreachable or its Advanced Search Security
    Code cannot be completed.
    """
    return [(t, ICTRP_SEARCH + "?" + urlencode({"SearchTermStat": t})) for t in terms]


def load_ctgov_fixture(path: Path) -> list[Trial]:
    """Normalise ClinicalTrials.gov-shaped records from a local JSON file.

    Accepts either the API envelope ({"studies": [...]}) or a bare list. Used to
    exercise the pipeline with no network access; the bundled fixture is
    synthetic and is never evidence for a research conclusion.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    studies = payload.get("studies", []) if isinstance(payload, dict) else payload
    return [normalize_ctgov(s) for s in studies]


def canonical_label(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()


def parse_ctri_html(html: str, source_url: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        key = canonical_label(cells[0].get_text(" ", strip=True))
        value = " ".join(c.get_text(" ", strip=True) for c in cells[1:]).strip()
        if key and value:
            fields[key] = value
    if source_url:
        fields["source url"] = source_url
    return fields


def lookup(fields: dict[str, str], *labels: str) -> str:
    wanted = [canonical_label(x) for x in labels]
    for key in wanted:
        if key in fields:
            return fields[key]
    for key, value in fields.items():
        if any(w in key for w in wanted):
            return value
    return ""


def normalize_ctri(fields: dict[str, str], source_url: str = "") -> Trial:
    reg = lookup(fields, "CTRI Number", "CTRI registration number", "Registration Number")
    title = lookup(fields, "Public Title of Study", "Public Title", "Trial Title")
    scientific = lookup(fields, "Scientific Title of Study", "Scientific Title")
    condition = lookup(fields, "Health Condition / Problems Studied", "Health Condition", "Condition")
    intervention = lookup(fields, "Intervention / Comparator Agent", "Intervention", "Comparator")
    status = lookup(fields, "Recruitment Status of Trial (India)", "Recruitment Status India", "Recruitment Status")
    sites = lookup(fields, "Site/s of Study", "Study Sites", "Sites of Study")
    identifiers = lookup(fields, "Secondary ID", "Secondary IDs", "Universal Trial Number")
    evidence = find_evidence(" ".join([title, scientific, condition, intervention]))
    nct_match = re.search(r"\bNCT\d{8}\b", identifiers + " " + " ".join(fields.values()), re.I)
    nct = nct_match.group(0).upper() if nct_match else ""
    enum = status_to_enum(status)
    has_india = bool(sites.strip())
    return Trial(
        source="CTRI", registry_id=reg, ctri_registration_number=reg, nct_number=nct,
        trial_title=title, scientific_title=scientific, cancer_type_indication=condition,
        investigational_treatment=intervention, mrna_qualification_rationale=evidence.rationale(),
        trial_phase=lookup(fields, "Phase of Trial", "Trial Phase"), recruitment_status=status,
        date_of_registration=lookup(fields, "Date of Registration", "Registration Date"),
        study_start_date=lookup(fields, "Date of First Enrollment (India)", "Study Start Date"),
        sponsor=lookup(fields, "Name and Address of the Sponsor", "Primary Sponsor", "Sponsor"),
        principal_investigator=lookup(fields, "Name of Principal Investigator", "Principal Investigator"),
        indian_trial_sites=sites, participating_hospitals_institutions=sites,
        contact_person=lookup(fields, "Contact Person (Scientific Query)", "Contact Person"),
        contact_email=lookup(fields, "Email", "Contact Email"), contact_phone=lookup(fields, "Phone", "Contact Phone"),
        key_inclusion_criteria=lookup(fields, "Inclusion Criteria"), key_exclusion_criteria=lookup(fields, "Exclusion Criteria"),
        relevant_age_limits=join([lookup(fields, "Age From"), lookup(fields, "Age To")], " to "),
        ctri_url=source_url or fields.get("source url", ""), international_identifiers=join([reg, nct, identifiers]),
        clinicaltrials_gov_url=CTGOV_STUDY.format(nct_id=nct) if nct else "",
        category=category(evidence.qualifies, has_india, enum), qualifies_mrna_cancer_vaccine=evidence.qualifies,
        has_verified_india_site=has_india,
        manual_verification_reason=disqualification_reason(evidence),
        classification_tier=evidence.tier, classification_vetoes=join(evidence.vetoes),
    )


def fetch_ctri_record(session: requests.Session, url: str) -> Trial:
    if "ctri.nic.in" not in url.lower():
        raise RuntimeError(f"Refusing non-CTRI URL: {url}")
    response = session.get(url, timeout=45)
    if response.status_code == 429:
        raise RuntimeError("CTRI returned HTTP 429; stop and retry later.")
    response.raise_for_status()
    return normalize_ctri(parse_ctri_html(response.text, url), url)


def deduplicate(trials: Iterable[Trial]) -> list[Trial]:
    out: dict[str, Trial] = {}
    for trial in trials:
        key = (trial.nct_number or trial.ctri_registration_number or trial.registry_id or trial.trial_title).strip().lower()
        if key:
            out[key] = trial
    return sorted(out.values(), key=lambda x: (x.category, x.registry_id, x.trial_title))


def write_outputs(trials: list[Trial], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "raw_results.json").write_text(json.dumps([asdict(t) for t in trials], indent=2, ensure_ascii=False), encoding="utf-8")
    fields = list(Trial.__dataclass_fields__.keys())
    for name, rows in {
        "deduplicated_candidates.csv": [t for t in trials if t.qualifies_mrna_cancer_vaccine and t.has_verified_india_site],
        "manual_verification.csv": [t for t in trials if t.category == "D"],
    }.items():
        with (output_dir / name).open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))


def load_terms(path: Path | None) -> list[str]:
    if not path:
        return DEFAULT_SEARCH_TERMS.copy()
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--search-terms-file", type=Path)
    p.add_argument("--output-dir", type=Path, default=Path("output"))
    p.add_argument("--ctri-url", action="append", default=[])
    p.add_argument("--ctri-url-file", type=Path)
    p.add_argument("--ctri-html-dir", type=Path)
    p.add_argument("--nct", nargs="*", default=[], metavar="NCT_ID",
                   help="fetch these specific ClinicalTrials.gov studies by id "
                        "instead of running the term sweep")
    p.add_argument("--print-ictrp-urls", action="store_true",
                   help="print WHO ICTRP search URLs for each term and exit; ICTRP "
                        "has no public API and mirrors CTRI, so it is searched by hand")
    p.add_argument("--fixture", type=Path,
                   help="normalise ClinicalTrials.gov records from a local JSON file "
                        "instead of querying the API (implies --skip-ctgov)")
    p.add_argument("--skip-ctgov", action="store_true",
                   help="do not query ClinicalTrials.gov; use for offline CTRI-only runs")
    p.add_argument("--sleep-seconds", type=float, default=0.35)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.print_ictrp_urls:
        for term, url in ictrp_search_urls(load_terms(args.search_terms_file)):
            print(f"{term}\t{url}")
        return 0

    try:
        if args.fixture:
            trials = load_ctgov_fixture(args.fixture)
        elif args.nct:
            trials = fetch_ctgov_ids(args.nct, args.sleep_seconds)
        elif args.skip_ctgov:
            trials = []
        else:
            trials = collect_ctgov(load_terms(args.search_terms_file), args.sleep_seconds)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    urls = list(args.ctri_url)
    if args.ctri_url_file:
        urls += [x.strip() for x in args.ctri_url_file.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    if urls:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html"})
        for url in urls:
            trials.append(fetch_ctri_record(session, url))
            time.sleep(max(0.0, args.sleep_seconds))

    if args.ctri_html_dir:
        for path in sorted(args.ctri_html_dir.glob("*.html")):
            trials.append(normalize_ctri(parse_ctri_html(path.read_text(encoding="utf-8", errors="replace"), str(path)), str(path)))

    trials = deduplicate(trials)
    write_outputs(trials, args.output_dir)
    counts: dict[str, int] = {}
    for trial in trials:
        counts[trial.category] = counts.get(trial.category, 0) + 1
    print(json.dumps({"trials": len(trials), "categories": counts, "output_dir": str(args.output_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
