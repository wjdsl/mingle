"""Personal info masking utilities."""

from __future__ import annotations

import re

_PHONE = re.compile(r"(?<!\d)(?:\+?82[- ]?)?0\d{1,2}[- .]?\d{3,4}[- .]?\d{4}(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONG_DIGITS = re.compile(r"\d{6,}")


def mask_personal_info(text: str) -> str:
    text = _EMAIL.sub("[\uc774\uba54\uc77c \uc0dd\ub7b5]", text)
    text = _PHONE.sub("[\uc5f0\ub77d\ucc98 \uc0dd\ub7b5]", text)
    return _LONG_DIGITS.sub("[\uc22b\uc790 \uc0dd\ub7b5]", text)
