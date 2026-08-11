import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import main as _app  # noqa: F401
from app.core.database import Base
from app.modules.imports.extension_devices import (
    DeviceChallengeUnavailable,
    DeviceRegistrationUnavailable,
    ExtensionDeviceService,
)
from app.modules.imports.models import ExtensionDeviceBinding, ExtensionToken
from app.modules.workspace.models import MemberRole, Workspace, WorkspaceMember


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def p256_fixture() -> tuple[ec.EllipticCurvePrivateKey, dict[str, str]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    numbers = private_key.public_key().public_numbers()
    return private_key, {
        "kty": "EC",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }


def sign_raw_p256(private_key: ec.EllipticCurvePrivateKey, payload: bytes) -> str:
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    der = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield Session(engine, expire_on_commit=False)
    finally:
        engine.dispose()


@pytest.fixture
def redis():
    from redis import Redis

    client = Redis.from_url(os.environ["REDIS_URL"], decode_responses=True)
    namespace = f"extension-device-test:{uuid4()}"
    try:
        yield client, namespace
    finally:
        keys = list(client.scan_iter(match=f"{namespace}:*"))
        if keys:
            client.delete(*keys)


def _workspace_member(session: Session) -> tuple[Workspace, WorkspaceMember]:
    workspace = Workspace(name="设备工作区")
    session.add(workspace)
    session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="管理员",
        role=MemberRole.ADMIN,
    )
    session.add(member)
    session.commit()
    return workspace, member


def _service(session: Session, redis, now=None) -> ExtensionDeviceService:
    client, namespace = redis
    return ExtensionDeviceService(
        session,
        redis=client,
        now=now,
        challenge_key_namespace=namespace,
    )


def test_device_challenge_is_single_use_and_renews_a_short_token(session, redis):
    workspace, admin = _workspace_member(session)
    service = _service(session, redis)
    private_key, public_jwk = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=UUID("00000000-0000-0000-0000-000000000301"),
        public_key_jwk=public_jwk,
        extension_version="0.3.0",
        label="Chrome on macOS",
    )
    challenge = service.issue_challenge(device_id=device.id)
    signature = sign_raw_p256(private_key, challenge.signing_payload)
    renewed = service.renew_session(
        device_id=device.id,
        challenge_id=challenge.id,
        signature=signature,
    )
    assert renewed.expires_at - renewed.issued_at == timedelta(hours=8)
    assert session.get(ExtensionToken, renewed.token_id).device_id == device.id
    with pytest.raises(DeviceChallengeUnavailable):
        service.renew_session(
            device_id=device.id,
            challenge_id=challenge.id,
            signature=signature,
        )


def test_device_registration_rejects_malformed_keys_and_duplicate_device_ids(
    session, redis
):
    workspace, admin = _workspace_member(session)
    service = _service(session, redis)
    _, key = p256_fixture()
    device_id = uuid4()
    with pytest.raises(DeviceRegistrationUnavailable):
        service.register_device(
            workspace_id=workspace.id,
            member_id=admin.id,
            device_id=device_id,
            public_key_jwk=None,  # type: ignore[arg-type]
            extension_version="0.3.0",
            label="Chrome",
        )
    with pytest.raises(DeviceRegistrationUnavailable):
        service.register_device(
            workspace_id=workspace.id,
            member_id=admin.id,
            device_id=device_id,
            public_key_jwk={"kty": "RSA", "crv": "P-256", "x": "x", "y": "y"},
            extension_version="0.3.0",
            label="Chrome",
        )
    service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=device_id,
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )
    with pytest.raises(DeviceRegistrationUnavailable):
        service.register_device(
            workspace_id=workspace.id,
            member_id=admin.id,
            device_id=device_id,
            public_key_jwk=key,
            extension_version="0.3.0",
            label="Chrome",
        )
    assert (
        session.scalar(select(func.count()).select_from(ExtensionDeviceBinding))
        == 1
    )


