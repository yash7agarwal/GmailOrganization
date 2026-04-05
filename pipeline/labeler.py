from utils.gmail_client import get_or_create_label, apply_label as gmail_apply_label, archive_message
from utils.logger import get_logger

logger = get_logger(__name__)

_label_cache: dict[str, str] = {}  # name → Gmail label id, per-session


def ensure_label_exists(label_name: str) -> str:
    """Return Gmail label id for name, creating if needed. Cached per session."""
    if label_name not in _label_cache:
        label_id = get_or_create_label(label_name)
        _label_cache[label_name] = label_id
        logger.debug(f"Label resolved: '{label_name}' → {label_id}")
    return _label_cache[label_name]


def apply_label(email_id: str, label_name: str) -> None:
    label_id = ensure_label_exists(label_name)
    gmail_apply_label(email_id, label_id)


def archive_if_skip(email_id: str, priority_tier: str) -> bool:
    if priority_tier == "skip":
        try:
            archive_message(email_id)
            return True
        except Exception as e:
            logger.warning(f"Archive failed for {email_id}: {e}")
    return False


def apply_labels_batch(classified_emails: list[dict]) -> dict:
    """
    For each classified email: apply label, optionally archive.
    Never raises on single failure — logs and continues.
    Returns summary dict.
    """
    labeled = 0
    archived = 0
    new_labels_created = []
    errors = []

    # Pre-warm label cache to detect newly created labels
    existing_label_count = len(_label_cache)

    for email in classified_emails:
        email_id = email.get("id")
        label = email.get("label", "Uncategorized")
        tier = email.get("priority_tier", "skim")

        if not email_id or label in ("NEW_CLUSTER", "Uncategorized"):
            continue

        try:
            label_id = ensure_label_exists(label)
            gmail_apply_label(email_id, label_id)
            labeled += 1

            if archive_if_skip(email_id, tier):
                archived += 1

        except Exception as e:
            logger.error(f"Label apply failed for {email_id} (label={label}): {e}")
            errors.append({"email_id": email_id, "error": str(e)})

    # Detect newly created labels this session
    new_in_cache = len(_label_cache) - existing_label_count
    if new_in_cache > 0:
        new_labels_created = [
            name for name, _ in list(_label_cache.items())[-new_in_cache:]
        ]

    logger.info(f"Labeling complete: {labeled} labeled, {archived} archived, "
                f"{len(new_labels_created)} new labels, {len(errors)} errors")

    return {
        "labeled": labeled,
        "archived": archived,
        "new_labels_created": new_labels_created,
        "errors": errors,
    }
