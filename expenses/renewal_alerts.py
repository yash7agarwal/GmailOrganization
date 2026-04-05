"""
Format renewal alerts and recent charges for the daily digest.
"""

from datetime import datetime, timedelta
from learning import store


def get_renewal_alerts() -> dict:
    """
    Returns categorised renewal data for the daily digest:
    {
        "urgent":   list of subscriptions renewing/expiring within 7 days,
        "upcoming": list of annual subscriptions renewing within 30 days (but not within 7),
        "expired":  list of subscriptions that expired in the last 3 days,
    }
    """
    today = datetime.utcnow()
    all_upcoming = store.get_upcoming_renewals(days=30)
    urgent, upcoming_annual, expired = [], [], []

    for sub in all_upcoming:
        due_date_str = sub.get("renewal_date") or sub.get("expiry_date")
        if not due_date_str:
            continue
        try:
            due = datetime.strptime(due_date_str, "%Y-%m-%d")
        except ValueError:
            continue

        days_away = (due - today).days
        cycle = sub.get("billing_cycle", "")

        if sub.get("status") == "expired" or days_away < 0:
            if days_away >= -3:
                expired.append(sub)
        elif days_away <= 7:
            urgent.append(sub)
        elif cycle == "annual":
            upcoming_annual.append(sub)

    return {"urgent": urgent, "upcoming": upcoming_annual, "expired": expired}


def format_renewal_section(alerts: dict) -> str:
    """Format renewal alerts as Telegram Markdown text. Returns empty string if nothing notable."""
    lines = []

    if alerts.get("expired"):
        for sub in alerts["expired"]:
            service = sub.get("service", "Unknown")
            date_str = sub.get("expiry_date") or sub.get("renewal_date", "")
            lines.append(f"❌ *{service}* expired {_relative_date(date_str)}")

    if alerts.get("urgent"):
        for sub in alerts["urgent"]:
            service = sub.get("service", "Unknown")
            amount = _fmt_amount(sub)
            due_str = sub.get("renewal_date") or sub.get("expiry_date", "")
            days = _days_until(due_str)
            label = "renews" if sub.get("renewal_date") else "expires"
            days_text = f"in {days}d" if days > 0 else "today"
            lines.append(f"⚠️  *{service}* — {label} {days_text}{amount}")

    if alerts.get("upcoming"):
        for sub in alerts["upcoming"]:
            service = sub.get("service", "Unknown")
            amount = _fmt_amount(sub)
            due_str = sub.get("renewal_date") or sub.get("expiry_date", "")
            lines.append(f"📅 *{service}* (annual) — renews {due_str}{amount}")

    if not lines:
        return ""
    return "🔔 *RENEWALS:*\n" + "\n".join(f"  {l}" for l in lines)


def format_charges_section(days: int = 1) -> str:
    """Format recent purchases for the daily digest. Returns empty string if none."""
    expenses = store.get_recent_expenses(days=days)
    if not expenses:
        return ""
    lines = [f"💳 *RECENT CHARGES ({len(expenses)}):*"]
    for e in expenses[:8]:
        merchant = e.get("merchant", "Unknown")
        amt = e.get("amount")
        currency = e.get("currency", "USD")
        date = e.get("date", "")[:10]
        amt_str = f" — {_currency_symbol(currency)}{amt:.2f}" if amt is not None else ""
        lines.append(f"  • {merchant}{amt_str} _{date}_")
    return "\n".join(lines)


def _fmt_amount(sub: dict) -> str:
    amt = sub.get("amount")
    currency = sub.get("currency", "USD")
    if amt is None:
        return ""
    return f" ({_currency_symbol(currency)}{amt:.2f})"


def _currency_symbol(currency: str) -> str:
    return {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(currency.upper(), currency + " ")


def _days_until(date_str: str) -> int:
    try:
        due = datetime.strptime(date_str, "%Y-%m-%d")
        return (due - datetime.utcnow()).days
    except ValueError:
        return 0


def _relative_date(date_str: str) -> str:
    days = _days_until(date_str)
    if days == 0:
        return "today"
    if days == -1:
        return "yesterday"
    return f"{abs(days)} days ago"
