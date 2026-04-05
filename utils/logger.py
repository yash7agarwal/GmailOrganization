import logging
import os
import uuid
from datetime import datetime

_run_id = None


def get_run_id() -> str:
    global _run_id
    if _run_id is None:
        _run_id = uuid.uuid4().hex[:8]
    return _run_id


def get_logger(name: str, log_dir: str = "logs/daily") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"{datetime.now().strftime('%Y-%m-%d')}.log")

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured — don't add duplicate handlers

    logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    fmt = logging.Formatter(
        f"%(asctime)s [%(levelname)s] %(name)s run={get_run_id()}: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger
