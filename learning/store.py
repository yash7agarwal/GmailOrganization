import json
import os
import sqlite3
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "learning/db/gmail_org.db")


def get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS classifications (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id         TEXT NOT NULL,
            thread_id        TEXT,
            subject          TEXT,
            sender           TEXT,
            sender_domain    TEXT,
            label            TEXT NOT NULL,
            confidence       REAL NOT NULL,
            priority_tier    TEXT,
            is_ambiguous     INTEGER DEFAULT 0,
            is_new_cluster   INTEGER DEFAULT 0,
            run_date         TEXT NOT NULL,
            timestamp        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cluster_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            label         TEXT NOT NULL,
            email_count   INTEGER NOT NULL,
            week_start    TEXT NOT NULL,
            snapshot_date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS sender_stats (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_domain           TEXT NOT NULL,
            sender_email            TEXT NOT NULL,
            email_count             INTEGER DEFAULT 0,
            last_seen               TEXT,
            user_replied            INTEGER DEFAULT 0,
            user_opened_via_bot     INTEGER DEFAULT 0,
            unsubscribe_candidate   INTEGER DEFAULT 0,
            sender_trust_score      INTEGER DEFAULT 50,
            month                   TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS feedback_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            payload    TEXT,
            timestamp  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bot_interactions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        TEXT NOT NULL,
            type             TEXT NOT NULL,  -- 'command', 'message', 'unknown_command', 'callback'
            input_text       TEXT,
            command_name     TEXT,
            status           TEXT NOT NULL,  -- 'success', 'error', 'unknown'
            error_message    TEXT,
            error_type       TEXT,
            response_sent    INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_bot_interactions_timestamp
            ON bot_interactions (timestamp);

        CREATE INDEX IF NOT EXISTS idx_bot_interactions_type
            ON bot_interactions (type, status);

        CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_month
            ON sender_stats (sender_email, month);

        CREATE INDEX IF NOT EXISTS idx_classifications_run_date
            ON classifications (run_date);

        CREATE INDEX IF NOT EXISTS idx_classifications_label
            ON classifications (label);

        CREATE TABLE IF NOT EXISTS expenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id    TEXT NOT NULL UNIQUE,
            merchant    TEXT,
            amount      REAL,
            currency    TEXT DEFAULT 'USD',
            date        TEXT,
            description TEXT,
            created_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            service         TEXT NOT NULL,
            merchant_domain TEXT,
            amount          REAL,
            currency        TEXT DEFAULT 'USD',
            billing_cycle   TEXT,
            renewal_date    TEXT,
            expiry_date     TEXT,
            status          TEXT DEFAULT 'active',
            last_updated    TEXT NOT NULL,
            UNIQUE(service)
        );
        """)
    print(f"Database initialized at {DB_PATH}")


def _extract_domain(sender: str) -> str:
    """Extract domain from 'Name <email@domain.com>' or 'email@domain.com'."""
    if "<" in sender:
        sender = sender.split("<")[1].rstrip(">")
    return sender.split("@")[-1].lower().strip() if "@" in sender else sender.lower()


def log_classification(
    email_id: str,
    thread_id: str,
    subject: str,
    sender: str,
    label: str,
    confidence: float,
    priority_tier: str,
    run_date: str,
    is_new_cluster: bool = False,
) -> None:
    threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO classifications
              (email_id, thread_id, subject, sender, sender_domain, label, confidence,
               priority_tier, is_ambiguous, is_new_cluster, run_date, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                email_id, thread_id, subject, sender, _extract_domain(sender),
                label, confidence, priority_tier,
                int(confidence < threshold), int(is_new_cluster),
                run_date, datetime.utcnow().isoformat(),
            ),
        )


def upsert_sender_stat(sender_email: str, month: str) -> None:
    domain = _extract_domain(sender_email)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sender_stats (sender_domain, sender_email, email_count, last_seen, month)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(sender_email, month) DO UPDATE SET
                email_count = email_count + 1,
                last_seen = excluded.last_seen
            """,
            (domain, sender_email, datetime.utcnow().isoformat(), month),
        )


def get_sender_volume(domain: str, days: int = 30) -> int:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM classifications WHERE sender_domain = ? AND run_date >= ?",
            (domain, cutoff),
        ).fetchone()
    return row["cnt"] if row else 0


def get_cluster_trend(label: str, weeks: int = 4) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT week_start, email_count FROM cluster_snapshots
            WHERE label = ?
            ORDER BY week_start ASC
            LIMIT ?
            """,
            (label, weeks),
        ).fetchall()
    return [dict(r) for r in rows]


def take_cluster_snapshot(counts_by_label: dict[str, int]) -> None:
    today = datetime.utcnow()
    week_start = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
    snapshot_date = today.strftime("%Y-%m-%d")
    with get_conn() as conn:
        for label, count in counts_by_label.items():
            conn.execute(
                """
                INSERT INTO cluster_snapshots (label, email_count, week_start, snapshot_date)
                VALUES (?, ?, ?, ?)
                """,
                (label, count, week_start, snapshot_date),
            )


def mark_unsubscribe_candidate(domain: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE sender_stats SET unsubscribe_candidate = 1 WHERE sender_domain = ?",
            (domain,),
        )


def get_unsubscribe_candidates(threshold: int = 5) -> list[dict]:
    month = datetime.utcnow().strftime("%Y-%m")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT sender_email, sender_domain, SUM(email_count) as total_volume
            FROM sender_stats
            WHERE user_replied = 0
              AND user_opened_via_bot = 0
              AND month >= ?
            GROUP BY sender_domain
            HAVING total_volume >= ?
            ORDER BY total_volume DESC
            """,
            (month, threshold),
        ).fetchall()
    return [dict(r) for r in rows]


