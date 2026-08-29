"""Features must survive a reinstall and a detect run (issue #50).

Two writers and one reader share /etc/kio/kiosk.yaml: the agent's save_features()
(PyYAML), setup.sh's config template, and setup.sh's yaml_get_features() which
carries features across a self-update. These tests pin the contract between them,
plus the two agent-side guards: a TV in standby must not read as "no CEC", and a
node whose local list was wiped adopts the server's copy — but an empty list
stays an empty list.
"""

import os
import subprocess
import textwrap
from types import SimpleNamespace

import pytest
import yaml
from kio_agent import config, hardware
from kio_agent.agent import KioAgent

SETUP_SH = os.path.join(os.path.dirname(config.__file__), "..", "setup.sh")


def _yaml_get_features(config_path) -> tuple[str, int, str]:
    """Run setup.sh's real yaml_get_features() against a config file.

    Extracts the function body from setup.sh so the test exercises the shipped
    parser, not a copy of it. Returns (stdout, returncode, stderr).
    """
    with open(SETUP_SH) as f:
        src = f.read()
    start = src.index("yaml_get_features() {")
    end = src.index("\n}\n", start) + 3
    script = src[start:end] + f'\nCONFIG_FILE="{config_path}"\nyaml_get_features\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    return r.stdout.strip(), r.returncode, r.stderr.strip()


def _write(tmp_path, body):
    p = tmp_path / "kiosk.yaml"
    p.write_text(textwrap.dedent(body).lstrip())
    return p


# --- setup.sh parser -----------------------------------------------------------


@pytest.mark.parametrize(
    "body, expected",
    [
        # What PyYAML's default dumper writes: items flush-left. This is the shape
        # that used to parse as '' and wipe the node's features on self-update.
        (
            """
            api:
              token: t
            features:
            - brightness
            - cec
            start_url: ''
            """,
            "brightness,cec",
        ),
        # What setup.sh's own template writes.
        (
            """
            start_url: x
            features:
              - display_power
              - input_switch

            api:
              url: u
            """,
            "display_power,input_switch",
        ),
        ("features: a,b\napi:\n  url: u\n", "a,b"),
        ("features: [cec, display_power]\napi:\n  url: u\n", "cec,display_power"),
        ("features: []\napi:\n  url: u\n", ""),
        ("features:\napi:\n  url: u\n", ""),
        ("api:\n  url: u\n", ""),
    ],
)
def test_setup_parser_reads_every_features_shape(tmp_path, body, expected):
    out, rc, _ = _yaml_get_features(_write(tmp_path, body))
    assert rc == 0
    assert out == expected


def test_setup_parser_refuses_unparseable_block(tmp_path):
    """A features block it can't read must abort the reinstall, not silently
    rewrite the config without it."""
    _, rc, err = _yaml_get_features(_write(tmp_path, "features:\n  weird: yes\napi:\n  url: u\n"))
    assert rc == 1
    assert "refusing to rewrite" in err


# --- agent writer <-> setup.sh reader ------------------------------------------


def test_save_features_round_trips_through_setup_parser(tmp_path, monkeypatch):
    cfg_path = _write(
        tmp_path,
        """
        start_url: ''
        api:
          url: https://api.local
          token: t
        mqtt:
          host: h
        """,
    )
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_path))

    config.save_features(["input_switch", "display_power", "cec"])

    text = cfg_path.read_text()
    assert "  - input_switch" in text, "list items must be indented for setup.sh"
    assert yaml.safe_load(text)["features"] == ["input_switch", "display_power", "cec"]
    assert yaml.safe_load(text)["start_url"] == ""
    out, rc, _ = _yaml_get_features(cfg_path)
    assert rc == 0
    assert out == "input_switch,display_power,cec"
    # And the agent reads its own file back the same way.
    assert config.load_config()["features"] == ["input_switch", "display_power", "cec"]


def test_save_features_empty_list_stays_empty_list(tmp_path, monkeypatch):
    cfg_path = _write(tmp_path, "api:\n  url: u\n  token: t\nfeatures:\n  - cec\n")
    monkeypatch.setattr(config, "CONFIG_FILE", str(cfg_path))

    config.save_features([])

    assert yaml.safe_load(cfg_path.read_text())["features"] == []
    assert config.load_config()["features"] == []
    out, rc, _ = _yaml_get_features(cfg_path)
    assert (out, rc) == ("", 0)


# --- CEC probe: a TV in standby is not "unsupported" ----------------------------


def _cec_run(physical: str):
    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=f"\tPhysical Address: {physical}\n", stderr="")

    return fake_run


def test_probe_cec_standby_display_is_unknown(monkeypatch):
    monkeypatch.setattr(hardware.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(hardware.subprocess, "run", _cec_run("f.f.f.f"))
    monkeypatch.setattr(hardware.time, "sleep", lambda _s: None)
    status, _ = hardware._probe_cec()
    assert status == "unknown"


def test_probe_cec_display_on_bus_is_supported(monkeypatch):
    monkeypatch.setattr(hardware.os.path, "exists", lambda _p: True)
    monkeypatch.setattr(hardware.subprocess, "run", _cec_run("1.0.0.0"))
    status, _ = hardware._probe_cec()
    assert status == "supported"


def test_probe_cec_no_adapter_is_unsupported(monkeypatch):
    monkeypatch.setattr(hardware.os.path, "exists", lambda _p: False)
    status, _ = hardware._probe_cec()
    assert status == "unsupported"


# --- adopting the server's copy ------------------------------------------------


def _agent_with(features, monkeypatch):
    import kio_agent.agent as agent_mod

    saved = []
    reported = []
    monkeypatch.setattr(agent_mod, "save_features", lambda f: saved.append(list(f)))
    monkeypatch.setattr(agent_mod, "_report_command", lambda *a, **k: reported.append(a))
    a = KioAgent.__new__(KioAgent)
    a.features = list(features)
    return a, saved, reported


def test_adopts_server_features_when_local_is_empty(monkeypatch):
    a, saved, reported = _agent_with([], monkeypatch)
    a._adopt_server_features(["display_power", "cec", "display_power"])
    assert a.features == ["cec", "display_power"]
    assert saved == [["cec", "display_power"]]
    assert reported and reported[0][0] == "features_restored"


def test_empty_local_stays_empty_when_server_is_empty(monkeypatch):
    for server in ([], None):
        a, saved, reported = _agent_with([], monkeypatch)
        a._adopt_server_features(server)
        assert a.features == []
        assert saved == [] and reported == []


def test_never_overrides_a_non_empty_local_list(monkeypatch):
    a, saved, _ = _agent_with(["cec"], monkeypatch)
    a._adopt_server_features(["cec", "display_power"])
    assert a.features == ["cec"]
    assert saved == []
