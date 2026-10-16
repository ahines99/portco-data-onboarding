"""Bounded, cancellable offload whose abandoned workers cannot hold process shutdown open."""

from __future__ import annotations

from collections.abc import Callable
from contextvars import copy_context
from threading import Event, Thread

import anyio


async def run_daemon[T](fn: Callable[[], T], *, interrupted: Event | None = None) -> T:
    """Preserve tracing context and the usual capacity limit, with bounded cancellation cleanup.

    AnyIO's default worker threads inherit the caller's daemon flag. Explicitly daemonizing this
    outer worker also makes its nested step workers daemon threads. Cancellation still fences their
    results; daemonization only prevents an uninterruptible Python call from blocking interpreter exit.
    """
    async with anyio.to_thread.current_default_thread_limiter():
        context = copy_context()
        finished = Event()
        results: list[T] = []
        errors: list[BaseException] = []

        def invoke() -> None:
            try:
                # Match AnyIO's context transfer: this new thread has no running event loop.
                # sniffio is optional in current AnyIO, so do not make it a runtime dependency.
                try:
                    import sniffio
                except ImportError:
                    pass
                else:
                    sniffio.current_async_library_cvar.set(None)
                results.append(fn())
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        worker = Thread(target=context.run, args=(invoke,), name="portco workflow", daemon=True)
        worker.start()
        try:
            while not finished.is_set():
                await anyio.sleep(0.01)
        except anyio.get_cancelled_exc_class():
            if interrupted is not None:
                interrupted.set()
                # Give the owning loop time to fence the attempt and release its lease before
                # server teardown. A blocked database/filesystem call cannot extend this bound.
                with anyio.move_on_after(2, shield=True):
                    while not finished.is_set():
                        await anyio.sleep(0.01)
            raise
        if errors:
            raise errors[0]
        return results[0]
