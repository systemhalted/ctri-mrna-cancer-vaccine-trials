# CTRI mRNA Cancer Vaccine Trial Research

Research and collection tooling for identifying therapeutic mRNA cancer-vaccine trials registered in India, with CTRI as the primary registry and ClinicalTrials.gov as a structured cross-check.

## Current finding

**As of 2026-08-22, this investigation did not verify any therapeutic mRNA cancer-vaccine trial that is currently recruiting, not yet recruiting, or otherwise open at an Indian study site.**

This is a conservative result, not proof that no such study exists. CTRI Advanced Search requires a human-entered Security Code (CAPTCHA) for submitted searches. This project does not automate, solve, or bypass that control. Because of that limitation, the investigation combines public CTRI record/index checks with structured ClinicalTrials.gov searches, WHO ICTRP indexing, CDSCO references, sponsor trial pages, and targeted searches for known products and identifiers.

## Repository branch

`research/ctri-mrna-cancer-vaccine-trials`

## Files

- `ctri_mrna_trials.py`: search, normalization, classification, CTRI-record parsing, and export tool.
- `search_terms.txt`: discovery terms and known investigational products.
- `data/raw_results.json`: curated research snapshot and excluded near matches.
- `data/deduplicated_candidates.csv`: verified India candidates. It is header-only because none were verified in this run.
- `data/excluded_near_matches.csv`: active mRNA cancer-vaccine programs found internationally but without a verified India site.
- `data/ctri_false_positives.csv`: CTRI records useful for testing the classifier's precision.
- `data/fixtures/clinicaltrials_fixture.json`: offline fixture for validating the collector without network access.
- `tests/test_classifier.py`: classifier and parser tests.
- `FINDINGS.md`: research report, candidate categories, contact paths, and limitations.

## How CTRI Advanced Search works

The public Advanced Search page exposes an HTML search form with filters including trial phase, sponsor, Indian recruitment status, state, district, and keyword. It also requires a human-entered **Security Code** shown as an image before a search can be submitted. No documented public search API was identified on that page.

The script therefore does **not** automate CTRI Advanced Search. Instead it supports two compliant CTRI workflows:

1. Parse known public CTRI record URLs with `--ctri-url` or `--ctri-url-file`.
2. Parse CTRI record HTML that a person saved after performing a manual search with `--ctri-html-dir`.

ClinicalTrials.gov provides a public v2 REST API, which is the script's primary structured discovery source.

## Installation

Python 3.10+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

## Run live discovery

```bash
python ctri_mrna_trials.py \
  --search-terms-file search_terms.txt \
  --output-dir output
```

The program queries ClinicalTrials.gov using each search term and `India` as the location query, deduplicates by NCT number, verifies that at least one returned location has `country == "India"`, applies a conservative mRNA-cancer-vaccine classifier, and writes JSON/CSV outputs.

To parse public CTRI records discovered manually:

```bash
python ctri_mrna_trials.py \
  --ctri-url "https://ctri.nic.in/Clinicaltrials/pmaindet2.php?trialid=..." \
  --output-dir output
```

Or save CTRI result pages as HTML and run:

```bash
python ctri_mrna_trials.py \
  --ctri-html-dir ./saved-ctri-records \
  --output-dir output
```

The script intentionally does not submit the CTRI CAPTCHA-protected Advanced Search form.

## Offline validation

The working environment used for this research did not provide outbound DNS to Python/CLI processes, so the live HTTP collector could not be executed from the container. The classifier/export pipeline was run against the included offline fixture and the unit tests were run locally. Actual findings in `data/raw_results.json` and `FINDINGS.md` were compiled from browser-accessible authoritative registry and sponsor sources, not from the fixture.

```bash
python -m unittest discover -s tests -v
python ctri_mrna_trials.py \
  --fixture data/fixtures/clinicaltrials_fixture.json \
  --output-dir /tmp/ctri-fixture-output
```

## Search methodology

The search starts broad and then expands by product and sponsor names discovered during review. Terms include:

- mRNA, messenger RNA, RNA vaccine
- cancer vaccine, tumor vaccine, therapeutic vaccine
- neoantigen, personalized neoantigen, personalized cancer vaccine
- individualized vaccine, tumor-specific antigen, mRNA immunotherapy
- V940, mRNA-4157, intismeran autogene
- BNT111, BNT113, BNT116, BNT122, autogene cevumeran, RO7198457
- mRNA-4359, RNA-LPX, RNA lipoplex, FixVac

A study is not classified as qualifying merely because it contains `RNA`, `vaccine`, `immunotherapy`, or `gene therapy`. A qualifying result must have evidence of all of the following:

1. Cancer/malignancy indication.
2. An mRNA or messenger-RNA therapeutic mechanism, or a validated known mRNA oncology product.
3. Therapeutic cancer-vaccine/immunotherapy context such as neoantigens, tumor-associated antigens, personalized/individualized vaccine construction, or a known therapeutic mRNA oncology platform.
4. A verified Indian study site for categories A-C.

## Patient enrollment safety

This project does not enroll anyone or transmit patient information. Trial eligibility is determined by trial investigators. For initial contact, give the trial identifier and a concise diagnosis/treatment summary first, and ask the trial team what records they want. Do not email complete medical records, government identifiers, or other sensitive information unless the verified study team explicitly requests a secure transfer method.

## Source set used for the 2026-08-22 snapshot

- CTRI Advanced Search: https://ctri.nic.in/Clinicaltrials/advancesearchmain.php
- CTRI home/about/search documentation: https://ctri.nic.in/
- ClinicalTrials.gov API documentation: https://clinicaltrials.gov/data-api/api
- ClinicalTrials.gov study pages for the NCT identifiers listed in `FINDINGS.md`
- Merck clinical-trial pages for V940/intismeran autogene studies
- BioNTech clinical-trial pages for BNT113, BNT116, and autogene cevumeran programs
- Moderna/ClinicalTrials.gov information for mRNA-4359
- CDSCO clinical-trial permission pages
- WHO ICTRP search/index cross-checks

See `FINDINGS.md` for study-specific source references and contact paths.
