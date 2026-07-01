# Auth utilities — Orange Lab Microbiology CDSS
# Pure stdlib (no Streamlit) so it can be unit-tested and reused by the
# password-hash generator CLI.

import hmac
import hashlib
import logging
import secrets as _secrets

logger = logging.getLogger("orange_lab.auth")

PBKDF2_ITERATIONS = 200_000


def hash_password(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    """Return a self-describing hash: pbkdf2_sha256$iters$salt_hex$hash_hex."""
    salt = _secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verification against a stored pbkdf2_sha256 hash."""
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"),
            bytes.fromhex(salt_hex), int(iters),
        )
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception as exc:
        logger.warning("verify_password: bad stored hash: %s", exc)
        return False
