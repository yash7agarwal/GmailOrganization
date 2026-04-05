import schedule
import time
from datetime import datetime

import yaml
from utils.logger import get_logger
from scheduler.daily import _get_last_run, _update_last_run

logger = get_logger(__name__, log_dir="logs/monthly")


def _check_and_run_monthly() -> None:
    if datetime.utcnow().day != 1:
        return
    monthly_job()


def monthly_job() -> None:
    try:
        logger.info("Monthly job starting")
        from learning.retrainer import run_monthly_retraining
        from learning.reporter import generate_monthly_report

        retraining_result = run_monthly_retraining()
        logger.info(f"Retraining complete: {retraining_result}")

        report = generate_monthly_report()

        import asyncio
        import os
        from telegram import Bot
        from notifications.monthly_report import send_monthly_report

        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if token:
            bot = Bot(token=token)
            asyncio.run(send_monthly_report(report, bot))

        _update_last_run("monthly")
    except Exception as e:
        logger.error(f"Monthly job failed: {e}")


def schedule_monthly() -> None:
    # Run the check daily at 06:00; the job itself only fires on day 1
    schedule.every().day.at("06:00").do(_check_and_run_monthly)
    logger.info("Monthly retraining scheduled (runs on 1st of each month at 06:00)")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    schedule_monthly()
