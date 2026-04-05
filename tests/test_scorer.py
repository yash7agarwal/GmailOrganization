import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.scorer import score_email, score_batch, get_must_reads


def make_email(email_id="msg_001", label="Newsletters", subject="Test", sender="test@bulk.com",
               snippet="content", has_unsubscribe=True) -> dict:
    email = {
        "id": email_id, "label": label, "confidence": 0.9,
        "subject": subject, "sender": sender, "snippet": snippet,
        "label_ids": [],
    }
    if has_unsubscribe:
        email["_raw_headers"] = {"List-Unsubscribe": "<mailto:unsub@bulk.com>"}
    return email


class TestScorerRules(unittest.TestCase):

    def test_renewal_is_must_read(self):
        email = make_email(label="Subscriptions & Renewals")
        tier = score_email(email, "Subscriptions & Renewals", 0.9)
        self.assertEqual(tier, "must_read")

    def test_promotion_is_skip(self):
        email = make_email(label="Promotions & Marketing")
        tier = score_email(email, "Promotions & Marketing", 0.9)
        self.assertEqual(tier, "skip")

    def test_unsubscribe_candidate_is_skip(self):
        email = make_email(label="Unsubscribe Candidates")
        tier = score_email(email, "Unsubscribe Candidates", 0.9)
        self.assertEqual(tier, "skip")

    def test_newsletter_is_skim(self):
        email = make_email(label="Newsletters")
        tier = score_email(email, "Newsletters", 0.9)
        self.assertEqual(tier, "skim")

    def test_ai_tech_is_skim(self):
        email = make_email(label="AI & Tech Intelligence")
        tier = score_email(email, "AI & Tech Intelligence", 0.9)
        self.assertEqual(tier, "skim")

    def test_personal_sender_is_must_read(self):
        # No List-Unsubscribe header, not a bulk domain → personal
        email = make_email(
            label="Transactional",
            sender="colleague@company.com",
            has_unsubscribe=False,
        )
        # Override: no bulk header present
        email.pop("_raw_headers", None)
        tier = score_email(email, "Transactional", 0.9)
        # Personal senders should be must_read
        self.assertEqual(tier, "must_read")


class TestScoreBatch(unittest.TestCase):

    def test_score_batch_adds_priority_tier(self):
        emails = [
            make_email("msg_1", "Subscriptions & Renewals"),
            make_email("msg_2", "Newsletters"),
            make_email("msg_3", "Promotions & Marketing"),
        ]
        scored = score_batch(emails)
        self.assertEqual(len(scored), 3)
        self.assertTrue(all("priority_tier" in e for e in scored))

    def test_get_must_reads_ai_tech_first(self):
        emails = [
            {**make_email("msg_1", "Subscriptions & Renewals"), "priority_tier": "must_read"},
            {**make_email("msg_2", "AI & Tech Intelligence"), "priority_tier": "must_read"},
            {**make_email("msg_3", "Newsletters"), "priority_tier": "skim"},
        ]
        must_reads = get_must_reads(emails)
        self.assertEqual(len(must_reads), 2)
        self.assertEqual(must_reads[0]["label"], "AI & Tech Intelligence",
                         "AI & Tech emails should be sorted first in must-reads")

    def test_scoring_rules_yaml_loaded(self):
        """Regression: scoring_rules.yaml changes don't silently break scoring."""
        import yaml
        with open("config/scoring_rules.yaml") as f:
            rules = yaml.safe_load(f)
        self.assertIn("must_read", rules)
        self.assertIn("skim", rules)
        self.assertIn("skip", rules)


if __name__ == "__main__":
    unittest.main()
