import asyncio
import json
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI

from app.db.models import Usage
from app.db.repo import KeyIdentity
from app.proxy import streaming
from tests.conftest import LiveGateway, usage_rows
from tests.fakes import StreamReply, Timeout
from tests.helpers import chat

URL = "/v1/chat/completions"
ApiKey = tuple[str, KeyIdentity]


async def read_events(resp: httpx.Response) -> list[Any]:
    events: list[Any] = []
    async for line in resp.aiter_lines():
        if line.startswith("data: "):
            payload = line[6:]
            events.append(payload if payload == "[DONE]" else json.loads(payload))
    return events


async def stream_chat(gateway: LiveGateway, key: str, **overrides: Any) -> tuple[httpx.Response, list[Any]]:
    async with gateway.client(key) as c, c.stream("POST", URL, json=chat(stream=True, **overrides)) as resp:
        return resp, await read_events(resp)


def text_of(events: list[Any]) -> str:
    return "".join(
        e["choices"][0]["delta"].get("content") or ""
        for e in events
        if isinstance(e, dict) and e.get("choices")
    )


async def test_streams_text_then_a_final_chunk_with_gateway_meta(
    gateway: LiveGateway, api_key: ApiKey
) -> None:
    resp, events = await stream_chat(gateway, api_key[0])
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["x-gateway-provider"] == "cerebras"
    assert text_of(events) == "Hello there!"
    assert events[-1] == "[DONE]"
    final = events[-2]
    assert final["choices"][0]["finish_reason"] == "stop"
    assert final["x_gateway"]["provider"] == "cerebras"
    assert final["x_gateway"]["ttft_ms"] >= 0
    assert all(e["choices"] for e in events[:-1]), "no usage chunk unless include_usage was requested"
    [row] = await usage_rows(gateway)
    assert (row.status, row.prompt_tokens, row.completion_tokens) == ("ok", 12, 3)
    assert row.ttft_ms is not None


async def test_include_usage_adds_a_usage_chunk(gateway: LiveGateway, api_key: ApiKey) -> None:
    _, events = await stream_chat(gateway, api_key[0], stream_options={"include_usage": True})
    usage_chunk = events[-2]
    assert usage_chunk["choices"] == []
    assert usage_chunk["usage"] == {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
    assert "x_gateway" in events[-3]


async def test_sdk_stream_without_include_usage_never_sees_empty_choices(
    gateway: LiveGateway, api_key: ApiKey
) -> None:
    client = AsyncOpenAI(base_url=f"{gateway.url}/v1", api_key=api_key[0], max_retries=0)
    stream = await client.chat.completions.create(
        model="llama-3.3-70b", messages=[{"role": "user", "content": "hi"}], stream=True
    )
    pieces = [chunk.choices[0].delta.content or "" async for chunk in stream]
    assert "".join(pieces) == "Hello there!"


async def test_sdk_stream_with_include_usage_reports_usage(gateway: LiveGateway, api_key: ApiKey) -> None:
    client = AsyncOpenAI(base_url=f"{gateway.url}/v1", api_key=api_key[0], max_retries=0)
    stream = await client.chat.completions.create(
        model="llama-3.3-70b",
        messages=[{"role": "user", "content": "hi"}],
        stream=True,
        stream_options={"include_usage": True},
    )
    chunks = [chunk async for chunk in stream]
    assert chunks[-1].choices == []
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 15


async def test_falls_back_before_the_first_token(gateway: LiveGateway, api_key: ApiKey) -> None:
    gateway.upstream.script("cerebras", Timeout())
    resp, events = await stream_chat(gateway, api_key[0])
    assert resp.headers["x-gateway-provider"] == "openrouter"
    assert resp.headers["x-gateway-attempts"] == "2"
    assert text_of(events) == "Hello there!"


async def test_all_providers_failing_is_a_json_502_not_a_stream(
    gateway: LiveGateway, api_key: ApiKey
) -> None:
    gateway.upstream.script("cerebras", Timeout())
    gateway.upstream.script("openrouter", Timeout())
    async with gateway.client(api_key[0]) as c:
        resp = await c.post(URL, json=chat(stream=True))
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"


async def test_midstream_failure_ends_with_an_error_event(gateway: LiveGateway, api_key: ApiKey) -> None:
    gateway.upstream.script("cerebras", StreamReply(pieces=["a", "b", "c"], fail_after=2))
    _, events = await stream_chat(gateway, api_key[0])
    assert text_of(events) == "ab"
    assert events[-2]["error"]["code"] == "upstream_error"
    assert events[-1] == "[DONE]"
    [row] = await usage_rows(gateway)
    assert (row.status, row.error_code) == ("partial", "network_error")
    assert row.completion_tokens == 1  # ceil(len("ab") / 4)


async def test_client_disconnect_records_partial_usage(gateway: LiveGateway, api_key: ApiKey) -> None:
    raw, identity = api_key
    gateway.upstream.script("cerebras", StreamReply(pieces=["word "] * 30, delay_s=0.05))
    async with gateway.client(raw) as c, c.stream("POST", URL, json=chat(stream=True)) as resp:
        seen = 0
        async for line in resp.aiter_lines():
            seen += line.startswith("data: ")
            if seen >= 4:
                break  # leaving the block closes the connection mid-answer
    rows: list[Usage] = []
    for _ in range(50):
        rows = await usage_rows(gateway)
        if rows:
            break
        await asyncio.sleep(0.1)
    [row] = rows
    assert (row.status, row.error_code) == ("partial", "client_disconnected")
    assert 0 < row.completion_tokens < 30 * 2
    used = await gateway.state.budget.used_today(str(identity.user_id))
    assert used == row.prompt_tokens + row.completion_tokens


async def test_deadline_cuts_a_long_stream(
    gateway: LiveGateway, api_key: ApiKey, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(streaming, "REQUEST_DEADLINE_S", 0.3)
    gateway.upstream.script("cerebras", StreamReply(pieces=["x"] * 40, delay_s=0.05))
    _, events = await stream_chat(gateway, api_key[0])
    assert "deadline_exceeded" in events[-2]["error"]["message"]
    [row] = await usage_rows(gateway)
    assert (row.status, row.error_code) == ("partial", "deadline_exceeded")


async def test_cached_answers_replay_as_a_stream(gateway: LiveGateway, api_key: ApiKey) -> None:
    async with gateway.client(api_key[0]) as c:
        first = await c.post(URL, json=chat(temperature=0))
    await gateway.state.tasks.drain()
    resp, events = await stream_chat(gateway, api_key[0], temperature=0)
    assert resp.headers["x-gateway-cache"] == "hit"
    assert text_of(events) == first.json()["choices"][0]["message"]["content"]
    assert events[-2]["x_gateway"]["cache"] == "hit"
    assert len(gateway.upstream.calls) == 1
