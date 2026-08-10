import hashlib
import hmac
import secrets
from collections import defaultdict, deque
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
from app.modules.imports.models import ExtensionDeviceBinding
from app.modules.imports.models import ExtensionPairingCode
from app.modules.workspace.models import WorkspaceMember


PAIRING_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


class PairingCodeUnavailable(ValueError):
    pass


class PairingCodeRateLimited(ValueError):
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
        attempts: dict[str, deque[datetime]] | None = None,
    ) -> None:
        self._session = session
        self._now = now or (lambda: datetime.now(UTC))
        self._attempts = attempts if attempts is not None else defaultdict(deque)

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

    def _record_attempt(self, client_id: str, now: datetime) -> None:
        attempts = self._attempts[client_id]
        window_start = now - timedelta(minutes=1)
        while attempts and attempts[0] <= window_start:
            attempts.popleft()
        if len(attempts) >= get_settings().rate_limit_auth_per_minute:
            raise PairingCodeRateLimited
        attempts.append(now)

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
        self._record_attempt(client_id, current)
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
        if (
            record is None
            or record.used_at is not None
            or record.revoked_at is not None
            or record.expires_at <= current
        ):
            raise PairingCodeUnavailable
        record.used_at = current
        device_binding_id = None
        if device_id is not None:
            if (
                device_public_key_jwk is None
                or extension_version is None
                or device_label is None
                or redis is None
            ):
                raise PairingCodeUnavailable
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
        self._session.flush()
        return issued


__all__ = [
    "CreatedPairingCode",
    "ExtensionPairingService",
    "PairingCodeRateLimited",
    "PairingCodeUnavailable",
]
