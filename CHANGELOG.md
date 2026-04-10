# Changelog

All notable changes are documented here following [Semantic Versioning](https://semver.org/).

## [0.4.4] — 2026-04-11
### Added
- `memory/issues_log.jsonl` — initialized for the cross-project self-healing system; receives eval pass/fail entries and known-issue patterns from `/post-task-eval` and `/self-heal` skills

## [0.4.3] — 2026-04-07
### Fixed
- Telegram Markdown parse errors in daily digest: added plain-text fallback that strips `*`, `_`, `` ` `` when Markdown send fails

## [0.4.2] — 2026-04-05
### Added
- Full project README with architecture diagram, setup guide, and command reference

## [0.4.1] — 2026-04-05
### Fixed
- Python 3.9 compatibility: added `from __future__ import annotations` across all modules

## [0.4.0] — 2026-04-05
### Added
- Auto-healing system with fallback error responses on all bot handlers
- Interaction logging to `bot_interactions` table for every command call
- `bot_healer.py` for process monitoring and auto-restart

## [0.3.0] — 2026-04-05
### Added
- Expense tracking: extracts purchases and charges from emails via Claude
- Subscription renewal monitoring with 7-day alert window
- Bot commands: `/spend`, `/renewals`, `/subscriptions`
- `expenses` and `subscriptions` tables in SQLite learning store
- `expenses/extractor.py`, `expenses/tracker.py`, `expenses/renewal_alerts.py`

## [0.2.0] — 2026-04-05
### Added
- Expense tracking and subscription renewal monitoring to project spec
- `CLAUDE.md` updated with full financial monitoring architecture

## [0.1.0] — 2026-04-05
### Added
- Autonomous Gmail inbox organisation with Claude-powered classification
- Daily pipeline: fetch → classify → label → score → notify
- Reading priority scoring (Must Read / Skim / Skip)
- Telegram bot with `/today`, `/clusters`, `/unsubscribe`, `/learn`, `/report` commands
- Auto-learning system with daily/weekly/monthly cadence
- SQLite learning store with classification history and sender stats
- APScheduler for daily, weekly, and monthly cron jobs
- Unsubscribe candidate detection
