from pydantic import BaseModel

from .schemas import JobRead
from .schemas_nl import NLJobPlan


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    action: str
    requires_confirmation: bool = False
    plan: NLJobPlan | None = None
    jobs: list[JobRead] = []
