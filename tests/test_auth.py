import time
from tvcontrol.auth import (
    validar_token, RateLimiter, gerar_codigo_pareamento, consumir_codigo_pareamento
)

def test_validar_token_constant_time():
    assert validar_token("secret123", "secret123") is True
    assert validar_token("secret123", "wrong") is False
    assert validar_token("", "secret123") is False
    assert validar_token(None, "secret123") is False

def test_rate_limiter_blocks_after_10_failures():
    limiter = RateLimiter()
    ip = "192.168.1.50"
    for _ in range(9):
        assert limiter.is_ip_blocked(ip) is False
        limiter.record_failed_login(ip)

    # 10th failure
    assert limiter.is_ip_blocked(ip) is False
    limiter.record_failed_login(ip)

    # Now blocked
    assert limiter.is_ip_blocked(ip) is True

    # Reset
    limiter.reset_failed_login(ip)
    assert limiter.is_ip_blocked(ip) is False

def test_rate_limiter_frequency_per_endpoint():
    limiter = RateLimiter()
    ip = "192.168.1.50"
    endpoint = "/mouse/move"
    for _ in range(10):
        assert limiter.check_rate_limit(ip, endpoint, max_per_sec=10) is True
    # 11th request in same second should be rate limited
    assert limiter.check_rate_limit(ip, endpoint, max_per_sec=10) is False

def test_ephemeral_pairing_code_single_use():
    code = gerar_codigo_pareamento()
    assert isinstance(code, str)
    assert len(code) > 10

    # First consumption succeeds
    assert consumir_codigo_pareamento(code) is True
    # Second consumption of the same code must fail
    assert consumir_codigo_pareamento(code) is False

def test_pairing_code_expiration():
    from tvcontrol import auth
    code = gerar_codigo_pareamento()
    # Expire it manually
    auth.PAIRING_CODES[code] = time.time() - 1
    assert consumir_codigo_pareamento(code) is False
