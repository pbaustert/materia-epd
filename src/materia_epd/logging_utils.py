"""Logging utilities for materia_epd package."""

import logging
import logging.config
from pathlib import Path

import structlog

logger = structlog.wrap_logger(logging.getLogger(__name__))

PACKAGE_NAME = "materia_epd"


# AI enhanced from LIST coding patterns
def setup_logging(
    verbose: bool,
    output_folder: Path | None = None,
) -> None:
    """
    Configure logging for the materia_epd package.

    Sets up two handlers:
    - Console handler for terminal output
    - JSON file handler for structured logging to file

    The logger is configured to only target this package and its children,
    not parent loggers.

    :param verbose: Controls the console log level:
                    - True: DEBUG level
                    - False: WARNING level
                    The JSON file handler always logs at DEBUG level.
    :param output_folder: Directory where the JSON log file will be stored.
                          Defaults to current working directory if not provided.
    """
    # Determine console log level based on verbose flag
    if verbose:
        console_level = logging.DEBUG
    else:
        console_level = logging.INFO

    # Set up output folder
    if output_folder is None:
        output_folder = Path.cwd()
    else:
        output_folder = Path(output_folder)

    output_folder.mkdir(parents=True, exist_ok=True)
    log_file_path = output_folder / "materia_epd.log.json"

    # Structlog processors shared between formatters
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    # Configure logging with dictConfig
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "console": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.dev.ConsoleRenderer(colors=True),
                    "foreign_pre_chain": shared_processors,
                },
                "json": {
                    "()": structlog.stdlib.ProcessorFormatter,
                    "processor": structlog.processors.JSONRenderer(),
                    "foreign_pre_chain": shared_processors,
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "console",
                    "level": console_level,
                    "stream": "ext://sys.stdout",
                },
                "json_file": {
                    "class": "logging.FileHandler",
                    "filename": str(log_file_path),
                    "formatter": "json",
                    "mode": "w",
                    "level": logging.DEBUG,
                },
            },
            "loggers": {
                PACKAGE_NAME: {
                    "handlers": ["console", "json_file"],
                    "level": logging.DEBUG,
                    "propagate": False,
                },
            },
        }
    )

    # Configure structlog
    structlog.configure(
        processors=shared_processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
    logger.info(
        f"Verbose mode: {verbose}, console level:"
        f" {'INFO' if console_level == 20 else 'DEBUG'}, Log file level: DEBUG.\n "
        f"Log files stored in {str(log_file_path)}"
    )
