"""Token-authorized Cognito self-service. No IAM credentials or user-selected targets."""
from __future__ import annotations

import json
import threading
import time
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException
from .security import NO_STORE, unauthorized

SELF_SERVICE_SCOPE = 'aws.cognito.signin.user.admin'
PROFILE_ATTRIBUTES = frozenset({'name', 'preferred_username'})


def account_error(status, code):
    return HTTPException(status, detail={'code': code}, headers=NO_STORE)


class AccountGateway:
    def __init__(self, issuer, *, transport=None, clock=time.monotonic):
        self.issuer = issuer
        self.endpoint = issuer.rsplit('/', 1)[0] + '/'
        self.transport, self.clock = transport, clock
        self._userinfo_url = None
        self._metadata_expires = 0
        self._lock = threading.Lock()

    def _request(self, method, url, *, operation=None, payload=None, token=None):
        headers = {'Accept': 'application/json'}
        if operation:
            headers.update({'Content-Type': 'application/x-amz-json-1.1',
                            'X-Amz-Target': 'AWSCognitoIdentityProviderService.' + operation})
        elif token:
            headers['Authorization'] = 'Bearer ' + token
        try:
            with httpx.Client(timeout=httpx.Timeout(6, connect=2), follow_redirects=False,
                              trust_env=False, transport=self.transport) as client:
                with client.stream(method, url, headers=headers, json=payload if operation else None) as response:
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise ValueError('Response too large')
                    status = response.status_code
            raw = json.loads(content) if content else {}
            if not isinstance(raw, dict):
                raise ValueError('Invalid provider response')
        except (httpx.HTTPError, OSError, ValueError, TypeError):
            raise account_error(503, 'ACCOUNT_UNAVAILABLE') from None
        if status >= 400:
            error = str(raw.get('__type', '')).rsplit('#', 1)[-1]
            message = str(raw.get('message', '')).lower()
            if status == 401 or raw.get('error') == 'invalid_token':
                raise unauthorized()
            if error == 'NotAuthorizedException':
                if 'scope' in message:
                    raise account_error(403, 'ACCOUNT_RECONNECT_REQUIRED')
                if operation == 'UpdateUserAttributes' and any(phrase in message for phrase in (
                    'write unauthorized attribute', 'write unauthorised attribute',
                    'not authorized to write', 'does not have write access',
                )) and not any(word in message for word in ('token', 'expired', 'revoked')):
                    raise account_error(403, 'ATTRIBUTE_NOT_WRITABLE')
                if operation == 'ChangePassword' and not any(word in message for word in ['token', 'expired', 'revoked']):
                    raise account_error(400, 'INCORRECT_PASSWORD')
                raise unauthorized()
            if error in {'PasswordResetRequiredException', 'UserNotConfirmedException'}:
                raise account_error(409, 'ACCOUNT_RECOVERY_REQUIRED')
            if error in {'TooManyRequestsException', 'LimitExceededException', 'TooManyFailedAttemptsException'} or status == 429:
                raise account_error(429, 'ACCOUNT_RATE_LIMITED')
            if error in {'CodeMismatchException', 'ExpiredCodeException', 'EnableSoftwareTokenMFAException'}:
                raise account_error(400, 'MFA_INVALID_CODE')
            if error == 'ConcurrentModificationException':
                raise account_error(409, 'MFA_SETUP_IN_PROGRESS')
            if error == 'SoftwareTokenMFANotFoundException':
                raise account_error(409, 'MFA_UNAVAILABLE')
            if error == 'ForbiddenException':
                raise account_error(403, 'ACCOUNT_ACTION_REJECTED')
            if error in {'InvalidPasswordException', 'PasswordHistoryPolicyViolationException'}:
                raise account_error(422, 'PASSWORD_POLICY')
            if error in {'InvalidParameterException', 'AliasExistsException'}:
                raise account_error(422, 'INVALID_ACCOUNT_INPUT')
            if error in {'OperationNotEnabledException', 'UnsupportedOperationException', 'FeatureUnavailableInTierException'}:
                raise account_error(409, 'ACTION_UNAVAILABLE')
            raise account_error(503, 'ACCOUNT_UNAVAILABLE')
        if not 200 <= status < 300:
            raise account_error(503, 'ACCOUNT_UNAVAILABLE')
        return raw

    def call(self, operation, token, **payload):
        # No user identifier or administrative API can be selected by the caller.
        if operation not in {'GetUser', 'GetUserAuthFactors', 'UpdateUserAttributes', 'ChangePassword', 'GlobalSignOut',
                             'AssociateSoftwareToken', 'VerifySoftwareToken', 'SetUserMFAPreference'}:
            raise account_error(409, 'ACTION_UNAVAILABLE')
        if operation == 'AssociateSoftwareToken' and payload:
            raise account_error(422, 'INVALID_ACCOUNT_INPUT')
        if operation == 'VerifySoftwareToken' and (set(payload) != {'UserCode'}
            or not isinstance(payload['UserCode'], str) or len(payload['UserCode']) != 6
            or any(c not in '0123456789' for c in payload['UserCode'])):
            raise account_error(422, 'INVALID_ACCOUNT_INPUT')
        if operation == 'SetUserMFAPreference' and (set(payload) != {'SoftwareTokenMfaSettings'}
            or not isinstance(payload['SoftwareTokenMfaSettings'], dict)
            or set(payload['SoftwareTokenMfaSettings']) != {'Enabled', 'PreferredMfa'}
            or any(v is not True for v in payload['SoftwareTokenMfaSettings'].values())):
            # This gateway supports enabling verified TOTP only, never disabling
            # another factor, administrative recovery or arbitrary preferences.
            raise account_error(422, 'INVALID_ACCOUNT_INPUT')
        if operation == 'UpdateUserAttributes':
            rows = payload.get('UserAttributes')
            if (set(payload) != {'UserAttributes'} or not isinstance(rows, list) or not 1 <= len(rows) <= 2
                or any(not isinstance(row, dict) or set(row) != {'Name', 'Value'}
                       or not isinstance(row.get('Name'), str) or row['Name'] not in PROFILE_ATTRIBUTES
                       or not isinstance(row.get('Value'), str) for row in rows)
                or len({row['Name'] for row in rows}) != len(rows)):
                raise account_error(422, 'INVALID_ACCOUNT_INPUT')
        return self._request('POST', self.endpoint, operation=operation,
                             payload={**payload, 'AccessToken': token})

    def _userinfo(self):
        with self._lock:
            if self._userinfo_url is None or self.clock() >= self._metadata_expires:
                metadata = self._request('GET', self.issuer + '/.well-known/openid-configuration')
                try:
                    endpoint = metadata.get('userinfo_endpoint')
                    if not isinstance(endpoint, str):
                        raise ValueError('Missing user-info endpoint')
                    url = urlsplit(endpoint)
                    if (metadata.get('issuer') != self.issuer or url.scheme != 'https'
                        or not url.hostname or not url.hostname.endswith('.amazoncognito.com')
                        or url.username or url.password or url.port not in {None, 443}
                        or url.path != '/oauth2/userInfo' or url.query or url.fragment):
                        raise ValueError('Untrusted user-info endpoint')
                except ValueError:
                    raise account_error(503, 'ACCOUNT_UNAVAILABLE') from None
                self._userinfo_url = url.geturl()
                self._metadata_expires = self.clock() + 300
            return self._userinfo_url

    def assert_active(self, token, scopes, subject):
        if SELF_SERVICE_SCOPE in scopes:
            raw = self.call('GetUser', token)
            attributes = attributes_from_user(raw)
        else:
            raw = self._request('GET', self._userinfo(), token=token)
            attributes = raw
        if attributes.get('sub') != subject:
            raise unauthorized()
        return raw


def attributes_from_user(raw):
    rows = raw.get('UserAttributes')
    if not isinstance(rows, list) or len(rows) > 64:
        raise account_error(503, 'ACCOUNT_UNAVAILABLE')
    values = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('Name'), str) or not isinstance(row.get('Value'), str):
            raise account_error(503, 'ACCOUNT_UNAVAILABLE')
        if row['Name'] in values:
            raise account_error(503, 'ACCOUNT_UNAVAILABLE')
        values[row['Name']] = row['Value']
    return values
