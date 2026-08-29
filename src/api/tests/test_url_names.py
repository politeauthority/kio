"""A kiosk's current URL resolves to the saved URL it was registered as."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.url_names import annotate_url_names, match_saved_url, normalize_url
from tests.conftest import make_kiosk

# --- normalisation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://grafana.lan/d/abc/", "https://grafana.lan/d/abc"),
        ("HTTPS://Grafana.LAN/d/abc", "https://grafana.lan/d/abc"),
        ("https://grafana.lan:443/d/abc", "https://grafana.lan/d/abc"),
        ("http://grafana.lan:80/d/abc", "http://grafana.lan/d/abc"),
        ("https://grafana.lan/d/abc#panel-3", "https://grafana.lan/d/abc"),
        ("  https://grafana.lan/d/abc  ", "https://grafana.lan/d/abc"),
    ],
)
def test_normalize_url_equates_equivalent_forms(a, b):
    assert normalize_url(a) == normalize_url(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("https://grafana.lan/d/abc?panelId=3", "https://grafana.lan/d/abc"),
        ("https://grafana.lan:3000/d/abc", "https://grafana.lan/d/abc"),
        ("https://grafana.lan/d/abc", "http://grafana.lan/d/abc"),
        ("https://grafana.lan/d/ABC", "https://grafana.lan/d/abc"),
    ],
)
def test_normalize_url_keeps_real_differences(a, b):
    assert normalize_url(a) != normalize_url(b)


def test_normalize_url_empty_and_junk():
    assert normalize_url(None) == ""
    assert normalize_url("") == ""
    assert normalize_url("about:blank") == "about:blank"
    assert normalize_url("not a url/") == "not a url"


# --- matching ---------------------------------------------------------------------


def _saved(name, url):
    return SimpleNamespace(id=uuid.uuid4(), name=name, url=url)


def test_match_saved_url_finds_equivalent_form():
    office = _saved("Grafana — Office", "https://grafana.lan/d/office/")
    assert match_saved_url("HTTPS://grafana.lan/d/office", [_saved("Other", "https://x/"), office]) is office


def test_match_saved_url_none_when_unregistered():
    assert match_saved_url("https://news.example", [_saved("Grafana", "https://grafana.lan")]) is None
    assert match_saved_url(None, [_saved("Grafana", "https://grafana.lan")]) is None


# --- annotate ---------------------------------------------------------------------


def _session_with_saved(rows):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    return session


async def test_annotate_sets_name_and_id_for_matches():
    office = _saved("Grafana — Office", "https://grafana.lan/d/office")
    k1 = make_kiosk(name="Office", current_url="https://grafana.lan/d/office/")
    k2 = make_kiosk(name="Lobby", current_url="https://news.example")
    k3 = make_kiosk(name="Idle", current_url=None)
    session = _session_with_saved([office])

    await annotate_url_names(session, [k1, k2, k3])

    assert (k1.current_url_name, k1.current_saved_url_id) == ("Grafana — Office", office.id)
    assert (k2.current_url_name, k2.current_saved_url_id) == (None, None)
    assert (k3.current_url_name, k3.current_saved_url_id) == (None, None)


async def test_annotate_skips_query_when_no_kiosk_has_a_url():
    k = make_kiosk(current_url=None)
    session = _session_with_saved([])
    await annotate_url_names(session, [k])
    session.execute.assert_not_awaited()
    assert k.current_url_name is None


# --- through the router ----------------------------------------------------------


async def test_list_kiosks_carries_url_name(client):
    office = _saved("Grafana — Office", "https://grafana.lan/d/office")
    kiosk = make_kiosk(name="Office", current_url="https://grafana.lan/d/office/")
    with (
        patch("app.routers.kiosks.kiosk_service.get_all", new_callable=AsyncMock, return_value=[kiosk]),
        patch("app.routers.kiosks.annotate_url_names", new_callable=AsyncMock) as annotate,
    ):
        async def _fake(session, kiosks):
            for k in kiosks:
                k.current_url_name = office.name
                k.current_saved_url_id = office.id

        annotate.side_effect = _fake
        r = await client.get("/kiosks")

    assert r.status_code == 200
    body = r.json()[0]
    assert body["current_url_name"] == "Grafana — Office"
    assert body["current_saved_url_id"] == str(office.id)
    assert body["current_url"] == "https://grafana.lan/d/office/"


async def test_list_kiosks_without_match_has_null_name(client):
    kiosk = make_kiosk(current_url="https://news.example")
    with patch("app.routers.kiosks.kiosk_service.get_all", new_callable=AsyncMock, return_value=[kiosk]):
        r = await client.get("/kiosks")
    assert r.status_code == 200
    assert r.json()[0]["current_url_name"] is None
    assert r.json()[0]["current_saved_url_id"] is None
