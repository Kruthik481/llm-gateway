import hashlib
import json
from dataclasses import asdict, dataclass

from redis.asyncio import Redis

from app.core.schemas import ChatRequest

CACHE_TTL_S = 24 * 3600
MAX_CACHED_BYTES = 32 * 1024
REPLAY_CHUNK_CHARS = 40


@dataclass(frozen=True)
class CachedCompletion:
    text: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    provider: str
    upstream_model: str


def is_cacheable(req: ChatRequest, *, bypass: bool) -> bool:
    return req.temperature == 0 and not bypass


def cache_key(user_id: str, req: ChatRequest) -> str:
    # Scoped per user so nobody can probe what someone else asked.
    canonical = json.dumps(
        {
            "model": req.model,
            "messages": [message.model_dump() for message in req.messages],
            "max_tokens": req.max_tokens,
            "top_p": req.top_p,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return f"cache:{user_id}:{hashlib.sha256(canonical.encode()).hexdigest()}"


class ResponseCache:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> CachedCompletion | None:
        raw = await self._redis.get(key)
        return CachedCompletion(**json.loads(raw)) if raw is not None else None

    async def put(self, key: str, value: CachedCompletion) -> bool:
        encoded = json.dumps(asdict(value), ensure_ascii=False)
        if len(encoded.encode()) > MAX_CACHED_BYTES:
            return False
        await self._redis.set(key, encoded, ex=CACHE_TTL_S)
        return True


def replay_chunks(text: str, size: int = REPLAY_CHUNK_CHARS) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
