import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.source_credibility import analyze_source
from modules.claim_assessment import assess_claim
from modules.ai_features import assess_claim_with_context, ai_claim_review
from modules.report_generator import generate_pdf_report, generate_investigation_pdf


class SourceCredibilityTests(unittest.TestCase):
    def test_https_and_known_publisher_indicators(self):
        result = analyze_source("https://www.reuters.com/world/example")
        self.assertTrue(result["valid_url"])
        self.assertTrue(result["https"])
        self.assertEqual(result["category"], "Listed news publisher")
        self.assertIn("indicator_level", result)

    def test_rejects_non_http_scheme(self):
        result = analyze_source("javascript:alert(1)")
        self.assertFalse(result["valid_url"])

    def test_rejects_private_ip(self):
        result = analyze_source("http://127.0.0.1/admin")
        self.assertFalse(result["valid_url"])


class ClaimAssessmentTests(unittest.TestCase):
    def test_mixed_evidence_is_reported_as_mixed(self):
        evidence = [
            {"claim": "The city opened a new hospital", "relation": "Supports", "url": "https://www.gov.in", "excerpt": "The city opened a new hospital."},
            {"claim": "The city opened a new hospital", "relation": "Contradicts", "url": "https://example.org", "excerpt": "The hospital project was cancelled."},
        ]
        result = assess_claim("The city opened a new hospital", evidence)
        self.assertEqual(result["status"], "Mixed Evidence")
        self.assertEqual(result["counts"]["Supports"], 1)
        self.assertEqual(result["counts"]["Contradicts"], 1)

    def test_no_evidence_is_not_verified(self):
        result = assess_claim("A claim without sources", [])
        self.assertEqual(result["status"], "Insufficient Evidence")

    def test_context_assessment_does_not_claim_truth_probability(self):
        result = assess_claim_with_context("A sample claim", [])
        self.assertEqual(result["conclusion"], "Not enough evidence collected")
        self.assertTrue(result["limitations"])


class AssistantTests(unittest.TestCase):
    @patch("modules.ai_features._hf_token", return_value="")
    def test_claim_review_has_local_fallback(self, _token):
        result = ai_claim_review("A sample claim", [])
        self.assertEqual(result["mode"], "Local evidence assessment")
        self.assertIn("Not enough evidence", result["answer"])

    @patch("modules.ai_features._hf_token", return_value="")
    def test_chatbot_returns_guidance_without_paid_api(self, _token):
        from modules.ai_features import chat_answer
        answer = chat_answer("How do I verify a claim?")
        self.assertTrue(answer)


class ReportTests(unittest.TestCase):
    def test_single_claim_pdf_is_generated(self):
        result = generate_pdf_report({
            "claim": "Example claim",
            "status": "Inconclusive",
            "counts": {"Supports": 0, "Contradicts": 0, "Context only": 0, "Unclear": 0},
            "sources": [],
        })
        self.assertTrue(result.startswith(b"%PDF"))

    def test_complete_investigation_pdf_is_generated(self):
        result = generate_investigation_pdf({
            "title": "Regression investigation",
            "source_name": "test.txt",
            "claims": [{"claim": "Example claim"}],
            "evidence": [{
                "claim": "Example claim",
                "title": "Example source",
                "url": "https://example.org",
                "excerpt": "An example evidence excerpt.",
                "relation": "Unclear",
            }],
        })
        self.assertTrue(result.startswith(b"%PDF"))


class DatabaseRegressionTests(unittest.TestCase):
    def setUp(self):
        import modules.auth as auth
        self.temp_dir = tempfile.TemporaryDirectory()
        auth.DB_PATH = Path(self.temp_dir.name) / "truthlens-test.db"
        auth.init_db()
        self.auth = auth

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_profile_avatar_is_saved_updated_and_removed(self):
        from modules.user_profile import (
            get_user_profile, save_user_avatar, save_user_profile,
            remove_user_avatar,
        )

        ok, _ = self.auth.register_user("avatar_user", "StrongPass123")
        self.assertTrue(ok)
        user = self.auth.authenticate_user("avatar_user", "StrongPass123")
        self.assertIsNotNone(user)

        save_user_avatar(user["id"], b"first-image-bytes")
        self.assertEqual(
            get_user_profile(user["id"])["avatar"],
            b"first-image-bytes",
        )

        save_user_avatar(user["id"], b"replacement-image-bytes")
        self.assertEqual(
            get_user_profile(user["id"])["avatar"],
            b"replacement-image-bytes",
        )

        # Saving personal details without an image must keep the existing photo.
        save_user_profile(user["id"], "Avatar User", "", "")
        self.assertEqual(
            get_user_profile(user["id"])["avatar"],
            b"replacement-image-bytes",
        )

        remove_user_avatar(user["id"])
        self.assertIsNone(get_user_profile(user["id"])["avatar"])

    def test_existing_auth_and_persistent_history_work_together(self):
        from modules.cloud_store import (
            save_investigation, list_user_investigations,
            update_investigation_claims, save_investigation_evidence,
            list_investigation_evidence, get_user_investigation,
            delete_user_investigation,
        )
        with patch("modules.cloud_store.supabase_configured", return_value=False):
            ok, _ = self.auth.register_user("regression_user", "StrongPass123")
            self.assertTrue(ok)
            user = self.auth.authenticate_user("regression_user", "StrongPass123")
            self.assertIsNotNone(user)

            investigation_id = save_investigation(
                user["id"], user["username"], "Test investigation",
                "A sample article text",
            )
            claims = [{"claim": "A sample claim"}]
            self.assertTrue(update_investigation_claims(
                user["id"], user["username"], investigation_id, claims
            ))
            self.assertTrue(save_investigation_evidence(
                user["id"], user["username"], investigation_id,
                {
                    "claim": "A sample claim",
                    "title": "Example",
                    "url": "https://example.org",
                    "excerpt": "Example excerpt",
                    "relation": "Supports",
                },
            ))
            records = list_user_investigations(user["id"], user["username"])
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["claims"], claims)
            restored = get_user_investigation(user["id"], user["username"], investigation_id)
            self.assertEqual(restored["text"], "A sample article text")
            evidence = list_investigation_evidence(user["id"], user["username"], investigation_id)
            self.assertEqual(len(evidence), 1)
            self.assertTrue(delete_user_investigation(user["id"], user["username"], investigation_id))


if __name__ == "__main__":
    unittest.main()
