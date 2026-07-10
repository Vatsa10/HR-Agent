"""
Password hashing (scrypt) and register/login helpers on top of db.py.
"""

import hashlib
import hmac
import secrets

import db

_N, _R, _P = 16384, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        scheme, salt_hex, hash_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        h = hashlib.scrypt(
            pw.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P
        )
        return hmac.compare_digest(h.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def register(email: str, password: str) -> str:
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    user_id = db.create_user(email, hash_password(password))
    return db.create_session(user_id)


def login(email: str, password: str) -> str:
    user = db.get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        raise ValueError("invalid credentials")
    return db.create_session(user["id"])
