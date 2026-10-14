"""Owner login: scrypt password hashes and signed tokens for sessions, email links and resets (stdlib only)."""
import base64
import hashlib
import hmac
import os
import secrets
import time

from dotenv import load_dotenv

load_dotenv()
SECRET = (os.getenv("SECRET_KEY") or secrets.token_hex(32)).encode()  # set SECRET_KEY so logins survive restarts
COOKIE = "session"
MAX_AGE = 7 * 24 * 3600
_N, _R, _P = 2**14, 8, 1


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calc.hex(), h)
    except Exception:
        return False


def temp_password() -> str:
    return secrets.token_urlsafe(9)


def fingerprint(password_hash: str) -> str:
    """Ties a reset link to the current password, so it stops working once the password changes."""
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def make_token(biz_id: str, purpose: str = "session", ttl: int = MAX_AGE, extra: str = "") -> str:
    payload = "|".join([purpose, biz_id, str(int(time.time()) + ttl), extra])
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode().rstrip("=")


def read_token(token: str, purpose: str = "session"):
    """Returns (biz_id, extra) or None."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode()
        payload, sig = raw.rsplit("|", 1)
        good = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        p, biz_id, exp, extra = payload.split("|")
        if hmac.compare_digest(sig, good) and p == purpose and int(exp) > time.time():
            return biz_id, extra
    except Exception:
        pass
    return None
