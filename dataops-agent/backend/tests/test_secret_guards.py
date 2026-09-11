"""The app must refuse to start with a placeholder JWT secret.

config.py declares `JWT_SECRET: str = "dev-jwt-secret"`. Before this guard, a
fresh clone, a stripped CI environment, or a deploy whose .env never arrived
would boot cleanly and sign every session with that string — which is on
GitHub. Nothing would raise; logins would simply work. Item #8 rotated the
real value; this closes the fail-open path that made rotation matter in the
first place. Mirrors the existing encryption-key guard, including its test
carve-out.
"""

import pytest

from config import settings
from services.auth_service import (
    JwtSecretMisconfiguredError,
    _MIN_JWT_SECRET_LEN,
    verify_jwt_secret_configured,
)


@pytest.fixture
def outside_tests(monkeypatch):
    """The guard is a no-op under APP_ENV=test (conftest sets that), so every
    refusal case has to step outside it explicitly."""
    monkeypatch.setattr(settings, "APP_ENV", "production")


@pytest.mark.parametrize("bad", [
    "dev-jwt-secret",          # the literal config.py default
    "",                        # unset
    "   ",                     # whitespace only
    "PRATYAKSH",               # the 9-char value that was really in .env until Item #8
    "a" * (_MIN_JWT_SECRET_LEN - 1),
], ids=["placeholder", "empty", "whitespace", "old_real_9_char", "one_short"])
def test_refuses_to_start_with_a_weak_or_placeholder_secret(outside_tests, monkeypatch, bad):
    monkeypatch.setattr(settings, "JWT_SECRET", bad)
    with pytest.raises(JwtSecretMisconfiguredError):
        verify_jwt_secret_configured()


def test_accepts_a_real_secret(outside_tests, monkeypatch):
    monkeypatch.setattr(settings, "JWT_SECRET", "e4" * 32)  # 64 hex chars
    verify_jwt_secret_configured()


def test_error_message_tells_the_operator_how_to_fix_it(outside_tests, monkeypatch):
    """A guard that only says 'no' costs the next person a search. Same
    standard the encryption guard set."""
    monkeypatch.setattr(settings, "JWT_SECRET", "dev-jwt-secret")
    with pytest.raises(JwtSecretMisconfiguredError) as exc:
        verify_jwt_secret_configured()
    msg = str(exc.value)
    assert "secrets.token_hex(32)" in msg
    assert "force-recreate" in msg


def test_test_environment_is_carved_out(monkeypatch):
    """Tests run with whatever the environment provides, exactly as the
    encryption guard allows. Without this carve-out the suite could not run
    against a fresh checkout at all."""
    monkeypatch.setattr(settings, "APP_ENV", "test")
    monkeypatch.setattr(settings, "JWT_SECRET", "dev-jwt-secret")
    verify_jwt_secret_configured()  # must not raise


def test_guard_is_wired_into_startup():
    """Present in the lifespan hook, not merely defined."""
    import inspect
    import main
    src = inspect.getsource(main.lifespan)
    assert "verify_jwt_secret_configured()" in src
    assert "verify_encryption_key_configured()" in src
