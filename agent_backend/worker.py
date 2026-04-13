"""Task consumer: bounded concurrent execution. Use Redis backend for a standalone process."""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import TYPE_CHECKING

from agent_backend.config import Settings, get_settings
from agent_backend.factory import create_store
from agent_backend.tasks_execution import execute_task, payload_from_raw

if TYPE_CHECKING:
    from agent_backend.store_protocol import TaskStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _log_task_done(t: asyncio.Task) -> None:
    exc = t.exception()
    if exc is not None:
        logger.error("task runner raised", exc_info=exc)


async def _run_one(
    store: "TaskStore",
    sem: asyncio.Semaphore,
    delivery_id: str,
    fields: dict[str, str],
) -> None:
    task_id = fields["task_id"]
    raw_payload = fields["payload"]
    payload = payload_from_raw(raw_payload)
    try:
        async with sem:
            logger.info("running task %s", task_id)
            await execute_task(store, task_id, payload)
    finally:
        await store.ack_delivery(delivery_id)
        logger.info("acked delivery %s task=%s", delivery_id, task_id)


async def worker_loop(
    settings: Settings | None = None,
    store: "TaskStore | None" = None,
) -> None:
    """Poll task queue (Redis Streams or in-memory asyncio.Queue) and run tasks."""
    settings = settings or get_settings()
    own_store = store is None
    if store is None:
        store = create_store(settings)
        await store.connect()
    try:
        await store.ensure_worker_ready()
        sem = asyncio.Semaphore(settings.max_concurrent_tasks)
        logger.info(
            "worker started backend=%s max_concurrent=%s",
            settings.store_backend,
            settings.max_concurrent_tasks,
        )
        while True:
            item = await store.consume_task()
            if item is None:
                continue
            delivery_id, fields = item
            t = asyncio.create_task(
                _run_one(store, sem, delivery_id, fields),
            )
            t.add_done_callback(_log_task_done)
    finally:
        if own_store:
            await store.close()


def main() -> None:
    settings = get_settings()
    if settings.store_backend == "memory":
        print(
            "Standalone worker is not supported with store_backend=memory "
            "(queue is in-process). Run the API with embed_worker=true (default) "
            "or set STORE_BACKEND=redis for a separate worker process.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
