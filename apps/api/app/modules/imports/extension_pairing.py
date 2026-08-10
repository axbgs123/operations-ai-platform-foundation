import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.imports.extension_auth import (
    ExtensionTokenService,
    IssuedExtensionToken,
)
from app.modules.imports.extension_devices import (
    DeviceRegistrationUnavailable,
    ExtensionDeviceService,
    RedisChallengeClient,
)
from app.modules.imports.models import ExtensionDeviceBinding, ExtensionPairingCode
from app.modules.imports.models import ExtensionToken
from app.modules.workspace.models import WorkspaceMember


PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class PairingCodeUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class CreatedPairingCode:
    code: str
    expires_at: datetime


class ExtensionPairingService:
    code_lifetime = timedelta(minutes=5)

    def __init__(
        self,
        session: Session,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def _normalize(code: str) -> str:
        return code.upper().replace(" ", "").replace("-", "")

    @staticmethod
    def _digest(code: str) -> str:
        secret = get_settings().session_signing_secret.get_secret_value()
        return hmac.new(
            secret.encode(), code.encode(), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _new_code() -> str:
        return "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(8))

    def _replay_fingerprint(
        self,
        *,
        code: str,
        client_id: str,
        device_id: UUID,
        public_key_jwk: dict[str, str],
        extension_version: str,
        device_label: str,
    ) -> str:
        payload = json.dumps(
            {
                "client_id": client_id,
                "device_id": str(device_id),
                "device_label": device_label,
                "extension_version": extension_version,
                "public_key_jwk": public_key_jwk,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return self._digest(f"pair-replay:{self._normalize(code)}:{payload}")

    def create(self, *, workspace_id: UUID, member_id: UUID) -> CreatedPairingCode:
        current = self._now()
        member = self._session.scalar(
            select(WorkspaceMember)
            .where(
                WorkspaceMember.id == member_id,
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if member is None:
            raise PairingCodeUnavailable

        self._session.execute(
            update(ExtensionPairingCode)
            .where(
                ExtensionPairingCode.workspace_id == workspace_id,
                ExtensionPairingCode.member_id == member_id,
                ExtensionPairingCode.used_at.is_(None),
                ExtensionPairingCode.revoked_at.is_(None),
            )
            .values(revoked_at=current)
        )
        while True:
            code = self._new_code()
            digest = self._digest(code)
            if self._session.scalar(
                select(ExtensionPairingCode.id).where(
                    ExtensionPairingCode.code_digest == digest
                )
            ) is None:
                break
        expires_at = current + self.code_lifetime
        self._session.add(
            ExtensionPairingCode(
                workspace_id=workspace_id,
                member_id=member_id,
                code_digest=digest,
                created_at=current,
                expires_at=expires_at,
            )
        )
        self._session.flush()
        return CreatedPairingCode(code=code, expires_at=expires_at)

    def redeem(
        self,
        code: str,
        *,
        client_id: str,
        device_id: UUID | None = None,
        device_public_key_jwk: dict[str, str] | None = None,
        extension_version: str | None = None,
        device_label: str | None = None,
        redis: RedisChallengeClient | None = None,
    ) -> IssuedExtensionToken:
        current = self._now()
        digest = self._digest(self._normalize(code))
        pairing = self._session.execute(
            select(
                ExtensionPairingCode.workspace_id,
                ExtensionPairingCode.member_id,
            )
            .where(ExtensionPairingCode.code_digest == digest)
        ).one_or_none()
        if pairing is None:
            raise PairingCodeUnavailable
        member = self._session.scalar(
            select(WorkspaceMember)
            .where(
                WorkspaceMember.id == pairing.member_id,
                WorkspaceMember.workspace_id == pairing.workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
            .with_for_update()
        )
        if member is None:
            raise PairingCodeUnavailable
        record = self._session.scalar(
            select(ExtensionPairingCode)
            .where(ExtensionPairingCode.code_digest == digest)
            .with_for_update()
        )
        if record is None or record.revoked_at is not None or record.expires_at <= current:
            raise PairingCodeUnavailable
        replay_fingerprint = None
        if device_id is not None:
            if (
                device_public_key_jwk is None
                or extension_version is None
                or device_label is None
                or redis is None
            ):
                raise PairingCodeUnavailable
            replay_fingerprint = self._replay_fingerprint(
                code=code,
                client_id=client_id,
                device_id=device_id,
                public_key_jwk=device_public_key_jwk,
                extension_version=extension_version,
                device_label=device_label,
            )
        if record.used_at is not None:
            if replay_fingerprint is None:
                raise PairingCodeUnavailable
            previous = self._session.scalar(
                select(ExtensionToken).where(
                    ExtensionToken.exchange_fingerprint == replay_fingerprint
                )
            )
            binding = (
                self._session.get(ExtensionDeviceBinding, previous.device_id)
                if previous is not None and previous.device_id is not None
                else None
            )
            if (
                previous is None
                or binding is None
                or binding.workspace_id != record.workspace_id
                or binding.member_id != record.member_id
                or binding.device_id != device_id
                or binding.revoked_at is not None
                or binding.public_key_jwk != device_public_key_jwk
                or binding.extension_version != extension_version
                or binding.label != device_label
            ):
                raise PairingCodeUnavailable
            return ExtensionTokenService(self._session, now=self._now).issue(
                workspace_id=record.workspace_id,
                member_id=record.member_id,
                client_id=client_id,
                device_id=binding.id,
                now=current,
            )
        record.used_at = current
        device_binding_id = None
        if device_id is not None:
            assert device_public_key_jwk is not None
            assert extension_version is not None
            assert device_label is not None
            assert redis is not None
            devices = ExtensionDeviceService(self._session, redis=redis, now=self._now)
            try:
                registered = devices.register_device(
                    workspace_id=record.workspace_id,
                    member_id=record.member_id,
                    device_id=device_id,
                    public_key_jwk=device_public_key_jwk,
                    extension_version=extension_version,
                    label=device_label,
                )
                device_binding_id = registered.id
            except DeviceRegistrationUnavailable:
                existing = self._session.scalar(
                    select(ExtensionDeviceBinding).where(
                        ExtensionDeviceBinding.device_id == device_id
                    )
                )
                if (
                    existing is None
                    or existing.workspace_id != record.workspace_id
                    or existing.member_id != record.member_id
                    or existing.revoked_at is not None
                    or existing.public_key_jwk != device_public_key_jwk
                    or existing.extension_version != extension_version
                    or existing.label != device_label
                ):
                    raise PairingCodeUnavailable from None
                device_binding_id = existing.id
        issued = ExtensionTokenService(self._session, now=self._now).issue(
            workspace_id=record.workspace_id,
            member_id=record.member_id,
            client_id=client_id,
            device_id=device_binding_id,
            now=current,
        )
        if replay_fingerprint is not None:
            token = self._session.get(ExtensionToken, issued.token_id)
            assert token is not None
            token.exchange_fingerprint = replay_fingerprint
        self._session.flush()
        return issued


__all__ = [
    "CreatedPairingCode",
    "ExtensionPairingService",
    "PairingCodeUnavailable",
]
