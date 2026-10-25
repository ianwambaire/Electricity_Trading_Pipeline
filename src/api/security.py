"""Cognito access-token verification. No AWS credentials, token logging or bypass."""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal, Mapping

import httpx
from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from joserfc import jwk, jwt
from joserfc.errors import JoseError

ADMIN_GROUP = "powerflow-admins"
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
bearer = HTTPBearer(auto_error=False, scheme_name="CognitoAccessToken")


def unauthorized():
    return HTTPException(401, "A valid Cognito access token is required.", headers={**NO_STORE, "WWW-Authenticate": "Bearer"})


def unavailable():
    return HTTPException(503, "Authentication verification is temporarily unavailable.", headers=NO_STORE)


@dataclass(frozen=True)
class SecuritySettings:
    issuer: str
    client_ids: frozenset[str]
    audience: str | None = None
    required_scopes: frozenset[str] = frozenset({"openid"})

    def __post_init__(self):
        if not re.fullmatch(r"https://cognito-idp\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9-]+_[A-Za-z0-9]+", self.issuer):
            raise ValueError("Invalid API identity configuration")
        issuer_region = self.issuer.split('.')[1]
        if self.issuer.rsplit('/', 1)[1].split('_', 1)[0] != issuer_region:
            raise ValueError('Invalid API identity configuration')
        if not self.client_ids or any(not re.fullmatch(r"[a-z0-9]{1,128}", v) for v in self.client_ids):
            raise ValueError("Invalid API identity configuration")
        if "openid" not in self.required_scopes or any(not re.fullmatch(r"[\x21-\x7e]{1,256}", v) for v in self.required_scopes):
            raise ValueError("Invalid API scope configuration")
        if self.audience is not None and (not self.audience or len(self.audience) > 2048 or re.search(r"\s", self.audience)):
            raise ValueError("Invalid API resource configuration")

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None):
        env = os.environ if env is None else env
        return cls(
            issuer=env.get("POWERFLOW_API_COGNITO_ISSUER", "").strip(),
            client_ids=frozenset(v.strip() for v in env.get("POWERFLOW_API_COGNITO_CLIENT_IDS", "").split(",") if v.strip()),
            audience=env.get("POWERFLOW_API_COGNITO_AUDIENCE") or None,
            required_scopes=frozenset({"openid", *env.get("POWERFLOW_API_REQUIRED_SCOPES", "").split()}),
        )

    @property
    def jwks_url(self):
        return self.issuer + "/.well-known/jwks.json"


@dataclass(frozen=True)
class CurrentUser:
    subject: str
    role: Literal["Admin", "Analyst"]
    email: str | None = None
    display_name: str | None = None
    scopes: frozenset[str] = frozenset()
    auth_time: int | None = None


def fetch_jwks(url: str) -> dict:
    # The URL is constructed only from validated server config, never token jku/iss.
    with httpx.Client(timeout=httpx.Timeout(5.0, connect=2.0), follow_redirects=False, trust_env=False) as client:
        with client.stream("GET", url, headers={"Accept": "application/json"}) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data) > 64 * 1024:
                    raise ValueError("Invalid JWKS response")
    return json.loads(data)


class JwksCache:
    """Bounded single-flight cache, with unknown-kid refresh and outage backoff."""
    def __init__(self, url: str, fetch: Callable = fetch_jwks, clock: Callable = time.monotonic):
        self.url, self.fetch, self.clock = url, fetch, clock
        self._lock = threading.Lock()
        self._keys = {}
        self._expires = 0.0
        self._last_miss = float("-inf")
        self._retry_after = 0.0

    def _refresh(self, now):
        if now < self._retry_after:
            raise unavailable()
        try:
            raw = self.fetch(self.url)
            entries = raw.get("keys") if isinstance(raw, dict) else None
            if not isinstance(entries, list) or not 1 <= len(entries) <= 16:
                raise ValueError("Invalid JWKS")
            keys = {}
            for value in entries:
                if not isinstance(value, dict) or value.get("kty") != "RSA" or value.get("alg") != "RS256" or value.get("use") != "sig":
                    raise ValueError("Invalid JWKS key")
                kid = value.get("kid")
                if not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", kid) or kid in keys:
                    raise ValueError("Invalid key identifier")
                if any(part in value for part in ("d", "p", "q", "dp", "dq", "qi", "oth")):
                    raise ValueError("Private key in public key set")
                if value.get("key_ops") is not None and value["key_ops"] != ["verify"]:
                    raise ValueError("Invalid key operations")
                key = jwk.RSAKey.import_key(value)
                if key.raw_value.key_size < 2048:
                    raise ValueError("Weak signing key")
                keys[kid] = key
            self._keys, self._expires = keys, now + 300
            self._retry_after = 0.0
        except (httpx.HTTPError, ValueError, TypeError, KeyError, JoseError, OSError):
            self._retry_after = now + 5
            raise unavailable() from None

    def key(self, kid):
        with self._lock:
            now = self.clock()
            refreshed = now >= self._expires
            if refreshed:
                self._refresh(now)
            if kid not in self._keys and not refreshed and now - self._last_miss >= 30:
                self._last_miss = now
                self._refresh(now)
            if kid not in self._keys:
                raise unauthorized()
            return self._keys[kid]


