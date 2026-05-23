# DeepDive 后端架构提案

## 1. 目标与边界

DeepDive 是一个基于 LLM 的源码分析后端平台。前端提交一个 Git 仓库地址和引用，例如分支、tag 或 commit。后端先创建不可变的仓库快照，将 Git 对象、文件内容、文件树和指令文件存储到 MinIO；随后由基于 OpenAI Responses API 的 Agent 在快照上执行只读源码分析。

本提案当前聚焦后端。实现语言为 Python，后端代码统一放置在 `backend/` 目录下。

前端不负责也无权指定以下内容：

```text
模型名称
system instruction
developer instruction
prompt 模板
工具 schema
工具权限
上下文拼接策略
最大 turn 数
compaction 策略
```

这些能力全部由后端配置文件和后端代码控制。系统启动时加载配置文件，创建分析任务时固化本次任务的 effective config snapshot，后续 Agent 执行、恢复、排查和审计都以该快照为准。

核心目标：

1. 支持云端长时间运行的源码分析 Agent。
2. 保证任务在 worker 重启、Kafka 重投递、SSE 断线、Responses API 流中断等情况下可恢复。
3. 让 Agent 通过有限、只读、可审计的工具读取和搜索源码。
4. 保留完整上下文、工具调用、证据、输出和配置版本，便于复现分析过程。
5. 不引入 tree-sitter、LSP、SCIP/LSIF 等预分析系统作为 MVP 依赖。现代 LLM 足以基于文件树、搜索和文件读取制定分析计划；过早依赖语言服务反而会被非规范仓库拖垮。

## 2. 总体原则

1. Postgres 18 是事实状态存储。Kafka 负责驱动异步流程，但不是任务状态的唯一记录。
2. MinIO 存储不可变大对象，包括 Git bundle、文件 blob、manifest、Agent 输入输出、工具结果和证据片段。
3. 仓库快照一旦创建即不可变。Agent 始终读取 `snapshot_id`，不直接读取可变分支。
4. 所有平台生成的 ID 都使用 UUIDv7。数据库主键、DTO 字段、Kafka event ID、correlation ID、causation ID 都使用 UUIDv7 字符串。
5. Prompt 是行为指导，不是安全边界。路径权限、工具权限、大小限制、缓存策略和执行策略都由后端代码强制执行。
6. 上下文拼接是平台能力，不是一次性字符串拼接。每次发往 Responses API 的输入都要保存来源引用、配置版本、token 估算和对象引用。
7. Compaction 是显式、可审计的状态转换。不能依赖模型上下文静默截断。
8. Worker 必须按 at-least-once 交付模型设计，所有副作用都要可幂等或可检测重复。

## 3. 参考实现经验

Codex 和 Claude Code 的公开资料对本平台有几条直接可用的经验：

1. 长任务应围绕 thread/session/turn/item 建模，而不是围绕一次 HTTP 请求建模。
2. `AGENTS.md`、`CLAUDE.md`、memory 等项目指令文件应作为可追踪上下文来源注入模型，而不是作为权限系统。
3. 工具调用需要两层控制：模型可见的 tool schema，以及后端强制执行的 policy evaluator。
4. 子 Agent 应使用隔离上下文，父 Agent 只接收结构化结论、证据引用和必要摘要，不共享完整上下文污染。
5. Compact 后应保留可继续执行的机器状态，包括已完成步骤、关键事实、证据引用、未解决问题、活动假设和下一步动作。
6. 恢复、fork、rollback、compact 这类长任务能力都依赖事件流、上下文 item 和持久化 session，而不是依赖进程内内存。

DeepDive 的 MVP 只实现单 Agent 主循环，但数据模型应为后续子 Agent、fork、reviewer、planner、explorer 等角色留下扩展点。

## 4. 高层流程

```text
POST /analysis
  -> API 校验请求
  -> 在数据库事务中写入 outbox event: AnalysisRequested
  -> outbox publisher 发布 Kafka 事件

snapshot worker
  -> 消费 AnalysisRequested 或 SnapshotRequested
  -> 使用 git CLI 解析仓库 URL 和 ref
  -> 创建不可变快照
  -> 将 Git bundle、manifest、文件 blob、文件树、AGENTS.md 存储到 MinIO
  -> 写入 snapshots、snapshot_files、agent_instruction_files
  -> 发布 SnapshotReady

agent worker
  -> 消费 SnapshotReady 或 AgentContinueRequested
  -> 根据 agent_session 和 config_snapshot 组装上下文
  -> 调用 OpenAI Responses API 并流式接收输出
  -> 持久化 stream event、turn、response metadata、usage
  -> 如果模型产生 tool call，写入 tool_calls 并发布 ToolCallRequested
  -> 如果模型完成分析，写入完成状态和最后一轮输出摘要，并发布 AnalysisCompleted

execution worker
  -> 消费 ToolCallRequested
  -> 通过 PermissionEngine 校验工具名、参数、路径、大小和运行限制
  -> 执行 list_files、search_file、search_text、read_file
  -> search_text 使用 ripgrep CLI，并通过本地 prefix cache 访问 MinIO 中的源码
  -> 持久化 tool_result、evidence、stream event
  -> 发布 ToolCallCompleted

agent worker
  -> 消费 ToolCallCompleted
  -> 将工具结果加入下一轮上下文
  -> 继续 Responses API 循环
```

