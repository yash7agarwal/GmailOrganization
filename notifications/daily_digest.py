import os
from datetime import datetime

from utils.claude_client import generate_text
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_TELEGRAM_CHARS = 4000


def _format_must_reads_section(must_reads: list[dict]) -> str:
    if not must_reads:
        return ""
    lines = [f"*MUST READ ({len(must_reads)}):*"]
    for e in must_reads[:10]:  # cap at 10 to stay within char limit
        subject = e.get("subject", "(no subject)")[:60]
        sender = e.get("sender", "")
        if "<" in sender:
            sender = sender.split("<")[1].rstrip(">")
        lines.append(f"  • {subject} — _{sender}_")
    return "\n".join(lines)


def _format_cluster_breakdown(cluster_counts: dict[str, int]) -> str:
    if not cluster_counts:
        return ""
    lines = ["*BREAKDOWN:*"]
    # AI & Tech first, then sorted by count
    ai_count = cluster_counts.pop("AI & Tech Intelligence", None)
    sorted_items = sorted(cluster_counts.items(), key=lambda x: x[1], reverse=True)
    if ai_count is not None:
        sorted_items = [("AI & Tech Intelligence", ai_count)] + sorted_items
        cluster_counts["AI & Tech Intelligence"] = ai_count

    for label, count in sorted_items:
        lines.append(f"  {label}: *{count}*")
    return "\n".join(lines)


def _format_ai_highlight(cluster_counts: dict[str, int], classified: list[dict]) -> str:
    ai_count = cluster_counts.get("AI & Tech Intelligence", 0)
    if not ai_count:
        return ""
    return f"🤖 *AI & Tech:* {ai_count} emails"


def _format_unsubscribe_section(candidates: list[dict]) -> str:
    if not candidates:
        return ""
    lines = [f"*UNSUBSCRIBE CANDIDATES ({len(candidates)}):*"]
    for c in candidates[:5]:
        domain = c.get("sender_domain", c.get("sender_email", "unknown"))
        volume = c.get("total_volume", "?")
        lines.append(f"  • {domain} ({volume}/mo, no engagement)")
    return "\n".join(lines)


def _generate_prose_summary(pipeline_result: dict) -> str:
    total = pipeline_result.get("total_fetched", 0)
    must_reads = pipeline_result.get("must_reads", [])
    clusters = pipeline_result.get("cluster_counts", {})

    if total == 0:
        return "Your inbox is clear — no new emails today."

    try:
        top_labels = sorted(clusters.items(), key=lambda x: x[1], reverse=True)[:3]
        top_str = ", ".join(f"{l} ({c})" for l, c in top_labels)
        prompt = f"""Write a 2-sentence natural language inbox summary. Be concise and informative.
Total emails: {total}
Must-reads: {len(must_reads)}
Top categories: {top_str}
New labels created: {pipeline_result.get('new_labels_created', [])}

Summary (2 sentences max, no greeting):"""
        return generate_text(prompt, max_tokens=80).strip()
    except Exception as e:
        logger.warning(f"Prose summary generation failed: {e}")
        return f"{total} emails processed. {len(must_reads)} require your attention."


def build_digest(pipeline_result: dict) -> str:
    date_str = datetime.now().strftime("%b %-d, %Y")
    total = pipeline_result.get("total_fetched", 0)
    must_reads = pipeline_result.get("must_reads", [])
    cluster_counts = dict(pipeline_result.get("cluster_counts", {}))
    candidates = pipeline_result.get("unsubscribe_candidates", [])
    classified = pipeline_result.get("classified", [])
    new_labels = pipeline_result.get("new_labels_created", [])
    new_clusters = pipeline_result.get("new_clusters_proposed", [])

    prose = _generate_prose_summary(pipeline_result)
    sections = [
        f"📬 *DAILY INBOX — {date_str}*",
        f"_{prose}_",
    ]

    must_read_block = _format_must_reads_section(must_reads)
    if must_read_block:
        sections.append(must_read_block)

    ai_highlight = _format_ai_highlight(cluster_counts, classified)
    if ai_highlight:
        sections.append(ai_highlight)

    breakdown = _format_cluster_breakdown(cluster_counts)
    if breakdown:
        sections.append(breakdown)

    if new_labels:
        sections.append(f"✨ *New labels created:* {', '.join(new_labels)}")

    if new_clusters:
        names = [c.get("suggested_label", "?") for c in new_clusters]
        sections.append(f"🔍 *New clusters proposed:* {', '.join(names)} — reply /clusters to review")

    unsubscribe_block = _format_unsubscribe_section(candidates)
    if unsubscribe_block:
        sections.append(unsubscribe_block)

    sections.append("─────────────────")
    sections.append("/today · /unsubscribe · /clusters · /report")

    message = "\n\n".join(sections)

    # Trim if over Telegram limit
    if len(message) > MAX_TELEGRAM_CHARS:
        message = message[:MAX_TELEGRAM_CHARS - 50] + "\n\n_[digest truncated]_"

    return message


async def send_daily_digest(pipeline_result: dict, bot) -> bool:
    """Send the daily digest via the Telegram bot instance."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID not set")
        return False

    try:
        message = build_digest(pipeline_result)
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode="Markdown",
        )
        logger.info("Daily digest sent via Telegram")
        return True
    except Exception as e:
        logger.error(f"Failed to send daily digest: {e}")
        return False
