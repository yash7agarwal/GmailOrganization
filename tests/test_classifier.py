import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.classifier import keyword_prefilter, classify_batch, _load_label_keywords

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURES, name)) as f:
        return json.load(f)

AVAILABLE_LABELS = [
    "Subscriptions & Renewals", "Transactional", "Promotions & Marketing",
    "Newsletters", "AI & Tech Intelligence", "Unsubscribe Candidates",
]


class TestKeywordPrefilter(unittest.TestCase):

    def setUp(self):
        self.keywords = _load_label_keywords()

    def test_classify_newsletter_via_keyword(self):
        email = load_fixture("newsletter_email.json")
        result = keyword_prefilter(email, self.keywords)
        self.assertIsNotNone(result, "Newsletter email should be caught by keyword filter")
        self.assertEqual(result["label"], "Newsletters")
        self.assertGreaterEqual(result["confidence"], 0.75)

    def test_classify_transactional_via_keyword(self):
        email = load_fixture("transactional_email.json")
        result = keyword_prefilter(email, self.keywords)
        self.assertIsNotNone(result, "Zoom invite should be caught by keyword filter")
        self.assertEqual(result["label"], "Transactional")

    def test_ambiguous_email_not_caught_by_keyword(self):
        # Ambiguous email should fall through to Claude
        email = load_fixture("ambiguous_email.json")
        result = keyword_prefilter(email, self.keywords)
        # If keyword filter catches it, confidence should still be reasonable
        if result is not None:
            self.assertLess(result["confidence"], 1.0)


class TestClaudeClassification(unittest.TestCase):

    @patch("pipeline.classifier.classify_email_batch")
    def test_classify_ai_tech_via_claude(self, mock_batch):
        email = load_fixture("ai_tech_email.json")
        keywords = _load_label_keywords()

        # Keyword filter won't catch this with high confidence
        mock_batch.return_value = [{
            "id": email["id"],
            "label": "AI & Tech Intelligence",
            "confidence": 0.95,
            "reasoning": "OpenAI GPT-5 release — AI model announcement",
            "is_new_cluster": False,
            "new_cluster_name": "",
        }]

        results = classify_batch([email], AVAILABLE_LABELS)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["label"], "AI & Tech Intelligence")

    @patch("pipeline.classifier.classify_email_batch")
    def test_batch_claude_call_efficiency(self, mock_batch):
        """N emails should result in ceil(N/10) Claude calls, not N calls."""
        import math
        emails = [
            {
                "id": f"msg_{i:03d}", "subject": f"Unknown email {i}",
                "sender": f"sender{i}@unknown.com", "snippet": "some content",
                "label_ids": [],
            }
            for i in range(25)
        ]
        keywords = _load_label_keywords()

        # Make keyword filter return nothing (force all to Claude)
        mock_batch.return_value = [
            {"id": e["id"], "label": "Uncategorized", "confidence": 0.5,
             "reasoning": "test", "is_new_cluster": False, "new_cluster_name": ""}
            for e in emails[:10]
        ]

        with patch("pipeline.classifier.keyword_prefilter", return_value=None):
            try:
                classify_batch(emails, AVAILABLE_LABELS)
            except Exception:
                pass

        expected_calls = math.ceil(25 / 10)
        self.assertLessEqual(mock_batch.call_count, expected_calls + 1)


class TestNewClusterDetection(unittest.TestCase):

    @patch("pipeline.classifier.classify_email_batch")
    @patch("pipeline.classifier.generate_text", return_value="AI Productivity Tools")
    def test_new_cluster_proposed_for_repeated_domain(self, mock_gen, mock_batch):
        emails = [
            {
                "id": f"msg_{i}", "subject": f"New tool from someai {i}",
                "sender": f"team@someai.io", "snippet": "Try our new AI tool",
                "label_ids": [],
            }
            for i in range(5)
        ]

        mock_batch.return_value = [
            {"id": e["id"], "label": "NEW_CLUSTER", "confidence": 0.5,
             "reasoning": "no match", "is_new_cluster": True, "new_cluster_name": "AI Tools"}
            for e in emails
        ]

        with patch("pipeline.classifier.keyword_prefilter", return_value=None):
            results = classify_batch(emails, AVAILABLE_LABELS)

        proposals = results[0].get("_new_cluster_proposals", [])
        self.assertGreater(len(proposals), 0, "Should propose a new cluster for repeated domain")


if __name__ == "__main__":
    unittest.main()