## 5. 后端目录分层

```text
backend/
  config/              启动配置加载、校验、effective config snapshot
  api/                 FastAPI 路由、认证、DTO 校验、SSE 输出
  events/              Kafka envelope、producer、consumer、outbox publisher
  db/                  SQLAlchemy/Alembic、repository、事务边界
  storage/             MinIO client、object key 规范、流式读写
  snapshot/            git CLI 快照、manifest 构建、AGENTS.md 扫描
  instructions/        system/developer/profile/AGENTS.md 解析
  agent/               上下文组装、Responses runner、stream parser、compaction
  execution/           ToolRegistry、PermissionEngine、工具执行器
  cache/               本地源码缓存、prefix materialization、LRU/TTL 清理
  workers/             snapshot、agent、execution、outbox、retry、DLQ worker
  observability/       日志、指标、trace、usage 统计
```

推荐模块边界：

```text
ConfigService
  加载 YAML/TOML/env
  校验配置
  生成 content_hash
  创建 config_snapshots

InstructionResolver
  解析配置中的 system/developer/profile 指令
  解析 snapshot 中的 AGENTS.md 作用域
  为 ContextAssembler 返回带 source_ref 的 instruction block

ContextAssembler
  读取 session、turn、memory、tool result、evidence
  生成 Responses API input items
  保存 context_assemblies

ResponsesRunner
  调用 OpenAI Responses API
  处理 streaming event
  识别 tool call 和完成输出

ToolRegistry
  根据后端配置生成模型可见 tool schema
  持久化 tool_registry_version 和 tool_schema_hash

PermissionEngine
  对工具调用做 deny -> ask -> allow 决策
  MVP 中 ask 可先实现为 soft-deny 或内部策略审批

CacheManager
  ensure_prefix(snapshot_id, prefix)
  ensure_file(snapshot_id, path)
  管理本地 cache coverage、lock、hash 校验和清理
```

## 6. 配置系统

### 6.1 启动配置

系统启动时加载后端配置文件。配置可以来自 `backend/config/*.yml`、环境变量和部署系统，但合并后的 effective config 必须可序列化、可 hash、可持久化。

推荐配置结构：

```yaml
openai:
  model: "gpt-5.5"
  reasoning_effort: "medium"
  reasoning_summary: "auto"
  show_reasoning_summary: true
  service_tier: "fast"
  parallel_tool_calls: false

prompt:
  system_instruction_file: "prompts/system.md"
  developer_instruction_file: "prompts/developer.md"
  compaction_instruction_file: "prompts/compact.md"

analysis:
  default_profile: "repository_architecture_review"
  profiles:
    repository_architecture_review:
      goal_file: "profiles/repository_architecture_review.md"
      max_turns: 80
      max_tool_calls: 200
      auto_compact_threshold_tokens: 120000

tools:
  enabled:
    - list_files
    - search_file
    - search_text
    - read_file
  read_file:
    default_lines: 200
    max_lines: 500
    max_bytes: 65536
  search_text:
    max_results: 100
    timeout_seconds: 20
    max_output_bytes: 1048576

snapshot:
  max_file_bytes: 1048576
  lfs_policy: "pointer_only"
  submodule_policy: "record_only"
  binary_policy: "metadata_only"

cache:
  root_dir: "/cache/deepdive"
  max_worker_cache_bytes: 53687091200
  max_prefix_bytes: 2147483648
  ttl_days: 7
  min_free_disk_percent: 15
```

### 6.2 前端不可覆盖配置

前端请求不能传入以下字段：

```text
model
system_instruction
developer_instruction
prompt
prompt_template
tool_registry
tool_choice
max_turns
parallel_tool_calls
cache_policy
snapshot_policy
```

如果未来需要不同分析模式，前端只能选择后端预先注册的 `analysis_profile_id` 或 profile key。profile 的实际 prompt、工具配置和运行限制仍由后端决定。

### 6.3 配置快照

创建 analysis 时必须保存本次任务的 effective config snapshot。原因是配置文件会随部署变化，如果不固化配置，旧任务无法复现，也无法解释为什么某次任务使用了某个模型、prompt、工具限制或 snapshot policy。

表结构建议：

```text
config_snapshots
  id uuid primary key default uuidv7()
  config_version text not null
  content_hash text not null
  config_json jsonb not null
  created_at timestamptz not null
```

`agent_sessions` 应保存：

```text
config_snapshot_id
effective_model
effective_prompt_version
effective_tool_registry_version
effective_limits_json
effective_runtime_json
```

## 7. REST API 设计

API 保持 REST 风格，但不强制使用复数资源名。当前采用 `/analysis` 作为分析资源前缀。

### 7.1 创建分析任务

```text
POST /analysis
```

请求体：

```json
{
  "repository_url": "https://github.com/example/project.git",
  "ref": "main"
}
```

可选的受控 profile：

```json
{
  "repository_url": "https://github.com/example/project.git",
  "ref": "main",
  "analysis_profile_id": "0197201c-7b6e-73d2-9d0b-34d66534b19a"
}
```

响应：

```json
{
  "analysis_id": "01972020-9630-737c-a507-348f44d7161e",
  "agent_id": "01972020-bd2f-70e3-8661-367b1f8e3a9f",
  "snapshot_id": null,
  "status": "queued",
  "created_at": "2026-05-22T05:00:00Z"
}
```

