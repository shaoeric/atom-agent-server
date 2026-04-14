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
| `ENABLE_LARK_CLI_TOOL` | 默认 `true`：在 `mode=agent` 时为模型注册飞书官方 `lark-cli` 工具 |
| `LARK_CLI_PATH`        | 可选，`lark-cli` 可执行文件绝对路径；不填则从 `PATH` 查找           |
| `LARK_DOC_FETCH_MAX_TOOL_CHARS` | 默认 `200000`：`feishu_fetch_doc` 工具合并输出给模型的最大字符数，避免长文档被过早截断 |
| `LARK_DOC_FETCH_DEFAULT_LIMIT` | 默认 `400`：`feishu_fetch_doc` 单次分页的 `limit`（与 lark-cli 一致）；长文档应多次调用并增大 `offset` 直至 `has_more` 为 false；工具返回末尾会附带分页提示块 |


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

4. 提交任务（示例）：

```bash
curl -s -X POST http://127.0.0.1:8080/api/v1/tasks -H "Content-Type: application/json" -d "{\"prompt\":\"hello\",\"mode\":\"mock\"}"
```

5. SSE 订阅（`task_id` 替换为返回的 id）：

```bash
curl -N "http://127.0.0.1:8080/api/v1/tasks/<task_id>/events?from_seq=0"
```

## 示例 CLI（Toolkit / `cli_exec`）

```bash
python -m agent_backend.examples.demo_cli slow
python -m agent_backend.examples.demo_cli sleep --seconds 2
```

## 飞书 / Lark CLI（`lark_cli_exec`）

与 [larksuite/cli](https://github.com/larksuite/cli) 官方工具对接：`mode=agent` 时除 `cli_exec` 外会注册 **`lark_cli_exec`**，在子进程中执行本机已安装的 `lark-cli`（输出进入任务 SSE，并截断后回传给模型）。

1. 安装 CLI 与 Agent Skills（官方推荐）：

```bash
npm install -g @larksuite/cli
npx skills add larksuite/cli -y -g
```

2. 在本机完成应用配置与登录（需在浏览器中操作）：

```bash
lark-cli config init --new
lark-cli auth login --recommend
lark-cli auth status
```

3. 启动本后端并提交 `mode=agent` 任务；模型可调用工具 **`lark_cli_exec`**，参数为 **`lark-cli` 后面的整段命令行**（例如 `auth status`、`calendar +agenda --format json`）。

若未在 `PATH` 中找到 `lark-cli`，可设置环境变量 **`LARK_CLI_PATH`** 指向可执行文件。关闭该工具：`ENABLE_LARK_CLI_TOOL=false`。

### 飞书文档：拉取全文与划词批注（专用工具）

在启用 `lark-cli` 的前提下，`mode=agent` 还会注册下列专用工具（底层均为 `lark-cli`）：

| 工具 | 作用 |
| --- | --- |
| **`feishu_fetch_doc`** | `lark-cli docs +fetch`：按 URL/token 拉取云文档正文（JSON，含 `markdown` 等）；支持 `offset` / `limit` 分页，配合返回中的 `has_more` 读完全文。 |
| **`feishu_doc_comment`** | `lark-cli drive +add-comment`：全文评论或划词评论；`comment_type=selection` 时需与正文一致的 `selection_text`（短句或 `开头...结尾` 以唯一匹配）。 |

推荐流程（**长文档须分页**）：反复调用 **`feishu_fetch_doc`**（`offset` 递增，直至返回中的 `has_more` 为 false；工具会在输出末尾附加 `feishu_fetch_pagination` 提示块），每页分析当前页 `markdown`，再对每条问题调用 **`feishu_doc_comment`**，`selection_text` 须从**当前页原文**拷贝；批注文案由模型生成。划词仅适用于新版 **docx**（或 wiki 解析为 docx），旧版 `doc` 宜用全文评论。

仓库另提供独立脚本（不经过 Agent）：

```bash
python scripts/lark_doc_comment.py --doc "<飞书文档链接>" -m "批注内容" -s "定位原文"
python scripts/lark_doc_comment.py -i   # 交互
```

### Agent 事件与流式块

任务日志里 **`type=agent`** 的每条事件可带 **`meta.is_final_chunk`**：与同一条模型流式输出是否已结束对齐。根目录 [`client.py`](client.py) 在 **`--no-stream`** 下只对 `is_final_chunk=true` 的 agent 事件打印，避免同一段正文重复多行；**`--stream`** 仍为逐块打印。

## Python 客户端（提交任务 + SSE）

### 仓库根目录 `client.py`

```bash
python client.py --prompt "你好" --mode agent
python client.py --prompt "接着聊" --session-id <ID> --mode agent --stream
python client.py --prompt "评审某文档" --session-id <ID> --mode agent --no-stream
```

- **默认不加 `--stream`**：非流式（收齐该任务全部 SSE 事件后再打印；`agent` 仅打印带 `is_final_chunk: true` 的完成块，见上文）。
- **`--stream`**：边收边打印，含 token 级中间块。
- **`--from-seq`**：断线重连时从指定序号之后拉取。

### 模块示例 `agent_backend.examples.client_sse`

```bash
python -m agent_backend.examples.client_sse --prompt "hello" --mode agent
```

实现见 [`agent_backend/examples/client_sse.py`](agent_backend/examples/client_sse.py)：`submit_task`、`iter_sse_events` 可拷贝到业务代码中；断线重连时把上次收到的最大 `seq` 传给 `--from-seq`。

## 测试

```bash
python -m pytest tests/test_memory_store.py tests/test_smoke.py -v
# Redis 可用时：
python -m pytest tests/test_redis_integration.py tests/test_load.py -v
```

设计规格见 `docs/superpowers/specs/2026-04-13-agentscope-backend-design.md`。