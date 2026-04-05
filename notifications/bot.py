from __future__ import annotations

import functools
import os
import traceback
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


# ── Auth ─────────────────────────────────────────────────────────────────────

def _is_authorized(update: Update) -> bool:
    return str(update.effective_chat.id) == str(ALLOWED_CHAT_ID)


# ── Safe handler decorator ────────────────────────────────────────────────────

def safe_handler(command_name: str | None = None):
    """
    Decorator that wraps a command or message handler with:
    - Always-send fallback: if the handler raises, the user gets a descriptive error
    - Interaction logging: every call (success or failure) is written to bot_interactions
    """
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            if not _is_authorized(update):
                return

            name = command_name or fn.__name__.replace("cmd_", "/")
            input_text = (update.message.text or "") if update.message else ""

            try:
                await fn(update, context)
                store.log_bot_interaction(
                    interaction_type="command" if command_name else "message",
                    input_text=input_text,
                    command_name=name,
                    status="success",
                    response_sent=True,
                )
            except Exception as exc:
                error_type = type(exc).__name__
                error_msg = str(exc)
                tb_summary = traceback.format_exc().splitlines()[-3:]
                logger.error(f"Handler /{name} failed [{error_type}]: {error_msg}")

                # Build a meaningful fallback message
                friendly = _friendly_error(exc)
                fallback = (
                    f"⚠️ *`{name}` couldn't complete*\n\n"
                    f"*Reason:* {friendly}\n\n"
                    f"*What to try:*\n"
                    f"{_suggest_alternatives(name)}"
                )
                try:
                    await update.message.reply_text(fallback, parse_mode="Markdown")
                except Exception:
                    pass  # If even the fallback fails, we can't do much

                store.log_bot_interaction(
                    interaction_type="command" if command_name else "message",
                    input_text=input_text,
                    command_name=name,
                    status="error",
                    error_message=error_msg[:500],
                    error_type=error_type,
                    response_sent=True,
                )
        return wrapper
    return decorator


def _friendly_error(exc: Exception) -> str:
    from notifications.bot_healer import _friendly_error as healer_friendly
    return healer_friendly(exc)


def _suggest_alternatives(failed_command: str) -> str:
    suggestions = {
        "/today": "• Try `/learn` to run the pipeline first, then `/today`",
        "/spend": "• Expenses are populated automatically as the pipeline runs\n• Run `/learn` to process today's emails first",
        "/renewals": "• Renewals are detected from billing emails — run `/learn` first\n• Check `/subscriptions` for the full list",
        "/subscriptions": "• Subscriptions are auto-detected from emails — run `/learn` first",
        "/clusters": "• Run `/learn` to populate cluster data first",
        "/report": "• Make sure the learning store has data — run `/learn` first\n• Check server logs for report generation errors",
        "/unsubscribe": "• No candidates may exist yet — run `/learn` to process more emails",
    }
    default = "• Use `/help` to see all available commands\n• Send a free-text message describing what you need"
    return suggestions.get(failed_command, default)


# ── Command handlers ──────────────────────────────────────────────────────────

@safe_handler("/today")
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    counts = store.get_label_counts_by_day(days=1)
    total_today = sum(counts.get(label, {}).get(today, 0) for label in counts)

    if total_today == 0:
        await update.message.reply_text(
            "Pipeline hasn't run today yet. Running now...", parse_mode="Markdown"
        )
        from pipeline.orchestrator import run_daily_pipeline
        from notifications.daily_digest import build_digest
        result = run_daily_pipeline()
        msg = build_digest(result)
    else:
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


