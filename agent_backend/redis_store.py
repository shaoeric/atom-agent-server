"""Redis Streams task queue + XRANGE log + Pub/Sub live channel."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

import redis.asyncio as redis


class RedisTaskStore:
    def __init__(
        self,
        redis_url: str,
        task_stream_key: str = "agent:tasks:pending",
        consumer_group: str = "workers",
        consumer_name: str = "worker-1",
    ) -> None:
        self._url = redis_url
        self._task_stream_key = task_stream_key
        self._consumer_group = consumer_group
        self._consumer_name = consumer_name
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is None:
            self._client = redis.from_url(self._url, decode_responses=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    @property
    def r(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("RedisTaskStore not connected")
        return self._client

    def meta_key(self, task_id: str) -> str:
        return f"task:{task_id}:meta"

    def log_key(self, task_id: str) -> str:
        return f"task:{task_id}:log"

    def live_channel(self, task_id: str) -> str:
        return f"task:{task_id}:live"

    def cancel_key(self, task_id: str) -> str:
        return f"task:{task_id}:cancel"

    def seq_key(self, task_id: str) -> str:
        return f"task:{task_id}:seq"

    async def ensure_worker_ready(self) -> None:
        try:
            await self.r.xgroup_create(
                self._task_stream_key,
                self._consumer_group,
                id="0",
                mkstream=True,
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def enqueue_task(
        self,
        payload: dict[str, Any],
        task_id: str | None = None,
    ) -> str:
        tid = task_id or str(uuid.uuid4())
        ts = str(int(time.time()))
        pipe = self.r.pipeline()
        pipe.hset(
            self.meta_key(tid),
            mapping={
                "status": "queued",
                "created_at": ts,
                "updated_at": ts,
                "payload": json.dumps(payload, ensure_ascii=False),
            },
        )
        pipe.set(self.seq_key(tid), "0")
        pipe.xadd(
            self._task_stream_key,
            {"task_id": tid, "payload": json.dumps(payload, ensure_ascii=False)},
        )
        await pipe.execute()
        await self.append_event(tid, "status", chunk="queued", meta={"task_id": tid})
        return tid

    async def update_meta(
        self,
        task_id: str,
        *,
        status: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        ts = str(int(time.time()))
        mapping: dict[str, str] = {"updated_at": ts}
        if status:
            mapping["status"] = status
        if extra:
            for k, v in extra.items():
                mapping[k] = v
        await self.r.hset(self.meta_key(task_id), mapping=mapping)

    async def get_meta(self, task_id: str) -> dict[str, str]:
        raw = await self.r.hgetall(self.meta_key(task_id))
        return dict(raw)

    async def append_event(
        self,
        task_id: str,
        event_type: str,
        *,
        chunk: str = "",
        meta: dict[str, Any] | None = None,
    ) -> int:
        seq = int(await self.r.incr(self.seq_key(task_id)))
        data = json.dumps(
            {"seq": seq, "type": event_type, "chunk": chunk, "meta": meta or {}},
            ensure_ascii=False,
        )
        await self.r.xadd(self.log_key(task_id), {"data": data})
        await self.r.publish(self.live_channel(task_id), data)
        return seq

    async def is_cancelled(self, task_id: str) -> bool:
        v = await self.r.get(self.cancel_key(task_id))
        return v == "1"

    async def request_cancel(self, task_id: str) -> None:
        await self.r.set(self.cancel_key(task_id), "1", ex=86400)
        await self.append_event(task_id, "status", chunk="cancel_requested", meta={})

    async def replay_events(self, task_id: str, from_seq: int) -> list[dict[str, Any]]:
        entries = await self.r.xrange(self.log_key(task_id))
        out: list[dict[str, Any]] = []
        for _mid, fields in entries:
            data = json.loads(fields["data"])
            if data["seq"] > from_seq:
                out.append(data)
        out.sort(key=lambda x: x["seq"])
        return out

    async def subscribe_live(self, task_id: str) -> Any:
        pubsub = self.r.pubsub()
        await pubsub.subscribe(self.live_channel(task_id))
        return pubsub

    async def consume_task(self) -> tuple[str, dict[str, str]] | None:
        streams = await self.r.xreadgroup(
            groupname=self._consumer_group,
            consumername=self._consumer_name,
            streams={self._task_stream_key: ">"},
            count=1,
            block=5000,
        )
        if not streams:
            return None
        for _sk, messages in streams:
            for msg_id, fields in messages:
                return (msg_id, dict(fields))
        return None

    async def ack_delivery(self, delivery_id: str) -> None:
        await self.r.xack(self._task_stream_key, self._consumer_group, delivery_id)
