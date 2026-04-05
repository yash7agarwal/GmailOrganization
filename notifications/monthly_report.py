import os
import asyncio
from utils.logger import get_logger

logger = get_logger(__name__)

MAX_CHARS = 4000


def _split_for_telegram(text: str) -> list[str]:
    """Split report on section boundaries to stay within Telegram's 4096 char limit."""
    sections = text.split("\n\n---\n\n")
    chunks = []
    current = ""
    for section in sections:
        if len(current) + len(section) + 6 > MAX_CHARS:
            if current:
                chunks.append(current.strip())
            current = section
        else:
            current = f"{current}\n\n---\n\n{section}" if current else section
    if current:
        chunks.append(current.strip())
    return chunks or [text[:MAX_CHARS]]


def format_ai_tool_table(tools: list[dict]) -> str:
    if not tools:
        return "_No AI tools detected this month._"
    lines = ["*Tool | Category | Rating*"]
    for t in tools[:15]:
        name = t.get("tool_name", "?")
        cat = t.get("category", "?")
        rating = t.get("claude_rating", "?")
        lines.append(f"• *{name}* ({cat}) — {rating}")
    return "\n".join(lines)


async def send_monthly_report(report: str, bot) -> bool:
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not chat_id:
        logger.error("TELEGRAM_CHAT_ID not set")
        return False

    chunks = _split_for_telegram(report)
    try:
        for i, chunk in enumerate(chunks):
            prefix = f"📊 *Monthly Report ({i+1}/{len(chunks)})*\n\n" if len(chunks) > 1 else ""
            await bot.send_message(
                chat_id=chat_id,
                text=prefix + chunk,
                parse_mode="Markdown",
            )
            if i < len(chunks) - 1:
                await asyncio.sleep(1)
        logger.info(f"Monthly report sent in {len(chunks)} message(s)")
        return True
    except Exception as e:
        logger.error(f"Failed to send monthly report: {e}")
        return False
