"""Redis Streams consumer: bounded concurrent task execution."""

from __future__ import annotations

import asyncio
import json
import logging
import sys

from agent_backend.config import Settings, get_settings
from agent_backend.store import RedisTaskStore
from agent_backend.tasks_execution import execute_task, payload_from_raw

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def _run_one(
    store: RedisTaskStore,
    settings: Settings,
    msg_id: str,
    fields: dict[str, str],
    sem: asyncio.Semaphore,
) -> None:
    task_id = fields["task_id"]
    raw_payload = fields["payload"]
    payload = payload_from_raw(raw_payload)
    try:
        async with sem:
            logger.info("running task %s", task_id)
            await execute_task(store, task_id, payload)
    except Exception:
        logger.exception("execute_task failed for %s", task_id)
    finally:
        await store.ack_task(settings.task_stream_key, settings.consumer_group, msg_id)
        logger.info("acked task %s", task_id)


async def worker_loop(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    store = RedisTaskStore(settings.redis_url, settings.task_stream_key)
    await store.connect()
    await store.ensure_consumer_group(
        settings.task_stream_key,
        settings.consumer_group,
    )
    sem = asyncio.Semaphore(settings.max_concurrent_tasks)
    logger.info(
        "worker listening stream=%s group=%s max_concurrent=%s",
        settings.task_stream_key,
        settings.consumer_group,
        settings.max_concurrent_tasks,
    )
    while True:
        try:
            streams = await store.r.xreadgroup(
                groupname=settings.consumer_group,
                consumername=settings.consumer_name,
                streams={settings.task_stream_key: ">"},
                count=20,
                block=5000,
            )
        except Exception:
            logger.exception("xreadgroup failed")
            await asyncio.sleep(1)
            continue
        if not streams:
            continue
        for _sk, messages in streams:
            for msg_id, fields in messages:
                asyncio.create_task(
                    _run_one(store, settings, msg_id, fields, sem),
                )


def main() -> None:
    try:
        asyncio.run(worker_loop())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