class CognitoVerifier:
    def __init__(self, settings: SecuritySettings, keys: JwksCache | None = None):
        self.settings = settings
        self.keys = keys or JwksCache(settings.jwks_url)

    def _key(self, obj):
        header = obj.headers()
        if set(header) - {"alg", "kid", "typ"} or header.get("alg") != "RS256" or header.get("typ", "JWT") != "JWT":
            raise unauthorized()
        kid = header.get("kid")
        if not isinstance(kid, str) or not re.fullmatch(r"[A-Za-z0-9_+/=-]{1,256}", kid):
            raise unauthorized()
        # This unverified header is only a key-selection hint; it grants no rights.
        return self.keys.key(kid)

    def verify(self, token: str) -> CurrentUser:
        if not isinstance(token, str) or len(token) > 16384 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", token):
            raise unauthorized()
        try:
            result = jwt.decode(token, self._key, algorithms=["RS256"])
            claims = result.claims  # Signature has been verified by joserfc.
            for field in ("iss", "sub", "client_id", "token_use", "scope"):
                if not isinstance(claims.get(field), str) or not claims[field]:
                    raise ValueError("Invalid claim type")
            for field in ("exp", "iat", "nbf"):
                if field in claims and (type(claims[field]) is not int):
                    raise ValueError("Invalid timestamp type")
            jwt.JWTClaimsRegistry(
                iss={"essential": True, "value": self.settings.issuer},
                exp={"essential": True}, iat={"essential": True}, sub={"essential": True},
                token_use={"essential": True, "value": "access"},
                client_id={"essential": True, "values": list(self.settings.client_ids)},
                scope={"essential": True},
            ).validate(claims)
            if claims["exp"] <= time.time() or claims["exp"] <= claims["iat"]:
                raise ValueError("Expired token")
            if not re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", claims["sub"]):
                raise ValueError("Invalid Cognito subject")
            if self.settings.audience is None:
                if "aud" in claims:
                    raise ValueError("Unexpected resource binding")
            elif claims.get("aud") != self.settings.audience:
                raise ValueError("Wrong resource binding")
            if not self.settings.required_scopes.issubset(claims["scope"].split()):
                raise ValueError("Insufficient OAuth scope")
            auth_time = claims.get('auth_time')
            if auth_time is not None and (type(auth_time) is not int or not 0 <= auth_time <= claims['iat']):
                raise ValueError('Invalid authentication time')
            groups = claims.get("cognito:groups", [])
            admin = isinstance(groups, list) and all(isinstance(v, str) for v in groups) and ADMIN_GROUP in groups
            def optional(field):
                v = claims.get(field)
                return v if isinstance(v, str) and 0 < len(v) <= 320 and not any(ord(c) < 32 for c in v) else None
            return CurrentUser(claims["sub"], "Admin" if admin else "Analyst", optional("email"), optional("name"), frozenset(claims["scope"].split()), auth_time)
        except HTTPException:
            raise
        except (JoseError, ValueError, TypeError, KeyError, OverflowError):
            raise unauthorized() from None


def get_current_user(request: Request, response: Response,
                     credential: HTTPAuthorizationCredentials | None = Depends(bearer)) -> CurrentUser:
    response.headers.update(NO_STORE)
    if credential is None or len(request.headers.getlist("authorization")) != 1:
        raise unauthorized()
    verifier = request.app.state.cognito_verifier
    if verifier is None:
        raise unavailable()
    user = verifier.verify(credential.credentials)
    gateway = getattr(request.app.state, 'account_gateway', None)
    if gateway is None:
        raise unavailable()
    request.state.cognito_user = gateway.assert_active(credential.credentials, user.scopes, user.subject)
    return user


require_authenticated_user = get_current_user


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if user.role != "Admin":
        raise HTTPException(403, "Administrator permission is required.", headers=NO_STORE)
    return user
