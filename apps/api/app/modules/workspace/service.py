from sqlalchemy.orm import Session

from app.modules.workspace.models import Workspace
from app.modules.workspace.schemas import WorkspaceCreate


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, data: WorkspaceCreate) -> Workspace:
        workspace = Workspace(name=data.name)
        self._session.add(workspace)
        self._session.flush()
        return workspace
