"""Account-only routes, with bounded/redacted input and live own-account checks."""
from __future__ import annotations

import json
import time
from typing import Literal
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator
from starlette.requests import Request as StarletteRequest
from .security import CurrentUser, require_authenticated_user, NO_STORE
from .account_service import SELF_SERVICE_SCOPE, account_error, attributes_from_user
from .mfa_service import mfa_status, enrollment_available


class AccountRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def bounded(request):
            if request.query_params:
                raise account_error(422, 'INVALID_ACCOUNT_INPUT')
            size = 0
            async def receive():
                nonlocal size
                message = await request.receive()
                size += len(message.get('body', b''))
                if size > 16384:
                    raise account_error(413, 'INVALID_ACCOUNT_INPUT')
                return message
            safe_request = StarletteRequest(request.scope, receive=receive)
            try:
                response = await original(safe_request)
                response.headers.update(NO_STORE)
                return response
            except RequestValidationError:
                # Never echo submitted passwords, verification codes or extra targets.
                raise account_error(422, 'INVALID_ACCOUNT_INPUT') from None
        return bounded


router = APIRouter(prefix='/account', tags=['Own account'], route_class=AccountRoute)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str | None = None
    preferred_username: str | None = None

    @field_validator('name', 'preferred_username')
    @classmethod
    def clean_attribute(cls, value):
        if value is None or not 1 <= len(value.strip()) <= 128 or any(ord(c)<32 or ord(c)==127 for c in value):
            raise ValueError('Invalid account field')
        return value.strip()

    @model_validator(mode='after')
    def nonempty(self):
        if not self.model_fields_set:
            raise ValueError('No account change')
        return self


class PasswordUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    current_password: SecretStr
    new_password: SecretStr

    @field_validator('current_password', 'new_password')
    @classmethod
    def bounded_password(cls, value):
        if not 1 <= len(value.get_secret_value()) <= 256:
            raise ValueError('Invalid password length')
        return value


class EmptyAction(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ActionResult(BaseModel):
    status: Literal['updated', 'password_changed', 'signed_out']


class AccountProfile(BaseModel):
    name: str | None
    email: str | None
    email_verified: bool | None
    preferred_username: str | None
    role: Literal['Admin', 'Analyst']
    connected_providers: list[Literal['Google']]
    name_editable: bool
    preferred_username_editable: Literal[True] = True
    email_editable: Literal[False] = False
    password_configured: bool | None
    mfa_management: Literal['available', 'provider_managed', 'unavailable']
    mfa_status: Literal['not_enabled', 'enabled', 'other_factor', 'unknown']


def own_account(request: Request, user: CurrentUser = Depends(require_authenticated_user)):
    if SELF_SERVICE_SCOPE not in user.scopes:
        raise account_error(403, 'ACCOUNT_RECONNECT_REQUIRED')
    # require_authenticated_user already made the live GetUser revocation check.
    raw = getattr(request.state, 'cognito_user', None)
    if raw is None:
        raise account_error(503, 'ACCOUNT_UNAVAILABLE')
    return user, raw


def linked_identities(attributes):
    if 'identities' not in attributes:
        return []
    try:
        value = attributes['identities']
        if not isinstance(value, str) or len(value)>8192:
            raise ValueError('Invalid linked identities')
        rows = json.loads(value)
        if not isinstance(rows, list) or len(rows)>10 or any(not isinstance(r,dict) or not isinstance(r.get('providerName'),str) for r in rows):
            raise ValueError('Invalid linked identities')
        return rows
    except (ValueError, TypeError):
        raise account_error(503, 'ACCOUNT_UNAVAILABLE') from None


def connected_providers(attributes):
    return ['Google'] if any(r['providerName']=='Google' for r in linked_identities(attributes)) else []


def password_configured(request, token):
    try:
        raw = request.app.state.account_gateway.call('GetUserAuthFactors', token)
    except HTTPException as error:
        # Missing capability evidence hides password changes; revocation never falls back.
        if getattr(error, 'status_code', None) in {409, 503}:
            return None
        raise
    factors = raw.get('ConfiguredUserAuthFactors')
    if not isinstance(factors, list) or len(factors)>8 or any(not isinstance(f,str) for f in factors):
        return None
    return 'PASSWORD' in factors


def current_token(request):
    return request.headers['authorization'].split(None, 1)[1]


def profile_response(request, user, raw):
    attributes = attributes_from_user(raw)
    def text(name):
        value = attributes.get(name)
        return value if isinstance(value,str) and 0<len(value)<=320 and not any(ord(c)<32 or ord(c)==127 for c in value) else None
    providers = connected_providers(attributes)
    password = password_configured(request, current_token(request))
    management = 'provider_managed' if linked_identities(attributes) else 'available' if (
        enrollment_available(request, user) and password is True
        and attributes.get('email_verified') == 'true' and mfa_status(raw) in {'not_enabled', 'enabled'}
    ) else 'unavailable'
    return AccountProfile(name=text('name'), email=text('email'),
        email_verified={'true':True,'false':False}.get(attributes.get('email_verified')),
        preferred_username=text('preferred_username'), role=user.role,
        connected_providers=providers, name_editable=not linked_identities(attributes),
        password_configured=password, mfa_management=management, mfa_status=mfa_status(raw))


@router.get('/profile', response_model=AccountProfile)
def get_profile(request: Request, account=Depends(own_account)):
    return profile_response(request, *account)


@router.patch('/profile', response_model=ActionResult)
def update_profile(body: ProfileUpdate, request: Request, account=Depends(own_account)):
    user, raw = account
    attributes = attributes_from_user(raw)
    if body.name is not None and linked_identities(attributes):
        raise account_error(409, 'NAME_MANAGED_BY_PROVIDER')
    changes = [{'Name': name, 'Value': getattr(body,name)} for name in body.model_fields_set]
    request.app.state.account_gateway.call('UpdateUserAttributes', current_token(request), UserAttributes=changes)
    return ActionResult(status='updated')


@router.post('/password', response_model=ActionResult)
def change_password(body: PasswordUpdate, request: Request, account=Depends(own_account)):
    if password_configured(request, current_token(request)) is not True:
        raise account_error(409, 'PASSWORD_UNAVAILABLE')
    request.app.state.account_gateway.call('ChangePassword', current_token(request),
        PreviousPassword=body.current_password.get_secret_value(), ProposedPassword=body.new_password.get_secret_value())
    return ActionResult(status='password_changed')


@router.post('/sign-out-all', response_model=ActionResult)
def sign_out_all(request: Request, body: EmptyAction | None = None, account=Depends(own_account)):
    user, _raw = account
    if user.auth_time is None or not 0 <= time.time()-user.auth_time <= 600:
        raise account_error(403, 'FRESH_SIGN_IN_REQUIRED')
    request.app.state.account_gateway.call('GlobalSignOut', current_token(request))
    return ActionResult(status='signed_out')
