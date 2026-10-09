import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog

log = structlog.get_logger()


class TaskTracker:
    """Keeps references to fire-and-forget tasks so they finish (and are awaited on shutdown)."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()

    def spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._done)

    def _done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.error("background_task_failed", exc_info=task.exception())

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