### 7.2 查询分析列表

```text
GET /analysis
```

查询参数：

```text
status
repository_url_hash
created_after
created_before
limit
cursor
```

返回：

```json
{
  "items": [
    {
      "analysis_id": "01972020-9630-737c-a507-348f44d7161e",
      "agent_id": "01972020-bd2f-70e3-8661-367b1f8e3a9f",
      "status": "running",
      "repository_url": "https://github.com/example/project.git",
      "requested_ref": "main",
      "resolved_commit_sha": "4f7a...",
      "created_at": "2026-05-22T05:00:00Z",
      "updated_at": "2026-05-22T05:03:20Z"
    }
  ],
  "next_cursor": null
}
```

### 7.3 查询单个分析任务

```text
GET /analysis/{analysis_id}
```

返回 analysis、snapshot、agent session、最新状态、错误信息和统计信息。

### 7.4 取消分析任务

```text
POST /analysis/{analysis_id}/cancel
```

取消不是删除数据，而是：

1. 将 analysis/session 状态更新为 `cancelling` 或 `cancelled`。
2. 写入 outbox event: `AnalysisCancelRequested`。
3. Worker 在安全边界内停止后续步骤。
4. 已持久化的 turn、tool call、stream event 和证据继续保留。

### 7.5 读取 Agent 输出流

```text
GET /analysis/{analysis_id}/events
```

使用 Server-Sent Events。客户端通过 `Last-Event-ID` 恢复。

SSE 规则：

```text
SSE id 使用 agent_stream_events.seq
Last-Event-ID 表示客户端已收到的最大 seq
API 先从 Postgres replay seq > Last-Event-ID 的事件
随后订阅 Kafka live stream
SSE 断线不影响 worker 执行
```

事件类型：

```text
status
model_reasoning_summary
delta
tool_call
tool_result
evidence
compact
error
done
```

`model_reasoning_summary` 事件来自 Responses completed payload 中的最终
reasoning summary，作为可恢复 stream event 写入 `agent_stream_events`。
客户端断线后通过 `Last-Event-ID` replay 时，应能恢复已持久化的最终模型思考
摘要。Responses API 的最终输出文本仍通过 live `response.output_text.delta`
流式输出给 `/events` 客户端，但不写入 `agent_stream_events`；raw OpenAI
token、tool argument delta、reasoning summary delta/done 只作为受控
debug 事件暴露，不作为默认 `/events` 输出，也不作为默认持久化 replay 内容。

示例：

```text
id: 42
event: delta
data: {"text":"该仓库的后端入口位于 backend/api/..."}
```

### 7.6 标准错误格式

```json
{
  "error": {
    "code": "ANALYSIS_NOT_FOUND",
    "message": "Analysis does not exist.",
    "request_id": "01972024-2863-7ccd-80cd-c4044e9fe1a6"
  }
}
```

## 8. 状态模型

### 8.1 Analysis 状态

```text
queued
snapshotting
running
waiting_for_tool
compacting
completed
failed
cancelling
cancelled
```

### 8.2 Agent 状态

```text
queued
assembling_context
calling_model
streaming
waiting_tool
compacting
completed
failed
cancelled
```

### 8.3 Tool Call 状态

```text
queued
validating
running
completed
failed
denied
cancelled
```

## 9. Kafka 事件设计

Kafka 使用统一 envelope。所有平台生成的 ID 都是 UUIDv7。

```json
{
  "event_id": "01972021-9e38-7cc4-a2f5-17430f3ef46f",
  "schema_version": 1,
  "event_type": "ToolCallRequested",
  "occurred_at": "2026-05-22T05:00:00Z",
  "correlation_id": "01972020-9630-737c-a507-348f44d7161e",
  "causation_id": "01972021-0f84-75e8-b100-47eb83f28b7d",
  "analysis_id": "01972020-9630-737c-a507-348f44d7161e",
  "agent_id": "01972020-bd2f-70e3-8661-367b1f8e3a9f",
  "snapshot_id": "01972020-f8e3-7777-ae8d-68188d8d8d5c",
  "attempt": 1,
  "payload": {}
}
```

推荐 topic：

```text
deepdive.analysis.commands
deepdive.snapshot.commands
deepdive.agent.commands
deepdive.execution.commands
deepdive.domain.events
deepdive.agent.stream
deepdive.dlq
```

事件 key：

```text
analysis_id   工作流推进事件
agent_id      Agent stream 事件
tool_call_id  工具执行事件
```

Kafka delivery 按 at-least-once 设计。每个 consumer 在处理前写入：

```text
processed_events(event_id, consumer_name)
```

如果唯一键冲突，说明该 consumer 已处理过此事件，可以直接 ack。

API 发布事件必须使用 transactional outbox：

1. API 在一个 Postgres 事务内写入 analysis/session/config_snapshot。
2. 同事务写入 `outbox_events`。
3. Outbox publisher 使用 `FOR UPDATE SKIP LOCKED` 读取未发布事件。
4. 发布 Kafka 成功后标记 `published_at`。

## 10. 数据库设计

目标数据库为 Postgres 18。主键统一使用 `uuid` 类型，默认值使用 Postgres 18 的 `uuidv7()`。

