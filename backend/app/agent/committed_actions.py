"""Per-call single-flight external writes, including interrupted/uncertain writes.

No automatic retry after an ambiguous result. This is not cross-worker durable
idempotency; a provider receipt is still required to claim success.
"""
from __future__ import annotations

import asyncio


class ActionUncertain(RuntimeError):
    pass


class NoAction(RuntimeError):
    """Validation failed before any write; a corrected request may try again."""


class CommittedActions:
    def __init__(self):
        self.tasks = {}

    async def run(self, key, operation, *, context):
        # SDK 1.6.4 executes function tools only after speech authorization.
        # Also reject a stale/interrupted invocation before starting a new write.
        if context.speech_handle.interrupted:
            raise ActionUncertain("Turn interrupted before action started")
        if key not in self.tasks:
            async def execute():
                try:
                    return await operation()
                except NoAction:
                    raise
                except Exception as exc:
                    # Retain an ambiguous terminal result so a repeated tool call
                    # cannot issue another write following a timeout/disconnect.
                    raise ActionUncertain("Action result unavailable; do not retry automatically") from exc
            task = asyncio.create_task(execute())
            # Consume exceptions even when the model turn was cancelled. Keep the
            # task strongly referenced so completed writes are not forgotten.
            task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            self.tasks[key] = task
        task = self.tasks[key]
        try:
            return await asyncio.shield(task)
        except NoAction:
            if self.tasks.get(key) is task:
                del self.tasks[key]
            raise