def get_ambiguous_classifications(days: int = 30) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM classifications
            WHERE is_ambiguous = 1 AND run_date >= ?
            ORDER BY confidence ASC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_classifications_for_period(days: int = 30) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM classifications WHERE run_date >= ? ORDER BY timestamp ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_label_counts_by_day(days: int = 7) -> dict[str, dict[str, int]]:
    """Returns {label: {date: count}} for the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT label, run_date, COUNT(*) as cnt
            FROM classifications
            WHERE run_date >= ?
            GROUP BY label, run_date
            """,
            (cutoff,),
        ).fetchall()
    result: dict[str, dict[str, int]] = {}
    for row in rows:
        result.setdefault(row["label"], {})[row["run_date"]] = row["cnt"]
    return result


def log_feedback(event_type: str, payload: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO feedback_events (event_type, payload, timestamp) VALUES (?, ?, ?)",
            (event_type, json.dumps(payload), datetime.utcnow().isoformat()),
        )


def log_bot_interaction(
    interaction_type: str,
    input_text: str,
    command_name: str | None,
    status: str,
    error_message: str | None = None,
    error_type: str | None = None,
    response_sent: bool = False,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO bot_interactions
              (timestamp, type, input_text, command_name, status, error_message, error_type, response_sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (datetime.utcnow().isoformat(), interaction_type, input_text,
             command_name, status, error_message, error_type, int(response_sent)),
        )


def get_recent_bot_interactions(days: int = 7) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM bot_interactions WHERE timestamp >= ? ORDER BY timestamp DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_unhandled_patterns(days: int = 7) -> list[dict]:
    """Return unknown commands and repeated free-text messages from the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT input_text, command_name, type, COUNT(*) as frequency, MAX(timestamp) as last_seen
            FROM bot_interactions
            WHERE timestamp >= ?
              AND (status = 'unknown' OR (status = 'error' AND type = 'message'))
            GROUP BY LOWER(TRIM(input_text))
            ORDER BY frequency DESC
            LIMIT 50
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_error_patterns(days: int = 7) -> list[dict]:
    """Return commands that errored, grouped by command and error type."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT command_name, error_type, COUNT(*) as frequency, MAX(error_message) as sample_error
            FROM bot_interactions
            WHERE timestamp >= ? AND status = 'error'
            GROUP BY command_name, error_type
            ORDER BY frequency DESC
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def log_expense(
    email_id: str,
    merchant: str,
    amount: float | None,
    currency: str,
    date: str,
    description: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO expenses
              (email_id, merchant, amount, currency, date, description, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (email_id, merchant, amount, currency, date, description, datetime.utcnow().isoformat()),
        )


def get_recent_expenses(days: int = 7) -> list[dict]:
    cutoff = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM expenses WHERE date >= ? ORDER BY date DESC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_subscription(
    service: str,
    merchant_domain: str,
    amount: float | None,
    currency: str,
    billing_cycle: str | None,
    renewal_date: str | None,
    expiry_date: str | None,
) -> None:
    now = datetime.utcnow()
    status = "active"
    if expiry_date:
        try:
            exp = datetime.strptime(expiry_date, "%Y-%m-%d")
            if exp < now:
                status = "expired"
            elif (exp - now).days <= 7:
                status = "expiring_soon"
        except ValueError:
            pass
    if renewal_date and status == "active":
        try:
            ren = datetime.strptime(renewal_date, "%Y-%m-%d")
            if (ren - now).days <= 7:
                status = "expiring_soon"
        except ValueError:
            pass

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions
              (service, merchant_domain, amount, currency, billing_cycle, renewal_date, expiry_date, status, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service) DO UPDATE SET
                merchant_domain = excluded.merchant_domain,
                amount = excluded.amount,
                currency = excluded.currency,
                billing_cycle = excluded.billing_cycle,
                renewal_date = excluded.renewal_date,
                expiry_date = excluded.expiry_date,
                status = excluded.status,
                last_updated = excluded.last_updated
            """,
            (service, merchant_domain, amount, currency, billing_cycle,
             renewal_date, expiry_date, status, now.isoformat()),
        )


def get_upcoming_renewals(days: int = 30) -> list[dict]:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    cutoff = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE (renewal_date BETWEEN ? AND ? OR expiry_date BETWEEN ? AND ?)
              AND status != 'expired'
            ORDER BY COALESCE(renewal_date, expiry_date) ASC
            """,
            (today, cutoff, today, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_subscriptions() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM subscriptions ORDER BY status ASC, COALESCE(renewal_date, expiry_date) ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_latest_snapshot() -> dict[str, int]:
    """Returns the most recent cluster snapshot as {label: count}."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT label, email_count FROM cluster_snapshots
            WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM cluster_snapshots)
            """,
        ).fetchall()
    return {row["label"]: row["email_count"] for row in rows}