```sql
id uuid primary key default uuidv7()
```

仍然需要保留 `created_at timestamptz` 和 `updated_at timestamptz`。UUIDv7 的时间有利于索引局部性，但不能替代业务时间字段。

### 10.1 Core Tables

```text
analyses
  id uuid primary key default uuidv7()
  tenant_id uuid
  repository_url text not null
  repository_url_hash text not null
  requested_ref text not null
  analysis_profile_id uuid
  config_snapshot_id uuid not null
  status text not null
  created_at timestamptz not null
  updated_at timestamptz not null
  completed_at timestamptz
  error_code text
  error_message text

agent_sessions
  id uuid primary key default uuidv7()
  analysis_id uuid not null
  snapshot_id uuid
  parent_agent_id uuid
  config_snapshot_id uuid not null
  status text not null
  goal_ref text not null
  effective_model text not null
  effective_prompt_version text not null
  effective_tool_registry_version text not null
  effective_limits_json jsonb not null
  effective_runtime_json jsonb not null
  latest_response_id text
  turn_count integer not null
  max_turns integer not null
  created_at timestamptz not null
  updated_at timestamptz not null

agent_turns
  id uuid primary key default uuidv7()
  agent_id uuid not null
  turn_index integer not null
  status text not null
  response_id text
  previous_response_id text
  input_ref text
  output_ref text
  input_token_count integer
  output_token_count integer
  total_token_count integer
  created_at timestamptz not null
  completed_at timestamptz

agent_stream_events
  id uuid primary key default uuidv7()
  analysis_id uuid not null
  agent_id uuid not null
  seq bigint not null
  event_type text not null
  payload_json jsonb not null
  created_at timestamptz not null

context_assemblies
  id uuid primary key default uuidv7()
  agent_id uuid not null
  turn_id uuid not null
  config_snapshot_id uuid not null
  source_refs_json jsonb not null
  input_ref text not null
  instructions_hash text not null
  tool_schema_hash text not null
  token_estimate integer
  created_at timestamptz not null

tool_calls
  id uuid primary key default uuidv7()
  agent_id uuid not null
  turn_id uuid not null
  snapshot_id uuid not null
  openai_call_id text not null
  tool_name text not null
  arguments_json jsonb not null
  tool_registry_version text not null
  tool_schema_hash text not null
  tool_policy_hash text not null
  permission_decision text
  status text not null
  result_ref text
  result_summary text
  duration_ms integer
  error_code text
  error_message text
  created_at timestamptz not null
  completed_at timestamptz

evidence
  id uuid primary key default uuidv7()
  agent_id uuid not null
  snapshot_id uuid not null
  tool_call_id uuid
  path text not null
  start_line integer
  end_line integer
  content_hash text
  snippet_ref text
  created_at timestamptz not null

memory_summaries
  id uuid primary key default uuidv7()
  agent_id uuid not null
  compacted_until_turn integer not null
  summary_json jsonb not null
  evidence_ids_json jsonb not null
  focus_paths_json jsonb not null
  next_action text
  created_at timestamptz not null

config_snapshots
  id uuid primary key default uuidv7()
  config_version text not null
  content_hash text not null
  config_json jsonb not null
  created_at timestamptz not null

outbox_events
  id uuid primary key default uuidv7()
  event_type text not null
  payload_json jsonb not null
  published_at timestamptz
  created_at timestamptz not null

processed_events
  event_id uuid not null
  consumer_name text not null
  processed_at timestamptz not null
```

### 10.2 Snapshot Tables

```text
snapshots
  id uuid primary key default uuidv7()
  tenant_id uuid
  repository_url_hash text not null
  requested_ref text not null
  resolved_commit_sha text not null
  tree_sha text not null
  snapshot_policy_hash text not null
  status text not null
  manifest_key text
  git_bundle_key text
  file_count integer
  total_bytes bigint
  created_at timestamptz not null
  ready_at timestamptz
  error_code text
  error_message text

snapshot_files
  id uuid primary key default uuidv7()
  snapshot_id uuid not null
  path text not null
  path_hash text not null
  parent_path text
  name text not null
  entry_kind text not null
  git_mode text
  git_blob_oid text
  content_key text
  content_hash text
  size_bytes bigint
  line_count integer
  is_binary boolean not null
  is_large boolean not null
  created_at timestamptz not null

agent_instruction_files
  id uuid primary key default uuidv7()
  snapshot_id uuid not null
  path text not null
  scope_path text not null
  depth integer not null
  content_hash text not null
  content_ref text not null
  created_at timestamptz not null
```

### 10.3 推荐索引

```text
analyses(tenant_id, created_at)
analyses(status, updated_at)
agent_sessions(analysis_id)
agent_turns(agent_id, turn_index)
agent_stream_events(analysis_id, seq) unique
agent_stream_events(agent_id, seq)
tool_calls(agent_id, status)
tool_calls(openai_call_id)
evidence(agent_id, path)
snapshots(repository_url_hash, resolved_commit_sha, snapshot_policy_hash)
snapshot_files(snapshot_id, path) unique
snapshot_files(snapshot_id, parent_path)
snapshot_files(snapshot_id, content_hash)
processed_events(event_id, consumer_name) unique
outbox_events(published_at, created_at)
```

高写入表建议预留分区或归档策略：

