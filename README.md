# GmailOrganization

> Autonomous Gmail inbox organiser with Claude-powered classification, expense tracking, and Telegram notifications — that gets smarter every month.

Managing a busy inbox is a full-time job. This system does it for you: it fetches emails daily, classifies them into meaningful clusters using Claude AI, scores each one for reading priority, tracks your purchases and subscription renewals, and delivers a clean daily digest straight to your phone via Telegram. A continuous learning loop means the system refines itself every week and month, adapting to your inbox patterns without any manual tuning.

---

## What It Does

- **Classifies every email automatically** into clusters (AI & Tech, Newsletters, Promotions, Transactional, Purchases, Subscriptions, and more) using a two-pass system: fast keyword prefilter + Claude batch classification.
- **Scores emails by reading priority** — Must Read, Skim, or Skip — so you only look at what actually matters.
- **Tracks purchases and charges** extracted from receipt emails: merchant, amount, currency, and date logged automatically.
- **Monitors subscriptions and renewals** — alerts you 7 days before a subscription renews or expires, and 30 days ahead for annual plans.
- **Sends a daily Telegram digest** with must-reads, recent charges, upcoming renewals, unsubscribe candidates, and a Claude-written inbox summary.
- **Auto-heals its own Telegram bot** — logs every command and message, detects gaps, and proposes new commands weekly via Claude analysis.
- **Learns continuously** — weekly drift detection, monthly retraining, and a monthly AI & Tech report that surfaces tools and trends from your inbox.
- **Never deletes anything** — only labels and archives; fully non-destructive.

---

## Architecture

```
Gmail API
  └─▶ pipeline/fetcher.py         Fetch unlabeled emails (last N days)
        └─▶ pipeline/classifier.py  Keyword prefilter → Claude batch classify
              └─▶ pipeline/scorer.py   Priority scoring (must_read / skim / skip)
                    └─▶ pipeline/labeler.py  Create + apply Gmail labels
                          └─▶ expenses/extractor.py  Extract purchases & renewals
                                └─▶ learning/store.py  Log everything to SQLite

Independent schedules:
  Daily   07:00  ─▶ orchestrator + daily digest → Telegram
  Weekly  Mon    ─▶ drift_detector + cluster snapshot + bot healing report
  Monthly 1st    ─▶ retrainer + reporter + monthly report → Telegram

Telegram bot (always-on):
  /today /clusters /learn /report
  /spend /renewals /subscriptions
  /heal  /heal_accept  /help
  + auto-generated commands from healing cycles
```

---

## Project Structure

```
GmailOrganization/
│
├── config/
│   ├── labels.yaml          Seed label definitions and classification keywords
│   ├── scoring_rules.yaml   Must Read / Skim / Skip scoring rules
│   └── settings.yaml        Global settings (cron times, thresholds)
│
├── pipeline/
│   ├── orchestrator.py      Daily pipeline entry point — coordinates all stages
│   ├── fetcher.py           Gmail fetch with pagination and date filtering
│   ├── classifier.py        Two-pass classifier: keyword prefilter + Claude batch
│   ├── labeler.py           Gmail label creation and application
│   └── scorer.py            Reading priority scoring engine
│
├── expenses/
│   ├── extractor.py         Claude-based parser: extracts purchase/renewal data from emails
│   └── renewal_alerts.py    Formats charge + renewal sections for the daily digest
│
├── learning/
│   ├── store.py             SQLite read/write layer (all tables)
│   ├── drift_detector.py    Weekly: detect cluster growth anomalies
│   ├── retrainer.py         Monthly: re-cluster, propose label changes
│   └── reporter.py          Monthly: generate inbox + AI & Tech report
│
├── notifications/
│   ├── bot.py               Telegram bot with all command handlers + safe fallbacks
│   ├── bot_healer.py        Auto-healing: analyse interaction logs, suggest new commands
│   ├── daily_digest.py      Daily digest formatter (inbox + charges + renewals)
│   └── monthly_report.py    Monthly report formatter and sender
│
├── scheduler/
│   ├── daily.py             Daily cron (07:00)
│   ├── weekly.py            Weekly cron (Monday 08:00) + healing cycle
│   ├── monthly.py           Monthly cron (1st of month)
│   └── main.py              Run all three schedulers in one process
│
├── utils/
│   ├── gmail_client.py      Gmail API wrapper (OAuth)
│   ├── claude_client.py     Anthropic SDK wrapper with retry + all Claude calls
│   └── logger.py            Centralized structured logging
│
├── scripts/
│   ├── setup_oauth.py       One-time Gmail OAuth flow
│   ├── test_connection.py   Verify Gmail connection
│   └── export_watchlist.py  Export AI tool watchlist to Markdown/CSV
│
├── tests/
│   ├── test_classifier.py
│   ├── test_scorer.py
│   └── fixtures/            Sample emails for unit tests
│
├── .env.example             Environment variable template
├── requirements.txt         Python dependencies
└── CLAUDE.md                Full project specification and design decisions
```

---

## Setup

**Prerequisites:** Python 3.9+, a Google Cloud project with Gmail API enabled, an Anthropic API key, and a Telegram bot token.

### 1. Clone and install dependencies

```bash
git clone https://github.com/yash7agarwal/GmailOrganization.git
cd GmailOrganization
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Open .env and fill in all values (see Configuration section below)
```

