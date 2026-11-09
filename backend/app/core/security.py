"""비밀번호 해싱, 개인 코드, 관리자 JWT 유틸리티."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.core.config import settings

PBKDF2_ITERATIONS = 260_000
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 혼동되는 0/O/1/I 제외


# --------------------------------------------------------------------------- #
# 비밀번호
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return secrets.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# 개인 코드 (회원가입 없는 대화 이어하기)
# --------------------------------------------------------------------------- #
def normalize_personal_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def generate_personal_code(prefix: str = "COMP") -> str:
    blocks = ["".join(secrets.choice(_CODE_ALPHABET) for _ in range(4)) for _ in range(2)]
    return f"{prefix}-{blocks[0]}-{blocks[1]}"


def hash_personal_code(code: str) -> str:
    normalized = normalize_personal_code(code)
    return hashlib.sha256(f"{settings.secret_key}:{normalized}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# 관리자 JWT
# --------------------------------------------------------------------------- #
def create_access_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
