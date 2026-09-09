"""Unit tests for the transport-agnostic verify_token(), extracted from
get_current_user_id() specifically so the WebSocket auth handshake (routers.
chat's /chat/ws) can reuse the exact same verification logic as the HTTP
path. Uses synthetic HS256-signed JWTs and a monkeypatched empty
SUPABASE_URL (so the JWKS path short-circuits without a network call) --
pure logic, no live Supabase project needed.
"""
from __future__ import annotations

import time

import jwt
import pytest

from app.core import auth as auth_module

TEST_SECRET = "unit-test-shared-secret-at-least-32-bytes-long"
TEST_AUD = "authenticated"


@pytest.fixture(autouse=True)
def _isolated_auth_settings(monkeypatch):
    """Force the JWKS path to short-circuit (no SUPABASE_URL -> no network
    call) and use a known HS256 secret, regardless of the real .env this
    process may have loaded and regardless of any JWKS client a previous
    test/import already cached."""
    monkeypatch.setattr(auth_module.settings, "SUPABASE_URL", "")
    monkeypatch.setattr(auth_module.settings, "SUPABASE_JWT_SECRET", TEST_SECRET)
    monkeypatch.setattr(auth_module.settings, "SUPABASE_JWT_AUD", TEST_AUD)
    monkeypatch.setattr(auth_module, "_jwk_client", None)


def _make_token(*, sub="user-123", aud=TEST_AUD, exp_delta=3600, secret=TEST_SECRET, **extra):
    payload = {"sub": sub, "aud": aud, "exp": int(time.time()) + exp_delta, **extra}
    if sub is None:
        del payload["sub"]
    return jwt.encode(payload, secret, algorithm="HS256")


def test_valid_token_returns_sub():
    token = _make_token(sub="user-abc")
    assert auth_module.verify_token(token) == "user-abc"


def test_missing_token_raises():
    with pytest.raises(auth_module.TokenVerificationError):
        auth_module.verify_token("")


def test_expired_token_raises_with_expected_message():
    token = _make_token(exp_delta=-10)
    with pytest.raises(auth_module.TokenVerificationError, match="expired"):
        auth_module.verify_token(token)


def test_wrong_signature_raises():
    token = _make_token(secret="a-completely-different-secret")
    with pytest.raises(auth_module.TokenVerificationError):
        auth_module.verify_token(token)


def test_wrong_audience_raises():
    token = _make_token(aud="some-other-audience")
    with pytest.raises(auth_module.TokenVerificationError):
        auth_module.verify_token(token)


def test_missing_sub_claim_raises():
    token = _make_token(sub=None)
    with pytest.raises(auth_module.TokenVerificationError, match="sub"):
        auth_module.verify_token(token)


def test_malformed_token_raises():
    with pytest.raises(auth_module.TokenVerificationError):
        auth_module.verify_token("not-a-real-jwt")
