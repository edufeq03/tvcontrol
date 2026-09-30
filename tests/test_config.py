import pytest
from tvcontrol.config import validar_config

def test_valid_config():
    valid_cfg = {
        "token": "a" * 32,
        "porta": 7000,
        "titulo": "Test",
        "tv_ip": "192.168.1.100",
        "botoes": [
            {"id": "play", "label": "Play/Pause", "comando": "playerctl play-pause"}
        ]
    }
    assert validar_config(valid_cfg) is True

def test_config_invalid_token():
    with pytest.raises(ValueError, match="Token de autenticação inválido"):
        validar_config({"token": "minhachave123", "porta": 7000})

    with pytest.raises(ValueError, match="Token de autenticação inválido"):
        validar_config({"token": "", "porta": 7000})

def test_config_invalid_port():
    with pytest.raises(ValueError, match="Porta inválida"):
        validar_config({"token": "valid_token_1234567890_abcdef", "porta": 99999})

    with pytest.raises(ValueError, match="Porta inválida"):
        validar_config({"token": "valid_token_1234567890_abcdef", "porta": "7000"})

def test_config_invalid_tv_ip():
    with pytest.raises(ValueError, match="IP da TV inválido"):
        validar_config({
            "token": "valid_token_1234567890_abcdef",
            "porta": 7000,
            "tv_ip": "not_an_ip"
        })

def test_config_invalid_buttons():
    with pytest.raises(ValueError, match="botoes.*deve ser uma lista"):
        validar_config({
            "token": "valid_token_1234567890_abcdef",
            "porta": 7000,
            "botoes": "not_a_list"
        })

    with pytest.raises(ValueError, match="caracteres especiais"):
        validar_config({
            "token": "valid_token_1234567890_abcdef",
            "porta": 7000,
            "botoes": [{"id": "bad;id", "label": "Bad"}]
        })
