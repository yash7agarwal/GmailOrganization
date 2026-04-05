import schedule
import time
from datetime import datetime

import yaml
from utils.logger import get_logger
from scheduler.daily import _get_last_run, _update_last_run

logger = get_logger(__name__, log_dir="logs/weekly")


def weekly_job() -> None:
    try:
        logger.info("Weekly job starting")
        from learning.drift_detector import detect_drift
        from learning.store import take_cluster_snapshot, get_label_counts_by_day

        drift_result = detect_drift()
        logger.info(f"Drift result: {drift_result.get('summary', 'no summary')}")

        # Snapshot current cluster counts
        counts = get_label_counts_by_day(days=7)
        label_totals = {label: sum(d.values()) for label, d in counts.items()}
        take_cluster_snapshot(label_totals)
        logger.info(f"Cluster snapshot saved: {label_totals}")

        _update_last_run("weekly")
    except Exception as e:
        logger.error(f"Weekly job failed: {e}")


def schedule_weekly() -> None:
    try:
        with open("config/settings.yaml") as f:
            settings = yaml.safe_load(f)
        run_day = settings.get("scheduler", {}).get("weekly_run_day", "monday")
    except Exception:
        run_day = "monday"

    # Catch-up: run if last weekly was more than 7 days ago
    last = _get_last_run("weekly")
    if last:
        from datetime import timedelta
        last_dt = datetime.fromisoformat(last)
        if (datetime.utcnow() - last_dt).days >= 7:
            logger.info("Missed weekly run detected — running catch-up now")
            weekly_job()

    getattr(schedule.every(), run_day).at("08:00").do(weekly_job)
    logger.info(f"Weekly drift check scheduled on {run_day} at 08:00")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    schedule_weekly()
