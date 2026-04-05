# Gmail Organization Project

## Project Purpose

Autonomously organize a Gmail inbox using intelligent email clustering, label management, reading priority scoring, unsubscribe detection, and Telegram/mobile notifications — with a **continuous auto-learning loop** that evolves its understanding of the user's inbox patterns month over month.

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

Beyond seeds, the system **auto-discovers** new clusters based on sender patterns, subject line similarity, and email frequency — then proposes and creates new labels dynamically.

### 2. Daily Run Loop

Every day the system should:
1. Fetch new/unlabeled emails
2. Classify each email into an existing or new cluster using the current model
3. Create any new Gmail labels that are needed
4. Apply labels to emails
5. Score each email for reading priority
6. Log classification decisions to the learning store
7. Send a daily digest notification via Telegram

### 3. Reading Priority Scoring

After clustering, evaluate each email and produce a tiered output:

- **Must Read** — Emails requiring action, personal messages, important alerts, high-signal AI/tech updates
- **Skim** — Useful content but low urgency (newsletters, some promotions)
- **Skip / Auto-Archive** — Purely promotional, mass-sent, or duplicate content

Delivered as part of the daily Telegram notification.

### 4. Unsubscribe Detection

A dedicated label `Unsubscribe Candidates` is maintained for emails where:
- The user has never clicked or replied
- Sender volume is high (more than N emails/month)
- Content matches promotional/marketing patterns

Daily report includes a list of domains/senders to unsubscribe from.

### 5. Telegram / Mobile Notifications

Communicate with the user via Telegram to report:
- Daily summary: total emails received, breakdown by cluster, must-read count
- New clusters discovered
- Unsubscribe recommendations
- Anomalies (e.g., unusual spike from a sender)
- Monthly learning report: what the model learned, which labels grew/shrank, new patterns detected

The Telegram bot accepts commands:
- `today` — show must-reads
- `unsubscribe` — list unsubscribe candidates
- `clusters` — show current label breakdown
- `learn` — trigger a manual learning cycle
- `report` — generate the monthly learning summary

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
├── notifications/
│   ├── bot.py                       # Telegram bot + command handlers
│   ├── daily_digest.py              # Daily digest formatter
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
