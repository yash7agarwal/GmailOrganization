# Gmail Organization Project

## Project Purpose

Autonomously organize a Gmail inbox using intelligent email clustering, label management, reading priority scoring, unsubscribe detection, expense tracking, and Telegram/mobile notifications — with a **continuous auto-learning loop** that evolves its understanding of the user's inbox patterns month over month.

The system also acts as a **personal finance monitor**: it extracts purchases, charges, and subscription costs from emails, tracks upcoming renewals and expiring subscriptions, and surfaces all of this in the daily Telegram digest.

---

## Core Features

### 1. Autonomous Email Clustering & Labeling

The system automatically identifies clusters of emails and creates/applies Gmail labels daily. Predefined seed categories:

| Label | Description |
|---|---|
| `Subscriptions & Renewals` | SaaS renewals, domain/hosting renewals, billing alerts |
| `Transactional` | Daily automated emails from services (Zoom, Webex, calendar invites, receipts) |
| `Promotions & Marketing` | Marketing blasts, MBA program emails, course promotions, sales |
| `Newsletters` | Curated newsletters, digest emails, Substack, etc. |
| `AI & Tech Intelligence` | AI research papers, model releases, LLM news, AI tool launches, developer digests — prioritized given user's active AI engagement |
| `Unsubscribe Candidates` | Emails from lists the user has never engaged with — flagged for unsubscribing |
| `Purchases & Receipts` | Order confirmations, payment receipts, invoices, charge notifications |
| `Subscriptions & Renewals` | Active subscriptions with renewal/expiry dates extracted for tracking |

Beyond seeds, the system **auto-discovers** new clusters based on sender patterns, subject line similarity, and email frequency — then proposes and creates new labels dynamically.

### 2. Daily Run Loop

Every day the system should:
1. Fetch new/unlabeled emails
2. Classify each email into an existing or new cluster using the current model
3. Create any new Gmail labels that are needed
4. Apply labels to emails
5. Score each email for reading priority
6. Extract purchases and subscription events from relevant emails
7. Update the expense and renewal tracking store
8. Log classification decisions to the learning store
9. Send a daily digest notification via Telegram (including purchases + renewal alerts)

### 3. Reading Priority Scoring

After clustering, evaluate each email and produce a tiered output:

- **Must Read** — Emails requiring action, personal messages, important alerts, high-signal AI/tech updates
- **Skim** — Useful content but low urgency (newsletters, some promotions)
- **Skip / Auto-Archive** — Purely promotional, mass-sent, or duplicate content

Delivered as part of the daily Telegram notification.

### 4. Expense & Subscription Tracking

The system extracts structured financial data from emails and maintains a running expense log and renewal calendar.

#### What Gets Tracked

**Recent Purchases** — extracted from order confirmations, payment receipts, and charge emails:
- Merchant / sender name
- Amount charged (currency + value)
- Purchase date
- Item/service description (if available)
- Transaction ID or order number

**Subscriptions & Renewals** — extracted from billing confirmation, renewal reminder, and trial-ending emails:
- Service name (e.g., Notion, AWS, Adobe)
- Billing amount and cycle (monthly/annual)
- Next renewal date
- Expiry date (for trials or fixed-term subscriptions)
- Status: `active`, `expiring_soon` (≤7 days), `expired`

#### Renewal Alert Rules

Proactively flag in the daily digest:
- Any subscription renewing **within 7 days** — "Upcoming: Netflix renews in 3 days ($15.99)"
- Any subscription that **expired in the last 3 days** — "Expired: Adobe CC expired yesterday"
- Any new charge above a configurable threshold (default: ₹500 / $10) — "New charge: AWS $47.30"
- Annual subscriptions renewing **within 30 days** — surfaced as a low-priority reminder

#### Data Extraction Approach

Use Claude to parse purchase/billing emails and extract structured JSON:
```json
{
  "type": "purchase" | "renewal" | "expiry_reminder" | "trial_ending",
  "merchant": "string",
  "amount": number,
  "currency": "string",
  "date": "YYYY-MM-DD",
  "renewal_date": "YYYY-MM-DD or null",
  "expiry_date": "YYYY-MM-DD or null",
  "billing_cycle": "monthly" | "annual" | "one-time" | null,
  "description": "string"
}
```

Store in the `expenses` and `subscriptions` tables in SQLite (see Learning Store).

#### Telegram Commands for Expenses

- `/spend` — recent purchases in the last 7 days with total
- `/renewals` — all subscriptions renewing in the next 30 days, sorted by date
- `/subscriptions` — full active subscription list with amounts and next renewal dates

### 5. Unsubscribe Detection

A dedicated label `Unsubscribe Candidates` is maintained for emails where:
- The user has never clicked or replied
- Sender volume is high (more than N emails/month)
- Content matches promotional/marketing patterns

Daily report includes a list of domains/senders to unsubscribe from.

### 6. Telegram / Mobile Notifications

