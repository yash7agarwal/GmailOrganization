"""
Extract purchase and subscription data from classified emails.
Called by the orchestrator after labeling for emails in financial categories.
"""

from utils.claude_client import extract_purchase_data
from utils.logger import get_logger
from learning import store

logger = get_logger(__name__)

FINANCIAL_LABELS = {
    "Purchases & Receipts",
    "Subscriptions & Renewals",
    "Transactional",
}


def process_financial_emails(emails: list[dict]) -> dict:
    """
    Given a list of scored+classified emails, extract financial data from
    those in financial label categories and persist to the store.

    Returns {"expenses_logged": int, "subscriptions_updated": int, "errors": int}
    """
    result = {"expenses_logged": 0, "subscriptions_updated": 0, "errors": 0}

    financial = [e for e in emails if e.get("label") in FINANCIAL_LABELS]
    if not financial:
        return result

    for email in financial:
        try:
            data = extract_purchase_data(
                subject=email.get("subject", ""),
                sender=email.get("sender", ""),
                snippet=email.get("snippet", ""),
                email_id=email.get("id", ""),
            )
            if not data:
                continue

            event_type = data.get("type")

            if event_type == "purchase":
                store.log_expense(
                    email_id=email.get("id", ""),
                    merchant=data.get("merchant", "Unknown"),
                    amount=data.get("amount"),
                    currency=data.get("currency", "USD"),
                    date=data.get("date", ""),
                    description=data.get("description", ""),
                )
                result["expenses_logged"] += 1

            elif event_type in ("renewal", "expiry_reminder", "trial_ending"):
                store.upsert_subscription(
                    service=data.get("merchant", "Unknown"),
                    merchant_domain=_extract_domain(email.get("sender", "")),
                    amount=data.get("amount"),
                    currency=data.get("currency", "USD"),
                    billing_cycle=data.get("billing_cycle"),
                    renewal_date=data.get("renewal_date"),
                    expiry_date=data.get("expiry_date"),
                )
                result["subscriptions_updated"] += 1

        except Exception as e:
            logger.warning(f"Expense extraction failed for email {email.get('id', '?')}: {e}")
            result["errors"] += 1

    logger.info(
        f"Expense extraction done: {result['expenses_logged']} expenses, "
        f"{result['subscriptions_updated']} subscriptions, {result['errors']} errors"
    )
    return result


def _extract_domain(sender: str) -> str:
    if "<" in sender:
        sender = sender.split("<")[1].rstrip(">")
    return sender.split("@")[-1].lower().strip() if "@" in sender else sender.lower()
