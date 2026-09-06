# 账号权限与任务投递升级

本次涉及 `0017_account_approvals`、`0018_task_dispatches` 两个迁移，衔接现有的
`0016_chunk_ref_indexes`。必须先升级数据库，再启动新版 API、MCP 和 Worker。

## 账号与知识库权限

- 角色分为超级管理员、管理员、普通用户。
- 迁移将最早创建且仍启用的管理员升级为超级管理员。如果已经存在启用的超级管理员，不再自动提升其他账号。
- 现有账号保持已审批；新安装执行 `synapsekb-admin --email ... --name ...` 创建超级管理员。
- 超级管理员可直接创建账号、管理管理员、批准或拒绝新增账号申请。
- 管理员可申请添加普通用户。待审批/被拒绝账号不能登录、刷新令牌或使用 API Key；不能通过“启用”绕过审批。
- 账号管理 → 账号审批：超级管理员看到全部申请，管理员看到自己提交的申请。审批记录和操作审计均保存在数据库。
- 账号管理 → 知识库权限：按库设置“所有用户”或“指定成员”。部门私有资料应选择指定成员。空成员列表意味着普通用户均无权访问。
- 管理员与超级管理员保留全库管理权限；需要部门隔离的人员应使用普通用户角色。此次不引入部门/组织模型。
- App、检索、Agent、Wiki 与 MCP 共用后端权限。Agent 每次读取知识工具前重新校验用户与知识库成员权限。
- 至少保留一位启用的超级管理员；修改角色和停用检查采用数据库锁，避免并发操作移除最后一位。

## 文档筛选和网页导入

知识库文档页支持名称、状态、上传时间、来源时间筛选。两种时间范围可同时设置，
语义为 AND；时间未知项仅在主动勾选“包含未知日期”时加入来源时间过滤结果。
筛选和计数均在 PostgreSQL 执行，再分页返回，不下载全库数据到浏览器过滤。

REST：`GET /api/v1/documents` 与 `GET /api/v1/documents/count` 使用一致参数：
`knowledge_base_id`、`name`、`status`、`created_from`、`created_to`、`source_from`、`source_to`、
`include_unknown`。时间须包含时区。原有 `time_field/from_time/to_time` 参数继续兼容。

网页导入入口位于文档列表上方，使用 `POST /api/v1/documents/import-url`。
支持登录 JWT 或带 `document:write` Scope 的管理员 Personal Access Token。
MCP 新增 `document_import_url`，参数为 `knowledge_base_id`、`url`，可选 `title`、`source_time`。
这是写操作；客户端应取得用户的导入授权。SynapseKB 内部 Agent 不获得此工具。

微信公众号页面提取 `#js_content` 正文、文章标题及明确的发布时间字段。
人工指定 `source_time` 优先。网页重定向仍逐跳执行 SSRF 检查。
微信可能返回验证码、环境异常、删除或访问受限页面，此时接口返回可理解的错误并且不创建文档。
可在浏览器完成验证后，将可阅读的正文保存为 HTML/Markdown 上传。图片型文章仍需上传图片/PDF 走 OCR。

## 新任务投递方式

`task_dispatches` 与业务任务在同一事务中创建，记录任务类型、业务 ID、队列、
预分配的 Redis 消息 ID、状态、执行次数、投递时间、心跳与错误摘要。

1. 创建任务写 `pending`，提交后尝试立即投递；Redis 暂时不可用时保留待投递记录。
2. 投递器锁定记录，发送后写 `sent`。发送成功、数据库提交前崩溃时，按已持久化的 Redis ID 检查 `.msgs`，避免再次发送。
3. Worker 将记录原子标记为 `claimed`，执行期间持有独立 PostgreSQL 会话锁，并每 30 秒更新心跳。
4. 重复消息在工作开始前退出。重试次数和退避时间由投递记录管理，避免和 Dramatiq 重试叠加。
5. 恢复器检查 `pending`、`.msgs` 中确实缺失的 `sent`、心跳超 10 分钟且执行锁已释放的 `claimed`。
   正常排队数小时、数天都不会因为年龄被重复投递。已预取/未确认消息仍存在 `.msgs`，也不会误补投。
6. 文档解析 → OCR → OCR 后索引使用独立阶段投递记录，`ProcessingJob.external_task_id` 继续专用于 PaddleOCR 云任务。

沿用现有 `wiki-scheduler` 进程，每 10 秒处理投递/恢复；Wiki 健康检查仍按原配置间隔运行。
知识库删除继续由 document-worker 消费 maintenance 队列，不增加独立 Worker。
投递表使用 `finished`/`failed` 记录结束状态；用户仍在任务中心查看业务任务状态。

## 已有服务器的升级步骤

先按[备份文档](backup-and-restore.md)备份数据库、对象存储及主密钥。构建期间可让 Worker 继续处理已有任务。

```bash
# 1. 停止旧恢复器，阻止继续重复投递
docker compose stop wiki-scheduler
git pull --ff-only
docker compose build api web

# 2. 显式迁移；不能先启动依赖新表的 Worker
docker compose run --rm --no-deps api alembic upgrade head

# 3. 切换所有业务进程到同一版镜像（不要启动 scheduler）
docker compose up -d api agent-runner document-worker ocr-worker wiki-worker mcp-server web

# 4. 检查历史消息，默认只读，输出计数，不输出文档或凭据
docker compose run --rm --no-deps api python -m synapsekb.tasks.recovery

# 5. 执行原子去重并为没有消息的任务补投；可重复执行
docker compose run --rm --no-deps api python -m synapsekb.tasks.recovery --apply

# 6. 启动新调度器
docker compose up -d wiki-scheduler
docker compose ps
docker compose logs --tail=100 wiki-scheduler
```

去重按“actor + 业务任务 ID”识别重复，仅删除仍在等待列表中的重复投递，不清空队列、
不删除业务文档。每次删除通过 Redis Lua 原子确认保留消息仍存在，并将被移除的冗余消息
备份到输出的 `backup_key`，保留 7 天。已经领取的消息不删除，交给 Worker 的领取锁消重。
升级期间还在执行的旧任务应先正常结束，或等旧 Worker 完全退出后再让新版恢复器恢复。

对旧 `running` 记录补录心跳后留出 10 分钟观察期；不要将整个队列的时间戳批量改为当前时间。
历史 `failed` 业务任务不会因为升级自动重跑，仍从任务中心按需重试。

验收时检查：管理员添加的账号需审批、普通用户无法通过文档 ID/MCP 访问未授权库、
长时间 queued 的任务 Redis 消息数不会周期性上涨、Worker 重启后任务能继续、文档筛选总数正确。

回退前先停止新调度器并保留数据库备份。旧版本不识别 `super_admin` 与投递表，不能直接只回退镜像；
需要协调账号角色和未完成任务。优先修复后前进升级，避免对含新数据的数据库盲目降级。
