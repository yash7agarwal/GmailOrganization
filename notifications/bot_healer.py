from __future__ import annotations

"""
Auto-healing system for the Telegram bot.

Runs weekly to:
1. Analyse unhandled commands and repeated free-text patterns from bot_interactions
2. Use Claude to suggest new commands that would cover those patterns
3. Send suggestions to the user via Telegram with Accept/Dismiss buttons
4. Persist accepted suggestions and dynamically register new handlers at runtime

Dynamic command registry:
  Accepted command suggestions are stored in learning/db/dynamic_commands.json.
  On bot startup and after each healing cycle, that file is loaded and placeholder
  handlers are registered — each one just calls Claude with the user's message
  and the command's declared intent.
"""

import json
import os
from datetime import datetime
from pathlib import Path

from utils.claude_client import generate_text
from utils.logger import get_logger
from learning import store

logger = get_logger(__name__)

DYNAMIC_COMMANDS_PATH = Path("learning/db/dynamic_commands.json")
KNOWN_COMMANDS = {
    "today", "unsubscribe", "clusters", "learn", "report",
    "spend", "renewals", "subscriptions", "help",
}


# ── Dynamic command registry ─────────────────────────────────────────────────

def load_dynamic_commands() -> list[dict]:
    """Load persisted dynamic commands from disk."""
    if not DYNAMIC_COMMANDS_PATH.exists():
        return []
    try:
        return json.loads(DYNAMIC_COMMANDS_PATH.read_text())
    except Exception:
        return []


def save_dynamic_command(command: dict) -> None:
    """Append a new dynamic command to the registry."""
    DYNAMIC_COMMANDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = load_dynamic_commands()
    # Deduplicate by name
    existing = [c for c in existing if c.get("name") != command.get("name")]
    existing.append(command)
    DYNAMIC_COMMANDS_PATH.write_text(json.dumps(existing, indent=2))
    logger.info(f"Dynamic command saved: /{command.get('name')}")


def make_dynamic_handler(command_name: str, intent: str):
    """
    Create an async handler function for a dynamically registered command.
    The handler uses Claude to answer the user's message guided by the command's declared intent.
    """
    from telegram import Update
    from telegram.ext import ContextTypes

    async def dynamic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        from learning.store import log_bot_interaction
        user_text = update.message.text or f"/{command_name}"
        await update.message.reply_text("_Thinking..._", parse_mode="Markdown")
        try:
            # Build a context-aware prompt using the intent + recent inbox data
            counts = store.get_label_counts_by_day(days=7)
            cluster_summary = ", ".join(
                f"{lbl}: {sum(d.values())}" for lbl, d in counts.items()
            ) or "No classified emails yet."

            prompt = f"""You are an inbox assistant responding to a Telegram command.

Command: /{command_name}
Command intent: {intent}
User message: {user_text}
Inbox summary (last 7 days): {cluster_summary}

Respond helpfully and concisely (4-8 sentences max). Be specific where possible."""

            response = generate_text(prompt, max_tokens=400)
            await update.message.reply_text(response, parse_mode="Markdown")
            log_bot_interaction("command", user_text, command_name, "success", response_sent=True)
        except Exception as e:
            logger.error(f"Dynamic handler /{command_name} failed: {e}")
            await update.message.reply_text(
                f"⚠️ `/{command_name}` ran into an issue: {_friendly_error(e)}\n\n"
                "This command was auto-generated. Try rephrasing your request as a free-text message.",
                parse_mode="Markdown",
            )
            log_bot_interaction("command", user_text, command_name, "error",
                                error_message=str(e), error_type=type(e).__name__, response_sent=True)

    dynamic_handler.__name__ = f"cmd_{command_name}"
    return dynamic_handler


def register_dynamic_commands(app) -> int:
    """
    Load all accepted dynamic commands from disk and register them on the given Application.
    Returns number of handlers registered.
    """
    from telegram.ext import CommandHandler as TGCommandHandler
    commands = load_dynamic_commands()
    registered = 0
    for cmd in commands:
        name = cmd.get("name", "").strip().lstrip("/")
        intent = cmd.get("intent", "")
        if not name or name in KNOWN_COMMANDS:
            continue
        handler = make_dynamic_handler(name, intent)
        app.add_handler(TGCommandHandler(name, handler))
        registered += 1
        logger.info(f"Registered dynamic command: /{name}")
    return registered


# ── Interaction analysis ──────────────────────────────────────────────────────

def _build_analysis_prompt(unhandled: list[dict], errors: list[dict]) -> str:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    known = ", ".join(f"/{c}" for c in sorted(KNOWN_COMMANDS))

    unhandled_block = "\n".join(
        f"- \"{r['input_text']}\" (seen {r['frequency']}x, type={r['type']})"
        for r in unhandled[:20]
    ) or "None"

    error_block = "\n".join(
        f"- /{r['command_name']}: {r['error_type']} — \"{r['sample_error']}\" ({r['frequency']}x)"
        for r in errors[:10]
    ) or "None"

    return f"""You are analyzing a Telegram inbox-assistant bot to improve it.

Today: {today}
Existing commands: {known}

Unhandled messages and unknown commands from the last 7 days:
{unhandled_block}

Commands that errored:
{error_block}

Task:
1. Identify up to 5 NEW commands that would meaningfully cover the unhandled patterns.
   Each command must NOT duplicate an existing one.
2. For each erroring command, suggest one concrete fix (data issue, missing module, etc.).

Respond ONLY with valid JSON:
{{
  "new_commands": [
    {{
      "name": "command_name_no_slash",
      "description": "one sentence — what this command does",
      "intent": "detailed intent for the handler to use when calling Claude",
      "triggers": ["example phrase 1", "example phrase 2"]
    }}
  ],
  "error_fixes": [
    {{
      "command": "command_name",
      "fix": "one sentence describing the likely fix"
    }}
  ]
}}"""


