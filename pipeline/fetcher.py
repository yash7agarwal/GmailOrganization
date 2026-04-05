import os
import yaml
from utils.gmail_client import search_messages, get_message, list_labels
from utils.logger import get_logger

logger = get_logger(__name__)

MANAGED_LABEL_NAMES = [
    "Subscriptions & Renewals",
    "Transactional",
    "Promotions & Marketing",
    "Newsletters",
    "AI & Tech Intelligence",
    "Unsubscribe Candidates",
]


def _load_seed_label_names() -> list[str]:
    try:
        with open("config/labels.yaml") as f:
            data = yaml.safe_load(f)
        return [lbl["name"] for lbl in data.get("labels", [])]
    except Exception:
        return MANAGED_LABEL_NAMES


def _build_exclusion_query(label_names: list[str]) -> str:
    """Build Gmail -label: exclusion terms for already-classified emails."""
    exclusions = []
    for name in label_names:
        gmail_label = name.lower().replace(" & ", "-").replace(" ", "-")
        exclusions.append(f"-label:{gmail_label}")
    return " ".join(exclusions)


def fetch_unlabeled_emails(max_results: int = 100, lookback_days: int = 1) -> list[dict]:
    """Fetch inbox emails from the last N days that have no managed labels applied."""
    managed = _load_seed_label_names()

    # Also exclude any dynamically created labels that exist in Gmail
    try:
        gmail_labels = list(list_labels().keys())
        all_managed = list(set(managed + [l for l in gmail_labels if l in managed]))
    except Exception:
        all_managed = managed

    exclusion = _build_exclusion_query(all_managed)
    query = f"in:inbox newer_than:{lookback_days}d {exclusion}"
    logger.info(f"Fetching emails with query: {query}")

    message_refs = search_messages(query, max_results=max_results)
    logger.info(f"Found {len(message_refs)} unlabeled messages")

    emails = []
    for ref in message_refs:
        try:
            email = get_message(ref["id"], fmt="metadata")
            emails.append(email)
        except Exception as e:
            logger.warning(f"Failed to fetch message {ref['id']}: {e}")

    return emails


def fetch_emails_by_date_range(
    start_date: str, end_date: str, max_results: int = 500
) -> list[dict]:
    """
    Fetch emails within a date range for the monthly retrainer.
    Dates in 'YYYY/MM/DD' format (Gmail query syntax).
    """
    query = f"after:{start_date} before:{end_date}"
    logger.info(f"Fetching emails for retraining: {query}")

    message_refs = search_messages(query, max_results=max_results)
    emails = []
    for ref in message_refs:
        try:
            email = get_message(ref["id"], fmt="metadata")
            emails.append(email)
        except Exception as e:
            logger.warning(f"Failed to fetch message {ref['id']}: {e}")

    return emails
