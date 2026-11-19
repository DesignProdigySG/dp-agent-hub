"""Secrets at rest, the admin password, and signed session cookies.

* A Fernet master key (HUB_SECRET_KEY, or a key generated once into data_dir/secret.key with
  0600 permissions) encrypts secret settings in the database.
* The admin password is stored as a scrypt hash. Until one exists, the first admin is created
  either from ADMIN_PASSWORD or with a one-time setup code printed to the server log.
* Sessions are HMAC-signed cookies (HttpOnly, SameSite=Strict). Changing the password
  invalidates every existing session.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, Request, WebSocket

from app.config import get_settings

log = logging.getLogger(__name__)

SESSION_COOKIE = "hub_session"
SESSION_TTL_S = 12 * 3600
ADMIN_HASH_KEY = "_admin_password_hash"  # AppSetting row, never exposed as a field


# --- Master key / encryption ------------------------------------------------------------------

_fernet: Fernet | None = None
_master: bytes | None = None


def _load_master_key() -> bytes:
    global _master
    if _master is None:
        _master = _read_or_create_master_key()
    return _master


def _read_or_create_master_key() -> bytes:
    settings = get_settings()
    if settings.hub_secret_key:
        return settings.hub_secret_key.encode()
    path: Path = settings.data_dir / "secret.key"
    if path.exists():
        return path.read_bytes().strip()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    log.warning("Generated a new encryption key at %s. Back it up (or set HUB_SECRET_KEY): "
                "stored secrets cannot be decrypted without it.", path)
    return key


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        try:
            _fernet = Fernet(_load_master_key())
        except ValueError as e:
            raise RuntimeError("HUB_SECRET_KEY must be a Fernet key (44 url-safe base64 "
                               "characters); generate one with "
                               "`python -c 'from cryptography.fernet import Fernet; "
                               "print(Fernet.generate_key().decode())'`") from e
    return _fernet


def reset_keys() -> None:
    """Forget cached keys, the setup code and login throttling (tests)."""
    global _fernet, _master, _setup_code
    _fernet = _master = _setup_code = None
    _failures.clear()


def encrypt(plaintext: str) -> str:
    return fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("A stored secret could not be decrypted; the encryption key changed. "
                           "Restore the old key or re-enter the secret in Settings.") from e


# --- Password hashing (scrypt, stdlib) --------------------------------------------------------

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    b64 = base64.b64encode
    return f"scrypt${_N}${_R}${_P}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n),
                                r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def check_password_strength(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(422, "Use at least 8 characters for the admin password")


# --- Sessions -----------------------------------------------------------------------------

def _session_key() -> bytes:
    return hashlib.sha256(_load_master_key() + b"|session").digest()


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]


def make_session(password_hash: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(
        {"exp": int(time.time()) + SESSION_TTL_S, "fp": _fingerprint(password_hash)}
    ).encode()).decode()
    sig = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def session_valid(token: str | None, password_hash: str | None) -> bool:
    if not token or not password_hash or "." not in token:
        return False
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(_session_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return False
    return data.get("exp", 0) > time.time() and data.get("fp") == _fingerprint(password_hash)


# --- Signed action links (approve / reject from an emailed link) -------------------------------

def _link_key() -> bytes:
    return hashlib.sha256(_load_master_key() + b"|action-link").digest()


def sign_link(data: dict, ttl_s: int) -> str:
    """A URL-safe token carrying `data`, valid for `ttl_s` seconds."""
    payload = base64.urlsafe_b64encode(json.dumps(
        {**data, "exp": int(time.time()) + ttl_s}, separators=(",", ":")).encode()).decode()
    sig = hmac.new(_link_key(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_link(token: str | None) -> dict | None:
    """The data in a link token, or None if it is forged, malformed or expired."""
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(_link_key(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("exp", 0) > time.time() else None


# --- First-run setup code ---------------------------------------------------------------------

_setup_code: str | None = None


def setup_code() -> str:
    """One-time code that authorises creating the first admin (printed to the server log)."""
    global _setup_code
    if _setup_code is None:
        _setup_code = "-".join(secrets.token_hex(2).upper() for _ in range(3))
        log.warning("No admin password is set. First-run setup code: %s "
                    "(enter it in the browser to create the admin password)", _setup_code)
    return _setup_code


def consume_setup_code(code: str) -> bool:
    global _setup_code
    ok = _setup_code is not None and hmac.compare_digest(code.strip().upper(), _setup_code)
    if ok:
        _setup_code = None
    return ok


# --- Login throttling ---------------------------------------------------------------------

_failures: dict[str, deque[float]] = defaultdict(deque)


def throttle(ip: str, limit: int = 5, window_s: float = 300) -> None:
    q = _failures[ip]
    now = time.monotonic()
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Too many failed attempts. Try again in a few minutes.")


def record_failure(ip: str) -> None:
    _failures[ip].append(time.monotonic())


# --- FastAPI dependencies -----------------------------------------------------------------

def _admin_hash() -> str | None:
    from app.settings_store import get_store

    return get_store().admin_hash()


def is_admin(conn: Request | WebSocket) -> bool:
    return session_valid(conn.cookies.get(SESSION_COOKIE), _admin_hash())


def require_admin(request: Request) -> None:
    if not is_admin(request):
        raise HTTPException(401, "Sign in as admin to do this")


def require_viewer(request: Request) -> None:
    if not (get_settings().public_read_access or is_admin(request)):
        raise HTTPException(401, "Sign in to view the hub")


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
