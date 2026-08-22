# 部署、备份与升级

## 生产部署

1. 在独立目录保存 `.env`，权限设为仅部署用户可读。
2. 使用云 PostgreSQL/Redis/对象存储时，关闭 Compose 中对应本地服务或覆盖连接地址。
3. 设置至少 32 字节的 `JWT_SECRET` 和 32 字节 base64 `CREDENTIAL_MASTER_KEY`。
4. 执行 `docker compose run --rm api alembic upgrade head`。
5. 启动服务后执行健康检查，再创建首个管理员。
6. 只通过 Nginx 暴露 Web/API/MCP；PostgreSQL、Redis 和 Worker 不开放公网端口。

### 上线前必检项

- `ENVIRONMENT=production`，`PUBLIC_BASE_URL`、CORS、Trusted Host 和 MCP Origin
  均改为真实 HTTPS 域名。
- 轮换开发和联调期间曾经出现过的模型、OCR、OSS 密钥；新密钥只通过
  管理页或受限 `.env` 写入，不进入镜像、日志和代码库。
- HTTP 模型网关只应位于受信 VPC/内网。SynapseKB 允许该配置并记录脱敏
  安全警告，不会阻断模型调用；如果链路经过公网，仍建议在网关前增加 HTTPS。
- 对象存储已切换到 OSS/COS/S3，Endpoint 使用 HTTPS，Bucket 开启版本和生命周期。
- 每个知识库显式绑定 Embedding、RAG Chat、Rerank、Wiki 生成和 Wiki 健康
  模型；每个 Agent 显式绑定 Agent Chat 模型。
- 在生产的完整数据副本上执行数据库迁移，确认 `alembic current` 与
  `alembic heads` 一致；升级前先备份。
- 执行一次普通 PDF、扫描 PDF、RAG、Agent、Wiki 更新、Wiki 健康检查和 MCP
  冒烟测试，确认引用可以定位原文。
- 任务中心不应存在长时间 `queued` / `running` 记录。调度器会对异常中断的
  文档、OCR、Agent 和 Wiki 任务重新入队，但上线前仍要确认恢复后的最终状态。

仓库内 Nginx 配置是容器源站配置。生产必须在云负载均衡/WAF 终止 TLS，或替换为
挂载证书并监听 443 的 Nginx 配置；公网 HTTP 应重定向到 HTTPS。设置
`PUBLIC_BASE_URL=https://...`，只允许实际域名进入 CORS、Trusted Host 和 MCP
Origin 白名单。API 容器不可另行映射公网端口。Compose 默认把 Web 映射到
`WEB_PORT=8088`，避免占用宿主机已有的 80 端口；生产上游代理到该端口即可。

### 公网 IP + HTTP 兼容模式

没有域名或证书时，可以显式启用 HTTP 兼容模式。它仍使用 `production` 的密钥、对象存储、
权限和任务安全检查，但 Refresh Cookie 不设置 `Secure`，MCP 接受配置的 HTTP Origin。
这只解决协议兼容，不提供传输加密：登录凭证、PAT、检索问题、引用和文档内容都可能被链路
上的第三方读取或篡改。

假设访问地址是 `http://203.0.113.10:8088`：

```dotenv
ENVIRONMENT=production
PUBLIC_BASE_URL=http://203.0.113.10:8088
ALLOW_INSECURE_HTTP=true
CORS_ORIGINS=["http://203.0.113.10:8088"]
TRUSTED_HOSTS=["203.0.113.10","api","mcp-server"]
MCP_ALLOWED_ORIGINS=["http://203.0.113.10:8088"]
MCP_ALLOW_NULL_ORIGIN=true
TRUST_PROXY_HEADERS=true
```

`PUBLIC_BASE_URL` 会自动补入 API 的 CORS/Trusted Host 和 MCP Origin/Host 校验，显式列表仍应
保留，便于审计。`MCP_ALLOW_NULL_ORIGIN=true` 只用于发送 `Origin: null` 的 WorkBuddy 或
Electron WebView；纯 Codex Streamable HTTP 客户端通常不发送 Origin。

更新后必须重建所有读取后端配置的进程：

```bash
docker compose build api mcp-server agent-runner document-worker ocr-worker wiki-worker wiki-scheduler web
docker compose up -d --remove-orphans
```

检查：

```bash
curl -i http://203.0.113.10:8088/api/v1/health
curl -i http://203.0.113.10:8088/mcp
```

第二个请求应返回 `401 缺少 Bearer Token`，这表示 Nginx 已成功转发到 MCP；`404`、`421` 或
连接失败表示路由、Host 白名单或安全组仍未配置正确。对象存储浏览器直传和预览还需要在
OSS/COS Bucket CORS 中允许该 HTTP Origin、`GET`/`PUT`/`HEAD` 方法、`Content-Type` 及实际
使用的 `x-cos-*` / `x-oss-*` 请求头。

后端 Docker 构建默认从阿里云 PyPI 镜像读取锁定依赖，并限制并发下载。需要使用其他
可信镜像时传入 `--build-arg PYPI_INDEX_URL=https://.../simple/`，同时用同一索引重新
生成 `uv.lock`，不得关闭 TLS 或跳过哈希校验。

OSS/COS/S3 参数见[对象存储配置](object-storage.md)。生产启动时会拒绝本地存储、
HTTP endpoint、缺失的对象存储凭证和开发 JWT/主密钥。

## 备份

- PostgreSQL：每日全量备份 + WAL/PITR；至少保留 7/30/180 天三级策略。
- 对象存储：开启版本控制和生命周期；原始文档与数据库备份使用相同保留窗口。
- Redis 不是业务真值，不依赖 Redis 备份恢复运行状态。
- 主密钥必须单独加密备份。丢失主密钥将无法解密模型密钥。

每季度在隔离环境执行恢复演练，验证数据库、对象版本和主密钥三者匹配。
完整操作与验收清单见 [备份与恢复](backup-and-restore.md)。

## 当前开发环境不可直接作为生产

默认 Compose 使用 `development` + HTTP + 本地存储，目的是方便本机联调。把现有容器
启动在云服务器上并不等于完成生产部署。切换 `ENVIRONMENT=production` 前，先完成
上述公网 HTTPS、对象存储和密钥轮换。HTTP 模型网关不会阻断启动，但应
限制在受信内网并配合安全组和出站访问控制。

## 升级

1. 阅读版本说明并完成备份。
2. 拉取固定镜像版本，不使用漂移的 `latest`。
3. 先运行迁移的离线检查，再执行 `alembic upgrade head`。
4. 滚动更新 API/Worker，最后更新 Web/Nginx。
5. 运行健康检查、权限冒烟、检索冒烟和任务恢复检查。

数据库迁移只允许向前兼容的 expand/migrate/contract 顺序。应用回滚不应依赖立即回滚破坏性数据库变更。
