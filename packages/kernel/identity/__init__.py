"""Login, sessions, CSRF and step-up authentication."""

import os
import secrets
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from kernel.canonical import sha256_hex
from kernel.db import global_session, utcnow
from kernel.errors import NotAuthenticated, TooManyAttempts
from kernel.identity.models import LoginAttempt, RoleAssignment, Tenant, UserAccount

SESSION_HOURS = 8
STEP_UP_MINUTES = 5
MAX_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=5)
JWT_ALGORITHM = "HS256"

_hasher = PasswordHasher()
# Verified when the account doesn't exist, so response time doesn't reveal which emails are real.
_dummy_hash = _hasher.hash("astra-timing-equalizer")


@dataclass(frozen=True)
class RoleGrant:
    role: str
    scope_type: str | None = None
    scope_id: str | None = None


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    tenant_id: UUID
    grants: tuple[RoleGrant, ...] = field(default_factory=tuple)
    step_up_fresh: bool = False

    @property
    def roles(self) -> set[str]:
        return {grant.role for grant in self.grants}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _secret() -> str:
    return os.environ["SESSION_SECRET"]


def issue_session(user_id: UUID, tenant_id: UUID, step_up: bool = False) -> str:
    now = utcnow()
    claims = {
        "sub": str(user_id),
        "tid": str(tenant_id),
        "iat": now,
        "exp": now + timedelta(hours=SESSION_HOURS),
    }
    if step_up:
        claims["sup"] = int((now + timedelta(minutes=STEP_UP_MINUTES)).timestamp())
    return jwt.encode(claims, _secret(), algorithm=JWT_ALGORITHM)


def decode_session(token: str) -> dict:
    try:
        return jwt.decode(
            token, _secret(), algorithms=[JWT_ALGORITHM], options={"require": ["exp"]}
        )
    except jwt.PyJWTError as exc:
        raise NotAuthenticated("Session is invalid or expired") from exc


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def tenant_by_slug(slug: str) -> Tenant:
    with global_session() as session:
        tenant = session.scalar(select(Tenant).where(Tenant.slug == slug))
    if tenant is None:
        raise NotAuthenticated("Invalid credentials")
    return tenant


def _attempt_key(email: str, client_ip: str) -> str:
    return sha256_hex(f"{email.lower()}|{client_ip}")


def authenticate(session: Session, email: str, password: str, client_ip: str) -> UserAccount:
    """Check credentials, with lockout after repeated failures for an email and IP pair."""
    key = _attempt_key(email, client_ip)
    since = utcnow() - FAILURE_WINDOW
    failures = session.scalar(
        select(func.count())
        .select_from(LoginAttempt)
        .where(
            LoginAttempt.key_hash == key,
            LoginAttempt.created_at >= since,
            LoginAttempt.success.is_(False),
        )
    )
    if failures >= MAX_FAILURES:
        raise TooManyAttempts("Too many failed attempts. Try again in a few minutes.")

    user = session.scalar(select(UserAccount).where(UserAccount.email == email.lower()))
    tenant_id = session.scalar(select(func.core.current_tenant()))
    valid = verify_password(user.password_hash if user else _dummy_hash, password)
    success = bool(user and user.active and valid)
    session.add(LoginAttempt(tenant_id=tenant_id, key_hash=key, success=success))
    if not success:
        session.flush()
        return None
    return user


def load_actor(session: Session, claims: dict) -> Actor:
    user_id = UUID(claims["sub"])
    user = session.get(UserAccount, user_id)
    if user is None or not user.active:
        raise NotAuthenticated("Account is not active")
    rows = session.scalars(select(RoleAssignment).where(RoleAssignment.user_id == user_id)).all()
    return Actor(
        user_id=user_id,
        tenant_id=user.tenant_id,
        grants=tuple(RoleGrant(row.role, row.scope_type, row.scope_id) for row in rows),
        step_up_fresh=claims.get("sup", 0) > utcnow().timestamp(),
    )
