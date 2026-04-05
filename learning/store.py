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

        CREATE UNIQUE INDEX IF NOT EXISTS idx_sender_month
            ON sender_stats (sender_email, month);

        CREATE INDEX IF NOT EXISTS idx_classifications_run_date
            ON classifications (run_date);

        CREATE INDEX IF NOT EXISTS idx_classifications_label
            ON classifications (label);
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