### 3. Run the one-time Gmail OAuth flow

```bash
python scripts/setup_oauth.py
```

Opens a browser for Google sign-in and prints your `GMAIL_REFRESH_TOKEN`. Copy it into `.env`.

### 4. Test the Gmail connection

```bash
python scripts/test_connection.py
```

Should print your Gmail labels and 3 recent emails. If it works, OAuth is set up correctly.

### 5. Initialize the database

```bash
python -c "from learning.store import init_db; init_db()"
```

### 6. Run the pipeline once manually

```bash
python -m pipeline.orchestrator
```

### 7. Start the Telegram bot

```bash
python -m notifications.bot
```

### 8. Start all schedulers (daily + weekly + monthly in one process)

```bash
python -m scheduler.main
```

---

## Usage

### Telegram Commands

| Command | What it does |
|---|---|
| `/today` | Today's must-read emails (runs pipeline if not yet run) |
| `/clusters` | 7-day email cluster breakdown with trend bars |
| `/learn` | Manually trigger the full classification pipeline |
| `/unsubscribe` | List unsubscribe candidates with one-tap review buttons |
| `/spend` | Recent purchases in the last 7 days with totals |
| `/renewals` | Upcoming renewals and expiring subscriptions (next 30 days) |
| `/subscriptions` | Full active subscription list with amounts and next renewal dates |
| `/report` | Generate the monthly learning and AI & Tech report |
| `/heal` | Run bot healing analysis — identify gaps and suggest new commands |
| `/heal_accept` | Register all suggested commands from the last healing cycle |
| `/help` | Show all available commands |

Any free-text message (e.g. "summarise my newsletters") is handled by Claude with live inbox context.

### Daily Digest (sent automatically at 07:00)

```
📬 DAILY INBOX — Apr 5
Your inbox had 34 new emails today...

MUST READ (3):
  • Invoice from AWS — billing@amazon.com
  • ...

🤖 AI & Tech: 8 emails

BREAKDOWN:
  Newsletters: 12   Promotions: 9   Transactional: 6 ...

💳 RECENT CHARGES (2):
  • AWS — $47.30  Apr 4
  • Notion — $16.00  Apr 5

🔔 RENEWALS:
  ⚠️  Adobe CC — renews in 2d ($54.99)
  📅  GitHub Pro (annual) — renews 2026-05-01

🗑️ UNSUBSCRIBE CANDIDATES (2): ...
```

---

## Configuration

| Variable | Description | Where to get it |
|---|---|---|
| `GMAIL_CLIENT_ID` | OAuth 2.0 client ID | Google Cloud Console → APIs & Services → Credentials |
| `GMAIL_CLIENT_SECRET` | OAuth 2.0 client secret | Same as above |
| `GMAIL_REFRESH_TOKEN` | Long-lived refresh token | Run `python scripts/setup_oauth.py` |
| `ANTHROPIC_API_KEY` | Claude API key | [console.anthropic.com](https://console.anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | Bot token | Create a bot via [@BotFather](https://t.me/BotFather) on Telegram |
| `TELEGRAM_CHAT_ID` | Your personal chat ID | Send a message to your bot, call `getUpdates` to find it |
| `DB_PATH` | SQLite database path | Default: `learning/db/gmail_org.db` |
| `LOG_LEVEL` | Logging verbosity | `INFO` (default) or `DEBUG` |

Key config files:

- **`config/labels.yaml`** — seed label definitions and classification keywords
- **`config/scoring_rules.yaml`** — Must Read / Skim / Skip scoring rules
- **`config/settings.yaml`** — pipeline fetch limits, scheduler times, drift thresholds

---

## Recent Changes

- `2026-04-05` — Fix Python 3.9 compatibility: add `from __future__ import annotations`
- `2026-04-05` — Add fallback responses, interaction logging, and auto-healing system
- `2026-04-05` — Implement expense tracking and `/spend`, `/renewals`, `/subscriptions` commands
- `2026-04-05` — Add expense tracking and subscription renewal monitoring to project spec
- `2026-04-05` — Initial commit: autonomous Gmail organization system

---

## Roadmap

- Monthly spend report — total by merchant and category vs. prior month
- Auto-unsubscribe flow (clicking unsubscribe links automatically)
- Weekly HTML report with cluster trend charts saved to `logs/reports/`
- Sender trust scoring — high-trust senders (GitHub, etc.) never flagged for unsubscribe
- Reply draft suggestions for personal must-read emails (shown as Telegram spoiler text)
- Calendar event detection — extract event details and generate Google Calendar quick-add links
- AI Tool Watchlist export — persist monthly AI tool discoveries to `ai_watchlist.json` / Notion
- Currency normalization across USD / INR / EUR charges
- Cross-account support (multiple Gmail accounts)
- Integration with Notion/Obsidian to log AI tool discoveries into a personal knowledge base

---

## Tech Stack

| Layer | Technology |
|---|---|
| Email access | Gmail API (OAuth 2.0) |
| AI classification | Claude claude-haiku-4-5 (batch) + claude-sonnet-4-6 (reports) |
| Storage | SQLite via `learning/store.py` |
| Notifications | Telegram Bot API (`python-telegram-bot` v20+) |
| Scheduler | `schedule` library (daily / weekly / monthly) |
| Language | Python 3.9+ |
