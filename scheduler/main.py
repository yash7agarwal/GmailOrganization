"""
Unified scheduler entry point.
Runs daily, weekly, and monthly jobs in a single process.

Usage:
    python -m scheduler.main
"""

import os
import schedule
import time
from datetime import datetime

import yaml
from dotenv import load_dotenv

from scheduler.daily import daily_job, _get_last_run, _update_last_run
from scheduler.weekly import weekly_job
from scheduler.monthly import _check_and_run_monthly
from utils.logger import get_logger

load_dotenv()
logger = get_logger("scheduler.main")


def _load_settings() -> dict:
    try:
        with open("config/settings.yaml") as f:
            return yaml.safe_load(f)
    except Exception:
        return {}


def main() -> None:
    settings = _load_settings()
    sched = settings.get("scheduler", {})

    daily_time = sched.get("daily_run_time", "07:00")
    weekly_day = sched.get("weekly_run_day", "monday")

    # Catch-up runs on startup
    today = datetime.utcnow().strftime("%Y-%m-%d")
    last_daily = _get_last_run("daily")
    if not last_daily or not last_daily.startswith(today):
        logger.info("Catch-up: running daily job now")
        daily_job()

    last_weekly = _get_last_run("weekly")
    if last_weekly:
        from datetime import timedelta
        if (datetime.utcnow() - datetime.fromisoformat(last_weekly)).days >= 7:
            logger.info("Catch-up: running weekly job now")
            weekly_job()

    # Register schedules
    schedule.every().day.at(daily_time).do(daily_job)
    getattr(schedule.every(), weekly_day).at("08:00").do(weekly_job)
    schedule.every().day.at("06:00").do(_check_and_run_monthly)

    logger.info(
        f"Scheduler running — daily={daily_time}, weekly={weekly_day}@08:00, monthly=1st@06:00"
    )

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