def analyze_interactions() -> dict:
    """
    Pull interaction logs, ask Claude for suggestions, return structured result.
    Returns {"new_commands": [...], "error_fixes": [...]}
    """
    unhandled = store.get_unhandled_patterns(days=7)
    errors = store.get_error_patterns(days=7)

    if not unhandled and not errors:
        logger.info("Healer: no patterns to analyze")
        return {"new_commands": [], "error_fixes": []}

    prompt = _build_analysis_prompt(unhandled, errors)
    try:
        raw = generate_text(prompt, max_tokens=1200)
        result = json.loads(raw.strip())
        return result
    except Exception as e:
        logger.error(f"Healer analysis failed: {e}")
        return {"new_commands": [], "error_fixes": []}


# ── Telegram suggestion message ───────────────────────────────────────────────

def format_healing_report(analysis: dict) -> str:
    lines = ["🛠 *BOT HEALING REPORT*\n"]

    new_cmds = analysis.get("new_commands", [])
    if new_cmds:
        lines.append(f"*{len(new_cmds)} new commands suggested:*")
        for cmd in new_cmds:
            triggers = ", ".join(f'"{t}"' for t in cmd.get("triggers", [])[:2])
            lines.append(
                f"  ✨ `/{cmd['name']}` — {cmd['description']}\n"
                f"     _Triggered by: {triggers}_"
            )

    fixes = analysis.get("error_fixes", [])
    if fixes:
        lines.append(f"\n*{len(fixes)} error fixes identified:*")
        for fix in fixes:
            lines.append(f"  🔧 `/{fix['command']}` — {fix['fix']}")

    if not new_cmds and not fixes:
        lines.append("_All commands healthy. No new patterns detected._")

    lines.append("\nReply `/heal_accept` to register all suggested commands.")
    return "\n".join(lines)


async def send_healing_report(bot, chat_id: str, analysis: dict) -> None:
    """Send the healing report to Telegram."""
    if not analysis.get("new_commands") and not analysis.get("error_fixes"):
        return
    try:
        msg = format_healing_report(analysis)
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="Markdown")
        logger.info("Healing report sent via Telegram")
    except Exception as e:
        logger.error(f"Failed to send healing report: {e}")


async def accept_suggestions(analysis: dict, app, bot, chat_id: str) -> None:
    """Persist all suggested commands and register them on the running app."""
    new_cmds = analysis.get("new_commands", [])
    if not new_cmds:
        await bot.send_message(chat_id=chat_id, text="No new commands to register.")
        return

    registered = []
    for cmd in new_cmds:
        name = cmd.get("name", "").strip().lstrip("/")
        if not name or name in KNOWN_COMMANDS:
            continue
        save_dynamic_command(cmd)
        handler = make_dynamic_handler(name, cmd.get("intent", cmd.get("description", "")))
        from telegram.ext import CommandHandler as TGCommandHandler
        app.add_handler(TGCommandHandler(name, handler))
        KNOWN_COMMANDS.add(name)
        registered.append(f"/{name}")

    if registered:
        msg = f"✅ Registered {len(registered)} new commands: {', '.join(registered)}\nThey are live now."
    else:
        msg = "No new commands were registered (all already existed)."

    await bot.send_message(chat_id=chat_id, text=msg)
    logger.info(f"Accepted and registered: {registered}")


async def run_healing_cycle(app, bot, chat_id: str) -> None:
    """Full weekly healing cycle: analyze → report → (user can accept)."""
    logger.info("Running bot healing cycle...")
    analysis = analyze_interactions()
    # Store analysis for /heal_accept to reference
    _PENDING_ANALYSIS["data"] = analysis
    await send_healing_report(bot, chat_id, analysis)


# Shared state so /heal_accept can reference the last analysis
_PENDING_ANALYSIS: dict = {"data": {}}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _friendly_error(exc: Exception) -> str:
    """Convert an exception into a user-readable one-liner."""
    name = type(exc).__name__
    msg = str(exc)
    if "API" in name or "anthropic" in msg.lower():
        return "Claude API is unavailable right now. Try again in a moment."
    if "database" in msg.lower() or "sqlite" in msg.lower() or "OperationalError" in name:
        return "Database isn't ready yet. Run `init_db()` and restart the bot."
    if "ModuleNotFoundError" in name or "ImportError" in name:
        return f"A required module isn't installed: `{msg}`"
    if "TELEGRAM" in msg or "Forbidden" in msg:
        return "Telegram API error — check the bot token and chat ID."
    if msg and len(msg) < 120:
        return msg
    return f"{name} — check server logs for details."
