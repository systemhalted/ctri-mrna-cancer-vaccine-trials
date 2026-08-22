"""
Classifier that decides whether a registry record is plausibly an
mRNA-based *therapeutic cancer vaccine* trial.

The brief for this work was explicit: a study must NOT be classified as an
mRNA cancer vaccine merely because the words "RNA", "gene therapy",
"immunotherapy" or "vaccine" appear somewhere in the record. So the rule is
a conjunction of three independent axes, plus an explicit veto list:

    (1) PLATFORM  - evidence the product is mRNA / messenger-RNA based
    (2) MODALITY  - evidence it is an active immunisation (vaccine), not a
                    passive antibody, cell therapy or small molecule
    (3) DISEASE   - evidence the indication is cancer

    (4) VETOES    - patterns that positively rule the record out even when
                    (1)-(3) all fire, e.g. an HPV E6/E7 mRNA *diagnostic
                    assay* (the mRNA is the analyte, not the drug), or a
                    prophylactic infectious-disease mRNA vaccine.

Output is a tier, not a boolean, because registry free text is often too
thin to decide. Everything that is not clearly confirmed lands in a
"needs manual verification" bucket rather than being silently dropped.
"""

import re

# ---------------------------------------------------------------- axis 1
PLATFORM_PATTERNS = [
    (r"\bm[\-\s]?rna\b", "explicit 'mRNA'"),
    (r"\bmessenger\s+rna\b", "'messenger RNA'"),
    (r"\bmessenger\s+ribonucleic\s+acid\b", "'messenger ribonucleic acid'"),
    (r"\bmod[\-\s]?rna\b", "'modRNA' (nucleoside-modified mRNA)"),
    (r"\bsa[\-\s]?rna\b", "'saRNA' (self-amplifying RNA)"),
    (r"\bself[\-\s]?amplifying\s+rna\b", "'self-amplifying RNA'"),
    (r"\breplicon\s+rna\b", "'replicon RNA'"),
    (r"\brna\s+lipoplex\b", "'RNA-lipoplex' (BioNTech mRNA formulation)"),
    (r"\blipoplex[\-\s]?formulated\b", "'lipoplex-formulated' mRNA"),
    (r"\buridine\s+mrna\b", "'uridine mRNA'"),
    (r"\bnucleoside[\-\s]?modified\s+rna\b", "'nucleoside-modified RNA'"),
    (r"\brna\s+vaccine\b", "'RNA vaccine'"),
    (r"\brna[\-\s]?based\s+(vaccine|immunotherap|therap)", "'RNA-based' product"),
    (r"\bcircular\s+rna\b", "'circular RNA'"),
    (r"\bin\s+vitro\s+transcribed\s+rna\b", "'in vitro transcribed RNA'"),
    (r"\bivt[\-\s]?rna\b", "'IVT-RNA'"),
]

# Product names that are, by definition, mRNA platforms. These carry
# platform evidence on their own because registry text often omits "mRNA".
KNOWN_MRNA_PRODUCTS = {
    "mrna-4157": "Moderna/Merck individualised neoantigen therapy (mRNA)",
    "mrna4157": "Moderna/Merck individualised neoantigen therapy (mRNA)",
    "v940": "V940 = mRNA-4157, Moderna/Merck mRNA neoantigen therapy",
    "intismeran": "intismeran autogene = mRNA-4157/V940, mRNA neoantigen therapy",
    "autogene cevumeran": "BioNTech/Genentech uridine-mRNA lipoplex iNeST",
    "bnt122": "autogene cevumeran, BioNTech mRNA iNeST",
    "ro7198457": "autogene cevumeran, BioNTech/Genentech mRNA iNeST",
    "bnt111": "BioNTech FixVac mRNA-lipoplex vaccine (melanoma)",
    "bnt113": "BioNTech FixVac mRNA-lipoplex vaccine (HPV16+ HNSCC)",
    "bnt115": "BioNTech FixVac mRNA-lipoplex vaccine (ovarian)",
    "bnt116": "BioNTech FixVac mRNA-lipoplex vaccine (NSCLC)",
    "mrna-4359": "Moderna mRNA checkpoint/antigen vaccine",
    "mrna-5671": "Moderna KRAS mRNA vaccine",
    "necvax-neo1": "neoantigen mRNA/oral vaccine candidate",
    "lipo-merit": "BioNTech RNA-lipoplex melanoma trial programme",
    "fixvac": "BioNTech off-the-shelf mRNA-lipoplex vaccine platform",
    "inest": "individualised neoantigen specific immunoTherapy (mRNA)",
    "bnt112": "BioNTech FixVac mRNA-lipoplex vaccine (prostate)",
    "cv9201": "CureVac RNActive self-adjuvanted mRNA vaccine (NSCLC)",
    "cv9202": "CureVac RNActive mRNA vaccine (NSCLC)",
    "bi 1361849": "CV9202, Boehringer/CureVac mRNA cancer vaccine",
    "bi1361849": "CV9202, Boehringer/CureVac mRNA cancer vaccine",
    "rna-lpx": "RNA-lipoplex, BioNTech mRNA vaccine formulation",
    "rna lpx": "RNA-lipoplex, BioNTech mRNA vaccine formulation",
}

