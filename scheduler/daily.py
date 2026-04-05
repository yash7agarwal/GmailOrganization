import json
import os
import schedule
import time
from datetime import datetime

import yaml
from utils.logger import get_logger

logger = get_logger(__name__, log_dir="logs/daily")
LAST_RUN_FILE = "logs/last_run.json"


def _get_last_run(key: str):
    if not os.path.exists(LAST_RUN_FILE):
        return None
    try:
        with open(LAST_RUN_FILE) as f:
            return json.load(f).get(key)
    except Exception:
        return None


def _update_last_run(key: str) -> None:
    os.makedirs("logs", exist_ok=True)
    data = {}
    if os.path.exists(LAST_RUN_FILE):
        try:
            with open(LAST_RUN_FILE) as f:
                data = json.load(f)
        except Exception:
            pass
    data[key] = datetime.utcnow().isoformat()
    with open(LAST_RUN_FILE, "w") as f:
        json.dump(data, f)


def daily_job() -> None:
    try:
        logger.info("Daily job starting")
        from pipeline.orchestrator import run_daily_pipeline

        result = run_daily_pipeline()
        _update_last_run("daily")

        # Send Telegram digest (requires running bot — use send via token directly)
        import asyncio
        from telegram import Bot
        from notifications.daily_digest import send_daily_digest

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            bot = Bot(token=token)
            asyncio.run(send_daily_digest(result, bot))

    except Exception as e:
        logger.error(f"Daily job failed: {e}")


def schedule_daily() -> None:
    try:
        with open("config/settings.yaml") as f:
            settings = yaml.safe_load(f)
        run_time = settings.get("scheduler", {}).get("daily_run_time", "07:00")
    except Exception:
        run_time = "07:00"

    # Catch-up: if last run was not today, run immediately
    last = _get_last_run("daily")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if not last or not last.startswith(today):
        logger.info("Missed daily run detected — running catch-up now")
        daily_job()

    schedule.every().day.at(run_time).do(daily_job)
    logger.info(f"Daily pipeline scheduled at {run_time}")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    schedule_daily()
