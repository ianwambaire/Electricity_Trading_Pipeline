"""Own-account TOTP setup; no IAM, administrative recovery or account targets."""
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

from .account_routes import AccountRoute, EmptyAction, own_account, current_token, linked_identities, password_configured
from .account_service import account_error, attributes_from_user
from .mfa_service import mfa_status, enrollment_available

router = APIRouter(prefix='/account/mfa', tags=['Own account MFA'], route_class=AccountRoute)


class Ticket(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    setup_ticket: SecretStr

    @field_validator('setup_ticket')
    @classmethod
    def valid_ticket(cls, value):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', value.get_secret_value()):
            raise ValueError('Invalid setup')
        return value


class Verify(Ticket):
    code: SecretStr

    @field_validator('code')
    @classmethod
    def valid_code(cls, value):
        if not re.fullmatch(r'[0-9]{6}', value.get_secret_value()):
            raise ValueError('Invalid code')
        return value


class Started(BaseModel):
    secret: str
    setup_ticket: str
    expires_in: int


class MfaResult(BaseModel):
    status: Literal['mfa_enabled', 'setup_cancelled']


def eligible(request: Request, account=Depends(own_account)):
    user, raw = account
    if not enrollment_available(request, user):
        raise account_error(409, 'ACTION_UNAVAILABLE')
    attrs = attributes_from_user(raw)
    if linked_identities(attrs):
        raise account_error(409, 'MFA_MANAGED_BY_PROVIDER')
    if user.auth_time is None or not 0 <= time.time() - user.auth_time <= 600:
        raise account_error(403, 'FRESH_SIGN_IN_REQUIRED')
    if attrs.get('email_verified') != 'true':
        raise account_error(409, 'MFA_RECOVERY_REQUIRED')
    if password_configured(request, current_token(request)) is not True:
        raise account_error(409, 'MFA_UNAVAILABLE')
    return user, raw


@router.post('/setup', response_model=Started)
def start(request: Request, body: EmptyAction | None = None, account=Depends(eligible)):
    user, raw = account
    if mfa_status(raw) != 'not_enabled':
        raise account_error(409, 'MFA_ALREADY_CONFIGURED')
    store = request.app.state.mfa_enrollments
    entry = store.begin(user.subject, user.auth_time)
    try:
        # Reserve and serialize before provider mutation. No key/session is stored.
        with store.use(user.subject, entry.ticket, user.auth_time, attempt=False):
            result = request.app.state.account_gateway.call('AssociateSoftwareToken', current_token(request))
            secret = result.get('SecretCode')
            if not isinstance(secret, str) or not re.fullmatch(r'[A-Z2-7]{16,128}', secret):
                raise account_error(503, 'ACCOUNT_UNAVAILABLE')
        return Started(secret=secret, setup_ticket=entry.ticket, expires_in=store.lifetime)
    except Exception:
        store.discard(user.subject, entry.ticket)
        raise


@router.post('/verify', response_model=MfaResult)
def verify(body: Verify, request: Request, account=Depends(eligible)):
    user, raw = account
    store = request.app.state.mfa_enrollments
    ticket = body.setup_ticket.get_secret_value()
    with store.use(user.subject, ticket, user.auth_time) as entry:
        if mfa_status(raw) == 'enabled' and entry.verified and raw.get('PreferredMfaSetting') == 'SOFTWARE_TOKEN_MFA':
            store.discard(user.subject, ticket)
            return {'status': 'mfa_enabled'}
        if mfa_status(raw) != 'not_enabled':
            raise account_error(409, 'MFA_ALREADY_CONFIGURED')
        gateway = request.app.state.account_gateway
        access = current_token(request)
        if not entry.verified:
            result = gateway.call('VerifySoftwareToken', access, UserCode=body.code.get_secret_value())
            if result.get('Status') != 'SUCCESS':
                raise account_error(400, 'MFA_INVALID_CODE')
            # Remember verification only, never the secret or code. A preference
            # failure can be retried without replacing/re-verifying the device.
            entry.verified = True
        gateway.call('SetUserMFAPreference', access, SoftwareTokenMfaSettings={'Enabled': True, 'PreferredMfa': True})
        updated = gateway.assert_active(access, user.scopes, user.subject)
        if mfa_status(updated) != 'enabled' or updated.get('PreferredMfaSetting') != 'SOFTWARE_TOKEN_MFA':
            raise account_error(503, 'MFA_CONFIRMATION_REQUIRED')
        store.discard(user.subject, ticket)
        return {'status': 'mfa_enabled'}


@router.post('/cancel', response_model=MfaResult)
def cancel(body: Ticket, request: Request, account=Depends(own_account)):
    user, _raw = account
    # Discards only ephemeral setup metadata; never disables/replaces a factor.
    request.app.state.mfa_enrollments.discard(user.subject, body.setup_ticket.get_secret_value(), require_idle=True)
    return {'status': 'setup_cancelled'}
