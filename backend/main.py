import asyncio
import logging
import time
from uuid import uuid4
import httpx
from google.genai.errors import APIError
from pydantic import ValidationError
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from .gemini import InvalidSetting, NotConfigured, generate_turn
from .schemas import TurnRequest, TurnResponse

app = FastAPI(title="Mingle local Gemini experiment")
logger = logging.getLogger("uvicorn.error.mingle.chat")


def log_failure(error: Exception, trace: str, started: float):
    # 예외 원문·traceback·제공자 body에는 키/프롬프트/입력이 있을 수 있다.
    # 고정 분류와 숫자 상태만 기록하고 클라이언트 requestId도 사용하지 않는다.
    code = error.code if isinstance(error, APIError) and type(error.code) is int else None
    if isinstance(error, NotConfigured):
        category = "not_configured"
    elif isinstance(error, InvalidSetting):
        category = "invalid_setting"
    elif isinstance(error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)):
        category = "timeout"
    elif isinstance(error, APIError):
        category = {400: "invalid_request", 401: "authentication", 403: "permission",
                    404: "model_not_found", 429: "quota", 503: "provider_unavailable",
                    504: "provider_timeout"}.get(code, "provider_error")
    elif isinstance(error, httpx.TransportError):
        category = "network"
    elif isinstance(error, ValidationError):
        category = "output_validation"
    else:
        category = "internal_error"
    logger.warning("gemini failure trace=%s category=%s upstream_http=%s elapsed_ms=%d",
                   trace, category, code, (time.monotonic() - started) * 1000)


@app.exception_handler(RequestValidationError)
async def invalid_request(_request: Request, _error: RequestValidationError):
    # Pydantic 기본 오류에 포함되는 입력 원문을 반환하지 않는다.
    return JSONResponse(status_code=422, content={"detail": "입력·선택지·턴·대화 맥락을 확인해 주세요."})


@app.post("/api/chat/turn", response_model=TurnResponse)
async def chat_turn(request: TurnRequest):
    trace, started = uuid4().hex, time.monotonic()
    try:
        response = await generate_turn(request)
        logger.info("gemini success trace=%s elapsed_ms=%d", trace, (time.monotonic() - started) * 1000)
        return response
    except NotConfigured as error:
        log_failure(error, trace, started)
        raise HTTPException(503, "backend/.env의 GEMINI_API_KEY 값이 없거나 비어 있어요. 키를 입력한 뒤 다시 시도해 주세요.") from None
    except InvalidSetting as error:
        log_failure(error, trace, started)
        raise HTTPException(503, "backend/.env의 GEMINI_THINKING_LEVEL 값은 low만 사용할 수 있어요. 값을 고치거나 항목을 지운 뒤 다시 시도해 주세요.") from None
    except (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException) as error:
        log_failure(error, trace, started)
        raise HTTPException(504, "AI 응답 시간이 초과됐어요. 다시 시도해 주세요.") from None
    except Exception as error:
        log_failure(error, trace, started)
        raise HTTPException(502, "AI 응답을 불러오지 못했어요. 다시 시도해 주세요.") from None