```text
agent_stream_events
agent_turns
tool_calls
outbox_events
processed_events
```

## 11. MinIO 存储设计

MinIO 存储不可变大对象。数据库只保存 object key、hash、摘要和结构化元数据。

Object key 规范：

```text
git-bundles/{repo_hash}/{commit_sha}.bundle
snapshots/{snapshot_id}/manifest.json.zst
snapshots/{snapshot_id}/tree.txt
snapshots/{snapshot_id}/file-tree.json.zst
blobs/sha256/{first2}/{next2}/{content_sha256}
instructions/{snapshot_id}/{path_hash}.md
agent-inputs/{agent_id}/{turn_id}.json.zst
agent-outputs/{agent_id}/{turn_id}.json.zst
tool-results/{tool_call_id}.json.zst
evidence/{evidence_id}.txt
configs/{config_snapshot_id}.json
```

文件内容按 `content_hash` 寻址，而不是按 path 寻址。path 存在 Postgres 和 manifest 中。这样可以跨 snapshot 去重。

## 12. Snapshot 模块

Snapshot worker 使用 git CLI，不直接用 Git library 实现核心 clone/fetch/cat-file 逻辑。

仓库输入视为不可信，执行时需要：

```text
隔离临时目录
命令超时
stdout/stderr 大小限制
credential 脱敏
禁止把 token 输出到日志
清理临时目录
```

主要命令：

```text
git clone --mirror <repository_url> repo.git
git -C repo.git fetch --prune
git -C repo.git rev-parse <ref>^{commit}
git -C repo.git rev-parse <commit>^{tree}
git -C repo.git ls-tree -r -z --long <commit>
git -C repo.git cat-file --batch
git -C repo.git bundle create snapshot.bundle <commit>
```

Snapshot 输出：

1. `snapshots` row，保存 resolved commit、tree hash、snapshot policy hash。
2. `snapshot_files` rows，保存文件、目录、symlink、submodule entry。
3. 文件 blob 存储到 MinIO `blobs/sha256/...`。
4. manifest、file tree、tree text 存储到 MinIO。
5. 扫描 `AGENTS.md` 并写入 `agent_instruction_files`。

默认策略：

```text
LFS: MVP 只记录 pointer，不下载真实 LFS object
Submodule: MVP 只记录 gitlink，不递归抓取
Binary: 只存元数据，不进入 read/search
Large file: 超过配置上限则只存元数据或截断策略记录
Generated/vendor: 存元数据；是否允许 read/search 由工具 policy 控制
```

幂等键建议：

```text
unique(repository_url_hash, resolved_commit_sha, snapshot_policy_hash)
```

`snapshot_policy_hash` 来自后端配置，至少包含：

```text
max_file_bytes
lfs_policy
submodule_policy
binary_policy
generated/vendor policy
secret path deny rules
```

同一个 commit 在不同 snapshot policy 下可能产生不同可读文件集合，因此应视为不同 snapshot。

## 13. 指令系统

DeepDive 使用多层指令系统。优先级：

```text
system instruction
developer instruction
analysis profile instruction
AGENTS.md scoped instruction
repository content / tool output
```

说明：

1. `system instruction` 来自后端配置，定义平台身份、安全边界、不可信仓库内容策略。
2. `developer instruction` 来自后端配置，定义 DeepDive 的分析习惯、证据要求、工具使用策略、输出格式。
3. `analysis profile instruction` 来自后端配置或已注册 profile，定义当前任务目标。
4. `AGENTS.md` 来自仓库 snapshot，只作为项目指导上下文。
5. repository content 和 tool output 是被分析对象，始终视为不可信内容。

`AGENTS.md` 规则：

```text
AGENTS.md 的作用域是其所在目录及所有子目录
根目录 AGENTS.md 可早期加载
Agent 关注某个 path 时，加载从根到该 path 的 AGENTS.md 链
更深层 AGENTS.md 对其作用域内文件的指导更具体
system/developer/profile 指令始终高于 AGENTS.md
AGENTS.md 不能放宽工具权限
AGENTS.md 不能扩大可读路径
AGENTS.md 不能覆盖后端配置
```

每次上下文组装必须在 `context_assemblies.source_refs_json` 中记录实际注入的指令来源：

```json
[
  {"type": "system", "ref": "config:prompts/system.md", "hash": "sha256:..."},
  {"type": "developer", "ref": "config:prompts/developer.md", "hash": "sha256:..."},
  {"type": "profile", "ref": "profile:repository_architecture_review", "hash": "sha256:..."},
  {"type": "agents_md", "path": "AGENTS.md", "scope_path": "", "hash": "sha256:..."}
]
```

## 14. Agent 模块

Agent worker 负责 Responses API 主循环，但不直接执行工具。

职责：

1. 根据 session 状态和 config snapshot 组装下一轮上下文。
2. 调用 OpenAI Responses API。
3. 流式接收输出并先持久化，再转发给前端。
4. 识别 function/tool call。
5. 写入 `tool_calls` 并发布 `ToolCallRequested`。
6. 在 `ToolCallCompleted` 后继续下一轮。
7. 在上下文接近阈值时执行 compaction。
8. 写入分析完成状态，并保存最后一轮 Agent 输出摘要。

上下文组装顺序建议：

