import pathlib
import unittest

from ctri_mrna_trials import (
    category,
    fetch_ctgov_ids,
    normalize_nct_ids,
    find_evidence,
    ictrp_search_urls,
    load_ctgov_fixture,
    normalize_ctri,
    parse_ctri_html,
    status_to_enum,
)

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "data" / "fixtures"


class EvidenceTests(unittest.TestCase):
    def test_known_mrna_oncology_product_qualifies(self):
        evidence = find_evidence(
            "Phase 3 cancer trial of V940 individualized neoantigen therapy in melanoma"
        )
        self.assertTrue(evidence.qualifies)
        self.assertIn("v940", evidence.known_product)

    def test_covid_mrna_vaccine_does_not_qualify(self):
        evidence = find_evidence("mRNA vaccine for prevention of COVID-19 in healthy adults")
        self.assertFalse(evidence.qualifies)

    def test_generic_immunotherapy_without_mrna_does_not_qualify(self):
        evidence = find_evidence("therapeutic cancer immunotherapy using autologous dendritic cells")
        self.assertFalse(evidence.qualifies)


class StatusTests(unittest.TestCase):
    def test_ctri_open_to_recruitment(self):
        self.assertEqual(status_to_enum("Open to Recruitment"), "RECRUITING")

    def test_ctri_not_yet_recruiting(self):
        self.assertEqual(status_to_enum("Not Yet Recruiting"), "NOT_YET_RECRUITING")

    def test_categories(self):
        self.assertEqual(category(True, True, "RECRUITING"), "A")
        self.assertEqual(category(True, True, "NOT_YET_RECRUITING"), "B")
        self.assertEqual(category(True, True, "COMPLETED"), "C")
        self.assertEqual(category(True, False, "RECRUITING"), "D")
        self.assertEqual(category(False, True, "RECRUITING"), "D")


class CtriParserTests(unittest.TestCase):
    def test_basic_record_normalization(self):
        html = """
        <table>
          <tr><td>CTRI Number</td><td>CTRI/2026/01/123456</td></tr>
          <tr><td>Public Title of Study</td><td>Personalized mRNA neoantigen vaccine for melanoma</td></tr>
          <tr><td>Scientific Title of Study</td><td>Individualized messenger RNA tumor vaccine</td></tr>
          <tr><td>Health Condition / Problems Studied</td><td>Melanoma cancer</td></tr>
          <tr><td>Intervention / Comparator Agent</td><td>mRNA encoding patient-specific neoantigens</td></tr>
          <tr><td>Recruitment Status of Trial (India)</td><td>Open to Recruitment</td></tr>
          <tr><td>Site/s of Study</td><td>Example Cancer Centre, Mumbai, India</td></tr>
          <tr><td>Secondary ID</td><td>NCT12345678</td></tr>
        </table>
        """
        fields = parse_ctri_html(html)
        trial = normalize_ctri(fields, "https://ctri.nic.in/example")
        self.assertEqual(trial.ctri_registration_number, "CTRI/2026/01/123456")
        self.assertEqual(trial.nct_number, "NCT12345678")
        self.assertTrue(trial.qualifies_mrna_cancer_vaccine)
        self.assertTrue(trial.has_verified_india_site)
        self.assertEqual(trial.category, "A")


