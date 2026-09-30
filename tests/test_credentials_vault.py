import json

import pytest

from alpha_workbench.credentials import MemoryCredentialVault


def test_memory_vault_returns_redacted_value_and_metadata_without_secret() -> None:
    vault = MemoryCredentialVault()
    metadata = vault.set("eodhd", "top-secret", account="research")
    value = vault.get("eodhd", account="research")
    assert value is not None
    assert value.reveal() == "top-secret"
    assert "top-secret" not in repr(value)
    assert "top-secret" not in str(value)
    assert "top-secret" not in json.dumps(metadata.to_dict())
    assert vault.list()[0].account == "research"


def test_memory_vault_deletes_and_validates_credentials() -> None:
    vault = MemoryCredentialVault()
    with pytest.raises(ValueError):
        vault.set("", "secret")
    with pytest.raises(ValueError):
        vault.set("provider", "")
    vault.set("provider", "secret")
    assert vault.delete("provider")
    assert vault.get("provider") is None
    assert not vault.delete("provider")
