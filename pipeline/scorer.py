import yaml
from utils.claude_client import generate_text
from utils.logger import get_logger

logger = get_logger(__name__)

BULK_SENDER_DOMAINS = {
    "mailchimp.com", "sendgrid.net", "constantcontact.com", "klaviyo.com",
    "hubspot.com", "marketo.com", "pardot.com", "salesforce.com",
    "amazonses.com", "mg.yourdomain.com",
}


def _load_scoring_rules() -> dict:
    try:
        with open("config/scoring_rules.yaml") as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Could not load scoring_rules.yaml: {e}")
        return {}


def _is_personal_sender(email: dict) -> bool:
    """
    Heuristic: no List-Unsubscribe header AND not a known bulk sender domain.
    Personal emails are almost never bulk-sent.
    """
    headers_raw = email.get("_raw_headers", {})
    if "List-Unsubscribe" in headers_raw or "list-unsubscribe" in headers_raw:
        return False

    sender = email.get("sender", "")
    if "@" in sender:
        domain = sender.split("@")[-1].rstrip(">").strip().lower()
        if domain in BULK_SENDER_DOMAINS:
            return False

    return True


def _rule_based_score(label: str, email: dict, rules: dict):
    """Apply scoring_rules.yaml rules. Returns tier if matched, else None."""

    # Must-read rules
    for rule in rules.get("must_read", []):
        if rule.get("label") == label:
            conditions = rule.get("conditions", [])
            if "any" in conditions or not conditions:
                return "must_read"
        if rule.get("sender_type") == "personal" and _is_personal_sender(email):
            return "must_read"

    # Skim rules
    for rule in rules.get("skim", []):
        if rule.get("label") == label:
            return "skim"

    # Skip rules
    for rule in rules.get("skip", []):
        if rule.get("label") == label:
            return "skip"

    return None


def _claude_intent_check(emails: list[dict]) -> dict[str, str]:
    """
    For ambiguous Transactional emails, ask Claude if action is required.
    Returns {email_id: tier}.
    """
    if not emails:
        return {}

    import json
    items = [
        {"id": e["id"], "subject": e.get("subject", ""), "snippet": e.get("snippet", "")}
        for e in emails
    ]
    prompt = f"""For each email below, determine if it requires the user to take an action within 7 days.

Emails:
{json.dumps(items, indent=2)}

Respond ONLY with a JSON object mapping email id to "must_read" or "skim":
{{"<email_id>": "must_read", ...}}"""

    try:
        raw = generate_text(prompt, max_tokens=300)
        return json.loads(raw.strip())
    except Exception as e:
        logger.warning(f"Claude intent check failed: {e}")
        return {e["id"]: "skim" for e in emails}


def score_email(email: dict, label: str, confidence: float) -> str:
    """Score a single email. Returns 'must_read', 'skim', or 'skip'."""
    rules = _load_scoring_rules()
    tier = _rule_based_score(label, email, rules)
    if tier:
        return tier

    # Default fallback by label
    if label in ("Subscriptions & Renewals",):
        return "must_read"
    if label in ("Promotions & Marketing", "Unsubscribe Candidates"):
        return "skip"
    return "skim"


def score_batch(classified_emails: list[dict]) -> list[dict]:
    """
    Add 'priority_tier' to each email dict.
    Collects ambiguous Transactionals for a single Claude batch check.
    """
    rules = _load_scoring_rules()
    ambiguous_transactional = []
    results = []

    for email in classified_emails:
        label = email.get("label", "Uncategorized")
        confidence = email.get("confidence", 0.0)

        tier = _rule_based_score(label, email, rules)

        if tier is None and label == "Transactional":
            ambiguous_transactional.append(email)
            tier = "skim"  # placeholder, will be overridden below
        elif tier is None:
            tier = score_email(email, label, confidence)

        results.append({**email, "priority_tier": tier})

    # Resolve ambiguous transactionals with Claude
    if ambiguous_transactional:
        corrections = _claude_intent_check(ambiguous_transactional)
        for email in results:
            if email["id"] in corrections:
                email["priority_tier"] = corrections[email["id"]]

    return results


def get_must_reads(scored_emails: list[dict]) -> list[dict]:
    """Return must_read emails, with AI & Tech Intelligence sorted first."""
    must_reads = [e for e in scored_emails if e.get("priority_tier") == "must_read"]
    ai_tech = [e for e in must_reads if e.get("label") == "AI & Tech Intelligence"]
    others = [e for e in must_reads if e.get("label") != "AI & Tech Intelligence"]
    return ai_tech + others