@safe_handler("/unsubscribe")
async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    candidates = store.get_unsubscribe_candidates(threshold=5)
    if not candidates:
        await update.message.reply_text("No unsubscribe candidates right now. Inbox looks clean!")
        return

    for candidate in candidates[:10]:
        domain = candidate.get("sender_domain", candidate.get("sender_email", "unknown"))
        volume = candidate.get("total_volume", "?")
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Mark Reviewed", callback_data=f"reviewed:{domain}"),
            InlineKeyboardButton("🙋 Actually Useful", callback_data=f"useful:{domain}"),
        ]])
        await update.message.reply_text(
            f"📧 *{domain}*\n_{volume} emails/month, zero engagement_",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
    store.log_feedback("command_run", {"command": "/unsubscribe"})


@safe_handler("/clusters")
async def cmd_clusters(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    counts = store.get_label_counts_by_day(days=7)
    if not counts:
        await update.message.reply_text("No data yet. Run `/learn` to process emails first.")
        return

    lines = ["*7-DAY CLUSTER TREND:*\n"]
    ai_labels = {l: v for l, v in counts.items() if l == "AI & Tech Intelligence"}
    other_labels = {l: v for l, v in counts.items() if l != "AI & Tech Intelligence"}
    for label, day_counts in {**ai_labels, **other_labels}.items():
        total = sum(day_counts.values())
        bar = "▓" * min(int(total / 2), 20)
        lines.append(f"*{label}*\n  {bar} {total}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@safe_handler("/learn")
async def cmd_learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Running pipeline now...")
    from pipeline.orchestrator import run_daily_pipeline
    from notifications.daily_digest import build_digest
    result = run_daily_pipeline()
    msg = build_digest(result)
    await update.message.reply_text(msg, parse_mode="Markdown")


@safe_handler("/report")
async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Generating monthly report...")
    from learning.reporter import generate_monthly_report
    from notifications.monthly_report import send_monthly_report
    report = generate_monthly_report()
    await send_monthly_report(report, context.bot)


@safe_handler("/spend")
async def cmd_spend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from learning.store import get_recent_expenses
    expenses = get_recent_expenses(days=7)
    if not expenses:
        await update.message.reply_text(
            "No purchases found in the last 7 days.\n\n"
            "Expenses are auto-detected from receipt emails. Run `/learn` to process new emails."
        )
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
        totals = ", ".join(
            f"{_sym.get(c.upper(), c + ' ')}{v:.2f}" for c, v in total_by_currency.items()
        )
        lines.append(f"\n*Total:* {totals}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@safe_handler("/renewals")
async def cmd_renewals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from learning.store import get_upcoming_renewals
    from expenses.renewal_alerts import format_renewal_section, get_renewal_alerts

    alerts = get_renewal_alerts()
    section = format_renewal_section(alerts)

    if not section:
        renewals = get_upcoming_renewals(days=30)
        if not renewals:
            await update.message.reply_text(
                "No upcoming renewals in the next 30 days.\n\n"
                "Renewals are detected from billing emails — run `/learn` to process more."
            )
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


@safe_handler("/subscriptions")
async def cmd_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from learning.store import get_all_subscriptions
    subs = get_all_subscriptions()
    if not subs:
        await update.message.reply_text(
            "No subscriptions tracked yet.\n\n"
            "They're auto-detected from billing emails as the pipeline runs. Try `/learn` first."
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


@safe_handler("/help")
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from notifications.bot_healer import load_dynamic_commands
    dynamic = load_dynamic_commands()

    lines = [
        "*INBOX ASSISTANT — COMMANDS*\n",
        "📬 *Inbox*",
        "  `/today` — Today's must-read emails (runs pipeline if needed)",
        "  `/clusters` — 7-day email cluster breakdown",
        "  `/learn` — Manually trigger the classification pipeline",
        "  `/unsubscribe` — List unsubscribe candidates",
        "",
        "💳 *Finances*",
        "  `/spend` — Recent purchases (last 7 days)",
        "  `/renewals` — Upcoming renewals & expiring subscriptions",
        "  `/subscriptions` — Full subscription list with amounts",
        "",
        "📊 *Reports*",
        "  `/report` — Generate monthly learning report",
        "",
        "🛠 *System*",
        "  `/heal` — Run bot healing analysis now",
        "  `/heal_accept` — Register all suggested commands from last heal",
        "  `/help` — Show this message",
    ]

    if dynamic:
        lines.append("\n✨ *Auto-generated commands*")
        for cmd in dynamic:
            lines.append(f"  `/{cmd['name']}` — {cmd['description']}")

    lines.append("\n_Or just type anything — I'll do my best to answer._")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@safe_handler("/heal")
async def cmd_heal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 Running bot healing analysis...")
    from notifications.bot_healer import run_healing_cycle
    chat_id = str(update.effective_chat.id)
    await run_healing_cycle(context.application, context.bot, chat_id)


@safe_handler("/heal_accept")
async def cmd_heal_accept(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from notifications.bot_healer import accept_suggestions, _PENDING_ANALYSIS
    analysis = _PENDING_ANALYSIS.get("data", {})
    if not analysis or not analysis.get("new_commands"):
        await update.message.reply_text(
            "No pending suggestions to accept. Run `/heal` first to generate suggestions."
        )
        return
    chat_id = str(update.effective_chat.id)
    await accept_suggestions(analysis, context.application, context.bot, chat_id)


# ── Unknown command handler ───────────────────────────────────────────────────

async def cmd_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    text = update.message.text or ""
    command = text.split()[0] if text else "unknown"

    store.log_bot_interaction(
        interaction_type="unknown_command",
        input_text=text,
        command_name=command,
        status="unknown",
        response_sent=True,
    )

    await update.message.reply_text(
        f"🤷 I don't recognise `{command}`.\n\n"
        "Use `/help` to see all available commands, or just type your question as a message.\n\n"
        "_Tip: Run `/heal` and I'll analyse recent unknown commands and suggest new ones._",
        parse_mode="Markdown",
    )


# ── Callback query handler ────────────────────────────────────────────────────

async def _handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    if ":" not in data:
        return

    action, domain = data.split(":", 1)
    try:
        if action == "reviewed":
            store.mark_unsubscribe_candidate(domain)
            store.log_feedback("unsubscribe_reviewed", {"domain": domain})
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"✅ {domain} marked as reviewed.")
        elif action == "useful":
            store.log_feedback("sender_useful", {"domain": domain})
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(f"👍 Got it — {domain} won't be flagged again.")
        store.log_bot_interaction("callback", data, action, "success", response_sent=True)
    except Exception as e:
        logger.error(f"Callback handler failed: {e}")
        store.log_bot_interaction("callback", data, action, "error",
                                  error_message=str(e), error_type=type(e).__name__, response_sent=False)


# ── Free-text message handler ─────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return

    text = update.message.text or ""
    await update.message.reply_text("_Thinking..._", parse_mode="Markdown")

    try:
        from utils.claude_client import generate_text
        from learning.store import get_label_counts_by_day
        from utils.gmail_client import search_messages, get_message

        counts = get_label_counts_by_day(days=7)
        cluster_summary = ", ".join(
            f"{lbl}: {sum(d.values())}" for lbl, d in counts.items()
        ) or "No classified emails yet."

        # Try to fetch relevant emails
        emails = []
        try:
            refs = search_messages("in:inbox newer_than:7d", max_results=20)
            for ref in refs[:15]:
                try:
                    emails.append(get_message(ref["id"], fmt="metadata"))
                except Exception:
                    pass
        except Exception:
            pass

        email_context = "\n".join(
            f"- {e.get('subject', '(no subject)')} | from: {e.get('sender', '')} | {e.get('snippet', '')[:80]}"
            for e in emails
        ) or "No recent emails available."

        prompt = f"""You are an inbox assistant. The user sent this message: "{text}"

Inbox summary (last 7 days): {cluster_summary}

Recent emails:
{email_context}

Answer the user's question directly and concisely (3-6 sentences). Be specific — name actual subjects/senders where relevant. If you can't answer, suggest which slash command would help."""

        response = generate_text(prompt, max_tokens=400)
        await update.message.reply_text(response, parse_mode="Markdown")

        store.log_bot_interaction("message", text, None, "success", response_sent=True)

    except Exception as e:
        error_type = type(e).__name__
        logger.error(f"Message handler failed [{error_type}]: {e}")

        from notifications.bot_healer import _friendly_error
        friendly = _friendly_error(e)
        await update.message.reply_text(
            f"⚠️ *Couldn't process your message*\n\n"
            f"*Reason:* {friendly}\n\n"
            "Try a specific command like `/today`, `/spend`, or `/help` to see what's available.",
            parse_mode="Markdown",
        )
        store.log_bot_interaction("message", text, None, "error",
                                  error_message=str(e)[:500], error_type=error_type, response_sent=True)


# ── Global error handler ──────────────────────────────────────────────────────

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Catch any unhandled exception from the dispatcher and notify the user."""
    exc = context.error
    logger.error(f"Unhandled dispatcher error: {exc}", exc_info=exc)

    from notifications.bot_healer import _friendly_error
    friendly = _friendly_error(exc) if exc else "An unexpected error occurred."

    if isinstance(update, Update) and update.message:
        try:
            await update.message.reply_text(
                f"⚠️ *Something went wrong*\n\n{friendly}\n\n"
                "The error has been logged. Run `/heal` later to see if a fix is suggested.",
                parse_mode="Markdown",
            )
        except Exception:
            pass

    if exc:
        input_text = (update.message.text or "") if isinstance(update, Update) and update.message else ""
        store.log_bot_interaction(
            interaction_type="unhandled_error",
            input_text=input_text,
            command_name=None,
            status="error",
            error_message=str(exc)[:500],
            error_type=type(exc).__name__,
            response_sent=True,
        )


# ── Bot startup ───────────────────────────────────────────────────────────────

def start_bot() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in environment")

    app = ApplicationBuilder().token(token).build()

    # Core commands
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("clusters", cmd_clusters))
    app.add_handler(CommandHandler("learn", cmd_learn))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("spend", cmd_spend))
    app.add_handler(CommandHandler("renewals", cmd_renewals))
    app.add_handler(CommandHandler("subscriptions", cmd_subscriptions))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("heal", cmd_heal))
    app.add_handler(CommandHandler("heal_accept", cmd_heal_accept))

    # Dynamic commands from previous healing cycles
    from notifications.bot_healer import register_dynamic_commands
    n_dynamic = register_dynamic_commands(app)
    if n_dynamic:
        logger.info(f"Loaded {n_dynamic} dynamic commands from previous healing cycles")

    # Callback + fallback handlers
    app.add_handler(CallbackQueryHandler(_handle_callback_query))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.COMMAND, cmd_unknown))  # catches unknown /commands

    # Global error handler
    app.add_error_handler(global_error_handler)

    logger.info("Telegram bot starting (polling mode)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_bot()
