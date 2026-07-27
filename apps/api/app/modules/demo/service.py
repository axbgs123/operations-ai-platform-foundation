import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.demo_seed import DEMO_SEED_VERSION, DEMO_WORKSPACE_STATUS
from app.modules.content.account_models import PlatformAccount
from app.modules.content.models import Content, ContentStatus
from app.modules.metrics.models import DataSnapshot, SnapshotMetricValue
from app.modules.metrics.models import BenchmarkRun
from app.modules.analysis.models import AnalysisRun, AnalysisSuggestion
from app.modules.style_facts.style_models import AccountStyleProfile, StyleSample
from app.modules.style_facts.fact_models import FactItem
from app.modules.risk_rag.models import RiskChunk, RiskDocument
from app.modules.workspace.models import Workspace


class DemoSessionInvalid(Exception):
    pass


class DemoLimitReached(Exception):
    pass


@dataclass
class SessionUsage:
    count: int
    expires_at: datetime


@dataclass
class IpUsage:
    count: int
    resets_at: datetime


@dataclass(frozen=True)
class DemoGeneration:
    content: str
    session_remaining: int
    ip_remaining: int


class DemoService:
    session_limit = 3
    ip_limit = 5
    session_lifetime = timedelta(hours=2)
    ip_window = timedelta(days=1)

    def __init__(self) -> None:
        self._sessions: dict[str, SessionUsage] = {}
        self._ip_usage: dict[str, IpUsage] = {}

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def workspace(self, session: Session) -> dict:
        workspace = session.scalar(
            select(Workspace).where(Workspace.status == DEMO_WORKSPACE_STATUS)
        )
        if workspace is None:
            raise LookupError("demo seed is not installed")
        accounts = list(
            session.scalars(
                select(PlatformAccount)
                .where(PlatformAccount.workspace_id == workspace.id)
                .order_by(PlatformAccount.platform)
            )
        )
        result_accounts: list[dict] = []
        for account in accounts:
            posts: list[dict] = []
            contents = session.scalars(
                select(Content)
                .where(
                    Content.workspace_id == workspace.id,
                    Content.account_id == account.id,
                    Content.status == ContentStatus.PUBLISHED,
                )
                .order_by(Content.published_at)
            )
            for content in contents:
                snapshot = session.scalar(
                    select(DataSnapshot)
                    .where(DataSnapshot.workspace_id == workspace.id, DataSnapshot.content_id == content.id)
                    .order_by(DataSnapshot.collected_at.desc())
                )
                metric_values = (
                    session.scalars(
                        select(SnapshotMetricValue).where(SnapshotMetricValue.snapshot_id == snapshot.id)
                    )
                    if snapshot is not None
                    else ()
                )
                metrics = {item.metric_key: int(item.raw_value or 0) for item in metric_values}
                posts.append(
                    {
                        "id": str(content.id),
                        "title": content.published_title or content.title,
                        "published_at": content.published_at.isoformat() if content.published_at else "",
                        "metrics": metrics,
                        "synthetic": content.body.startswith("[synthetic:"),
                    }
                )
            result_accounts.append(
                {
                    "id": str(account.id),
                    "name": account.name,
                    "platform": account.platform.value,
                    "synthetic": True,
                    "posts": posts,
                }
            )
        first_content = session.scalar(select(Content).where(Content.workspace_id == workspace.id, Content.status == "published").order_by(Content.published_at))
        first_snapshot = session.scalar(select(DataSnapshot).where(DataSnapshot.workspace_id == workspace.id, DataSnapshot.confirmed.is_(True)).order_by(DataSnapshot.collected_at))
        benchmark = session.scalar(select(BenchmarkRun).where(BenchmarkRun.workspace_id == workspace.id))
        analysis = session.scalar(select(AnalysisRun).where(AnalysisRun.workspace_id == workspace.id))
        suggestion = session.scalar(select(AnalysisSuggestion).where(AnalysisSuggestion.workspace_id == workspace.id))
        sample = session.scalar(select(StyleSample).where(StyleSample.workspace_id == workspace.id))
        style = session.scalar(select(AccountStyleProfile).where(AccountStyleProfile.workspace_id == workspace.id))
        fact = session.scalar(select(FactItem).where(FactItem.workspace_id == workspace.id))
        risk = session.scalar(select(RiskDocument).where(RiskDocument.workspace_id == workspace.id))
        chunk = session.scalar(select(RiskChunk).where(RiskChunk.workspace_id == workspace.id))
        draft = session.scalar(select(Content).where(Content.workspace_id == workspace.id, Content.status == "draft"))
        assert first_content and first_snapshot and benchmark and analysis and suggestion and sample and style and fact and risk and chunk and draft
        return {
            "id": str(workspace.id),
            "name": workspace.name,
            "label": "示例数据 / Mock 数据",
            "seed_version": DEMO_SEED_VERSION,
            "synthetic": True,
            "accounts": result_accounts,
            "published_content": {"title": first_content.title, "synthetic": True},
            "confirmed_snapshot": {"label": "正式确认数据快照", "confirmed": first_snapshot.confirmed, "synthetic": True},
            "benchmark": {"label": "动态基准（Mock）", "sample_count": benchmark.sample_count, "synthetic": True},
            "analysis": {"summary": analysis.report["summary"] if analysis.report else "证据不足", "mock": True, "synthetic": True},
            "suggestion": {"text": suggestion.recommendation["text"], "synthetic": True},
            "style_sample": {"label": style.style["tone"], "synthetic": True},
            "confirmed_fact": {"value": fact.value, "confirmed": True, "synthetic": True},
            "risk_knowledge": {"title": risk.title, "rule": chunk.text, "synthetic": True},
            "draft": {"title": draft.title, "synthetic": True},
        }

    def create_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[self._digest(token)] = SessionUsage(
            count=0,
            expires_at=self._now() + self.session_lifetime,
        )
        return token

    def generate(self, token: str, client_ip: str, prompt: str) -> DemoGeneration:
        now = self._now()
        session = self._sessions.get(self._digest(token))
        if session is None or session.expires_at <= now:
            raise DemoSessionInvalid

        ip_usage = self._ip_usage.get(client_ip)
        if ip_usage is None or ip_usage.resets_at <= now:
            ip_usage = IpUsage(count=0, resets_at=now + self.ip_window)
            self._ip_usage[client_ip] = ip_usage

        if session.count >= self.session_limit or ip_usage.count >= self.ip_limit:
            raise DemoLimitReached

        session.count += 1
        ip_usage.count += 1
        subject = prompt.strip()[:24] or "今日内容"
        return DemoGeneration(
            content=f"{subject}：3 个让内容更容易被看见的细节",
            session_remaining=self.session_limit - session.count,
            ip_remaining=self.ip_limit - ip_usage.count,
        )