Communicate with the user via Telegram to report:
- Daily summary: total emails received, breakdown by cluster, must-read count
- **Recent purchases** (last 24h) — merchant, amount, date
- **Renewal alerts** — subscriptions expiring or renewing within 7 days
- **Annual renewal reminders** — surfaced 30 days ahead
- New clusters discovered
- Unsubscribe recommendations
- Anomalies (e.g., unusual spike from a sender)
- Monthly learning report: what the model learned, which labels grew/shrank, new patterns detected

#### Daily Digest Structure (Telegram)

```
📬 Inbox Summary — Apr 5
━━━━━━━━━━━━━━━━━━━━
Must Read (3): ...
AI & Tech (5 new): ...

💳 Recent Charges
• AWS — $47.30 (Apr 4)
• Notion — $16.00 (Apr 5)

🔔 Upcoming Renewals
⚠️  Adobe CC — renews in 2 days ($54.99)
📅  GitHub Pro — renews in 6 days ($4.00)

📦 30-Day Reminder
• AWS Annual — renews May 3 ($299.00)

🗑️ Unsubscribe (2 candidates): ...
```

#### Telegram Bot Commands

| Command | Description |
|---|---|
| `/today` | Show today's must-reads |
| `/unsubscribe` | List unsubscribe candidates |
| `/clusters` | Show current label breakdown |
| `/learn` | Trigger a manual learning cycle |
| `/report` | Generate the monthly learning summary |
| `/spend` | Recent purchases in the last 7 days with total |
| `/renewals` | All subscriptions renewing in the next 30 days |
| `/subscriptions` | Full active subscription list with amounts and dates |

---

## Auto-Learning System

This is the core differentiator. The system is not static — it continuously refines its classification model based on observed patterns and implicit user feedback.

### Learning Cadence

| Cycle | What Happens |
|---|---|
| **Daily** | Log every classification decision (email → label, confidence score) to the learning store |
| **Weekly** | Detect drift: are new senders dominating a cluster? Any cluster growing unusually fast? Flag for review |
| **Monthly** | Full retraining cycle — re-cluster the last 30 days of email, compare against current labels, propose label additions/merges/splits, update classifier weights |

### Signals Used for Learning

- **Volume trends** — which senders/domains are increasing over time
- **Subject line patterns** — recurring keywords that suggest a new cluster
- **Time-of-day patterns** — transactional emails vs. newsletter sends
- **User engagement signals** — which Telegram commands the user runs, which must-reads they acknowledge vs. ignore (implicit feedback)
- **New topic emergence** — e.g., if AI tool launch emails spike in a month, auto-create or reinforce `AI & Tech Intelligence` label

### AI & Tech Context Awareness

The user is entering a period of heavy AI engagement — evaluating tools, systems, and processes. The learning system should:
- Give elevated weight to AI/ML/LLM-related email clusters
- Surface patterns in what AI tools, newsletters, or research sources the user is receiving
- Proactively suggest: "You're now receiving emails from 8 new AI tool sources — should I create a sub-label `AI Tools` under `AI & Tech Intelligence`?"
- In the monthly report, highlight AI-related systems and workflows the user is being exposed to, as a signal for tools/processes worth adopting

### Monthly Learning Report (via Telegram)

Sent on the 1st of each month, includes:
1. **Inbox snapshot** — total volume, breakdown by label, growth vs. prior month
2. **New patterns detected** — senders or topics that emerged this month
3. **Label health** — labels that have grown stale or ballooned
4. **AI & Tech digest** — summary of AI tools, frameworks, and trends detected in emails this month, with a suggested "worth exploring" shortlist
5. **Unsubscribe progress** — how many senders were cleaned up, inbox noise reduction %
6. **Model confidence** — how confident the classifier was this month, which emails were ambiguous

---

## Technical Architecture

### Gmail Access
- **Gmail MCP tool** (`mcp__claude_ai_Gmail__*`) for reading, searching, labeling
- OAuth-authenticated access

### Classification Engine
- Claude-based classifier: reads subject + sender + snippet
- Embeddings for semantic similarity clustering
- Keyword rules for seed categories as a bootstrap
- Monthly retraining updates classifier priors

### Learning Store
- SQLite database tracking:
  - Every classification decision (email_id, label, confidence, timestamp)
  - Sender engagement history
  - Cluster size over time (for trend detection)
  - User feedback signals from Telegram interactions
  - **`expenses` table** — extracted purchases (merchant, amount, currency, date, email_id)
  - **`subscriptions` table** — tracked subscriptions (service, amount, billing_cycle, renewal_date, expiry_date, status)

### Scheduler
- Daily cron (`CronCreate`) — full pipeline: fetch → classify → label → score → notify
- Weekly cron — drift detection
- Monthly cron (1st of month) — retraining + monthly report

### Notification Layer
- Telegram Bot API for digests, commands, and alerts
- Optional: iOS/Android push via lightweight webhook

