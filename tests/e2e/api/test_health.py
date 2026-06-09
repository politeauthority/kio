import httpx


def test_health(api_url: str):
    r = httpx.get(f"{api_url}/_health", timeout=5)
    assert r.status_code == 200
