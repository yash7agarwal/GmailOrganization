import time
from collections import Counter
from datetime import datetime

import yaml

from learning import store
from pipeline.fetcher import fetch_unlabeled_emails
from pipeline.classifier import classify_batch
from pipeline.labeler import apply_labels_batch
from pipeline.scorer import score_batch, get_must_reads
from utils.gmail_client import list_labels
from utils.logger import get_logger

logger = get_logger(__name__)


def _load_settings() -> dict:
    try:
        with open("config/settings.yaml") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def _get_available_labels(gmail_labels: dict) -> list[str]:
    """Combine seed label names with any dynamically created ones in Gmail."""
    try:
        with open("config/labels.yaml") as f:
            data = yaml.safe_load(f)
        seed = [lbl["name"] for lbl in data.get("labels", [])]
    except Exception:
        seed = []

    all_labels = list(set(seed + list(gmail_labels.keys())))
    # Remove system Gmail labels
    system = {"INBOX", "SENT", "DRAFT", "TRASH", "SPAM", "STARRED", "IMPORTANT",
              "CATEGORY_PERSONAL", "CATEGORY_SOCIAL", "CATEGORY_PROMOTIONS",
              "CATEGORY_UPDATES", "CATEGORY_FORUMS", "CHAT", "UNREAD",
              "YELLOW_STAR", "[Gmail]/Drafts", "[Gmail]/Sent Mail", "[Gmail]/Starred",
              "[Mailspring]/Snoozed"}
    return [l for l in all_labels if l not in system and not l.startswith("[")]


def _update_sender_stats(classified_emails: list[dict]) -> None:
    month = datetime.utcnow().strftime("%Y-%m")
    for email in classified_emails:
        sender = email.get("sender", "")
        if sender:
            try:
                store.upsert_sender_stat(sender, month)
            except Exception as e:
                logger.warning(f"Sender stat update failed for {sender}: {e}")


def _check_unsubscribe_candidates(classified_emails: list[dict]) -> list[dict]:
    settings = _load_settings()
    threshold = settings.get("scoring_rules", {}).get("unsubscribe_volume_threshold", 5)
    return store.get_unsubscribe_candidates(threshold=threshold)


def run_daily_pipeline() -> dict:
    """
    Full daily pipeline: fetch → classify → label → score → log → return result.
    Each stage is wrapped — a single failure never aborts the whole run.
    """
    start_time = time.time()
    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    logger.info(f"=== Daily pipeline starting: {run_date} ===")

    result = {
        "run_date": run_date,
        "total_fetched": 0,
        "classified": [],
        "must_reads": [],
        "new_labels_created": [],
        "new_clusters_proposed": [],
        "unsubscribe_candidates": [],
        "cluster_counts": {},
        "errors": [],
        "duration_seconds": 0.0,
    }

    # Stage 0: Fetch current Gmail labels to build available_labels list
    try:
        gmail_labels = list_labels()
        available_labels = _get_available_labels(gmail_labels)
        logger.info(f"Available labels: {available_labels}")
    except Exception as e:
        logger.error(f"Failed to fetch Gmail labels: {e}")
        result["errors"].append(f"label_fetch: {e}")
        available_labels = []

    # Stage 1: Fetch
    settings = _load_settings()
    pipeline_cfg = settings.get("pipeline", {})
    try:
        emails = fetch_unlabeled_emails(
            max_results=pipeline_cfg.get("fetch_max_results", 100),
            lookback_days=pipeline_cfg.get("lookback_days", 1),
        )
        result["total_fetched"] = len(emails)
        logger.info(f"Fetched {len(emails)} emails")
    except Exception as e:
        logger.error(f"Fetch stage failed: {e}")
        result["errors"].append(f"fetch: {e}")
        emails = []

    if not emails:
        result["duration_seconds"] = round(time.time() - start_time, 2)
        logger.info("No emails to process. Pipeline complete.")
        return result

    # Stage 2: Classify
    try:
        classified = classify_batch(emails, available_labels)
        # Extract new cluster proposals if any
        if classified and "_new_cluster_proposals" in classified[0]:
            result["new_clusters_proposed"] = classified[0].pop("_new_cluster_proposals")
        logger.info(f"Classified {len(classified)} emails")
    except Exception as e:
        logger.error(f"Classify stage failed: {e}")
        result["errors"].append(f"classify: {e}")
        classified = [{**e, "label": "Uncategorized", "confidence": 0.0, "priority_tier": "skim"}
                      for e in emails]

    # Stage 3: Score
    try:
        scored = score_batch(classified)
        result["must_reads"] = get_must_reads(scored)
        logger.info(f"Scored: {Counter(e['priority_tier'] for e in scored)}")
    except Exception as e:
        logger.error(f"Score stage failed: {e}")
        result["errors"].append(f"score: {e}")
        scored = [{**e, "priority_tier": "skim"} for e in classified]

    # Stage 4: Label
    try:
        label_result = apply_labels_batch(scored)
        result["new_labels_created"] = label_result["new_labels_created"]
        result["errors"].extend([f"label: {err}" for err in label_result["errors"]])
        logger.info(f"Labeled: {label_result['labeled']}, archived: {label_result['archived']}")
    except Exception as e:
        logger.error(f"Label stage failed: {e}")
        result["errors"].append(f"label: {e}")

    # Stage 4.5: Extract expenses and subscriptions from financial emails
    try:
        from expenses.extractor import process_financial_emails
        expense_result = process_financial_emails(scored)
        logger.info(
            f"Expenses: {expense_result['expenses_logged']} logged, "
            f"{expense_result['subscriptions_updated']} subscriptions updated"
        )
    except Exception as e:
        logger.warning(f"Expense extraction stage failed: {e}")
        result["errors"].append(f"expenses: {e}")

    # Stage 5: Log to learning store
    try:
        for email in scored:
            store.log_classification(
                email_id=email.get("id", ""),
                thread_id=email.get("thread_id", ""),
                subject=email.get("subject", ""),
                sender=email.get("sender", ""),
                label=email.get("label", "Uncategorized"),
                confidence=email.get("confidence", 0.0),
                priority_tier=email.get("priority_tier", "skim"),
                run_date=run_date,
                is_new_cluster=email.get("is_new_cluster", False),
            )
        _update_sender_stats(scored)
    except Exception as e:
        logger.error(f"Store log stage failed: {e}")
        result["errors"].append(f"store: {e}")

    # Stage 6: Unsubscribe candidates
    try:
        result["unsubscribe_candidates"] = _check_unsubscribe_candidates(scored)
    except Exception as e:
        logger.warning(f"Unsubscribe check failed: {e}")

    # Build cluster counts summary
    result["classified"] = scored
    result["cluster_counts"] = dict(Counter(e.get("label", "Uncategorized") for e in scored))

    result["duration_seconds"] = round(time.time() - start_time, 2)
    logger.info(
        f"=== Pipeline complete in {result['duration_seconds']}s | "
        f"fetched={result['total_fetched']} must_reads={len(result['must_reads'])} "
        f"errors={len(result['errors'])} ==="
    )
    return result
