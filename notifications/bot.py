import os
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

from learning import store
from utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

ALLOWED_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


def _is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)


async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    today = datetime.utcnow().strftime("%Y-%m-%d")
    counts = store.get_label_counts_by_day(days=1)

    # Check if pipeline has run today
    total_today = sum(
        counts.get(label, {}).get(today, 0)
        for label in counts
    )

    if total_today == 0:
        await update.message.reply_text(
            "Pipeline hasn't run today yet. Running now...",
            parse_mode="Markdown",
        )
        from pipeline.orchestrator import run_daily_pipeline
        from notifications.daily_digest import build_digest
        result = run_daily_pipeline()
        msg = build_digest(result)
    else:
        # Fetch must-reads from store
        from learning.store import get_classifications_for_period
        today_emails = [
            e for e in get_classifications_for_period(days=1)
            if e.get("priority_tier") == "must_read"
        ]
        if today_emails:
            lines = [f"*TODAY'S MUST READS ({len(today_emails)}):*"]
            for e in today_emails[:15]:
                lines.append(f"  • {e.get('subject', '(no subject)')[:60]}")
                lines.append(f"    _from {e.get('sender', '?')}_")
            msg = "\n".join(lines)
        else:
            msg = "No must-reads today. Inbox looks clear!"

    await update.message.reply_text(msg, parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/today", "date": today})


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    candidates = store.get_unsubscribe_candidates(threshold=5)
    if not candidates:
        await update.message.reply_text("No unsubscribe candidates right now. Inbox looks clean!")
        return

    for candidate in candidates[:10]:
        domain = candidate.get("sender_domain", candidate.get("sender_email", "unknown"))
        volume = candidate.get("total_volume", "?")

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Mark Reviewed", callback_data=f"reviewed:{domain}"),
                InlineKeyboardButton("🙋 Actually Useful", callback_data=f"useful:{domain}"),
            ]
        ])
        await update.message.reply_text(
            f"📧 *{domain}*\n_{volume} emails/month, zero engagement_",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    store.log_feedback("command_run", {"command": "/unsubscribe"})


async def cmd_clusters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    counts = store.get_label_counts_by_day(days=7)
    if not counts:
        await update.message.reply_text("No data yet. Run the pipeline first.")
        return

    lines = ["*7-DAY CLUSTER TREND:*\n"]
    ai_labels = {l: v for l, v in counts.items() if l == "AI & Tech Intelligence"}
    other_labels = {l: v for l, v in counts.items() if l != "AI & Tech Intelligence"}

    for label, day_counts in {**ai_labels, **other_labels}.items():
        total = sum(day_counts.values())
        bar = "▓" * min(int(total / 2), 20)
        lines.append(f"*{label}*\n  {bar} {total}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/clusters"})


async def cmd_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    await update.message.reply_text("Running pipeline now...")
    from pipeline.orchestrator import run_daily_pipeline
    from notifications.daily_digest import build_digest

    result = run_daily_pipeline()
    msg = build_digest(result)
    await update.message.reply_text(msg, parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/learn"})


async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    await update.message.reply_text("Generating monthly report...")
    try:
        from learning.reporter import generate_monthly_report
        from notifications.monthly_report import send_monthly_report
        report = generate_monthly_report()
        await send_monthly_report(report, context.bot)
    except Exception as e:
        await update.message.reply_text(f"Report generation failed: {e}")
    store.log_feedback("command_run", {"command": "/report"})


async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    from learning.store import get_recent_expenses
    expenses = get_recent_expenses(days=7)

    if not expenses:
        await update.message.reply_text("No purchases found in the last 7 days.")
        return

    _sym = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}
    total_by_currency: dict[str, float] = {}
    lines = ["*RECENT PURCHASES — last 7 days:*\n"]
    for e in expenses[:20]:
        merchant = e.get("merchant", "Unknown")
        amt = e.get("amount")
        currency = e.get("currency", "USD")
        date = e.get("date", "")[:10]
        symbol = _sym.get(currency.upper(), currency + " ")
        amt_str = f"{symbol}{amt:.2f}" if amt is not None else "amount unknown"
        lines.append(f"  • {merchant} — *{amt_str}* _{date}_")
        if amt is not None:
            total_by_currency[currency] = total_by_currency.get(currency, 0.0) + amt

    if total_by_currency:
        totals = ", ".join(f"{_sym.get(c.upper(), c + ' ')}{v:.2f}" for c, v in total_by_currency.items())
        lines.append(f"\n*Total:* {totals}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/spend"})


