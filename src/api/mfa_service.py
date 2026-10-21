"""Bounded, ephemeral enrollment metadata. Never stores tokens, codes or TOTP keys."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import secrets
import threading
import time

from .account_service import account_error


def enrollment_available(request, user):
    """Optional local-test scope uses immutable sub, never editable email/labels."""
    target = request.app.state.account_totp_test_subject
    return request.app.state.account_totp_enabled and (target is None or user.subject == target)


def mfa_status(raw):
    factors = raw.get('UserMFASettingList', [])
    preferred = raw.get('PreferredMfaSetting')
    if (not isinstance(factors, list) or len(factors) > 8
        or any(not isinstance(f, str) or f not in {'SOFTWARE_TOKEN_MFA', 'SMS_MFA', 'EMAIL_OTP'} for f in factors)
        or (preferred is not None and not isinstance(preferred, str))
        or (preferred and preferred not in factors)):
        return 'unknown'
    if 'SOFTWARE_TOKEN_MFA' in factors:
        return 'enabled'
    return 'other_factor' if factors else 'not_enabled'


@dataclass
class Setup:
    ticket: str
    auth_time: int
    expires: float
    busy: bool = False
    attempts: int = 0
    verified: bool = False


class EnrollmentStore:
    """Single-process setup coordination; restart/expiry fails closed, not durable state."""
    def __init__(self, *, clock=time.monotonic, lifetime=300, limit=1000):
        self.clock, self.lifetime, self.limit = clock, lifetime, limit
        self._entries = {}
        self._lock = threading.Lock()

    def begin(self, subject, auth_time):
        with self._lock:
            now = self.clock()
            self._entries = {s: e for s, e in self._entries.items() if e.busy or e.expires > now}
            if subject in self._entries:
                raise account_error(409, 'MFA_SETUP_IN_PROGRESS')
            if len(self._entries) >= self.limit:
                raise account_error(429, 'ACCOUNT_RATE_LIMITED')
            entry = Setup(secrets.token_urlsafe(32), auth_time, now + self.lifetime)
            self._entries[subject] = entry
            return entry

    @contextmanager
    def use(self, subject, ticket, auth_time, *, attempt=True):
        with self._lock:
            entry = self._entries.get(subject)
            if (entry is None or not secrets.compare_digest(entry.ticket, ticket)
                or entry.auth_time != auth_time or entry.expires <= self.clock() or entry.attempts >= 5):
                raise account_error(409, 'MFA_SETUP_EXPIRED')
            if entry.busy:
                raise account_error(409, 'MFA_SETUP_IN_PROGRESS')
            entry.busy = True
            if attempt:
                entry.attempts += 1
        try:
            yield entry
        finally:
            with self._lock:
                entry.busy = False

    def discard(self, subject, ticket, *, require_idle=False):
        with self._lock:
            entry = self._entries.get(subject)
            if entry and secrets.compare_digest(entry.ticket, ticket):
                if require_idle and entry.busy:
                    raise account_error(409, 'MFA_SETUP_IN_PROGRESS')
                self._entries.pop(subject)