# ---------------------------------------------------------------- axis 2
MODALITY_PATTERNS = [
    (r"\bvaccin", "'vaccine/vaccination'"),
    (r"\bimmuni[sz]ation\b", "'immunisation'"),
    (r"\bneo[\-\s]?antigen", "'neoantigen'"),
    (r"\bneo[\-\s]?epitope", "'neoepitope'"),
    (r"\bindividuali[sz]ed\s+neoantigen", "'individualised neoantigen therapy'"),
    (r"\bantigen[\-\s]?specific\s+immunotherap", "'antigen-specific immunotherapy'"),
    (r"\btumou?r[\-\s]?specific\s+antigen", "'tumour-specific antigen'"),
    (r"\btumou?r[\-\s]?associated\s+antigen", "'tumour-associated antigen'"),
    (r"\bactive\s+immunotherap", "'active immunotherapy'"),
]

# ---------------------------------------------------------------- axis 3
DISEASE_PATTERNS = [
    r"\bcancer\b", r"\bcarcinoma\b", r"\btumou?r\b", r"\bneoplas", r"\bmalignan",
    r"\bmelanoma\b", r"\bsarcoma\b", r"\blymphoma\b", r"\bleukae?mia\b",
    r"\bmyeloma\b", r"\bglioma\b", r"\bglioblastoma\b", r"\boncolog",
    r"\bmetasta", r"\bnsclc\b", r"\bhnscc\b", r"\bcrc\b", r"\bpdac\b",
    r"\bsolid\s+tumou?r", r"\badenocarcinoma\b",
]

# ---------------------------------------------------------------- axis 4
# Each veto is (pattern, human-readable reason). Vetoes are checked against
# the whole record and are strong enough to override axes 1-3.
VETO_PATTERNS = [
    # mRNA as an ANALYTE / biomarker / diagnostic, not as a drug.
    (r"\b(e6\s*/?\s*e7|e6\s+and\s+e7)\s+mrna\b.*\b(test|assay|triage|screen|detect)",
     "HPV E6/E7 mRNA is used here as a diagnostic analyte, not a therapeutic"),
    (r"\bmrna\b[^.]{0,60}\b(expression|quantification|detection|assay|biomarker|rt[\-\s]?pcr|transcriptom)",
     "mRNA appears as a measured biomarker/assay endpoint, not the intervention"),
    (r"\b(qrt|rt)[\-\s]?pcr\b[^.]{0,40}\bmrna\b",
     "mRNA measured by RT-PCR - laboratory endpoint, not an intervention"),
    # Prophylactic infectious-disease vaccines.
    (r"\b(sars[\-\s]?cov[\-\s]?2|covid|influenza|rabies|zika|rsv|dengue|chikungunya|nipah|mpox)\b",
     "indication is an infectious disease, not cancer therapy"),
    # Prophylactic HPV vaccination (cancer PREVENTION, not therapeutic vaccine).
    (r"\bprophylactic\b[^.]{0,40}\bhpv\b|\bhpv\b[^.]{0,40}\bprophylactic\b",
     "prophylactic HPV vaccination - cancer prevention, not a therapeutic cancer vaccine"),
    # Other RNA modalities that are not vaccines.
    (r"\b(sirna|shrna|mirna|micro[\-\s]?rna|antisense\s+oligonucleotide|aso)\b",
     "RNA modality is siRNA/miRNA/antisense - gene silencing, not an mRNA vaccine"),
]

# Modalities that are adjacent but are NOT mRNA vaccines. These downgrade
# rather than veto outright, because e.g. mRNA-electroporated dendritic
# cells genuinely are an mRNA-based cancer vaccine.
DOWNGRADE_PATTERNS = [
    (r"\bcar[\-\s]?t\b", "CAR-T cell therapy"),
    (r"\bdendritic\s+cell\b", "dendritic-cell platform"),
    (r"\bpeptide\s+vaccine\b", "peptide vaccine"),
    (r"\bdna\s+vaccine\b", "DNA (plasmid) vaccine"),
    (r"\bviral\s+vector\b|\badenoviral\b|\bmva\b", "viral-vector vaccine"),
    (r"\bwhole\s+cell\s+vaccine\b", "whole-cell vaccine"),
    (r"\bbcg\b|\bmycobacterium\s+w\b", "bacterial immunostimulant"),
]

TIER_CONFIRMED = "A_confirmed_mrna_cancer_vaccine"
TIER_PROBABLE = "B_probable_needs_confirmation"
TIER_MANUAL = "C_possible_manual_verification"
TIER_EXCLUDED = "D_excluded"


