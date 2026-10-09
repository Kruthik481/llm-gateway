from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request

from app.core.errors import GatewayError
from app.db.models import User
from app.db.repo import upsert_user
from app.state import GatewayState, get_state

JWT_LEEWAY_S = 10
MAX_TOKEN_LIFETIME_S = 600


@dataclass(frozen=True)
class Claims:
    github_id: int
    login: str
    avatar_url: str


def _invalid(message: str) -> GatewayError:
    return GatewayError(401, "invalid_token", message)


def decode_control_token(token: str, secret: str) -> Claims:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            options={"require": ["exp", "iat", "github_id", "login"]},
            leeway=JWT_LEEWAY_S,
        )
    except jwt.PyJWTError as exc:
        raise _invalid("Dashboard session is invalid or expired.") from exc
    github_id, login = payload["github_id"], payload["login"]
    if isinstance(github_id, bool) or not isinstance(github_id, int) or not isinstance(login, str):
        raise _invalid("Dashboard session is malformed.")
    if int(payload["exp"]) - int(payload["iat"]) > MAX_TOKEN_LIFETIME_S:
        raise _invalid("Dashboard session lives too long.")
    return Claims(
        github_id=github_id, login=login[:100], avatar_url=str(payload.get("avatar_url") or "")[:500]
    )


async def require_user(request: Request, state: Annotated[GatewayState, Depends(get_state)]) -> User:
    scheme, _, token = request.headers.get("authorization", "").strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _invalid("Dashboard session is missing.")
    claims = decode_control_token(token.strip(), state.settings.control_jwt_secret)
    async with state.sessions() as session, session.begin():
        return await upsert_user(
            session, github_id=claims.github_id, login=claims.login, avatar_url=claims.avatar_url
        )
