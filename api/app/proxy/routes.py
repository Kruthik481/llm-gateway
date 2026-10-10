from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response

from app.core.auth import parse_bearer
from app.core.errors import GatewayError
from app.core.schemas import ChatRequest
from app.db.repo import KeyIdentity
from app.proxy.service import admit, complete_response, finalize, make_record
from app.proxy.streaming import stream_response
from app.state import GatewayState, get_state

router = APIRouter(prefix="/v1", tags=["proxy"])
StateDep = Annotated[GatewayState, Depends(get_state)]


def request_id_of(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) else uuid4().hex


async def require_key(request: Request, state: StateDep) -> KeyIdentity:
    raw = parse_bearer(request.headers.get("authorization"))
    identity = await state.resolver.resolve(raw) if raw else None
    if identity is None:
        raise GatewayError(401, "invalid_api_key", "Invalid API key. Create one in the dashboard.")
    return identity


KeyDep = Annotated[KeyIdentity, Depends(require_key)]


@router.get("/models")
async def list_models(_: KeyDep, state: StateDep) -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {"id": alias, "object": "model", "created": 0, "owned_by": "llm-gateway"}
            for alias in state.catalog.aliases()
        ],
    }


@router.post("/chat/completions")
async def chat_completions(req: ChatRequest, request: Request, identity: KeyDep, state: StateDep) -> Response:
    adm = await admit(state, identity, req, request.headers, request_id_of(request))
    try:
        if req.stream:
            return await stream_response(state, adm, req)
        return await complete_response(state, adm, req)
    except GatewayError:
        raise  # these paths have already settled the reservation
    except Exception:
        record = make_record(adm, req, status="error", error_code="internal_error", attempts=0)
        finalize(state, adm, record, actual_tokens=0)
        raise
