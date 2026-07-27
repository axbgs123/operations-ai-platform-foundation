from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.content.models import Content
from app.modules.content.account_models import PlatformAccount
from app.modules.workspace.models import Workspace


def test_demo_seed_is_explicit_idempotent_and_persists_only_synthetic_records() -> None:
    from app.demo_seed import DEMO_SEED_VERSION, seed_demo

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        first = seed_demo(session, storage=None)
        session.commit()
        second = seed_demo(session, storage=None)
        session.commit()

        assert first.seed_version == DEMO_SEED_VERSION
        assert second.created is False
        assert session.scalar(select(func.count()).select_from(Workspace)) == 1
        assert session.scalar(select(func.count()).select_from(PlatformAccount)) == 2
        assert session.scalar(select(func.count()).select_from(Content)) >= 4
        assert all("synthetic" in content.body for content in session.scalars(select(Content)))


def test_demo_service_reads_seeded_workspace_from_database() -> None:
    from app.demo_seed import seed_demo
    from app.modules.demo.service import DemoService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_demo(session, storage=None)
        session.commit()
        payload = DemoService().workspace(session)

    assert payload["seed_version"]
    assert payload["synthetic"] is True
    assert {account["platform"] for account in payload["accounts"]} == {"douyin", "xiaohongshu"}
    assert all(post["synthetic"] for account in payload["accounts"] for post in account["posts"])


def test_demo_seed_exposes_database_backed_public_demo_closure() -> None:
    from app.demo_seed import seed_demo
    from app.modules.demo.service import DemoService

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_demo(session, storage=None)
        session.commit()
        payload = DemoService().workspace(session)

    assert payload["published_content"]["synthetic"] is True
    assert payload["confirmed_snapshot"]["confirmed"] is True
    assert payload["benchmark"]["label"] == "动态基准（Mock）"
    assert payload["analysis"]["mock"] is True
    assert payload["suggestion"]["synthetic"] is True
    assert payload["style_sample"]["synthetic"] is True
    assert payload["confirmed_fact"]["confirmed"] is True
    assert payload["risk_knowledge"]["synthetic"] is True
    assert payload["draft"]["synthetic"] is True
