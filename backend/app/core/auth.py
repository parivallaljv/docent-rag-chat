"""Verifies Supabase-issued JWTs and extracts the authenticated user id.

Supabase projects sign user session JWTs one of two ways:
  - Newer projects (the default since Supabase's 2025 "JWT Signing Keys"
    rollout): asymmetric ES256/RS256, verified against the project's public
    JWKS endpoint (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`).
  - Older/legacy projects: HS256 signed with a single shared secret
    (SUPABASE_JWT_SECRET).

This verifies via JWKS first (the current default), and falls back to the
legacy HS256 shared secret only if SUPABASE_JWT_SECRET is configured and the
JWKS path can't validate the token -- so this backend works against either
project configuration without needing to know upfront which one it's talking
to.
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings

_bearer_scheme = HTTPBearer(auto_error=False)

_ASYMMETRIC_ALGORITHMS = ["ES256", "RS256"]

_jwk_client: jwt.PyJWKClient | None = None


def _get_jwk_client() -> jwt.PyJWKClient | None:
    """Lazily builds (and caches) a PyJWKClient for the project's JWKS endpoint.

    PyJWKClient caches fetched keys in-process, so this only hits the network
    on the first request (and again after a signing-key rotation, since a
    cache miss on `kid` triggers a refetch).
    """
    global _jwk_client
    if _jwk_client is None and settings.SUPABASE_URL:
        jwks_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwk_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwk_client


def _decode_via_jwks(token: str) -> dict:
    jwk_client = _get_jwk_client()
    if jwk_client is None:
        raise jwt.InvalidTokenError("SUPABASE_URL not configured; cannot fetch JWKS")
    signing_key = jwk_client.get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=_ASYMMETRIC_ALGORITHMS,
        audience=settings.SUPABASE_JWT_AUD,
    )


def _decode_via_shared_secret(token: str) -> dict:
    if not settings.SUPABASE_JWT_SECRET:
        raise jwt.InvalidTokenError("SUPABASE_JWT_SECRET not configured")
    return jwt.decode(
        token,
        settings.SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        audience=settings.SUPABASE_JWT_AUD,
    )


class TokenVerificationError(Exception):
    """Raised by verify_token() on any failure (missing/expired/malformed
    token, missing 'sub' claim). Transport-agnostic on purpose: the HTTP path
    (get_current_user_id) converts this to a 401 HTTPException, while the
    WebSocket path (routers.chat's /chat/ws) converts it to a close frame
    instead, since raising an HTTPException after a socket is already
    accepted wouldn't mean anything."""


def verify_token_claims(token: str) -> dict:
    """Verify a raw bearer token string and return its claims (including `sub`,
    the Supabase user id, and `exp`). This is the transport-agnostic core shared by both
    the HTTP dependency below and the WebSocket auth handshake -- it knows
    nothing about HTTPAuthorizationCredentials, Request, or WebSocket."""
    if not token:
        raise TokenVerificationError("Missing bearer token")

    payload: dict | None = None
    last_error: Exception | None = None

    try:
        payload = _decode_via_jwks(token)
    except jwt.ExpiredSignatureError as exc:
        raise TokenVerificationError("Token expired") from exc
    except jwt.InvalidTokenError as exc:
        last_error = exc

    if payload is None:
        try:
            payload = _decode_via_shared_secret(token)
        except jwt.ExpiredSignatureError as exc:
            raise TokenVerificationError("Token expired") from exc
        except jwt.InvalidTokenError as exc:
            last_error = exc

    if payload is None:
        raise TokenVerificationError(f"Invalid token: {last_error}")

    user_id = payload.get("sub")
    if not user_id:
        raise TokenVerificationError("Token missing 'sub' claim")
    return payload


def verify_token(token: str) -> str:
    """Verify a bearer token and return the Supabase user id (`sub` claim)."""
    return verify_token_claims(token)["sub"]


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: validate the `Authorization: Bearer <jwt>` header and
    return the Supabase user id (the token's `sub` claim). Raises 401 on any
    failure (missing token, bad signature, expired token, missing claim)."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        return verify_token(credentials.credentials)
    except TokenVerificationError as exc:
        detail = "Token expired" if str(exc) == "Token expired" else str(exc)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail) from exc
