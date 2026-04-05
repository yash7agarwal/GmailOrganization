import os
from datetime import datetime, timedelta

import yaml

from learning import store
from utils.claude_client import generate_text
from utils.logger import get_logger

logger = get_logger(__name__, log_dir="logs/weekly")


def _load_settings() -> dict:
    try:
        with open("config/settings.yaml") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def _compare_snapshots(current: dict[str, int], prior: dict[str, int], threshold: float) -> list[dict]:
    drifting = []
    for label, count in current.items():
        prior_count = prior.get(label, 0)
        if prior_count == 0:
            continue
        ratio = count / prior_count
        if ratio >= threshold:
            drifting.append({
                "label": label,
                "this_week": count,
                "last_week": prior_count,
                "ratio": round(ratio, 2),
            })
    return sorted(drifting, key=lambda x: x["ratio"], reverse=True)


def _detect_new_senders(days: int = 7, baseline_weeks: int = 4) -> list[dict]:
    """Senders that appeared this week but not in the prior 4-week baseline."""
    cutoff_this_week = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    cutoff_baseline = (datetime.utcnow() - timedelta(weeks=baseline_weeks)).strftime("%Y-%m-%d")

    from learning.store import get_conn
    with store.get_conn() as conn:
        # Domains active this week
        this_week = {
            row["sender_domain"]
            for row in conn.execute(
                "SELECT DISTINCT sender_domain FROM classifications WHERE run_date >= ?",
                (cutoff_this_week,),
            ).fetchall()
        }
        # Domains that existed in baseline
        baseline = {
            row["sender_domain"]
            for row in conn.execute(
                "SELECT DISTINCT sender_domain FROM classifications WHERE run_date >= ? AND run_date < ?",
                (cutoff_baseline, cutoff_this_week),
            ).fetchall()
        }

    new_domains = this_week - baseline
    results = []
    for domain in new_domains:
        count = store.get_sender_volume(domain, days=days)
        if count >= 5:
            results.append({"domain": domain, "count": count})

    return sorted(results, key=lambda x: x["count"], reverse=True)


def detect_drift() -> dict:
    settings = _load_settings()
    threshold = settings.get("learning", {}).get("drift_alert_threshold", 2.0)

    # Current week counts from recent classifications
    counts_by_day = store.get_label_counts_by_day(days=7)
    current_counts = {label: sum(d.values()) for label, d in counts_by_day.items()}

    # Prior week snapshot
    prior_counts = store.get_latest_snapshot()

    drifting = _compare_snapshots(current_counts, prior_counts, threshold)
    new_senders = _detect_new_senders()

    summary = ""
    if drifting or new_senders:
        try:
            import json
            prompt = f"""Summarize these inbox changes in one sentence for a weekly digest.
Drifting clusters: {json.dumps(drifting[:3])}
New dominant senders: {json.dumps(new_senders[:3])}
One sentence:"""
            summary = generate_text(prompt, max_tokens=60).strip()
        except Exception:
            summary = f"{len(drifting)} clusters drifting, {len(new_senders)} new senders detected."

    result = {
        "drifting_labels": drifting,
        "new_dominant_senders": new_senders,
        "summary": summary,
    }

    # Send Telegram alert only if something notable
    if drifting or new_senders:
        _send_drift_alert(result)

    return result


def _send_drift_alert(drift_result: dict) -> None:
    import asyncio
    import os
    from telegram import Bot

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return

    lines = ["📊 *Weekly Inbox Drift Alert*\n"]
    if drift_result["drifting_labels"]:
        lines.append("*Clusters growing fast:*")
        for d in drift_result["drifting_labels"][:3]:
            lines.append(f"  • {d['label']}: {d['last_week']} → {d['this_week']} ({d['ratio']}x)")

    if drift_result["new_dominant_senders"]:
        lines.append("\n*New active senders:*")
        for s in drift_result["new_dominant_senders"][:3]:
            lines.append(f"  • {s['domain']} ({s['count']} emails this week)")

    if drift_result["summary"]:
        lines.append(f"\n_{drift_result['summary']}_")

    message = "\n".join(lines)
    try:
        bot = Bot(token=token)
        asyncio.run(bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown"))
        logger.info("Drift alert sent via Telegram")
    except Exception as e:
        logger.warning(f"Drift alert send failed: {e}")
