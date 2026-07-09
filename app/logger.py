import logging
import logging.config
import sys
from pathlib import Path

import yaml
from rich.logging import RichHandler

from app.config import config

# Rich wraps records at the console width (80 columns when stdout is not a
# TTY), splitting one record across multiple lines in collected deploy logs.
PLAIN_LOG_FORMAT = "%(levelname)s %(name)s - %(message)s"


def should_use_rich_logs() -> bool:
    return sys.stdout.isatty()


# Load logging configuration from YAML file if it exists
log_config_path = Path(__file__).parent.parent / "log_conf.yaml"
if log_config_path.exists():
    with open(log_config_path) as f:
        log_config = yaml.safe_load(f)

    if not should_use_rich_logs():
        for formatter in log_config["formatters"].values():
            formatter["format"] = PLAIN_LOG_FORMAT
        for name, handler in log_config["handlers"].items():
            log_config["handlers"][name] = {
                "class": "logging.StreamHandler",
                "formatter": handler["formatter"],
                "stream": "ext://sys.stdout",
            }

    logging.config.dictConfig(log_config)

    # Set the log level from config after loading the YAML
    log_level = getattr(logging, config.LOG_LEVEL)
    logging.root.setLevel(log_level)

    # Also set level for specific loggers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "app"]:
        logging.getLogger(logger_name).setLevel(log_level)
else:
    # Fallback logging if YAML file doesn't exist
    if should_use_rich_logs():
        fallback_handler: logging.Handler = RichHandler(
            rich_tracebacks=False,
            show_time=False,
            show_level=False,
            show_path=False,
            markup=False,
        )
    else:
        fallback_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[fallback_handler],
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


logger = get_logger(__name__)


def configure_uvicorn_loggers() -> None:
    """Configure uvicorn loggers to use our handlers after uvicorn has started.

    This must be called after uvicorn initializes its loggers (e.g., in app lifespan).
    """
    # Replace uvicorn.access default handlers so formatting matches our other logs
    uvicorn_access = logging.getLogger("uvicorn.access")
    if uvicorn_access.handlers:
        uvicorn_access.handlers.clear()
        if should_use_rich_logs():
            handler: logging.Handler = RichHandler(
                rich_tracebacks=False,
                show_time=False,
                show_level=True,
                show_path=False,
                markup=False,
            )
            handler.setFormatter(logging.Formatter("%(name)s - %(message)s"))
        else:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(PLAIN_LOG_FORMAT))
        uvicorn_access.addHandler(handler)
