"""Хэширование паролей: scrypt + соль, строка `saltHex:hashHex`.

Порт `backend/src/passwords.js`. Те же параметры scrypt (N=16384, r=8, p=1,
maxmem=64MiB) и тот же формат хранения — `hashlib.scrypt` даёт побитово
идентичный результат Node `crypto.scryptSync`, поэтому существующие хэши
паролей (если БД переносится, а не создаётся заново) остаются валидными.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

_N = 16384
_R = 8
_P = 1
_MAXMEM = 64 * 1024 * 1024
_DKLEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=_DKLEN
    )
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, AttributeError):
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_N,
        r=_R,
        p=_P,
        maxmem=_MAXMEM,
        dklen=len(expected),
    )
    return hmac.compare_digest(expected, actual)
