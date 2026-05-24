# DeepDive

DeepDive 是一个基于 LLM 的项目源码分析平台，旨在将源码仓库经过 LLM 分析，沉淀为一系列文档。

## 项目状态

后端正在开发中。

当前仓库以后端能力为主，包含 API、事件流、Worker、源码快照、只读工具、持久化和对象存储等基础模块。前端、鉴权体系、多租户治理、MCP 接入、前端和生产级部署能力会随着后续阶段逐步完善。

## 成熟阶段架构



## 核心模块

- API 接入层：接收分析请求、查询任务状态、输出 SSE 流。
- 鉴权与认证层：负责用户身份、租户隔离、权限策略和审计。
- MCP 接入层：统一管理模型可见工具、外部集成和权限边界。
- Worker 层：执行快照、分析、模型调用、工具调用、压缩、索引、重试和 DLQ 处理。
- 中间件层：通过 Kafka、Redis、服务注册中心和可观测性组件支撑异步任务与横向扩展。
- 存储层：Postgres 保存事实状态，MinIO 保存不可变大对象，Redis 保存热缓存与协调状态。
- 部署层：开发环境使用 Docker / Docker Compose，成熟阶段面向 Kubernetes 部署。

## 开发

安装依赖：

```shell
uv sync
```

运行测试：

```shell
uv run python -m unittest -v
```

启动基础设施：

```shell
docker compose up postgres kafka minio minio-init -d
```

启动完整应用栈：

```shell
docker compose --profile app up --build
```

## 开源协议

本项目基于 MIT 协议开源。
