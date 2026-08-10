import base64
import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.imports.extension_auth import (
    AuthenticatedExtension,
    ExtensionTokenService,
    IssuedExtensionToken,
)
from app.modules.imports.models import ExtensionDeviceBinding
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


EXTENSION_CLIENT_ID = "operations-capture-extension"


class RedisChallengeClient(Protocol):
    def set(self, name: str, value: str, *, ex: int, nx: bool) -> object: ...

    def eval(self, script: str, numkeys: int, *keys_and_args: str) -> object: ...


class DeviceChallengeUnavailable(ValueError):
    pass


class DeviceRegistrationUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class DevicePublicKey:
    jwk: dict[str, str]
    fingerprint: str


@dataclass(frozen=True)
class ExtensionDeviceIdentity:
    id: UUID
    device_id: UUID
    workspace_id: UUID
    member_id: UUID
    public_key: DevicePublicKey
    extension_version: str
    label: str


@dataclass(frozen=True)
class DeviceChallenge:
    id: UUID
    device_id: UUID
    expires_at: datetime
    signing_payload: bytes


class ExtensionDeviceService:
    challenge_lifetime = timedelta(minutes=2)
    _CONSUME_CHALLENGE = """
local payload = redis.call('GET', KEYS[1])
if not payload then
  return false
end
redis.call('DEL', KEYS[1])
return payload
""".strip()

    def __init__(
        self,
        session: Session,
        *,
        redis: RedisChallengeClient,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session = session
        self._redis = redis
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def _b64url_decode(value: str) -> bytes:
        if not isinstance(value, str) or not value:
            raise ValueError
        try:
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        except Exception as error:
            raise ValueError from error

    @classmethod
    def _validate_public_key(cls, public_key_jwk: Mapping[str, str]) -> DevicePublicKey:
        if (
            not isinstance(public_key_jwk, Mapping)
            or set(public_key_jwk) != {"kty", "crv", "x", "y"}
        ):
            raise DeviceRegistrationUnavailable
        if public_key_jwk.get("kty") != "EC" or public_key_jwk.get("crv") != "P-256":
            raise DeviceRegistrationUnavailable
        try:
            x = cls._b64url_decode(public_key_jwk["x"])
            y = cls._b64url_decode(public_key_jwk["y"])
            if len(x) != 32 or len(y) != 32:
                raise ValueError
            ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
            ).public_key()
        except (KeyError, TypeError, ValueError):
            raise DeviceRegistrationUnavailable from None
        canonical = json.dumps(
            dict(public_key_jwk), sort_keys=True, separators=(",", ":")
        ).encode()
        return DevicePublicKey(
            jwk=dict(public_key_jwk),
            fingerprint=hashlib.sha256(canonical).hexdigest(),
        )

    @staticmethod
    def _challenge_key(device_id: UUID, challenge_id: UUID) -> str:
        return f"extension-device-challenge:{device_id}:{challenge_id}"

    @staticmethod
    def _identity(binding: ExtensionDeviceBinding) -> ExtensionDeviceIdentity:
        return ExtensionDeviceIdentity(
            id=binding.id,
            device_id=binding.device_id,
            workspace_id=binding.workspace_id,
            member_id=binding.member_id,
            public_key=DevicePublicKey(
                jwk=binding.public_key_jwk,
                fingerprint=binding.public_key_fingerprint,
            ),
            extension_version=binding.extension_version,
            label=binding.label,
        )

    def _active_member(
        self, workspace_id: UUID, member_id: UUID
    ) -> WorkspaceMember | None:
        workspace = self._session.get(Workspace, workspace_id)
        if workspace is None or workspace.status != "active":
            return None
        return self._session.scalar(
            select(WorkspaceMember).where(
                WorkspaceMember.id == member_id,
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.revoked_at.is_(None),
            )
        )

    def _active_binding(self, binding_id: UUID) -> ExtensionDeviceBinding | None:
        device = self._session.get(ExtensionDeviceBinding, binding_id)
        if device is None or device.revoked_at is not None:
            return None
        if self._active_member(device.workspace_id, device.member_id) is None:
            return None
        return device

    def _active_public_device(
        self, public_device_id: UUID
    ) -> ExtensionDeviceBinding | None:
        device = self._session.scalar(
            select(ExtensionDeviceBinding).where(
                ExtensionDeviceBinding.device_id == public_device_id
            )
        )
        if device is None or device.revoked_at is not None:
            return None
        if self._active_member(device.workspace_id, device.member_id) is None:
            return None
        return device

    def register_device(
        self,
        *,
        workspace_id: UUID,
        member_id: UUID,
        device_id: UUID,
        public_key_jwk: dict[str, str],
        extension_version: str,
        label: str,
    ) -> ExtensionDeviceIdentity:
        if self._active_member(workspace_id, member_id) is None:
            raise DeviceRegistrationUnavailable
        public_key = self._validate_public_key(public_key_jwk)
        binding = ExtensionDeviceBinding(
            workspace_id=workspace_id,
            member_id=member_id,
            device_id=device_id,
            public_key_jwk=public_key.jwk,
            public_key_fingerprint=public_key.fingerprint,
            extension_version=extension_version,
            label=label,
        )
        try:
            with self._session.begin_nested():
                self._session.add(binding)
                self._session.flush()
        except IntegrityError:
            raise DeviceRegistrationUnavailable from None
        return self._identity(binding)

    def issue_challenge(self, *, device_id: UUID) -> DeviceChallenge:
        device = self._active_binding(device_id)
        return self._issue_challenge(device)

    def issue_public_challenge(self, *, device_id: UUID) -> DeviceChallenge:
        device = self._active_public_device(device_id)
        return self._issue_challenge(device)

    def _issue_challenge(
        self, device: ExtensionDeviceBinding | None
    ) -> DeviceChallenge:
        if device is None:
            raise DeviceChallengeUnavailable
        challenge_id = uuid4()
        payload = secrets.token_bytes(32)
        current = self._now()
        expires_at = current + self.challenge_lifetime
        stored = json.dumps(
            {
                "device_id": str(device.id),
                "expires_at": expires_at.isoformat(),
                "payload": _b64url_encode(payload),
            }
        )
        if not self._redis.set(
            self._challenge_key(device.id, challenge_id),
            stored,
            ex=int(self.challenge_lifetime.total_seconds()),
            nx=True,
        ):
            raise DeviceChallengeUnavailable
        return DeviceChallenge(
            id=challenge_id,
            device_id=device.device_id,
            expires_at=expires_at,
            signing_payload=payload,
        )

    def renew_session(
        self,
        *,
        device_id: UUID,
        challenge_id: UUID,
        signature: str,
    ) -> IssuedExtensionToken:
        device = self._active_binding(device_id)
        return self._renew_session(
            device=device,
            challenge_id=challenge_id,
            signature=signature,
        )

    def renew_public_session(
        self,
        *,
        device_id: UUID,
        challenge_id: UUID,
        signature: str,
    ) -> IssuedExtensionToken:
        device = self._active_public_device(device_id)
        return self._renew_session(
            device=device,
            challenge_id=challenge_id,
            signature=signature,
        )

    def _renew_session(
        self,
        *,
        device: ExtensionDeviceBinding | None,
        challenge_id: UUID,
        signature: str,
    ) -> IssuedExtensionToken:
        if device is None:
            raise DeviceChallengeUnavailable
        result = self._redis.eval(
            self._CONSUME_CHALLENGE,
            1,
            self._challenge_key(device.id, challenge_id),
        )
        if not result:
            raise DeviceChallengeUnavailable
        if isinstance(result, bytes):
            result = result.decode()
        try:
            challenge = json.loads(str(result))
            if challenge["device_id"] != str(device.id):
                raise ValueError
            expires_at = datetime.fromisoformat(challenge["expires_at"])
            if expires_at <= self._now():
                raise ValueError
            payload = self._b64url_decode(challenge["payload"])
            raw_signature = self._b64url_decode(signature)
            if len(raw_signature) != 64:
                raise ValueError
            public_key = self._validate_public_key(device.public_key_jwk)
            x = int.from_bytes(self._b64url_decode(public_key.jwk["x"]), "big")
            y = int.from_bytes(self._b64url_decode(public_key.jwk["y"]), "big")
            verifier = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
            verifier.verify(
                encode_dss_signature(
                    int.from_bytes(raw_signature[:32], "big"),
                    int.from_bytes(raw_signature[32:], "big"),
                ),
                payload,
                ec.ECDSA(hashes.SHA256()),
            )
        except (InvalidSignature, KeyError, TypeError, ValueError):
            raise DeviceChallengeUnavailable from None
        current = self._now()
        return ExtensionTokenService(self._session, now=self._now).issue(
            workspace_id=device.workspace_id,
            member_id=device.member_id,
            client_id=EXTENSION_CLIENT_ID,
            device_id=device.id,
            now=current,
        )

    def revoke_device(
        self,
        *,
        workspace_id: UUID,
        device_id: UUID,
        revoked_by: UUID,
    ) -> None:
        revoked_by_member = self._active_member(workspace_id, revoked_by)
        if (
            revoked_by_member is None
            or revoked_by_member.role is not MemberRole.ADMIN
        ):
            raise DeviceChallengeUnavailable
        device = self._session.get(ExtensionDeviceBinding, device_id)
        self._revoke(device=device, workspace_id=workspace_id)

    def revoke_public_device(
        self,
        *,
        workspace_id: UUID,
        device_id: UUID,
        revoked_by: UUID,
    ) -> None:
        revoked_by_member = self._active_member(workspace_id, revoked_by)
        if (
            revoked_by_member is None
            or revoked_by_member.role is not MemberRole.ADMIN
        ):
            raise DeviceChallengeUnavailable
        device = self._session.scalar(
            select(ExtensionDeviceBinding).where(
                ExtensionDeviceBinding.device_id == device_id
            )
        )
        self._revoke(device=device, workspace_id=workspace_id)

    def _revoke(
        self,
        *,
        device: ExtensionDeviceBinding | None,
        workspace_id: UUID,
    ) -> None:
        if device is None or device.workspace_id != workspace_id:
            raise DeviceChallengeUnavailable
        if device.revoked_at is None:
            device.revoked_at = self._now()
            self._session.flush()

    def authenticate(self, access_token: str) -> AuthenticatedExtension | None:
        return ExtensionTokenService(self._session, now=self._now).authenticate(
            access_token
        )


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


__all__ = [
    "DeviceChallenge",
    "DeviceChallengeUnavailable",
    "DevicePublicKey",
    "DeviceRegistrationUnavailable",
    "ExtensionDeviceIdentity",
    "ExtensionDeviceService",
]
