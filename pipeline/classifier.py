import math
import yaml
from utils.claude_client import classify_email, classify_email_batch
from utils.logger import get_logger

logger = get_logger(__name__)

KEYWORD_CONFIDENCE_THRESHOLD = 0.90
BATCH_SIZE = 10


def _load_label_keywords() -> dict[str, list[str]]:
    try:
        with open("config/labels.yaml") as f:
            data = yaml.safe_load(f)
        return {lbl["name"]: lbl.get("keywords", []) for lbl in data.get("labels", [])}
    except Exception as e:
        logger.warning(f"Could not load labels.yaml: {e}")
        return {}


def keyword_prefilter(email: dict, label_keywords: dict) -> dict:
    """
    Fast keyword match against subject + snippet.
    Returns a classification dict if confident, else None.
    Skips 'Unsubscribe Candidates' (dynamically populated, not keyword-matched).
    """
    text = f"{email.get('subject', '')} {email.get('snippet', '')}".lower()

    best_label = None
    best_score = 0

    for label, keywords in label_keywords.items():
        if label == "Unsubscribe Candidates" or not keywords:
            continue
        hits = sum(1 for kw in keywords if kw.lower() in text)
        score = hits / len(keywords) if keywords else 0
        if score > best_score:
            best_score = score
            best_label = label

    if best_label and best_score >= 0.15:  # At least 15% keyword overlap
        confidence = min(KEYWORD_CONFIDENCE_THRESHOLD, 0.7 + best_score * 0.3)
        return {
            "id": email["id"],
            "label": best_label,
            "confidence": round(confidence, 2),
            "reasoning": f"Keyword match ({int(best_score*100)}% overlap)",
            "is_new_cluster": False,
            "new_cluster_name": "",
        }
    return None


def _detect_new_cluster_pattern(
    new_cluster_emails: list[dict], available_labels: list[str]
) -> list[dict]:
    """
    If 3+ NEW_CLUSTER emails share a sender domain or subject keywords,
    propose a concrete new label name via Claude.
    Returns list of {pattern, suggested_label, email_ids}.
    """
    if len(new_cluster_emails) < 3:
        return []

    from collections import Counter
    from utils.claude_client import generate_text
    import json

    domain_counts = Counter()
    for e in new_cluster_emails:
        sender = e.get("sender", "")
        if "@" in sender:
            domain = sender.split("@")[-1].rstrip(">").strip()
            domain_counts[domain] += 1

    proposals = []
    for domain, count in domain_counts.items():
        if count >= 3:
            sample_subjects = [
                e.get("subject", "") for e in new_cluster_emails
                if domain in e.get("sender", "")
            ][:5]

            prompt = f"""I have {count} emails from {domain} that don't fit existing categories.
Existing categories: {available_labels}
Sample subjects: {json.dumps(sample_subjects)}

Suggest a short, descriptive label name (2-4 words) for a new inbox category.
Respond with ONLY the label name, nothing else."""

            try:
                suggested = generate_text(prompt, max_tokens=20).strip().strip('"')
                proposals.append({
                    "pattern": f"domain:{domain}",
                    "suggested_label": suggested,
                    "email_ids": [e["id"] for e in new_cluster_emails if domain in e.get("sender", "")],
                })
            except Exception as e:
                logger.warning(f"New cluster proposal failed for {domain}: {e}")

    return proposals


def classify_batch(emails: list[dict], available_labels: list[str]) -> list[dict]:
    """
    Classify a list of emails. Returns emails enriched with:
    label, confidence, reasoning, is_new_cluster, new_cluster_name.
    """
    label_keywords = _load_label_keywords()
    results = []
    needs_claude = []

    # Pass 1: keyword prefilter
    for email in emails:
        match = keyword_prefilter(email, label_keywords)
        if match:
            enriched = {**email, **match}
            results.append(enriched)
            logger.debug(f"Keyword match: '{email.get('subject', '')[:50]}' → {match['label']}")
        else:
            needs_claude.append(email)

    logger.info(f"Keyword prefilter: {len(results)} matched, {len(needs_claude)} need Claude")

    # Pass 2: Claude batch classification
    if needs_claude:
        num_batches = math.ceil(len(needs_claude) / BATCH_SIZE)
        for i in range(num_batches):
            batch = needs_claude[i * BATCH_SIZE: (i + 1) * BATCH_SIZE]
            try:
                classifications = classify_email_batch(batch, available_labels)
                for email, clf in zip(batch, classifications):
                    enriched = {**email, **clf}
                    results.append(enriched)
                    logger.debug(f"Claude: '{email.get('subject', '')[:50]}' → {clf.get('label')} ({clf.get('confidence', 0):.2f})")
            except Exception as e:
                logger.error(f"Claude batch {i+1}/{num_batches} failed: {e}")
                # Fallback: mark each as low-confidence uncategorized
                for email in batch:
                    results.append({
                        **email,
                        "label": "Uncategorized",
                        "confidence": 0.0,
                        "reasoning": f"Classification error: {e}",
                        "is_new_cluster": False,
                        "new_cluster_name": "",
                    })

    # Detect new cluster patterns from NEW_CLUSTER results
    new_cluster_emails = [e for e in results if e.get("label") == "NEW_CLUSTER"]
    if new_cluster_emails:
        proposals = _detect_new_cluster_pattern(new_cluster_emails, available_labels)
        if proposals:
            logger.info(f"New cluster proposals: {[p['suggested_label'] for p in proposals]}")
        # Store proposals on the first result for the orchestrator to pick up
        if results:
            results[0]["_new_cluster_proposals"] = proposals

    return results
