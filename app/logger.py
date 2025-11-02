import logging
import logging.config
from pathlib import Path

import yaml
from rich.logging import RichHandler

from app.config import config

# Load logging configuration from YAML file if it exists
log_config_path = Path(__file__).parent.parent / "log_conf.yaml"
if log_config_path.exists():
    with open(log_config_path) as f:
        log_config = yaml.safe_load(f)
        logging.config.dictConfig(log_config)

    # Set the log level from config after loading the YAML
    log_level = getattr(logging, config.LOG_LEVEL)
    logging.root.setLevel(log_level)

    # Also set level for specific loggers
    for logger_name in ["uvicorn", "uvicorn.error", "uvicorn.access", "fastapi", "app"]:
        logging.getLogger(logger_name).setLevel(log_level)
else:
    # Fallback to Rich logging if YAML file doesn't exist
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            RichHandler(
                rich_tracebacks=False,
                show_time=False,
                show_level=False,
                show_path=False,
                markup=False,
            )
        ],
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


logger = get_logger(__name__)


def configure_uvicorn_loggers() -> None:
    """Configure uvicorn loggers to use RichHandler after uvicorn has started.

    This must be called after uvicorn initializes its loggers (e.g., in app lifespan).
    """
    # Force uvicorn.access to use RichHandler and remove its default handlers
    # This ensures consistent formatting across all logs
    uvicorn_access = logging.getLogger("uvicorn.access")
    if uvicorn_access.handlers:
        uvicorn_access.handlers.clear()
        rich_handler = RichHandler(
            rich_tracebacks=False,
            show_time=False,
            show_level=True,
            show_path=False,
            markup=False,
        )
        # Use a simple formatter that matches our other logs
        formatter = logging.Formatter("%(name)s - %(message)s")
        rich_handler.setFormatter(formatter)
        uvicorn_access.addHandler(rich_handler)
