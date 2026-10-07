from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from .database import get_session
from .models.auth import AuthSession, LoginThrottle, MfaChallenge, SecurityEvent, User, UserRole


SESSION_COOKIE_NAME = "va_session"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
GENERIC_LOGIN_ERROR = "Invalid email, password, or account state."


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalized_email(value: str) -> str:
    return value.strip().lower()


def validate_password(value: str) -> None:
    if len(value) < 12 or len(value) > 256:
        raise ValueError("Password must be between 12 and 256 characters.")
    if not (any(c.islower() for c in value) and any(c.isupper() for c in value) and any(c.isdigit() for c in value)):
        raise ValueError("Password must include upper-case, lower-case, and numeric characters.")


def hash_password(value: str) -> str:
    validate_password(value)
    return PASSWORD_HASHER.hash(value)


def verify_password(stored_hash: str, candidate: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(stored_hash, candidate)
    except (VerifyMismatchError, InvalidHashError):
        return False


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    raw = os.environ.get("MFA_ENCRYPTION_KEY", "")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as error:
        raise RuntimeError("MFA_ENCRYPTION_KEY is missing or invalid") from error


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("ascii")).decode("ascii")


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("ascii")
    except InvalidToken as error:
        raise RuntimeError("MFA secret cannot be decrypted") from error


def generate_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def totp_code(secret: str, *, at_time: int | None = None) -> str:
    counter = int(at_time if at_time is not None else time.time()) // 30
    padded = secret + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{number:06d}"


def verify_totp(secret: str, code: str, *, at_time: int | None = None) -> bool:
    current = int(at_time if at_time is not None else time.time())
    return any(hmac.compare_digest(totp_code(secret, at_time=current + offset * 30), code) for offset in (-1, 0, 1))


def session_duration() -> timedelta:
    raw = os.environ.get("AUTH_SESSION_HOURS", "12")
    try:
        hours = int(raw)
    except ValueError as error:
        raise RuntimeError("AUTH_SESSION_HOURS must be an integer") from error
    if not 1 <= hours <= 168:
        raise RuntimeError("AUTH_SESSION_HOURS must be between 1 and 168")
    return timedelta(hours=hours)


def cookie_secure() -> bool:
    return os.environ.get("AUTH_COOKIE_SECURE", "true").strip().casefold() not in {"0", "false", "no"}


def record_event(session: Session, event_type: str, *, user_id=None, subject: str | None = None) -> None:
    session.add(SecurityEvent(event_type=event_type, user_id=user_id, subject_hash=token_hash(subject) if subject else None))


def create_user(session: Session, *, email: str, display_name: str, password: str, role: str, commit: bool = True) -> User:
    normalized = normalized_email(email)
    if session.scalar(select(User).where(User.email == normalized)):
        raise ValueError("A user with this email already exists.")
    if role not in {item.value for item in UserRole}:
        raise ValueError("Invalid role.")
    user = User(email=normalized, display_name=display_name.strip(), password_hash=hash_password(password), role=role)
    if not user.display_name:
        raise ValueError("Display name is required.")
    session.add(user)
    if commit:
        session.commit()
        session.refresh(user)
    else:
        session.flush()
    return user


def _throttle_key(email: str, client_host: str) -> str:
    return token_hash(f"{normalized_email(email)}\0{client_host}")


def check_throttle(session: Session, email: str, client_host: str) -> LoginThrottle:
    now = now_utc()
    key = _throttle_key(email, client_host)
    row = session.get(LoginThrottle, key)
    if row is None:
        row = LoginThrottle(key_hash=key, window_started_at=now)
        session.add(row)
        session.flush()
    if row.locked_until and as_utc(row.locked_until) > now:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts. Try again later.")
    if as_utc(row.window_started_at) < now - timedelta(minutes=15):
        row.failed_attempts = 0
        row.window_started_at = now
        row.locked_until = None
    return row


def register_login_failure(session: Session, throttle: LoginThrottle, *, user_id=None, subject: str) -> None:
    throttle.failed_attempts += 1
    if throttle.failed_attempts >= 5:
        throttle.locked_until = now_utc() + timedelta(minutes=15)
    record_event(session, "login_failed", user_id=user_id, subject=subject)
    session.commit()


