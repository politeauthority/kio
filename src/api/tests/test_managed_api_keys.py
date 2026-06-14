"""Regression tests for the managed API key serialization.

The create endpoint must return the freshly generated plaintext `key`. The
plaintext exists only at creation time and is never stored on the ORM row, so
validating ApiKeyCreated directly against the row raised `key: Field required`
(every create 500'd while still committing an unusable row). See
routers/managed_api_keys.py::create_api_key.
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.api_key import ApiKey, generate_key
from app.routers.managed_api_keys import ApiKeyCreated, ApiKeyRead


def _row() -> ApiKey:
    return ApiKey(
        id=uuid.uuid4(),
        name="staging",
        key_prefix="kio_abcdef12",
        token_hash="0" * 64,
        created_at=datetime.now(timezone.utc),
        last_used_at=None,
        is_active=True,
    )


def test_created_response_includes_plaintext_key():
    obj = _row()
    key = generate_key()
    result = ApiKeyCreated(**ApiKeyRead.model_validate(obj).model_dump(), key=key)
    assert result.key == key
    assert result.name == "staging"
    assert result.key_prefix == "kio_abcdef12"
    assert result.is_active is True


def test_validating_created_against_row_is_the_bug():
    # Documents why the old `ApiKeyCreated.model_validate(obj)` path failed:
    # the row has no `key` attribute.
    with pytest.raises(ValidationError):
        ApiKeyCreated.model_validate(_row())
