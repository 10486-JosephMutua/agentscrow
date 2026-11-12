"""Runs the async orchestrator from Flask's synchronous request threads.

One background thread owns one asyncio event loop. Requests either wait for a coroutine
(:meth:`run`) or start it and return immediately (:meth:`spawn`) while progress streams
to the UI through the job's event timeline.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class AsyncRunner:
    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="agentescrow-async", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run(self, coro: Coroutine[Any, Any, T], timeout: float | None = 120) -> T:
        """Run ``coro`` on the background loop and wait for its result."""
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def spawn(self, coro: Coroutine[Any, Any, Any], on_error: Callable[[BaseException], None] | None = None) -> Future:
        """Start ``coro`` and return immediately. ``on_error`` is called if it raises."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)

        def _done(done: Future) -> None:
            error = done.exception()
            if error is not None:
                logger.error("Background task failed: %s", error, exc_info=error)
                if on_error:
                    on_error(error)

        future.add_done_callback(_done)
        return future

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
