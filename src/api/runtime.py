"""Validated runtime boundaries and fixed-schema, credential-free HTTP telemetry."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4

logger = logging.getLogger('powerflow.api')
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(handler)


def event(name, **fields):
    # Callers supply only fixed names, numeric values and server route templates.
    logger.info(json.dumps({'event': name, **fields}, separators=(',', ':')))


@dataclass(frozen=True)
class RuntimeSettings:
    environment: str = 'development'
    allowed_hosts: tuple[str, ...] = ('localhost', '127.0.0.1', 'testserver')
    cors_origins: tuple[str, ...] = ()

    def __post_init__(self):
        if self.environment not in {'development', 'staging', 'production'}:
            raise ValueError('Invalid API runtime configuration')
        if not self.allowed_hosts or any(
            not re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', h)
            or len(h) > 253 for h in self.allowed_hosts
        ):
            raise ValueError('Invalid API host configuration')
        for origin in self.cors_origins:
            try:
                u = urlsplit(origin)
                port = u.port
                if (u.scheme not in {'https', 'http'} or not u.hostname or u.username or u.password
                    or u.path or u.query or u.fragment or '*' in origin
                    or (u.scheme != 'https' and not (self.environment == 'development' and u.hostname == 'localhost'))
                    or (port is not None and not 1 <= port <= 65535)):
                    raise ValueError()
            except ValueError:
                raise ValueError('Invalid API CORS configuration') from None

    @property
    def deployed(self):
        return self.environment != 'development'

    @classmethod
    def from_environment(cls):
        mode = os.environ.get('POWERFLOW_API_ENV', 'development')
        hosts = os.environ.get('POWERFLOW_API_ALLOWED_HOSTS', '')
        if not hosts and mode == 'development':
            hosts = 'localhost,127.0.0.1,testserver'
        return cls(mode, tuple(h.strip() for h in hosts.split(',') if h.strip()),
                   tuple(o.strip() for o in os.environ.get('POWERFLOW_API_CORS_ORIGINS', '').split(',') if o.strip()))


class SafeRequestMiddleware:
    """Pure ASGI: no body/header/query logging and no caller-controlled log IDs."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        request_id = uuid4().hex
        scope.setdefault('state', {})['request_id'] = request_id
        started, status, sent = time.monotonic(), 500, False

        async def safe_send(message):
            nonlocal status, sent
            if message['type'] == 'http.response.start':
                status, sent = message['status'], True
                headers = [(k, v) for k, v in message.get('headers', []) if k.lower() not in {b'x-request-id', b'cache-control', b'pragma'}]
                headers += [(b'x-request-id', request_id.encode()), (b'cache-control', b'no-store'),
                            (b'pragma', b'no-cache'), (b'x-content-type-options', b'nosniff')]
                message = {**message, 'headers': headers}
            await send(message)
        try:
            await self.app(scope, receive, safe_send)
        except Exception:
            # Never log exception text/tracebacks: provider errors can carry inputs.
            event('request_failed', request_id=request_id)
            if sent:
                raise RuntimeError('Response interrupted') from None
            payload = json.dumps({'detail': 'The service could not complete this request.', 'request_id': request_id}).encode()
            await safe_send({'type': 'http.response.start', 'status': 500, 'headers': [(b'content-type', b'application/json')]})
            await safe_send({'type': 'http.response.body', 'body': payload})
        finally:
            route = scope.get('route')
            template = getattr(route, 'path', 'unmatched')
            event('http_request', request_id=request_id, route=template, status=status,
                  method=scope['method'] if scope['method'] in {'GET','HEAD','POST','PATCH','OPTIONS','PUT','DELETE'} else 'OTHER',
                  duration_ms=round((time.monotonic()-started)*1000, 2),
                  access='rejected' if status == 401 else 'forbidden' if status == 403 else 'completed')


class SafeExceptionMiddleware:
    """Inside CORS so sanitized 500 responses retain the configured CORS policy."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        sent = False

        async def track(message):
            nonlocal sent
            if message['type'] == 'http.response.start':
                sent = True
            await send(message)
        try:
            await self.app(scope, receive, track)
        except Exception:
            if sent:
                raise RuntimeError('Response interrupted') from None
            request_id = scope.get('state', {}).get('request_id')
            event('request_failed', request_id=request_id)
            payload = json.dumps({'detail': 'The service could not complete this request.', 'request_id': request_id}).encode()
            await send({'type':'http.response.start','status':500,'headers':[(b'content-type',b'application/json')]})
            await send({'type':'http.response.body','body':payload})
