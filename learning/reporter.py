import json
import os
from collections import Counter
from datetime import datetime, timedelta

from learning import store
from utils.claude_client import generate_text, extract_ai_tools
from utils.logger import get_logger

logger = get_logger(__name__, log_dir="logs/monthly")

AI_WATCHLIST_PATH = "learning/db/ai_watchlist.json"


def _inbox_snapshot(month: str) -> str:
    all_emails = store.get_classifications_for_period(days=30)
    label_counts = Counter(e.get("label", "Uncategorized") for e in all_emails)
    total = len(all_emails)

    lines = [f"*INBOX SNAPSHOT — {month}*", f"Total emails processed: *{total}*\n"]
    for label, count in sorted(label_counts.items(), key=lambda x: x[1], reverse=True):
        pct = int(count / total * 100) if total else 0
        lines.append(f"  {label}: {count} ({pct}%)")
    return "\n".join(lines)


def _new_patterns_section() -> str:
    # Senders that first appeared in the last 30 days
    all_emails = store.get_classifications_for_period(days=30)
    cutoff_60 = (datetime.utcnow() - timedelta(days=60)).strftime("%Y-%m-%d")
    cutoff_30 = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d")

    from learning.store import get_conn
    with store.get_conn() as conn:
        new_domains = {
            row["sender_domain"]
            for row in conn.execute(
                "SELECT DISTINCT sender_domain FROM classifications WHERE run_date >= ? "
                "AND sender_domain NOT IN ("
                "  SELECT DISTINCT sender_domain FROM classifications WHERE run_date < ?"
                ")",
                (cutoff_30, cutoff_30),
            ).fetchall()
        }

    if not new_domains:
        return "*NEW PATTERNS:* None detected this month."

    lines = [f"*NEW PATTERNS ({len(new_domains)} new senders):*"]
    for domain in list(new_domains)[:8]:
        count = store.get_sender_volume(domain, days=30)
        lines.append(f"  • {domain} ({count} emails)")
    return "\n".join(lines)


def _label_health_section() -> str:
    counts_by_day = store.get_label_counts_by_day(days=30)
    lines = ["*LABEL HEALTH:*"]
    issues = []

    for label, day_counts in counts_by_day.items():
        total = sum(day_counts.values())
        active_days = len(day_counts)
        if total == 0 or active_days < 3:
            issues.append(f"  ⚠️  {label}: stale (only {total} emails in 30 days)")
        elif total > 300:
            issues.append(f"  ⚠️  {label}: overloaded ({total} emails — consider splitting)")

    if not issues:
        lines.append("  All labels healthy.")
    else:
        lines.extend(issues)
    return "\n".join(lines)


def _ai_tech_digest() -> str:
    """The crown jewel: extract AI tools from this month's AI & Tech emails."""
    all_emails = store.get_classifications_for_period(days=30)
    ai_emails = [
        e for e in all_emails
        if e.get("label") == "AI & Tech Intelligence"
    ]

    if not ai_emails:
        return "*AI & TECH DIGEST:* No AI/Tech emails this month."

    # Build text batch from subjects + snippets
    text_batch = "\n".join(
        f"Subject: {e.get('subject', '')} | Sender: {e.get('sender', '')}"
        for e in ai_emails
    )

    tools = []
    try:
        tools = extract_ai_tools(text_batch)
        _save_ai_watchlist(tools)
    except Exception as e:
        logger.warning(f"AI tool extraction failed: {e}")

    lines = [f"*AI & TECH DIGEST ({len(ai_emails)} emails):*\n"]

    if tools:
        # Group by rating
        worth_exploring = [t for t in tools if t.get("claude_rating") == "Worth Exploring"]
        monitor = [t for t in tools if t.get("claude_rating") == "Monitor"]

        if worth_exploring:
            lines.append("🌟 *Worth Exploring:*")
            for t in worth_exploring[:5]:
                lines.append(f"  • *{t['tool_name']}* ({t['category']}) — {t['description']}")

        if monitor:
            lines.append("\n👀 *Monitor:*")
            for t in monitor[:5]:
                lines.append(f"  • *{t['tool_name']}* ({t['category']})")
    else:
        lines.append("  No specific tools extracted.")

    return "\n".join(lines)


def _save_ai_watchlist(tools: list[dict]) -> None:
    os.makedirs(os.path.dirname(AI_WATCHLIST_PATH), exist_ok=True)
    existing = []
    if os.path.exists(AI_WATCHLIST_PATH):
        try:
            with open(AI_WATCHLIST_PATH) as f:
                existing = json.load(f)
        except Exception:
            pass

    today = datetime.utcnow().strftime("%Y-%m-%d")
    existing_names = {t.get("tool_name", "").lower() for t in existing}
    for tool in tools:
        if tool.get("tool_name", "").lower() not in existing_names:
            tool["first_seen"] = today
            existing.append(tool)

    with open(AI_WATCHLIST_PATH, "w") as f:
        json.dump(existing, f, indent=2)
    logger.info(f"AI watchlist updated: {len(existing)} total tools")


def _unsubscribe_progress() -> str:
    candidates = store.get_unsubscribe_candidates(threshold=5)
    lines = [f"*UNSUBSCRIBE CANDIDATES:* {len(candidates)} domains flagged"]
    for c in candidates[:5]:
        domain = c.get("sender_domain", c.get("sender_email", "?"))
        volume = c.get("total_volume", "?")
        lines.append(f"  • {domain} ({volume} emails/mo)")
    return "\n".join(lines)


def _model_confidence_summary() -> str:
    all_emails = store.get_classifications_for_period(days=30)
    if not all_emails:
        return "*MODEL CONFIDENCE:* No data."

    total = len(all_emails)
    ambiguous = sum(1 for e in all_emails if e.get("is_ambiguous"))
    high_conf = total - ambiguous
    pct = int(high_conf / total * 100) if total else 0

    ambiguous_by_label = Counter(
        e.get("label") for e in all_emails if e.get("is_ambiguous")
    )
    worst = ambiguous_by_label.most_common(3)

    lines = [
        f"*MODEL CONFIDENCE:*",
        f"  High confidence: {high_conf}/{total} ({pct}%)",
    ]
    if worst:
        lines.append("  Most ambiguous labels:")
        for label, count in worst:
            lines.append(f"    • {label}: {count} uncertain")
    return "\n".join(lines)


def generate_monthly_report() -> str:
    month = datetime.utcnow().strftime("%B %Y")
    logger.info(f"Generating monthly report for {month}")

    separator = "\n\n---\n\n"
    sections = [
        f"📊 *MONTHLY INBOX REPORT — {month}*",
        _inbox_snapshot(month),
        _new_patterns_section(),
        _label_health_section(),
        _ai_tech_digest(),
        _unsubscribe_progress(),
        _model_confidence_summary(),
    ]

    report = separator.join(sections)
    logger.info(f"Monthly report generated ({len(report)} chars)")
    return report
