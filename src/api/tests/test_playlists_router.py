"""Router tests for /playlists — verifies HTTP layer behaviour with a mocked session."""

import uuid

# ---------------------------------------------------------------------------
# GET /playlists
# ---------------------------------------------------------------------------


async def test_list_playlists_returns_200(client):
    r = await client.get("/playlists")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /playlists
# ---------------------------------------------------------------------------


async def test_create_playlist_missing_name_returns_422(client):
    r = await client.post("/playlists", json={})
    assert r.status_code == 422


async def test_create_playlist_name_only_description_returns_422(client):
    r = await client.post("/playlists", json={"description": "no name"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# GET /playlists/{id}
# ---------------------------------------------------------------------------


async def test_get_playlist_not_found(client):
    """With mock session returning None, playlist lookup should 404."""
    r = await client.get(f"/playlists/{uuid.uuid4()}")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PUT /playlists/{id}
# ---------------------------------------------------------------------------


async def test_update_playlist_not_found(client):
    r = await client.put(
        f"/playlists/{uuid.uuid4()}",
        json={"name": "P", "description": None, "items": []},
    )
    assert r.status_code == 404


async def test_update_playlist_missing_name_returns_422(client):
    r = await client.put(
        f"/playlists/{uuid.uuid4()}",
        json={"description": "no name", "items": []},  # name is required
    )
    assert r.status_code == 422


async def test_update_playlist_item_missing_url_returns_422(client):
    r = await client.put(
        f"/playlists/{uuid.uuid4()}",
        json={"name": "P", "description": None, "items": [{"title": "slide"}]},
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /playlists/{id}
# ---------------------------------------------------------------------------


async def test_delete_playlist_not_found(client):
    """With mock session returning None, delete should 404."""
    r = await client.delete(f"/playlists/{uuid.uuid4()}")
    assert r.status_code == 404