```text
system instruction
developer instruction
analysis profile instruction
active AGENTS.md chain
snapshot metadata
file tree 或 compact file tree
memory summary
recent turns
recent tool result summaries
pending tool outputs
current analysis objective
```

注意：`current analysis objective` 来自后端 profile，不来自前端任意 prompt。

工具调用使用 Responses API function calling 语义。MVP 建议：

```text
parallel_tool_calls=false
```

这样可以简化顺序和证据归因。如果后续要支持并行工具调用，需要确保 tool call 之间没有共享可变状态，并且每个 call 都独立幂等。

## 15. Compaction 设计

Compaction 是平台主动执行的上下文压缩，不依赖静默截断。

触发条件：

```text
上下文 token 估算超过 auto_compact_threshold
turn 数超过配置阈值
工具结果累计过大
Agent worker 恢复时发现上下文无法安全拼接
```

Compact 输出不应只是自然语言摘要，而应是机器可恢复状态：

```json
{
  "goal": "分析仓库后端架构与关键模块边界。",
  "completed_steps": [
    "已完成仓库快照",
    "已读取根目录文件树",
    "已搜索 API 入口和 worker 入口"
  ],
  "confirmed_facts": [
    {
      "claim": "API 层位于 backend/api。",
      "evidence_ids": ["01972028-bcd0-7acf-a4f4-d8d470d978f5"]
    }
  ],
  "active_hypotheses": [
    {
      "claim": "worker 使用 Kafka topic 进行解耦。",
      "confidence": "medium",
      "needed_evidence": "继续读取 backend/workers 和 backend/events。"
    }
  ],
  "open_questions": [
    "execution worker 是否已经实现 prefix cache？"
  ],
  "focus_paths": ["backend/api/", "backend/workers/", "backend/events/"],
  "next_action": "search_text query='ToolCallRequested' path_prefix='backend/'"
}
```

证据片段不被 compaction 替代。`memory_summaries` 只引用 `evidence_id`，原始证据继续保留在 Postgres + MinIO。

Compaction 后下一轮上下文应包含：

```text
固定 system/developer/profile 指令
必要 AGENTS.md chain
最新 memory summary
最近若干原始 turns
未完成 tool output
当前分析目标
```

## 16. 工具调用设计

MVP 只暴露只读工具：

```text
list_files
search_file
search_text
read_file
```

`snapshot_id`、`analysis_id`、`agent_id` 来自持久化 tool call 上下文，不由模型参数传入。模型不能选择任意 snapshot。

工具统一响应 envelope：

```json
{
  "ok": true,
  "tool_name": "read_file",
  "snapshot_id": "01972020-f8e3-7777-ae8d-68188d8d8d5c",
  "result": {},
  "evidence_ids": ["01972028-bcd0-7acf-a4f4-d8d470d978f5"],
  "truncated": false,
  "next_cursor": null
}
```

错误 envelope：

```json
{
  "ok": false,
  "error": {
    "code": "PATH_NOT_FOUND",
    "message": "No file exists at backend/server.py in this snapshot.",
    "retryable": false,
    "suggested_next_tool": "search_file"
  }
}
```

### 16.1 list_files

从 Postgres `snapshot_files` 列出文件和目录，不下载 MinIO 文件内容。

参数：

```json
{
  "path": null,
  "recursive": false,
  "glob": null,
  "max_results": 100,
  "cursor": null
}
```

返回字段：

```text
path
type
size_bytes
line_count
child_count
is_binary
is_large
```

### 16.2 search_file

按文件名或路径搜索 `snapshot_files`，不搜索文件内容。

参数：

```json
{
  "query": "settings",
  "glob": "**/*.py",
  "max_results": 50,
  "cursor": null
}
```

### 16.3 search_text

使用 ripgrep CLI 搜索文件内容。由于源码存储在 MinIO，执行前需要通过本地 prefix cache materialize 指定目录。

参数：

```json
{
  "query": "KafkaConsumer",
  "mode": "literal",
  "path_prefix": "backend/",
  "path_glob": "**/*.py",
  "case_sensitive": false,
  "context_lines": 2,
  "max_results": 50,
  "cursor": null
}
```

执行要求：

```text
使用 argv list，不拼 shell 字符串
rg 输出使用 --json
设置 timeout
设置最大输出字节数
设置最大结果数
只允许在 CacheManager materialized prefix 内搜索
解析 JSON 输出后写入 evidence
```

示例 argv：

```text
rg --json --line-number --column -C 2 KafkaConsumer /cache/deepdive/snapshots/{snapshot_id}/files/backend
```

### 16.4 read_file

按行读取单个文件。默认读取前 200 行，硬上限由配置控制。

参数：

```json
{
  "path": "backend/workers/agent.py",
  "start_line": 1,
  "end_line": 200,
  "max_bytes": 65536
}
```

规则：

```text
行号从 1 开始
未指定范围时默认读取 1-200
最大行数由配置限制，例如 500
最大字节数由配置限制，例如 64 KiB
超限时返回 truncated=true 和 next_start_line
读取前通过 CacheManager.ensure_file(snapshot_id, path) 下载并校验 hash
```

## 17. Permission Engine

权限模型采用：

```text
deny -> ask -> allow
```

MVP 中 `ask` 可以先映射为内部 soft-deny 或需要管理员策略审批；不建议让模型自行决定。

