"""Single COM worker thread for safe Excel automation."""

import asyncio
import functools
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _init_thread() -> None:
    """Initialize COM apartment on the worker thread."""
    try:
        import pythoncom

        pythoncom.CoInitialize()
        logger.debug("pythoncom.CoInitialize() succeeded on COM worker thread")
    except ImportError:
        logger.debug("pythoncom not available (non-Windows platform)")


class ComThread:
    """Thread pool executor with exactly one worker thread for COM operations."""

    def __init__(self) -> None:
        self._executor: ThreadPoolExecutor | None = None
        self._ensure_executor()

    def _ensure_executor(self) -> ThreadPoolExecutor:
        """Ensure the single-worker thread pool is alive and initialized."""
        if self._executor is None or self._executor._shutdown:
            self._executor = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="excel-com-worker",
                initializer=_init_thread,
            )
        return self._executor

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run synchronous COM function on the dedicated COM worker thread."""
        executor = self._ensure_executor()
        loop = asyncio.get_running_loop()
        call = functools.partial(fn, *args, **kwargs)
        return await loop.run_in_executor(executor, call)

    def shutdown(self) -> None:
        """Shut down the COM worker thread."""
        if self._executor is not None and not self._executor._shutdown:
            try:
                import pythoncom

                self._executor.submit(pythoncom.CoUninitialize).result(timeout=1.0)
            except Exception as exc:  # noqa: BLE001
                logger.debug("COM uninitialize ignored: %s", exc)
            self._executor.shutdown(wait=True)
            logger.debug("COM worker thread shut down")


com_thread = ComThread()
