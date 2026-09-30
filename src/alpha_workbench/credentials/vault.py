"""OS-backed credential vault and a deterministic test backend.

Secrets are intentionally absent from metadata, JSON, and repr output.  Code
that needs to call a provider must explicitly invoke ``SecretValue.reveal``;
ordinary logging and serialization only see ``<redacted>``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("secret must not be empty")
        self._value = value

    def reveal(self) -> str:
        """Return the secret only at the provider boundary."""

        return self._value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def __str__(self) -> str:
        return "<redacted>"

    def __bool__(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class CredentialMetadata:
    provider: str
    account: str
    updated_at: datetime
    present: bool = True

    def to_dict(self) -> dict[str, str | bool]:
        timestamp = self.updated_at.astimezone(UTC).isoformat()
        return {
            "provider": self.provider,
            "account": self.account,
            "updated_at": timestamp,
            "present": self.present,
        }


class CredentialVault(Protocol):
    def set(
        self, provider: str, secret: str, *, account: str = "default"
    ) -> CredentialMetadata: ...

    def get(self, provider: str, *, account: str = "default") -> SecretValue | None: ...

    def delete(self, provider: str, *, account: str = "default") -> bool: ...

    def list(self) -> list[CredentialMetadata]: ...


def _validate(provider: str, account: str) -> None:
    if not provider.strip() or not account.strip():
        raise ValueError("provider and account must not be empty")
    if any(character in provider + account for character in "\r\n"):
        raise ValueError("provider and account must not contain newlines")


class MemoryCredentialVault:
    """A fake backend used by tests; never writes plaintext to disk."""

    def __init__(self) -> None:
        self._secrets: dict[tuple[str, str], str] = {}
        self._updated: dict[tuple[str, str], datetime] = {}

    def set(self, provider: str, secret: str, *, account: str = "default") -> CredentialMetadata:
        _validate(provider, account)
        if not secret:
            raise ValueError("secret must not be empty")
        key = (provider, account)
        now = datetime.now(UTC)
        self._secrets[key] = secret
        self._updated[key] = now
        return CredentialMetadata(provider, account, now)

    def get(self, provider: str, *, account: str = "default") -> SecretValue | None:
        _validate(provider, account)
        value = self._secrets.get((provider, account))
        return SecretValue(value) if value is not None else None

    def delete(self, provider: str, *, account: str = "default") -> bool:
        _validate(provider, account)
        key = (provider, account)
        self._updated.pop(key, None)
        return self._secrets.pop(key, None) is not None

    def list(self) -> list[CredentialMetadata]:
        return [
            CredentialMetadata(provider, account, self._updated[(provider, account)])
            for provider, account in sorted(self._secrets)
        ]


class KeyringCredentialVault:
    """Use the operating system keychain through the ``keyring`` package."""

    def __init__(self, *, service: str = "agentic-alpha-workbench") -> None:
        self.service = service
        self._updated: dict[tuple[str, str], datetime] = {}

    def _account(self, provider: str, account: str) -> str:
        _validate(provider, account)
        return f"{provider}:{account}"

    def set(self, provider: str, secret: str, *, account: str = "default") -> CredentialMetadata:
        if not secret:
            raise ValueError("secret must not be empty")
        try:
            import keyring
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("keyring is required for OS credential storage") from error
        keyring.set_password(self.service, self._account(provider, account), secret)
        now = datetime.now(UTC)
        self._updated[(provider, account)] = now
        return CredentialMetadata(provider, account, now)

    def get(self, provider: str, *, account: str = "default") -> SecretValue | None:
        try:
            import keyring
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("keyring is required for OS credential storage") from error
        value = keyring.get_password(self.service, self._account(provider, account))
        return SecretValue(value) if value else None

    def delete(self, provider: str, *, account: str = "default") -> bool:
        try:
            import keyring
        except ImportError as error:  # pragma: no cover
            raise RuntimeError("keyring is required for OS credential storage") from error
        key = self._account(provider, account)
        existing = keyring.get_password(self.service, key)
        if existing is None:
            return False
        keyring.delete_password(self.service, key)
        self._updated.pop((provider, account), None)
        return True

    def list(self) -> list[CredentialMetadata]:
        # Keyring intentionally provides no portable account enumeration API.
        # Metadata is available for credentials written through this process.
        return [
            CredentialMetadata(provider, account, timestamp)
            for (provider, account), timestamp in sorted(self._updated.items())
        ]