---

## Key Design Principles

- **Autonomous by default** — no manual curation required day-to-day
- **Continuously learning** — the system gets smarter every month, not just at setup
- **Context-aware** — adapts to the user's current focus areas (e.g., AI tools in this phase)
- **Non-destructive** — never delete emails; only label and archive
- **Transparent** — always explains what it learned and why, via monthly reports
- **Low-friction feedback** — user corrections via simple Telegram commands, no dashboards required

---

## Project Structure

```
GmailOrganization/
├── CLAUDE.md                        # Project bible (this file)
├── .env.example                     # Environment variable template
├── requirements.txt                 # Python dependencies
├── .gitignore
│
├── config/
│   ├── labels.yaml                  # Seed label definitions + keywords
│   ├── scoring_rules.yaml           # Must Read / Skim / Skip rules
│   └── settings.yaml                # Global settings (cron times, thresholds)
│
├── pipeline/
│   ├── orchestrator.py              # Daily pipeline entry point
│   ├── fetcher.py                   # Gmail fetch + pagination
│   ├── classifier.py                # Claude-based classifier
│   ├── labeler.py                   # Label creation + application
│   └── scorer.py                    # Reading priority scoring
│
├── learning/
│   ├── store.py                     # SQLite read/write layer
│   ├── drift_detector.py            # Weekly drift detection
│   ├── retrainer.py                 # Monthly retraining cycle
│   ├── reporter.py                  # Monthly report generator
│   └── db/                          # (gitignored) live SQLite database
│
├── expenses/
│   ├── extractor.py                 # Claude-based parser: extract purchase/renewal data from emails
│   ├── tracker.py                   # Read/write expenses + subscriptions tables in SQLite
│   └── renewal_alerts.py            # Generate renewal alert list for daily digest
│
├── notifications/
│   ├── bot.py                       # Telegram bot + command handlers (/spend, /renewals, /subscriptions)
│   ├── daily_digest.py              # Daily digest formatter (includes charges + renewal section)
│   └── monthly_report.py            # Monthly report formatter
│
├── scheduler/
│   ├── daily.py                     # Daily trigger (07:00)
│   ├── weekly.py                    # Weekly drift check (Monday)
│   └── monthly.py                   # Monthly retraining (1st of month)
│
├── utils/
│   ├── gmail_client.py              # Gmail API wrapper
│   ├── claude_client.py             # Anthropic SDK wrapper
│   └── logger.py                    # Centralized logging
│
├── tests/
│   ├── test_classifier.py
│   ├── test_scorer.py
│   └── fixtures/                    # Sample emails for testing
│
└── logs/                            # (gitignored) runtime logs
    ├── daily/
    ├── weekly/
    └── monthly/
```

> New modules (e.g., `unsubscriber/`, `knowledge_base/`) should be added as top-level folders following the same pattern.

---

## Setup From Scratch

Follow these steps after cloning the repo to get the full system running.

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment variables
```bash
cp .env.example .env
# Fill in all values in .env
```

Required values:
| Variable | How to get it |
|---|---|
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` | Google Cloud Console → OAuth 2.0 credentials |
| `GMAIL_REFRESH_TOKEN` | Run OAuth flow once; store the refresh token |
| `ANTHROPIC_API_KEY` | console.anthropic.com |
| `TELEGRAM_BOT_TOKEN` | Create a bot via @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | Send a message to your bot, then call `getUpdates` to find your chat ID |

### 3. Run the one-time Gmail OAuth flow
```bash
python scripts/setup_oauth.py
```
This opens a browser for Google sign-in and prints your `GMAIL_REFRESH_TOKEN`. Copy it into `.env`.

### 4. Test the Gmail connection
```bash
python scripts/test_connection.py
```
Should print your labels and 3 recent emails. If it works, OAuth is set up correctly.

### 5. Initialize the learning database
```bash
python -c "from learning.store import init_db; init_db()"
```

### 6. Run the daily pipeline manually (first test)
```bash
python -m pipeline.orchestrator
```

### 5. Start the Telegram bot
```bash
python -m notifications.bot
```

### 6. Start the scheduler (all three cadences)
```bash
python -m scheduler.daily &
python -m scheduler.weekly &
python -m scheduler.monthly &
```

### 7. Verify logs
```bash
tail -f logs/daily/$(date +%Y-%m-%d).log
```

---

## Future Extensions

- Auto-unsubscribe flow (clicking unsubscribe links automatically)
- Weekly rollup report
- Priority inbox integration
- Cross-account support (multiple Gmail accounts)
- Smart reply suggestions for must-read emails
- Integration with Notion/Obsidian to log AI tool discoveries from emails into a personal knowledge base
- Monthly spend report — total by merchant, by category, vs. prior month
- Configurable charge alert threshold (notify only above ₹X / $X)
- Currency normalization across USD/INR/EUR charges
- Export subscriptions to CSV / Google Sheets for budget review
