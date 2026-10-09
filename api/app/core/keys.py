import hashlib
import secrets

KEY_PREFIX = "lgw_"
_RANDOM_BYTES = 32
_DISPLAY_PREFIX_LEN = 12


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(_RANDOM_BYTES)


def hash_key(key: str) -> str:
    # A 256-bit random secret needs no slow hash; a fast one keeps the per-request lookup indexed.
    return hashlib.sha256(key.encode()).hexdigest()


def key_prefix(key: str) -> str:
    return key[:_DISPLAY_PREFIX_LEN]
