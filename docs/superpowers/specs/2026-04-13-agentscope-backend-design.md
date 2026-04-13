# AgentScope 长任务后端设计规格（单机高并发）

**版本**: 1.0  
**日期**: 2026-04-13  
**依赖**: `agentscope==1.0.14`, `agentscope-runtime==1.1.3`, Python ≥3.10

## 1. 目标与范围

- 单机/少机部署，约 **50 路并发**长任务（单任务约 10 分钟量级）。
- **任务隔离**：每任务独立 `task_id`、独立 agent 会话键、CLI 为独立子进程。
- **传输**：**WebSocket** 与 **SSE** 共用同一事件模型；支持断线后按 **seq** 增量拉取。
- **持久化**：Redis 保存队列、状态与日志流；进程重启后可继续消费排队任务（运行中任务依 consumer group PEL 再投递策略）。

## 2. 状态机

`queued` → `running` → `succeeded` | `failed` | `cancelled`

- `queued`：已入队，尚未被 worker 认领执行。
- `running`：worker 已认领且执行协程未结束。
- `succeeded` / `failed` / `cancelled`：终态；日志流末尾带 `type=result` 或 `type=error`。

## 3. Redis 键与流

| 键/流 | 说明 |
|--------|------|
| `agent:tasks:pending` | Stream：入队任务，`fields`: `task_id`, `payload`（JSON） |
| `agent:cg:workers` | Consumer group 名称，用于再投递与恢复 |
| `task:{task_id}:meta` | Hash：`status`, `user_id`, `created_at`, `updated_at`, `payload` |
| `task:{task_id}:log` | Stream：事件记录，字段 `data` 为 JSON（含 `seq`） |
| `task:{task_id}:seq` | String：当前最大 seq（INCR） |
| `task:{task_id}:cancel` | String：置 `1` 表示请求取消 |

**实时推送**：每次 `XADD` 后 `PUBLISH` 到频道 `task:{task_id}:live`，载荷与 `data` 相同 JSON，便于 WS/SSE 低延迟 fan-out。

## 4. 事件 JSON 格式

```json
{
  "seq": 42,
  "type": "stdout|stderr|agent|status|result|error",
  "chunk": "可选文本片段",
  "meta": {}
}
```

- `stdout` / `stderr`：CLI 子进程输出。
- `agent`：来自 `stream_printing_messages` 的 agent 可打印消息（序列化为文本）。
- `status`：如 `started`, `queued_position`。
- `result`：成功结束，`meta` 可含 `exit_code` 等。
- `error`：异常或失败。

客户端订阅时以 `seq` 单调递增；SSE 使用 `Last-Event-ID` 或查询参数 `from_seq` 恢复。

## 5. HTTP / WS API

- `POST /api/v1/tasks`  
  Body: `{ "prompt": "...", "user_id": "optional", "mode": "mock|agent" }`  
  Response: `{ "task_id", "status" }`

- `GET /api/v1/tasks/{task_id}`  
  返回 meta 与当前状态。

- `GET /api/v1/tasks/{task_id}/events`  
  **SSE**，Query: `from_seq`（默认 0）。先 `XRANGE` 重放历史，再 `SUBSCRIBE` 实时（或轮询 stream 尾部，实现二选一；实现采用 XRANGE + PubSub）。

- `WebSocket /api/v1/tasks/{task_id}/ws`  
  支持 JSON：`{"op":"subscribe","from_seq":0}`；服务端推送与 SSE 相同事件对象。

- `POST /api/v1/tasks/{task_id}/cancel`  
  设置取消标记；worker 与子进程协作退出。

## 6. 并发与背压

- Worker 进程内 `asyncio.Semaphore(MAX_CONCURRENT_TASKS)`，`MAX_CONCURRENT_TASKS` 默认 **50**（环境变量可覆盖）。
- 入队不拒绝；若需「队列位置」可在 `status` 事件中扩展 `queue_depth`（可选）。

## 7. Agent 与 CLI 执行

- **mock**：无 LLM，用于压测与 CI；模拟分段日志与延迟。
- **agent**：`ReActAgent` + `stream_printing_messages`，工具集中注册 **CLI 工具**（`cli_runner` 异步子进程，按行/块写入事件流）。
- **Runtime**：执行路径对齐 AgentScope 1.x 管道；`AgentApp` 可作为可选独立服务挂载（本仓库以任务 API 为主，避免与长轮询 SSE 模型重复）。

## 8. 取消与 Windows

- 取消时设置 Redis 键并 `PUBLISH`；执行循环检查取消标志。
- 子进程：POSIX 使用 `os.killpg`（若创建了进程组）；Windows 使用 `subprocess` + `terminate()` / `kill()` 或 `taskkill /T /PID`（实现于 `cli_runner`）。

## 9. 观测

- 结构化日志含 `task_id`。
- 可选：队列深度 = `XLEN agent:tasks:pending` 近似（或独立计数）。

## 10. 测试

- 单元：事件 seq、状态迁移。
- 集成：假 CLI、SSE+WS 同时订阅、断线 `from_seq` 重放。
- 负载：50 路 `mock` 并发，验证背压与无异常退出。
