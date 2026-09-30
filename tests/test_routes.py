import pytest
from tvcontrol.app import create_app
from tvcontrol.config import carregar_config
from tvcontrol.auth import gerar_codigo_pareamento, rate_limiter

@pytest.fixture
def app():
    app = create_app({"TESTING": True})
    return app

@pytest.fixture
def client(app):
    return app.test_client()

def test_unauthenticated_index_returns_401(client):
    res = client.get('/')
    assert res.status_code == 401
    assert 'IgnoControl' in res.get_data(as_text=True)

def test_host_header_validation_blocks_dns_rebinding(client):
    res = client.get('/', headers={'Host': 'malicious-attacker.com'})
    assert res.status_code == 400

def test_security_headers_present_on_all_responses(client):
    res = client.get('/')
    headers = res.headers
    assert headers.get('X-Content-Type-Options') == 'nosniff'
    assert headers.get('X-Frame-Options') == 'DENY'
    assert headers.get('Referrer-Policy') == 'no-referrer'
    assert 'default-src' in headers.get('Content-Security-Policy', '')

def test_manifest_does_not_leak_token(client):
    res = client.get('/manifest.json')
    assert res.status_code == 200
    data = res.get_json()
    assert data.get('start_url') == '/'
    assert 'token' not in data.get('start_url')

def test_qrcode_requires_auth_or_localhost(client):
    # From external IP without auth -> 401
    res = client.get('/qrcode', environ_base={'REMOTE_ADDR': '198.51.100.2'})
    assert res.status_code == 401

    # From localhost -> 200 PNG
    res_local = client.get('/qrcode', environ_base={'REMOTE_ADDR': '127.0.0.1'})
    assert res_local.status_code == 200
    assert res_local.mimetype == 'image/png'

def test_single_use_pairing_qr_code(client):
    code = gerar_codigo_pareamento()
    # First use: redirects and sets session cookie
    res = client.get(f'/?pair={code}')
    assert res.status_code == 302
    assert 'ignocontrol_session' in res.headers.get('Set-Cookie', '')

    # Second use: fails with 401
    res2 = client.get(f'/?pair={code}')
    assert res2.status_code == 401

def test_action_routes_reject_get(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)
    actions = ['/play', '/vol-up', '/vol-down', '/poweroff', '/exec/test']
    for route in actions:
        res = client.get(route)
        assert res.status_code == 405

def test_timer_set_input_validation(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    # Valid: 30 minutes
    res_valid = client.post('/timer/set', json={'minutes': 30})
    assert res_valid.status_code == 200

    # Invalid: 0 minutes
    res_zero = client.post('/timer/set', json={'minutes': 0})
    assert res_zero.status_code == 400

    # Invalid: string
    res_str = client.post('/timer/set', json={'minutes': 'abc'})
    assert res_str.status_code == 400

def test_key_whitelist_validation(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    # Valid key
    res_valid = client.post('/key', json={'key': 'Return'})
    assert res_valid.status_code in (200, 500) # May return 200 if simulation tool succeeds

    # Invalid key
    res_invalid = client.post('/key', json={'key': 'ctrl+alt+F2'})
    assert res_invalid.status_code == 400

def test_mouse_routes(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    res_move = client.post('/mouse/move?dx=10&dy=-5')
    assert res_move.status_code == 200

    res_click = client.post('/mouse/click?button=1')
    assert res_click.status_code == 200

    res_scroll = client.post('/mouse/scroll?delta=1')
    assert res_scroll.status_code == 200

def test_volume_routes(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    res_get = client.get('/volume')
    assert res_get.status_code == 200
    assert 'volume' in res_get.get_json()

    res_post = client.post('/volume', json={'volume': 70, 'mute': 'toggle'})
    assert res_post.status_code == 200

def test_typing_route(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    res_type = client.post('/type', json={'text': 'hello', 'enter': True})
    assert res_type.status_code == 200

def test_media_execution_and_404(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    # 404 for unknown button
    res_404 = client.post('/exec/unknown_btn_random')
    assert res_404.status_code == 404

    # TV command intercept
    res_tv = client.post('/exec/tv-ok')
    assert res_tv.status_code == 200

def test_main_login_and_logout(client):
    token = carregar_config().get('token')

    # Successful login via form
    res_login = client.post('/login', data={'token': token})
    assert res_login.status_code == 302
    assert 'ignocontrol_session' in res_login.headers.get('Set-Cookie', '')

    # Successful login via query token and redirect to clean /
    res_token_redirect = client.get(f'/?token={token}')
    assert res_token_redirect.status_code == 302

    # Follow redirect
    res_home = client.get(f'/?token={token}', follow_redirects=True)
    assert res_home.status_code == 200
    assert 'IgnoControl' in res_home.get_data(as_text=True)

    # Logout
    res_logout = client.get('/logout')
    assert res_logout.status_code == 302
    assert 'login' in res_logout.headers.get('Location', '')

    # Static assets
    assert client.get('/favicon.ico').status_code == 204
    assert client.get('/icon.png').status_code == 200

def test_tv_ip_endpoints(client):
    token = carregar_config().get('token')
    client.set_cookie('ignocontrol_session', token)

    # 1. Get TV IP
    res_get = client.get('/api/config/tv-ip')
    assert res_get.status_code == 200
    assert 'tv_ip' in res_get.get_json()

    # 2. Update TV IP with valid IPv4
    res_post = client.post('/api/config/tv-ip', json={'tv_ip': '192.168.15.55'})
    assert res_post.status_code == 200
    assert res_post.get_json().get('tv_ip') == '192.168.15.55'

    # 3. Update TV IP with invalid IP
    res_invalid = client.post('/api/config/tv-ip', json={'tv_ip': '999.999.999.999'})
    assert res_invalid.status_code == 400

    # 4. Update TV IP empty
    res_empty = client.post('/api/config/tv-ip', json={'tv_ip': ''})
    assert res_empty.status_code == 400

    # 5. Test connection endpoint
    res_test = client.post('/api/tv/test-connection', json={'tv_ip': '127.0.0.1'})
    assert res_test.status_code == 200
    assert 'online' in res_test.get_json()