async def cmd_renewals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    from learning.store import get_upcoming_renewals
    from expenses.renewal_alerts import format_renewal_section, get_renewal_alerts

    alerts = get_renewal_alerts()
    section = format_renewal_section(alerts)

    if not section:
        renewals = get_upcoming_renewals(days=30)
        if not renewals:
            await update.message.reply_text("No upcoming renewals in the next 30 days.")
            return
        _sym = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}
        lines = ["*UPCOMING RENEWALS — next 30 days:*\n"]
        for r in renewals:
            service = r.get("service", "Unknown")
            due = r.get("renewal_date") or r.get("expiry_date", "?")
            amt = r.get("amount")
            currency = r.get("currency", "USD")
            symbol = _sym.get(currency.upper(), currency + " ")
            amt_str = f" — {symbol}{amt:.2f}" if amt is not None else ""
            lines.append(f"  • {service}{amt_str} — _{due}_")
        section = "\n".join(lines)

    await update.message.reply_text(section, parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/renewals"})


async def cmd_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    from learning.store import get_all_subscriptions
    subs = get_all_subscriptions()

    if not subs:
        await update.message.reply_text(
            "No subscriptions tracked yet.\n\n"
            "They'll be auto-detected from billing emails as the pipeline runs."
        )
        return

    _status_emoji = {"active": "✅", "expiring_soon": "⚠️", "expired": "❌"}
    _sym = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}
    lines = [f"*ALL SUBSCRIPTIONS ({len(subs)}):*\n"]
    for s in subs:
        service = s.get("service", "Unknown")
        amt = s.get("amount")
        currency = s.get("currency", "USD")
        cycle = s.get("billing_cycle") or ""
        renewal = s.get("renewal_date") or s.get("expiry_date") or "unknown"
        status = s.get("status", "active")
        emoji = _status_emoji.get(status, "•")
        symbol = _sym.get(currency.upper(), currency + " ")
        amt_str = f"{symbol}{amt:.2f}/{cycle}" if amt is not None else "amount unknown"
        lines.append(f"  {emoji} *{service}* — {amt_str}\n      next: _{renewal}_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    store.log_feedback("command_run", {"command": "/subscriptions"})


async def _handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, domain = data.split(":", 1)

    if action == "reviewed":
        store.mark_unsubscribe_candidate(domain)
        store.log_feedback("unsubscribe_reviewed", {"domain": domain})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"✅ {domain} marked as reviewed.")

    elif action == "useful":
        store.log_feedback("sender_useful", {"domain": domain})
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"👍 Got it — {domain} won't be flagged again.")


def _fetch_gmail_emails_for_query(text: str) -> list[dict]:
    """
    Fetch emails directly from Gmail for label-specific queries.
    Falls back to store classifications if Gmail fetch fails.
    """
    from utils.gmail_client import search_messages, get_message

    # Map user intent to Gmail search queries
    gmail_query_map = {
        ("unsubscribe", "newsletter", "newsletters"): "label:newsletters newer_than:7d",
        ("ai", "tech", "artificial intelligence"): "label:ai-tech-intelligence newer_than:7d",
        ("promo", "promotion", "marketing"): "label:promotions-marketing newer_than:7d",
        ("transactional",): "label:transactional newer_than:7d",
        ("subscription", "renewal"): "label:subscriptions-renewals newer_than:7d",
    }

    query = None
    for keywords, gmail_q in gmail_query_map.items():
        if any(k in text for k in keywords):
            query = gmail_q
            break

    if not query:
        # Generic recent inbox search
        query = "in:inbox newer_than:7d"

    try:
        refs = search_messages(query, max_results=30)
        emails = []
        for ref in refs[:20]:
            try:
                emails.append(get_message(ref["id"], fmt="metadata"))
            except Exception:
                pass
        return emails
    except Exception:
        return []


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text messages using Claude to interpret and respond."""
    if not _is_authorized(update):
        return

    text = update.message.text.lower()
    await update.message.reply_text("_Thinking..._", parse_mode="Markdown")

    try:
        from utils.claude_client import generate_text
        from learning.store import get_label_counts_by_day

        # Always fetch live from Gmail so we catch emails pipeline hasn't seen yet
        emails = _fetch_gmail_emails_for_query(text)

        # Also get cluster summary from store for context
        counts = get_label_counts_by_day(days=7)
        cluster_summary = ", ".join(
            f"{label}: {sum(d.values())}" for label, d in counts.items()
        ) or "No classified emails yet."

        email_context = "\n".join(
            f"- {e.get('subject', '(no subject)')} | from: {e.get('sender', '')} | {e.get('snippet', '')[:80]}"
            for e in emails
        ) or "No emails found for this query."

        prompt = f"""You are an inbox assistant. The user asked: "{update.message.text}"

Inbox summary (last 7 days, classified so far): {cluster_summary}

Emails found matching the query:
{email_context}

Instructions:
- Answer the user's question directly and concisely (3-6 sentences max)
- If they asked about newsletters or unsubscribing: list the senders/subjects clearly and suggest which ones to unsubscribe from based on relevance
- If they asked for a summary: highlight key themes and notable senders
- If they asked what to read: pick the most important ones
- Be specific — name actual subjects and senders from the list above"""

        response = generate_text(prompt, max_tokens=400)
        await update.message.reply_text(response)

        store.log_feedback("free_text_query", {"query": update.message.text, "emails_found": len(emails)})

    except Exception as e:
        logger.error(f"Message handler failed: {e}")
        await update.message.reply_text(
            "Sorry, I couldn't process that. Try /today, /clusters, /unsubscribe, or /report."
        )


def start_bot() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("clusters", cmd_clusters))
    app.add_handler(CommandHandler("learn", cmd_learn))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("renewals", cmd_renewals))
    app.add_handler(CommandHandler("subscriptions", cmd_subscriptions))
    app.add_handler(CallbackQueryHandler(_handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Telegram bot starting (polling mode)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_bot()