默认 deny：

```text
绝对路径
path traversal
.git 内部路径
平台元数据路径
配置中的 secret path
二进制文件 read/search
超过 hard max size 的文件
未启用的工具
参数 schema 不匹配
snapshot_id 与 tool_call 上下文不一致
```

默认 soft-deny 或受限：

```text
大文件
vendor/generated 目录
lockfile
LFS 真实对象下载
超大 prefix materialization
```

默认 allow：

```text
list_files/search_file 访问 snapshot metadata
search_text/read_file 在允许 path 和运行限制内读取文本文件
```

权限决策需要写入 `tool_calls.permission_decision`，并在 stream 中产生 `tool_result` 或 `error` 事件。

## 18. 本地源码缓存

execution worker 需要本地文件系统视图供 ripgrep 使用。MinIO 是源数据，本地 cache 只是性能层。

Cache layout：

```text
/cache/deepdive/
  snapshots/{snapshot_id}/
    files/
      <repo-relative-path>
    coverage.json
    locks/
    line-index/
```

### 18.1 Prefix Cache

Agent 经常在某个目录内搜索，因此 `search_text` 支持 prefix materialization。

`CacheManager.ensure_prefix(snapshot_id, prefix)`：

1. normalize prefix，拒绝不安全路径。
2. 检查 `coverage.json`，判断是否已有相同或更宽的 prefix 覆盖。例如 `backend/` 已覆盖 `backend/api/`。
3. 查询 Postgres `snapshot_files`，列出 prefix 下的文本文件。
4. 排除 binary、large、policy deny 文件。
5. 从 MinIO 下载缺失对象到临时文件。
6. 校验 `content_hash`。
7. atomic rename 到 `files/<path>`。
8. 更新 `coverage.json`，标记 prefix 完成。

`coverage.json` 示例：

```json
{
  "snapshot_id": "01972020-f8e3-7777-ae8d-68188d8d8d5c",
  "manifest_hash": "sha256:...",
  "prefixes": [
    {
      "prefix": "backend/",
      "completed_at": "2026-05-22T05:00:00Z",
      "file_count": 132,
      "bytes": 824120
    }
  ]
}
```

缓存行为：

```text
cache 不是事实来源，可删除重建
cache 通过 Postgres + MinIO 重建
prefix 下载使用锁避免重复下载
清理策略使用 TTL + LRU + disk watermark
```

建议初始限制：

```text
max cache size per execution worker: 50 GiB
max prefix materialization size: 2 GiB
TTL for unused snapshot cache: 7 days
minimum free disk watermark: 15%
```

### 18.2 Single File Cache

`read_file` 不应为了读取一个文件 materialize 整个目录。它应使用：

```text
CacheManager.ensure_file(snapshot_id, path)
```

该方法只下载单个文件，校验 hash，并放在 snapshot cache 的相同相对路径下。

大文件 line index 可后续添加：

```text
line-index/{path_hash}.idx
```

MVP 可以逐行读取，只要严格执行最大行数和最大字节数限制。

## 19. Worker 设计

### 19.1 Snapshot Worker

消费：

```text
AnalysisRequested
SnapshotRequested
```

发布：

```text
SnapshotStarted
SnapshotReady
SnapshotFailed
```

幂等策略：

```text
unique(repository_url_hash, resolved_commit_sha, snapshot_policy_hash)
```

如果相同 snapshot 已 ready，可以直接关联现有 snapshot 并发布 `SnapshotReady`。

### 19.2 Agent Worker

消费：

```text
SnapshotReady
AgentContinueRequested
ToolCallCompleted
CompactRequested
AnalysisCancelRequested
```

发布：

```text
AgentStarted
ToolCallRequested
AgentWaitingForTool
AgentCompacted
AnalysisCompleted
AnalysisFailed
AnalysisCancelled
```

模型 Responses API 的 token 级实时预览流不作为 durable domain event 发布，
也不写入 `agent_stream_events`。Agent worker 直接向 `deepdive.agent.stream`
发布轻量 `LiveModelStreamEvent`；API 只读该 topic 并转发给当前在线的
`GET /analysis/{analysis_id}/events` SSE 连接。`response.completed` 的 live
事件只携带轻量完成信号和 `response_id`，完整模型输出在请求完成后通过
`agent_turns.output_ref` 指向的对象存储结果恢复。

Agent worker 必须可恢复。崩溃后新 worker 应读取：

```text
agent_sessions
agent_turns
tool_calls
agent_stream_events
latest_response_id
context_assemblies
```

然后决定继续、重试、等待工具结果、compact 或标记失败。

### 19.3 Execution Worker

消费：

```text
ToolCallRequested
AnalysisCancelRequested
```

发布：

```text
ToolCallStarted
ToolCallCompleted
ToolCallFailed
ToolCallDenied
```

幂等键：

```text
tool_call_id
```

如果工具结果已存在，则重新发布 `ToolCallCompleted` 或直接 ack 重复事件。

### 19.4 Outbox Publisher

读取 `outbox_events`，发布 Kafka，标记 `published_at`。允许多实例运行，使用：

```sql
FOR UPDATE SKIP LOCKED
```

## 20. Responses API 使用约定

DeepDive 直接调用 OpenAI Responses API。

使用约定：

