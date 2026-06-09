import httpx


def test_login_valid(api_url, auth_token):
    assert isinstance(auth_token, str)
    assert len(auth_token) > 20


def test_login_invalid_credentials(api_url):
    r = httpx.post(
        f"{api_url}/auth/login",
        json={"username": "wrong", "password": "wrong"},
        timeout=5,
    )
    assert r.status_code == 401


def test_unauthenticated_request_returns_401(api_url):
    r = httpx.get(f"{api_url}/kiosks", timeout=5)
    assert r.status_code == 401
