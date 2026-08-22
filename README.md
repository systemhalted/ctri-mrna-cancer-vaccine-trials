# CTRI mRNA Cancer Vaccine Trial Research

Research and collection tooling for identifying therapeutic mRNA cancer-vaccine trials registered in India, with CTRI as the primary registry and ClinicalTrials.gov as a structured cross-check.

> **Not medical advice.** This repository is research support. Trial eligibility is
> determined solely by the trial investigators. See [`NOTICE.md`](NOTICE.md) for the
> full research, patient-data and medical-use safeguards, and [Licensing](#licensing)
> for reuse terms.
>
> **Patient-data warning:** Do not store personally identifiable patient information, medical records, pathology reports, imaging, genomic files tied to a person, or other sensitive health information in this repository. Use only verified secure transfer mechanisms provided by trial investigators, hospitals, or sponsors. See [`NOTICE.md`](NOTICE.md).

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
- `data/fixtures/clinicaltrials_fixture.json`: synthetic ClinicalTrials.gov fixture for validating the collector without network access.
- `data/fixtures/ctri_record.html`: synthetic CTRI record page for validating the CTRI parser.
- `classify.py`: the mRNA cancer-vaccine classifier (three evidence axes plus vetoes).
- `tests/test_classifier.py`: classifier and parser tests.
- `FINDINGS.md`: research report, candidate categories, contact paths, and limitations.
- `NOTICE.md`: registry-use, verification, copyright, patient-data, and medical-use safeguards.
- `LICENSE`: MIT license covering the source code.
- `LICENSE-DATA`: CC BY 4.0 license covering the research data and documentation.

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

Add `--skip-ctgov` to parse saved CTRI records with no network access at all:

```bash
python ctri_mrna_trials.py \
  --skip-ctgov \
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

`search_terms.txt` holds 90 terms in six groups. Terms are run separately, not
combined: CTRI does no stemming or synonym expansion, so `tumour vaccine` and
`tumor vaccine` return different result sets and both are needed.

- **Platform** -- mRNA, messenger RNA, RNA vaccine, self-amplifying RNA, saRNA, RNA lipoplex, uridine mRNA, nucleoside-modified RNA
- **Product class** -- cancer vaccine, tumor/tumour vaccine, therapeutic vaccine, neoantigen, neoepitope, personalized/personalised neoantigen, individualized vaccine, tumor-specific antigen, mRNA immunotherapy, iNeST, FixVac
- **Combined phrases** -- mRNA cancer vaccine, neoantigen mRNA vaccine, individualized neoantigen therapy
- **Products** -- V940, mRNA-4157, intismeran autogene, BNT111/112/113/115/116/122, autogene cevumeran, RO7198457, mRNA-4359, mRNA-5671, CV9201, CV9202, BI 1361849, RNA-LPX
- **Sponsors** -- Moderna, BioNTech, Genentech, Merck Sharp, MSD Pharmaceuticals, CureVac, Gritstone, Gennova, Emcure
- **India-adjacent** -- dendritic cell vaccine, APCEDEN, peptide vaccine cancer, DNA vaccine cancer. Not mRNA vaccines, but they identify Indian investigators and sites with cancer-vaccine trial experience.

A study is not classified as qualifying merely because it contains `RNA`,
`vaccine`, `immunotherapy`, or `gene therapy`. `classify.py` requires evidence
on three independent axes with no veto firing, plus a site check:

1. **Platform** -- an mRNA/messenger-RNA construct, or a product name that is an
   mRNA platform by definition.
2. **Modality** -- active immunisation: vaccine, vaccination, neoantigen,
   antigen-specific immunotherapy.
3. **Disease** -- a cancer indication.
4. **No veto.** Vetoes cover mRNA used as a diagnostic analyte or measured
   biomarker rather than as the drug, infectious-disease vaccines, prophylactic
   HPV vaccination, and siRNA/miRNA/antisense.
5. **A verified Indian study site** for categories A-C.

The axes are deliberately narrow. An earlier revision matched bare terms
including `breast`, `lung` and `immunotherapy`; because `breast feeding` and
`prior immunotherapy` appear in the exclusion criteria of most trials, cancer
and therapeutic evidence fired on almost any record, and four of five hard
negatives wrongly qualified. Those five cases are now regression tests.

Adjacent modalities -- dendritic cell, peptide, DNA, viral vector, CAR-T --
downgrade rather than veto, so an mRNA-electroporated dendritic-cell vaccine is
flagged for review instead of dropped.

## Patient enrollment safety

This project does not enroll anyone or transmit patient information. Trial eligibility is determined by trial investigators. For initial contact, give the trial identifier and a concise diagnosis/treatment summary first, and ask the trial team what records they want. Do not email complete medical records, government identifiers, or other sensitive information unless the verified study team explicitly requests a secure transfer method.

**Never commit patient-identifiable medical information to this repository.** Defensive ignore rules cover common patient-data directories and DICOM file extensions, but `.gitignore` is not a security boundary; contributors remain responsible for ensuring sensitive information is never added to Git history.

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

## Licensing

This repository is split-licensed, because it contains two different kinds of
work.

| What | License | File |
|---|---|---|
| Source code (`*.py`, `tests/`, packaging) | **MIT** | [`LICENSE`](LICENSE) |
| Research data and documentation (`data/`, `docs/`, `FINDINGS.md`, `VALIDATION.txt`, `search_terms.txt`) | **CC BY 4.0** | [`LICENSE-DATA`](LICENSE-DATA) |

MIT keeps the tooling frictionless to reuse, fork and vendor. CC BY 4.0 is the
normal choice for a curated research dataset: reuse is unrestricted, including
commercially, but the compilation must be credited.

Two limits are worth stating plainly:

- **The facts are not owned.** CTRI registration numbers, NCT identifiers,
  sponsor names, recruitment statuses and published contact details are factual
  information and are not subject to copyright. CC BY 4.0 covers the selection,
  arrangement and annotation that make up this dataset -- not the underlying
  facts.
- **Source material keeps its own terms.** Records retrieved from CTRI,
  ClinicalTrials.gov, the WHO ICTRP and sponsor websites remain governed by
  those sources' terms. Check them before redistributing their content.

### Warranty disclaimer

Both licenses are provided without warranty of any kind. Nothing here is medical
advice or an eligibility determination, and the research snapshot is dated --
verify every detail against the primary registry record before acting on it.
[`NOTICE.md`](NOTICE.md) states the research, patient-data and medical-use
safeguards in full.