```text
model 来自 config_snapshot
tools 来自 ToolRegistry
instructions/input 由 ContextAssembler 生成
stream=true
parallel_tool_calls MVP 默认为 false
previous_response_id 可用于连续 turn，但每轮仍保存完整输入引用
```

注意：

1. 不依赖 OpenAI 侧保存的上下文作为唯一恢复来源。
2. 每轮发出的 input、tool schema hash、instruction hash 都要存储到 MinIO/Postgres。
3. 如果使用 `previous_response_id`，仍应保存本地 `agent_turns.previous_response_id` 和 `latest_response_id`。
4. 恢复时以后端本地 session store 为准，再决定是否继续引用 previous response。

## 21. 可观测性

日志、trace、metric 中应包含：

```text
request_id
analysis_id
agent_id
snapshot_id
turn_id
tool_call_id
event_id
tenant_id
```

关键指标：

```text
Kafka consumer lag by topic
Worker event processing duration
Snapshot duration
Repository file count and total bytes
MinIO upload/download bytes and latency
Cache hit/miss rate by prefix
Prefix materialization duration and bytes
ripgrep duration and result count
Responses API latency
Responses API token usage
SSE connected clients
Tool call failure count by code
DLQ event count
Compaction count and token reduction
```

## 22. 失败处理

常见失败策略：

```text
Git clone/fetch timeout:
  标记 snapshot failed，发布 SnapshotFailed。

Kafka duplicate delivery:
  processed_events 唯一键跳过重复处理。

Agent worker streaming 时崩溃:
  已持久化 stream event 可 replay；下一 worker 根据 turn 状态恢复或重试。

Agent worker 等待工具时崩溃:
  状态是 waiting_tool；ToolCallCompleted 可触发继续。

Execution worker prefix 下载时崩溃:
  临时文件忽略；coverage 不标记完成；下次重建。

Responses API stream 中断:
  保存 response_id 和 partial state；按策略 retrieve、retry 或 fail。

SSE client 断开:
  不影响任务；客户端用 Last-Event-ID 重连。

配置变更:
  已创建任务继续使用 config_snapshot；新任务使用新配置。
```

DLQ：

```text
超过重试次数的事件进入 deepdive.dlq
DLQ payload 包含原始 event、错误码、错误摘要、attempt count
修复根因后由管理任务重放
```

## 23. 安全边界

仓库源码、README、注释、AGENTS.md、脚本和测试文件都视为不可信输入。

必须防止：

```text
prompt injection 要求泄露配置或 token
AGENTS.md 要求扩大工具权限
源码注释诱导读取平台路径
恶意文件名触发路径穿越
超大文件消耗内存
ripgrep 输出爆炸
Git URL 或日志泄露 credential
```

安全原则：

```text
模型不能直接访问 MinIO
模型不能直接访问 Postgres
模型不能指定 snapshot_id
模型不能执行 shell
模型不能创建或修改仓库文件
工具参数必须 schema 校验
路径必须 normalize 后再决策
所有读取必须受 size、line、timeout、结果数量和输出大小限制
```

## 24. MVP 范围

当前阶段不实现独立的最终文档或报告输出。调试阶段以前端通过 `GET /analysis/{analysis_id}/events` 读取到的 Agent 输出流为准；后端只保存 stream event、最后一轮输出摘要、状态、工具结果和证据引用。后续如果需要 Markdown、PDF、DOCX 或其他报告产物，应单独设计 report/export worker，消费 `AnalysisCompleted` 后生成。

当前阶段不实现 token 或成本预算系统。后端只保留 Responses API usage、上下文 token 估算、compact 触发阈值和自动 compact 能力；不做预算分配、预算告警、成本上限控制，也不基于预算调度任务。

MVP 包含：

1. `backend/` Python 后端目录结构。
2. 启动配置加载、校验和 `config_snapshots` 持久化。
3. REST 风格 API：`POST /analysis`、`GET /analysis`、`GET /analysis/{analysis_id}`、`POST /analysis/{analysis_id}/cancel`、`GET /analysis/{analysis_id}/events`。
4. Postgres 18 schema，所有平台 ID 使用 UUIDv7。
5. Kafka event envelope、schema version、transactional outbox、processed_events 幂等。
6. Snapshot worker 使用 git CLI。
7. MinIO 存储 Git bundle、manifest、文件 blob、Agent 输入输出、工具结果和证据。
8. Agent worker 支持 Responses API streaming、上下文组装、工具调用识别、compaction。
9. Execution worker 支持 `list_files`、`search_file`、`search_text`、`read_file`。
10. ripgrep prefix cache 和 read_file single file cache。
11. AGENTS.md 扫描、作用域解析和上下文注入。
12. SSE replay，基于 Postgres `agent_stream_events` 恢复输出流。
13. 基础日志、指标、错误状态和 DLQ。

MVP 明确不包含：

```text
tree-sitter
LSP
SCIP/LSIF
语义依赖预分析
shell execution tools
代码编辑工具
递归 submodule snapshot
真实 LFS object 下载
多 Agent 并发执行
自动 PR / patch 生成
最终文档/报告输出
token 或成本预算系统
```

第一阶段应优先把“快照 -> 文件树 -> 搜索 -> 读取 -> 证据 -> 长任务恢复”这条只读 Agent 闭环做稳定，再扩展更复杂的代码智能能力。
