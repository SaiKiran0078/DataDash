import time

import jwt
import pytest
from app.core.config import Settings
from app.core.ratelimit import RateLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    new_share_token,
    verify_password,
)

SECRET = "x" * 40


def test_password_hash_and_verify():
    h = hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong password", h)
    assert hash_password("same") != hash_password("same")  # unique salt each time


@pytest.mark.parametrize("bad", ["", "plain", "bcrypt$1$2$3$a$b", "scrypt$x$y$z$a$b", "scrypt$16384$8$1$!!$!!"])
def test_verify_rejects_malformed_hashes(bad):
    assert verify_password("anything", bad) is False


def test_token_roundtrip_and_tampering():
    token = create_access_token(42, SECRET, minutes=5)
    assert decode_access_token(token, SECRET) == 42
    assert decode_access_token(token, "y" * 40) is None            # wrong secret
    assert decode_access_token(token[:-2] + "xx", SECRET) is None   # tampered signature
    assert decode_access_token("garbage", SECRET) is None


def test_expired_and_unsigned_tokens_rejected():
    assert decode_access_token(create_access_token(1, SECRET, minutes=-1), SECRET) is None
    unsigned = jwt.encode({"sub": "1", "exp": int(time.time()) + 100}, key=None, algorithm="none")
    assert decode_access_token(unsigned, SECRET) is None            # "alg: none" attack
    no_exp = jwt.encode({"sub": "1"}, SECRET, algorithm="HS256")
    assert decode_access_token(no_exp, SECRET) is None              # tokens must expire


def test_share_tokens_are_long_and_unique():
    a, b = new_share_token(), new_share_token()
    assert a != b and len(a) >= 32


def test_rate_limiter_blocks_then_recovers():
    now = [0.0]
    rl = RateLimiter(3, 60, clock=lambda: now[0])
    assert [rl.allow("ip") for _ in range(4)] == [True, True, True, False]
    assert rl.allow("other-ip") is True                              # separate keys
    now[0] = 61
    assert rl.allow("ip") is True                                    # window passed


def test_production_requires_strong_secret():
    with pytest.raises(RuntimeError):
        Settings(env="production", secret_key="dev-only-secret-change-me-please").validate_for_production()
    Settings(env="production", secret_key="a" * 40).validate_for_production()
