import hashlib
import secrets
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.demo.seed import DEMO_WORKSPACE


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

    def workspace(self) -> dict:
        return deepcopy(DEMO_WORKSPACE)

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
