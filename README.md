# agent-backend

基于 AgentScope / AgentScope Runtime 的长任务后端：Redis 持久队列、任务隔离、WebSocket 与 SSE 双通道、CLI 子进程流式日志。

## 依赖版本

- `agentscope` 1.0.x
- `agentscope-runtime` 1.1.x
- Redis 6+
- Python 3.10+

## 配置

环境变量：

| 变量 | 说明 |
|------|------|
| `REDIS_URL` | 默认 `redis://127.0.0.1:6379/0` |
| `MAX_CONCURRENT_TASKS` | 默认 `50` |
| `DASHSCOPE_API_KEY` | `mode=agent` 时 LLM 需要 |
| `MOCK_AGENT_DEFAULT` | `1` 时默认 mock 任务（无 LLM） |

## 运行

1. 启动 Redis（本地或 Docker）。

2. API：

```bash
pip install -e ".[dev]"
uvicorn agent_backend.main:app --host 0.0.0.0 --port 8080
```

3. Worker（单独终端）：

```bash
python -m agent_backend.worker
```

4. 提交任务：

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/tasks -H "Content-Type: application/json" -d "{\"prompt\":\"hello\",\"mode\":\"mock\"}"
```

5. SSE 订阅（`task_id` 替换为返回的 id）：

```bash
curl -N "http://127.0.0.1:8080/api/v1/tasks/<task_id>/events?from_seq=0"
```

## 负载测试

```bash
python -m pytest tests/test_load.py -v
```

设计规格见 `docs/superpowers/specs/2026-04-13-agentscope-backend-design.md`。