def password_login(session: Session, *, email: str, password: str, client_host: str) -> tuple[User, str, MfaChallenge, str | None]:
    throttle = check_throttle(session, email, client_host)
    normalized = normalized_email(email)
    user = session.scalar(select(User).where(User.email == normalized))
    password_valid = verify_password(user.password_hash if user else DUMMY_PASSWORD_HASH, password)
    valid = bool(user and user.is_active and password_valid)
    if not valid:
        register_login_failure(session, throttle, user_id=user.id if user else None, subject=normalized)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_ERROR)
    throttle.failed_attempts = 0
    throttle.locked_until = None
    raw_token = secrets.token_urlsafe(32)
    secret = None if user.mfa_enabled else generate_totp_secret()
    challenge = MfaChallenge(
        token_hash=token_hash(raw_token), user_id=user.id,
        purpose="LOGIN" if user.mfa_enabled else "ENROLLMENT",
        pending_secret_encrypted=encrypt_secret(secret) if secret else None,
        expires_at=now_utc() + timedelta(minutes=5),
    )
    session.add(challenge)
    record_event(session, "password_accepted", user_id=user.id)
    session.commit()
    return user, raw_token, challenge, secret


def provisioning_uri(user: User, secret: str) -> str:
    label = quote(f"Visa Automatic:{user.email}")
    return f"otpauth://totp/{label}?secret={quote(secret)}&issuer=Visa%20Automatic&digits=6&period=30"


def complete_mfa(session: Session, *, challenge_token: str, code: str) -> tuple[User, str, str, AuthSession]:
    now = now_utc()
    challenge = session.scalar(select(MfaChallenge).options(joinedload(MfaChallenge.user)).where(MfaChallenge.token_hash == token_hash(challenge_token)))
    if not challenge or challenge.consumed_at is not None or as_utc(challenge.expires_at) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="MFA challenge is invalid or expired.")
    user = challenge.user
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_LOGIN_ERROR)
    encrypted = challenge.pending_secret_encrypted if challenge.purpose == "ENROLLMENT" else user.mfa_secret_encrypted
    if not encrypted or not verify_totp(decrypt_secret(encrypted), code):
        challenge.failed_attempts += 1
        if challenge.failed_attempts >= 5:
            challenge.consumed_at = now
        record_event(session, "mfa_failed", user_id=user.id)
        session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code.")
    challenge.consumed_at = now
    if challenge.purpose == "ENROLLMENT":
        user.mfa_secret_encrypted = encrypted
        user.mfa_enabled = True
        record_event(session, "mfa_enrolled", user_id=user.id)
    raw_session = secrets.token_urlsafe(48)
    raw_csrf = secrets.token_urlsafe(32)
    auth_session = AuthSession(
        token_hash=token_hash(raw_session), csrf_token_hash=token_hash(raw_csrf),
        user_id=user.id, expires_at=now + session_duration(),
    )
    user.last_successful_login_at = now
    session.add(auth_session)
    record_event(session, "mfa_succeeded", user_id=user.id)
    record_event(session, "login_succeeded", user_id=user.id)
    session.commit()
    return user, raw_session, raw_csrf, auth_session


def authenticated_session(request: Request, session: Session = Depends(get_session)) -> AuthSession:
    raw = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw or len(raw) > 256:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    auth_session = session.scalar(
        select(AuthSession).options(joinedload(AuthSession.user)).where(AuthSession.token_hash == token_hash(raw))
    )
    now = now_utc()
    if not auth_session or auth_session.revoked_at is not None or as_utc(auth_session.expires_at) <= now or not auth_session.user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")
    return auth_session


def require_authenticated_request(request: Request, auth_session: AuthSession = Depends(authenticated_session)) -> User:
    if request.method.upper() not in SAFE_METHODS:
        supplied = request.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(token_hash(supplied), auth_session.csrf_token_hash):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    return auth_session.user


def require_admin_user(user: User = Depends(require_authenticated_request)) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Administrator access required.")
    return user
