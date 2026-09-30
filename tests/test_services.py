from tvcontrol.services.media import executar_comando_seguro
from tvcontrol.services.tv import executar_comando_tv
from tvcontrol.services.power import set_timer, cancel_timer, get_timer_status

def test_executar_comando_seguro_list():
    assert executar_comando_seguro(['true']) is True
    assert executar_comando_seguro(['false']) is False

def test_executar_comando_seguro_string_fallback():
    # First command succeeds
    assert executar_comando_seguro('true || false') is True
    # First command fails, second succeeds
    assert executar_comando_seguro('false || true') is True
    # All commands fail
    assert executar_comando_seguro('false || false') is False

def test_executar_comando_tv_validation():
    # Unknown button
    ok, err = executar_comando_tv('unknown-key', '192.168.1.100')
    assert ok is False
    assert 'desconhecido' in err

    # Invalid IP
    ok_ip, err_ip = executar_comando_tv('tv-play', 'not.an.ip')
    assert ok_ip is False
    assert 'inválido' in err_ip

def test_timer_operations():
    rem = set_timer(10)
    assert rem == 600

    active, remaining = get_timer_status()
    assert active is True
    assert remaining > 0

    cancel_timer()
    active_cancelled, rem_cancelled = get_timer_status()
    assert active_cancelled is False
    assert rem_cancelled == 0
