"""Tests for the per-API-URL comms-state persistence in kio_agent.config."""

import json

import pytest

from kio_agent import config


@pytest.fixture
def comms_file(tmp_path, monkeypatch):
    path = tmp_path / "comms-state.json"
    monkeypatch.setattr(config, "COMMS_FILE", str(path))
    return path


def test_load_missing_file_returns_empty(comms_file):
    assert config._load_comms_state() == {}


def test_record_then_load_roundtrip(comms_file):
    config.record_api_contact("https://api.one", last_event="heartbeat", kiosk_id="k1")
    state = config._load_comms_state()
    rec = state["https://api.one"]
    assert rec["last_event"] == "heartbeat"
    assert rec["kiosk_id"] == "k1"
    assert "last_contact_at" in rec
    assert isinstance(rec["last_contact_epoch"], float)


def test_record_keeps_separate_records_per_url(comms_file):
    config.record_api_contact("https://api.one", kiosk_id="k1")
    config.record_api_contact("https://api.two", kiosk_id="k2")
    state = config._load_comms_state()
    assert set(state) == {"https://api.one", "https://api.two"}
    assert state["https://api.one"]["kiosk_id"] == "k1"
    assert state["https://api.two"]["kiosk_id"] == "k2"


def test_record_merges_without_dropping_prior_fields(comms_file):
    config.record_api_contact("https://api.one", certs_synced_at="t1")
    config.record_api_contact("https://api.one", hosts_synced_at="t2")
    rec = config._load_comms_state()["https://api.one"]
    assert rec["certs_synced_at"] == "t1"  # preserved across the second write
    assert rec["hosts_synced_at"] == "t2"


def test_record_with_empty_url_is_noop(comms_file):
    config.record_api_contact("", kiosk_id="k1")
    assert config._load_comms_state() == {}


def test_seconds_since_last_contact_recent(comms_file):
    config.record_api_contact("https://api.one")
    gap = config.seconds_since_last_contact("https://api.one")
    assert gap is not None
    assert 0.0 <= gap < 5.0


def test_seconds_since_last_contact_unknown_url_is_none(comms_file):
    config.record_api_contact("https://api.one")
    assert config.seconds_since_last_contact("https://api.other") is None


def test_seconds_since_last_contact_from_old_epoch(comms_file):
    comms_file.write_text(json.dumps({"https://api.one": {"last_contact_epoch": 1000.0}}))
    gap = config.seconds_since_last_contact("https://api.one")
    assert gap is not None
    assert gap > 1_000_000  # far in the past
