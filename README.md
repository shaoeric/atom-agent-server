# agent-backend

基于 AgentScope / AgentScope Runtime 的长任务后端：**任务队列**（内存或 Redis Streams）、任务隔离、WebSocket 与 SSE、示例 CLI（argparse 子命令）流式日志。

## 任务队列说明

- **memory（默认）**：`asyncio.Queue` 作为待处理队列；meta / 日志在进程内字典；实时订阅用每任务一组 `asyncio.Queue` 模拟 Pub/Sub。需与 **API 同进程** 的嵌入 worker（`EMBED_WORKER=true`）共享队列。
- **redis**：`XADD` 到 Stream + **consumer group** 消费；`XRANGE` 重放日志 + Redis **Pub/Sub** 推送。可 **单独进程** 运行 `python -m agent_backend.worker`。

## 依赖版本

- `agentscope` 1.0.x
- `agentscope-runtime` 1.1.x
- Redis 6+（仅当 `STORE_BACKEND=redis`）
- Python 3.10+

## 配置

环境变量（可用 `.env`，见 `Settings`）：


| 变量                     | 说明                                                       |
| ---------------------- | -------------------------------------------------------- |
| `STORE_BACKEND`        | `memory`（默认）或 `redis`                                    |
| `EMBED_WORKER`         | `memory` 时是否在 API 进程内启动 worker，默认 `true`                 |
| `REDIS_URL`            | `STORE_BACKEND=redis` 时，默认 `redis://127.0.0.1:6379/0`    |
| `MAX_CONCURRENT_TASKS` | 默认 `50`                                                  |
| `OPENAI_API_KEY`       | `mode=agent` 时 LLM 需要（也可用配置项 `openai_api_key`）           |
| `OPENAI_BASE_URL`      | 可选，OpenAI 兼容服务根地址（如 `http://localhost:8000/v1`），留空则用官方默认 |
| `OPENAI_MODEL`         | 可选，默认 `gpt-4o-mini`                                      |
| `MOCK_AGENT_DEFAULT`   | 默认 `true`（本地默认 mock）                                     |


## 运行

### 默认（内存后端，无需 Redis）

```bash
pip install -e ".[dev]"
uvicorn agent_backend.main:app --host 0.0.0.0 --port 8080
```

嵌入 worker 会随 API 启动，无需单独开 worker。

### Redis 后端（持久化 / 多进程 worker）

1. 启动 Redis。
2. 设置 `STORE_BACKEND=redis`，启动 API（同上）。
3. Worker（单独终端）：

```bash
set STORE_BACKEND=redis
python -m agent_backend.worker
```

1. 提交任务（示例）：

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/tasks -H "Content-Type: application/json" -d "{\"prompt\":\"hello\",\"mode\":\"mock\"}"
```

1. SSE 订阅（`task_id` 替换为返回的 id）：

```bash
curl -N "http://127.0.0.1:8080/api/v1/tasks/<task_id>/events?from_seq=0"
```

## 示例 CLI（Toolkit / `cli_exec`）

```bash
python -m agent_backend.examples.demo_cli slow
python -m agent_backend.examples.demo_cli sleep --seconds 2
```

## Python 客户端（提交任务 + SSE 流式）

```bash
python -m agent_backend.examples.client_sse --prompt "hello" --mode mock
```

实现见 [`agent_backend/examples/client_sse.py`](agent_backend/examples/client_sse.py)：`submit_task`、`iter_sse_events` 可拷贝到业务代码中；断线重连时把上次收到的最大 `seq` 传给 `--from-seq`。

## 测试

```bash
python -m pytest tests/test_memory_store.py tests/test_smoke.py -v
# Redis 可用时：
python -m pytest tests/test_redis_integration.py tests/test_load.py -v
```

设计规格见 `docs/superpowers/specs/2026-04-13-agentscope-backend-design.md`。