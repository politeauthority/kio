"""Tests for config loading and TLS-verify resolution."""

import textwrap

import pytest

from kio_agent import config, runtime

# --- resolve_tls_verify -----------------------------------------------------


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off", "  OFF  "])
def test_resolve_tls_verify_disables_for_falsey_strings(value):
    assert runtime.resolve_tls_verify(value) is False


def test_resolve_tls_verify_disables_for_bool_false():
    assert runtime.resolve_tls_verify(False) is False


def test_resolve_tls_verify_returns_explicit_bundle_path():
    assert runtime.resolve_tls_verify("/etc/ssl/my-ca.crt") == "/etc/ssl/my-ca.crt"


def test_resolve_tls_verify_true_without_system_bundle(monkeypatch):
    monkeypatch.setattr(runtime.os.path, "exists", lambda _p: False)
    assert runtime.resolve_tls_verify(True) is True


def test_resolve_tls_verify_true_uses_system_bundle_when_present(monkeypatch):
    monkeypatch.setattr(runtime.os.path, "exists", lambda _p: True)
    assert runtime.resolve_tls_verify(True) == runtime._SYSTEM_CA_BUNDLE


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", ""])
def test_resolve_tls_verify_truthy_strings_fall_through_to_system(value, monkeypatch):
    monkeypatch.setattr(runtime.os.path, "exists", lambda _p: False)
    assert runtime.resolve_tls_verify(value) is True


# --- load_config ------------------------------------------------------------


def _write_config(tmp_path, body):
    p = tmp_path / "kiosk.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_load_config_full(tmp_path, monkeypatch):
    cfg_path = _write_config(
        tmp_path,
        """
        id: kiosk-1
        api:
          url: https://api.example.com/
          token: secret-token
          tls_verify: false
        mqtt:
          host: broker.example.com
          port: 8883
          topic_prefix: kio/stg
        features: cec, brightness
        start_url: https://home.example.com
        """,
    )
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_path))
    cfg = config.load_config()

    assert cfg["kiosk_id"] == "kiosk-1"
    assert cfg["api_url"] == "https://api.example.com"  # trailing slash stripped
    assert cfg["api_token"] == "secret-token"
    assert cfg["tls_verify"] is False
    assert cfg["mqtt_host"] == "broker.example.com"
    assert cfg["mqtt_port"] == 8883
    assert cfg["topic_prefix"] == "kio/stg"
    # Comma-separated feature string is split into a list.
    assert cfg["features"] == ["cec", "brightness"]
    assert cfg["start_url"] == "https://home.example.com"


def test_load_config_defaults(tmp_path, monkeypatch):
    cfg_path = _write_config(
        tmp_path,
        """
        api:
          url: http://api.local
          token: t
        """,
    )
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_path))
    cfg = config.load_config()

    assert cfg["kiosk_id"] == ""  # absent id -> empty fallback
    assert cfg["tls_verify"] is True  # default
    assert cfg["mqtt_host"] == ""
    assert cfg["mqtt_port"] == 1883
    assert cfg["topic_prefix"] == "kio/prd"
    assert cfg["features"] == []
    assert cfg["start_url"] == "about:blank"


def test_load_config_features_as_list(tmp_path, monkeypatch):
    cfg_path = _write_config(
        tmp_path,
        """
        api:
          url: http://api.local
          token: t
        features:
          - cec
          - input_switch
        """,
    )
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_path))
    cfg = config.load_config()
    assert cfg["features"] == ["cec", "input_switch"]