class BoilerplateFalsePositiveTests(unittest.TestCase):
    """Records that a bare-keyword matcher wrongly accepted.

    Every string below carries the eligibility boilerplate that real registry
    records carry -- "breast feeding", "prior immunotherapy" -- which is what
    defeated the previous matcher: "breast" scored as cancer evidence and
    "immunotherapy" as therapeutic evidence, so four of these five qualified.
    """

    def assert_rejected(self, text):
        evidence = find_evidence(text)
        self.assertFalse(
            evidence.qualifies,
            f"wrongly qualified: cancer={evidence.cancer} mrna={evidence.mrna} "
            f"therapeutic={evidence.therapeutic}",
        )
        return evidence

    def test_covid_vaccine_with_breast_feeding_exclusion(self):
        e = self.assert_rejected(
            "A study of an mRNA vaccine for prevention of COVID-19. Exclusion: "
            "pregnant or breast feeding women. Immunotherapy within 30 days."
        )
        self.assertTrue(e.vetoes)

    def test_mrna_expression_biomarker_study(self):
        self.assert_rejected(
            "Prognostic value of gene mRNA expression by qRT-PCR in patients with "
            "breast carcinoma receiving immunotherapy. No investigational agent."
        )

    def test_hpv_mrna_triage_assay_is_a_diagnostic(self):
        self.assert_rejected(
            "HPV E6/E7 mRNA versus HPV DNA as triage for cervical cancer screening. "
            "The mRNA test triages screen-positive women. Immunotherapy not given."
        )

    def test_sirna_oncology_drug_is_not_a_vaccine(self):
        self.assert_rejected(
            "siRNA targeting KRAS in pancreatic carcinoma. Lipid nanoparticle "
            "siRNA immunotherapy combination."
        )

    def test_influenza_vaccine_mentioning_lung(self):
        self.assert_rejected(
            "An mRNA influenza vaccine in healthy adults; endpoints include lung "
            "function. Prior immunotherapy excluded."
        )

    def test_true_positive_survives_the_same_boilerplate(self):
        evidence = find_evidence(
            "Phase 3 trial of V940 (mRNA-4157) individualized neoantigen therapy plus "
            "pembrolizumab in resected melanoma. Exclusion: breast feeding, prior "
            "immunotherapy."
        )
        self.assertTrue(evidence.qualifies)
        self.assertIn("v940", evidence.known_product)


class AdjacentModalityTests(unittest.TestCase):
    """Cancer vaccines that are not mRNA, and mRNA that is not a vaccine."""

    def test_peptide_neoantigen_vaccine_is_not_confirmed(self):
        self.assertFalse(find_evidence(
            "Personalised neoantigen synthetic long peptide vaccine in advanced melanoma"
        ).qualifies)

    def test_dendritic_cell_vaccine_is_not_confirmed(self):
        self.assertFalse(find_evidence(
            "Autologous dendritic cell vaccine pulsed with tumour lysate in refractory "
            "solid malignancies"
        ).qualifies)

    def test_car_t_is_not_a_vaccine(self):
        self.assertFalse(find_evidence(
            "Autologous CD19-directed CAR-T cell therapy in relapsed B-cell lymphoma"
        ).qualifies)

    def test_mrna_loaded_dendritic_cells_are_flagged_not_dropped(self):
        evidence = find_evidence(
            "Autologous dendritic cells electroporated with tumour mRNA encoding WT1 "
            "in glioblastoma"
        )
        self.assertTrue(evidence.qualifies or evidence.needs_manual_review)


class CtriFalsePositiveTests(unittest.TestCase):
    """Real CTRI records from data/ctri_false_positives.csv."""

    def test_gemcovac_covid_vaccine(self):
        self.assertFalse(find_evidence(
            "GEMCOVAC-19 mRNA COVID-19 vaccine in healthy adult volunteers"
        ).qualifies)

    def test_hgco19_covid_vaccine(self):
        self.assertFalse(find_evidence(
            "HGCO19 self-amplifying mRNA COVID-19 vaccine safety and immunogenicity"
        ).qualifies)

    def test_hcar19_car_t(self):
        self.assertFalse(find_evidence(
            "HCAR19 anti-CD19 CAR-T using lentiviral modification for relapsed "
            "refractory diffuse large B-cell lymphoma"
        ).qualifies)

    def test_apceden_dendritic_cell(self):
        self.assertFalse(find_evidence(
            "APCEDEN autologous dendritic-cell immunotherapy in refractory solid tumours"
        ).qualifies)

