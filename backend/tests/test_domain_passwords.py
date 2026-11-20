"""Тесты хэширования паролей.

`NODE_HASH_FOR_SECRET` сгенерирован реальным `backend/src/passwords.js`
(`hashPassword('secret')`) — подтверждает побитовую совместимость
Python `hashlib.scrypt` с Node `crypto.scryptSync` (см. port-to-python-plan.md §4.4).
"""

from app.domain.passwords import hash_password, verify_password

NODE_HASH_FOR_SECRET = (
    "7ba3b12141adddef96d03a419cdc1890:"
    "41b6765c9449a9921edcf23b67c9ed3d9b7e62f39fca0038a5e7351cfa3aee76"
)


def test_verifies_hash_produced_by_node_implementation():
    assert verify_password("secret", NODE_HASH_FOR_SECRET)


def test_rejects_wrong_password_against_node_hash():
    assert not verify_password("wrong", NODE_HASH_FOR_SECRET)


def test_hash_and_verify_roundtrip():
    hashed = hash_password("hunter2")
    assert verify_password("hunter2", hashed)
    assert not verify_password("hunter3", hashed)


def test_hash_password_is_salted():
    assert hash_password("hunter2") != hash_password("hunter2")


def test_verify_password_handles_malformed_stored_value():
    assert not verify_password("secret", "not-a-valid-hash")
    assert not verify_password("secret", "")
