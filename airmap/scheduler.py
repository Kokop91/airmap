"""Background periodic-scan loop, driven by asyncio.

Deliberately generic: this module knows nothing about WiFi scanning or the
database -- it just repeats a callback on an interval until told to stop,
and makes sure one failing cycle doesn't kill the loop. `app.py` supplies
the actual "scan + persist" callback. Keeping that split means this class
is trivial to reason about (and to test) independent of what it's looping.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

MIN_INTERVAL_SECONDS = 10.0
"""Floor for the scan interval, so a fat-fingered request can't turn this
into a tight polling loop against the OS's WiFi tool."""


class AutoScanScheduler:
    """Owns the single background auto-scan task, if any is running."""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._interval_seconds: float | None = None

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def interval_seconds(self) -> float | None:
        return self._interval_seconds if self.is_running else None

    async def start(self, interval_seconds: float, callback: Callable[[], None]) -> None:
        """(Re)start the loop at the given interval, running `callback` each cycle.

        `callback` is a plain blocking callable (it wraps a subprocess-based
        WiFi scan), so it's run via `asyncio.to_thread` each cycle rather
        than awaited directly -- otherwise a single scan would block the
        entire event loop, including all other API requests, for as long as
        the scan takes.

        Calling `start` while already running replaces the existing loop
        with a new one at the new interval, rather than raising or running
        two loops concurrently -- the simplest interpretation of "change the
        interval" for a single named auto-scan mode.
        """
        if interval_seconds < MIN_INTERVAL_SECONDS:
            raise ValueError(
                f"interval_seconds must be >= {MIN_INTERVAL_SECONDS} "
                f"(got {interval_seconds})"
            )
        await self.stop()
        self._interval_seconds = interval_seconds
        self._task = asyncio.create_task(self._loop(interval_seconds, callback))

    async def stop(self) -> None:
        """Stop the loop if running. A no-op if it isn't."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._interval_seconds = None

    @staticmethod
    async def _loop(interval_seconds: float, callback: Callable[[], None]) -> None:
        while True:
            try:
                await asyncio.to_thread(callback)
            except Exception:
                logger.exception("auto-scan cycle failed; will retry next interval")
            await asyncio.sleep(interval_seconds)
