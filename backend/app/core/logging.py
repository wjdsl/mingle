"""간단한 로깅 설정."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


# 원문·키 없이 분류 정보만 남기도록 검토한 로거만 파일에 보존한다.
FAILURE_LOGGERS = ("app.services.llm.gemini_provider", "app.api.routes.story_chat")
_FAILURE_HANDLER_NAME = "llm-failure-file"


def configure_failure_log(path: str, *, max_bytes: int = 1_000_000, backup_count: int = 3) -> Path | None:
    """LLM 실패 로그(WARNING 이상)를 크기 제한 회전 파일에 추가로 남긴다. 경로가 비면 아무것도 하지 않는다."""
    if not path:
        return None
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(target, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
    handler.set_name(_FAILURE_HANDLER_NAME)
    handler.setLevel(logging.WARNING)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"))
    for name in FAILURE_LOGGERS:
        logger = logging.getLogger(name)
        for old in [h for h in logger.handlers if h.get_name() == _FAILURE_HANDLER_NAME]:
            logger.removeHandler(old)
            old.close()
        logger.addHandler(handler)
    return target