def _haystack(record):
    """Concatenate every free-text field we care about, lowercased."""
    fields = [
        "public_title", "scientific_title", "brief_title", "official_title",
        "intervention", "interventions", "condition", "conditions",
        "summary", "brief_summary", "detailed_description", "keywords",
        "sponsor", "primary_sponsor", "method_of_generating_sequence",
        "inclusion_criteria", "exclusion_criteria", "arms",
    ]
    parts = []
    for f in fields:
        v = record.get(f)
        if isinstance(v, (list, tuple)):
            parts.extend(str(x) for x in v)
        elif v:
            parts.append(str(v))
    return " ".join(parts).lower()


def classify(record):
    """Return a dict describing whether `record` is an mRNA cancer vaccine trial.

    `record` is any dict with registry-ish free-text fields (see _haystack).
    """
    text = _haystack(record)
    if not text.strip():
        return {
            "tier": TIER_EXCLUDED,
            "named_products": [],
            "platform_evidence": [], "modality_evidence": [],
            "disease_evidence": [], "vetoes": ["record contains no usable text"],
            "downgrades": [], "rationale": "Empty record - nothing to classify.",
        }

    platform, modality, disease, vetoes, downgrades = [], [], [], [], []

    for pat, why in PLATFORM_PATTERNS:
        if re.search(pat, text):
            platform.append(why)
    for name, why in KNOWN_MRNA_PRODUCTS.items():
        if name in text:
            platform.append(f"named product '{name}': {why}")
    for pat, why in MODALITY_PATTERNS:
        if re.search(pat, text):
            modality.append(why)
    for pat in DISEASE_PATTERNS:
        m = re.search(pat, text)
        if m:
            disease.append(m.group(0))
    for pat, why in VETO_PATTERNS:
        if re.search(pat, text):
            vetoes.append(why)
    for pat, why in DOWNGRADE_PATTERNS:
        if re.search(pat, text):
            downgrades.append(why)

    named_products = sorted({n for n in KNOWN_MRNA_PRODUCTS if n in text})
    platform = sorted(set(platform))
    modality = sorted(set(modality))
    disease = sorted(set(disease))
    vetoes = sorted(set(vetoes))
    downgrades = sorted(set(downgrades))

    # A named mRNA product is strong enough to survive a generic veto such as
    # an incidental mention of COVID vaccination in exclusion criteria.
    named_product = any(e.startswith("named product") for e in platform)
    hard_veto = [v for v in vetoes if not named_product or "diagnostic" in v or "analyte" in v]

    if hard_veto:
        tier = TIER_EXCLUDED
        rationale = "Vetoed: " + "; ".join(hard_veto)
    elif platform and modality and disease:
        if downgrades and not named_product and not any(
            "mRNA" in p or "RNA" in p for p in platform
        ):
            tier = TIER_MANUAL
            rationale = ("Meets all three axes but the platform reads as "
                         + ", ".join(downgrades) + " - verify the construct.")
        elif downgrades and not named_product:
            tier = TIER_PROBABLE
            rationale = ("mRNA + vaccine + cancer all present, but record also "
                         "mentions " + ", ".join(downgrades) +
                         "; confirm the active agent is the mRNA itself.")
        else:
            tier = TIER_CONFIRMED
            rationale = ("mRNA platform (" + "; ".join(platform[:3]) +
                         "), active-immunisation modality (" + "; ".join(modality[:3]) +
                         "), cancer indication (" + ", ".join(disease[:3]) + ").")
    elif platform and disease and not modality:
        tier = TIER_MANUAL
        rationale = ("mRNA and cancer present but no clear vaccine/active-"
                     "immunisation wording - could be an RNA biomarker study "
                     "or a non-vaccine RNA therapeutic.")
    elif modality and disease and not platform:
        tier = TIER_MANUAL
        rationale = ("Cancer vaccine present but platform is not stated as mRNA - "
                     "may be peptide/DC/DNA/viral-vector. Verify the construct.")
    else:
        tier = TIER_EXCLUDED
        missing = [n for n, v in (("mRNA platform", platform),
                                  ("vaccine modality", modality),
                                  ("cancer indication", disease)) if not v]
        rationale = "Missing required evidence: " + ", ".join(missing) + "."

    return {
        "tier": tier,
        "named_products": named_products,
        "platform_evidence": platform,
        "modality_evidence": modality,
        "disease_evidence": disease,
        "vetoes": vetoes,
        "downgrades": downgrades,
        "rationale": rationale,
    }


RECRUITING_OPEN = {
    "recruiting", "not yet recruiting", "open to recruitment",
    "enrolling by invitation", "active, not recruiting",
    "open", "yet to start",
}


def recruitment_bucket(status):
    """Map a free-text recruitment status onto the A/B/C reporting buckets."""
    s = (status or "").strip().lower()
    if not s:
        return "B_status_uncertain"
    if "not yet" in s or "yet to start" in s:
        return "B_status_uncertain"
    if "recruiting" in s and "not recruiting" not in s:
        return "A_recruiting"
    if s.startswith("open") or "enrolling" in s:
        return "A_recruiting"
    if any(k in s for k in ("completed", "closed", "terminated", "withdrawn",
                            "suspended", "not recruiting", "no longer")):
        return "C_closed_or_past"
    return "B_status_uncertain"