class FixturePipelineTests(unittest.TestCase):
    """End-to-end over the bundled synthetic fixtures, with no network."""

    def test_ctgov_fixture_categorises_correctly(self):
        trials = {t.nct_number: t for t in
                  load_ctgov_fixture(FIXTURES / "clinicaltrials_fixture.json")}
        self.assertEqual(len(trials), 4)

        qualifying = trials["NCT09999001"]
        self.assertEqual(qualifying.category, "A")
        self.assertTrue(qualifying.qualifies_mrna_cancer_vaccine)
        self.assertTrue(qualifying.has_verified_india_site)

        covid = trials["NCT09999002"]
        self.assertFalse(covid.qualifies_mrna_cancer_vaccine)
        self.assertIn("infectious disease", covid.manual_verification_reason)

        cart = trials["NCT09999003"]
        self.assertFalse(cart.qualifies_mrna_cancer_vaccine)

        # A genuine mRNA cancer vaccine, but with no India site: it must still
        # classify as qualifying, and be excluded on the site axis alone.
        no_india = trials["NCT09999004"]
        self.assertTrue(no_india.qualifies_mrna_cancer_vaccine)
        self.assertFalse(no_india.has_verified_india_site)
        self.assertEqual(no_india.category, "D")

    def test_ctri_record_fixture_parses_every_reported_field(self):
        html = (FIXTURES / "ctri_record.html").read_text(encoding="utf-8")
        trial = normalize_ctri(parse_ctri_html(html), "https://ctri.nic.in/example")
        self.assertIn("CTRI/2026/01/123456", trial.ctri_registration_number)
        self.assertEqual(trial.nct_number, "NCT09999001")
        self.assertEqual(trial.trial_phase, "Phase 2")
        self.assertEqual(trial.recruitment_status, "Open to Recruitment")
        self.assertIn("Mumbai", trial.indian_trial_sites)
        self.assertEqual(trial.contact_email, "trials@example.invalid")
        self.assertIn("18.00", trial.relevant_age_limits)
        self.assertIn("ECOG", trial.key_inclusion_criteria)
        self.assertIn("autoimmune", trial.key_exclusion_criteria)
        self.assertEqual(trial.category, "A")

class ByIdLookupTests(unittest.TestCase):
    """--nct validation. The network path itself is not exercised here."""

    def test_rejects_non_nct_identifiers(self):
        with self.assertRaises(RuntimeError) as ctx:
            normalize_nct_ids(["NOTANID"])
        self.assertIn("NOTANID", str(ctx.exception))

    def test_rejects_malformed_nct_numbers(self):
        for bad in ("NCT123", "NCT123456789", "nct", "06077760"):
            with self.assertRaises(RuntimeError, msg=f"accepted {bad!r}"):
                normalize_nct_ids([bad])

    def test_empty_input_makes_no_request(self):
        self.assertEqual(normalize_nct_ids([]), [])
        self.assertEqual(normalize_nct_ids(["", "  "]), [])
        self.assertEqual(fetch_ctgov_ids([]), [])

    def test_ids_are_upper_cased_and_blanks_dropped(self):
        self.assertEqual(
            normalize_nct_ids(["nct06077760", " ", "NCT06623422"]),
            ["NCT06077760", "NCT06623422"],
        )


class IctrpUrlTests(unittest.TestCase):
    def test_builds_one_url_per_term_with_encoding(self):
        urls = dict(ictrp_search_urls(["mRNA", "cancer vaccine"]))
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls["mRNA"], "https://trialsearch.who.int/?SearchTermStat=mRNA")
        self.assertIn("cancer+vaccine", urls["cancer vaccine"])

    def test_handles_terms_needing_escaping(self):
        _, url = ictrp_search_urls(["RNA-LPX & neoantigen"])[0]
        self.assertNotIn(" ", url)
        self.assertIn("%26", url)

if __name__ == "__main__":
    unittest.main()
