import logging
import sys

from app.core.config import Settings


def configure_logging(settings: Settings) -> None:
    """统一标准输出日志格式；容器内由采集侧负责 JSON 化。"""
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        force=True,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