def test_device_challenges_fail_closed_for_wrong_signature_expiration_and_revocation(
    session, redis
):
    workspace, admin = _workspace_member(session)
    current = datetime(2026, 8, 10, tzinfo=UTC)
    service = _service(session, redis, now=lambda: current)
    private_key, key = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=uuid4(),
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )
    challenge = service.issue_challenge(device_id=device.id)
    with pytest.raises(DeviceChallengeUnavailable):
        service.renew_session(
            device_id=device.id, challenge_id=challenge.id, signature="bad"
        )
    challenge = service.issue_challenge(device_id=device.id)
    current += timedelta(minutes=3)
    with pytest.raises(DeviceChallengeUnavailable):
        service.renew_session(
            device_id=device.id,
            challenge_id=challenge.id,
            signature=sign_raw_p256(private_key, challenge.signing_payload),
        )
    service.revoke_device(
        workspace_id=workspace.id, device_id=device.id, revoked_by=admin.id
    )
    with pytest.raises(DeviceChallengeUnavailable):
        service.issue_challenge(device_id=device.id)


def test_device_operations_require_active_same_workspace_member(session, redis):
    workspace, admin = _workspace_member(session)
    other_workspace, other_member = _workspace_member(session)
    service = _service(session, redis)
    _, key = p256_fixture()
    with pytest.raises(DeviceRegistrationUnavailable):
        service.register_device(
            workspace_id=workspace.id,
            member_id=other_member.id,
            device_id=uuid4(),
            public_key_jwk=key,
            extension_version="0.3.0",
            label="Chrome",
        )
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=uuid4(),
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )
    with pytest.raises(DeviceChallengeUnavailable):
        service.revoke_device(
            workspace_id=other_workspace.id,
            device_id=device.id,
            revoked_by=other_member.id,
        )
    admin.revoked_at = datetime.now(UTC)
    session.commit()
    with pytest.raises(DeviceChallengeUnavailable):
        service.issue_challenge(device_id=device.id)


def test_only_admin_can_revoke_a_device(session, redis):
    workspace, admin = _workspace_member(session)
    editor = WorkspaceMember(
        workspace_id=workspace.id,
        display_name="编辑",
        role=MemberRole.EDITOR,
    )
    session.add(editor)
    session.commit()
    service = _service(session, redis)
    _, key = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=uuid4(),
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )

    with pytest.raises(DeviceChallengeUnavailable):
        service.revoke_device(
            workspace_id=workspace.id,
            device_id=device.id,
            revoked_by=editor.id,
        )

    assert session.get(ExtensionDeviceBinding, device.id).revoked_at is None


def test_concurrent_challenge_consumption_issues_only_one_token(session, redis):
    workspace, admin = _workspace_member(session)
    service = _service(session, redis)
    private_key, key = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=uuid4(),
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )
    challenge = service.issue_challenge(device_id=device.id)
    signature = sign_raw_p256(private_key, challenge.signing_payload)

    def renew() -> str:
        try:
            service.renew_session(
                device_id=device.id, challenge_id=challenge.id, signature=signature
            )
            return "renewed"
        except DeviceChallengeUnavailable:
            return "unavailable"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: renew(), range(2)))
    assert results.count("renewed") == 1
    assert results.count("unavailable") == 1


def test_device_bound_tokens_recheck_device_member_and_workspace_on_authentication(
    session, redis
):
    workspace, admin = _workspace_member(session)
    service = _service(session, redis)
    private_key, key = p256_fixture()
    device = service.register_device(
        workspace_id=workspace.id,
        member_id=admin.id,
        device_id=uuid4(),
        public_key_jwk=key,
        extension_version="0.3.0",
        label="Chrome",
    )
    challenge = service.issue_challenge(device_id=device.id)
    renewed = service.renew_session(
        device_id=device.id,
        challenge_id=challenge.id,
        signature=sign_raw_p256(private_key, challenge.signing_payload),
    )
    assert service.authenticate(renewed.access_token) is not None
    workspace.status = "deleting"
    session.commit()
    assert service.authenticate(renewed.access_token) is None
