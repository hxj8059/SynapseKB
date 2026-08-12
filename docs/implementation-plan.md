# 实施计划、假设与验收基线

## 必要假设

1. 单实例部署只有一个逻辑空间，不设计租户或组织层级。
2. 用户时区默认 `Asia/Shanghai`，时间在数据库中统一保存为带时区时间戳。
3. `source_time` 无可靠证据时必须为 `NULL`；上传时间只写入 `created_at`。
4. 生产数据库固定为 PostgreSQL + pgvector，Redis 同时承担 Dramatiq、事件流、缓存和限流。
5. 浏览器认证使用短期 Access JWT 和 HttpOnly Refresh Cookie；MCP 使用独立 PAT。
6. 生产文件必须进入对象存储。本地文件存储只允许在开发环境使用。
7. 模型与 OCR 未配置密钥时使用显式 Mock 配置运行测试，产品界面不会把 Mock 结果伪装成真实调用。
8. 中文关键词检索 V1 使用 Jieba 预分词 + PostgreSQL `simple` 全文检索；无需引入 Elasticsearch。
9. Embedding 维度由激活的 Embedding 模型决定。V1 数据库默认 1536 维，切换维度需要专门迁移并重建向量索引。
10. 不直接执行生产部署，不接触生产数据；Docker Compose 是本项目的正式交付路径。

## 模块边界

```text
apps/                    独立进程入口，不承载业务规则
  api/                   HTTP API、认证、SSE 转发
  agent_runner/          LangGraph 运行与事件
  document_worker/       本地解析、分块、Embedding、索引
  ocr_worker/            PaddleOCR 云任务与限流
  wiki_worker/           Wiki 生成、质检、原子发布
  mcp_server/            远程 Streamable HTTP MCP
  mcp_stdio_proxy/       stdio 到远程 API 的薄代理
  web/                   React/Vite
packages/synapsekb/      共享领域、应用服务和基础设施适配器
migrations/              Alembic
skills/                  面向外部 AI 工具的四个 Skill
deploy/                  镜像、Nginx 和运维配置
tests/                   单元、集成、E2E、负载测试
```

`apps` 可以独立扩容，但共享同一领域包和数据库。这样保留清楚的扩缩容边界，同时避免不必要的微服务网络调用和重复模型。

## 分阶段目标

### Phase 1：基础平台

- 可重复启动的 Monorepo、锁文件和 Docker Compose。
- 用户、管理员、JWT/Refresh Token、服务端授权和审计。
- 知识库授权、模型密钥加密、对象存储抽象。
- React 登录、首页、知识库与系统设置的真实 API 闭环。
- 验收：迁移成功、管理员可创建、未授权请求被拒绝、前后端构建和测试通过。

### Phase 2：文档和 RAG

- 直传/本地开发上传、处理任务、解析器、PaddleOCR、时间提取、分块、Embedding。
- 向量和中文关键词均在 SQL 阶段应用同一权限/时间过滤，RRF 合并，可选 Rerank。
- SSE 问答、消息持久化和可定位引用。
- 验收：普通/扫描 PDF 均可完成上传到问答闭环，三个时间字段可独立严格过滤。

### Phase 3：Agent

- LangGraph 状态图、内部只读知识工具、运行/步骤持久化、Redis Streams SSE。
- 时间短语解析、分时期检索、取消、超时和恢复。
- 验收：不具备互联网、Shell、浏览器或第三方 MCP 能力；执行摘要可审计且不泄露隐藏思维链。

### Phase 4：Wiki 与图

- 分批初建、增量影响分析、保护区块、质检、事务发布和回滚。
- 页面/文档/主题节点与有证据的时间化边，局部子图查询。
- 验收：失败不影响当前发布版本；文档删除正确清理引用但保留仍有其他来源的内容。

### Phase 5：MCP 和 Skills

- Remote Streamable HTTP、PAT/Scope/Origin/限流/审计和 stdio 代理。
- 稳定工具 Schema、长 Agent `start/get/cancel`。
- 四个独立 Skill，强制结构化时间过滤与引用保留。
- 验收：MCP 与 App 使用同一授权及检索应用服务，结果一致。

### Phase 6：产品化

- 完整 UI、深色模式、SVG 品牌资产、虚拟滚动、可访问性。
- 3M Chunk 查询计划压测、安全检查、备份恢复演练和升级回滚。

## Definition of Done

每个模块必须同时具备：领域实现、服务端授权、迁移、测试、错误语义、日志脱敏、可观测性和运维文档。只有界面、静态假数据或绕过真实服务的演示不计为完成。

## 当前实现状态

- Phase 1～5 已形成可运行的纵向首版闭环。
- Phase 6 已完成品牌、深浅色、路由拆包、安全基线、备份/升级说明和可执行负载
  测试入口；真实 10,000 文档/300 万 Chunk 压测及云厂商实网认证需要目标部署
  环境与密钥，未在本地结果中冒充完成。
