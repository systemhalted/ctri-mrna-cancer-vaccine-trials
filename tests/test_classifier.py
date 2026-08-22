import unittest

from ctri_mrna_trials import (
    category,
    find_evidence,
    normalize_ctri,
    parse_ctri_html,
    status_to_enum,
)


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


if __name__ == "__main__":
    unittest.main()
