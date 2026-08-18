# SynapseKB（触智）

SynapseKB 是面向个人和中小团队的私有智能知识库。项目采用一个代码仓库、多个独立进程的模块化单体架构：业务规则集中在共享 Python 包中，API、Agent、文档、OCR、Wiki 和 MCP 按扩缩容边界分别运行。

当前仓库提供可运行的首版纵向闭环：认证与权限、模型配置、对象存储上传、
普通/OCR 文档处理、时间化混合检索与 Rerank、SSE RAG、受限 LangGraph
Agent、原子发布 Wiki、局部时间关系图、Remote MCP、stdio 代理和四个 Skill。
生产压测、云厂商实网兼容认证和更完整的 Wiki 编辑体验仍列在路线图中。

## 本地启动

前置条件：Docker Compose、Node.js 22+、Python 3.12（`uv` 可自动安装）。

```bash
cp .env.example .env
docker compose up --build
```

启动后：

- Web：<http://localhost>
- OpenAPI：<http://localhost/api/docs>
- 健康检查：<http://localhost/api/v1/health>
- MCP：<http://localhost/mcp>

首次启动会执行数据库迁移。随后创建管理员：

```bash
docker compose exec api synapsekb-admin \
  --email admin@example.com \
  --name 管理员
```

命令会安全地交互式读取并确认密码。当前管理 CLI 只有一个操作，因此 Typer
将其作为根命令执行，不需要添加 `create` 子命令。不要把密码写入命令行或 `.env`。

## 更新已有部署

以下流程适用于从本仓库源码构建、使用 Docker Compose 运行的本机或服务器部署。
更新不会主动删除 PostgreSQL、Redis、MinIO 或本地文件存储卷；生产使用 COS/OSS/S3
时，对象文件也不在 Docker 容器内。完整生产要求见[部署与升级](docs/deployment.md)。

### 1. 更新前检查和备份

先确认当前服务正常，并检查工作区是否有尚未保存的修改：

```bash
docker compose ps
curl -f http://127.0.0.1:8088/api/v1/health
git status --short
```

如果 `git status` 有输出，先保存或提交这些修改，不要使用 `git reset --hard` 强行覆盖。
使用 Compose 自带 PostgreSQL 时，可以创建一次升级前备份：

```bash
mkdir -p backups
docker compose exec -T postgres sh -c \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "backups/synapsekb-before-update-$(date +%Y%m%d-%H%M%S).dump"
```

生产使用云数据库时，应先创建云数据库快照或 PITR 恢复点；COS/OSS/S3 应已启用版本控制。
同时单独保管 `.env` 和 `CREDENTIAL_MASTER_KEY`，不要把它们提交到 Git。

### 2. 拉取代码并合并新增配置

```bash
PREVIOUS_COMMIT="$(git rev-parse HEAD)"
git fetch --prune
git pull --ff-only
git diff "$PREVIOUS_COMMIT"..HEAD -- .env.example
```

根据最后一条命令显示的变化，把新增配置手动补入现有 `.env`。不要执行
`cp .env.example .env`，否则可能覆盖数据库密码、JWT 密钥、主密钥和云存储配置。
升级期间不要随意更换 `JWT_SECRET` 或 `CREDENTIAL_MASTER_KEY`。

### 3. 构建镜像、执行迁移并重启

先保留当前应用镜像，便于应用层回退，然后构建新镜像：

```bash
docker image tag synapsekb-backend:0.1.0 synapsekb-backend:rollback
docker image tag synapsekb-web:0.1.0 synapsekb-web:rollback
docker compose build --pull api web
```

先单独执行数据库迁移；只有迁移成功后才重启全部进程：

```bash
docker compose run --rm api alembic upgrade head
docker compose up -d --remove-orphans
```

`api`、`agent-runner`、各 Worker 和 `mcp-server` 共用同一个后端镜像，执行一次
后端构建即可。Compose 会根据新镜像重新创建相关容器，但会保留命名数据卷。

如果部署使用私有镜像仓库而不是服务器源码构建，应在生产 Compose override 中固定版本号，
然后用 `docker compose pull` 和 `docker compose up -d --remove-orphans` 更新；不要使用漂移的
`latest` 标签。

### 4. 更新后验收

```bash
docker compose ps
docker compose exec api alembic current
curl -f http://127.0.0.1:8088/api/v1/health
docker compose logs --since=10m api document-worker ocr-worker wiki-worker agent-runner mcp-server
```

随后至少验证一次登录、文档检索、RAG 引用、Agent、Wiki 和 MCP。确认运行稳定后，
可以清理未使用的构建缓存和悬空镜像：

```bash
docker builder prune -f
docker image prune -f
```

不要执行 `docker compose down -v` 或 `docker system prune --volumes`；这两类命令可能删除
PostgreSQL、本地对象存储和 Redis 数据卷。

### 5. 失败回退

如果数据库迁移尚未执行或新版本未包含不兼容迁移，可以恢复保留的应用镜像：

```bash
docker image tag synapsekb-backend:rollback synapsekb-backend:0.1.0
docker image tag synapsekb-web:rollback synapsekb-web:0.1.0
docker compose up -d --force-recreate
```

如果迁移已经成功执行，不要直接运行未经确认的 `alembic downgrade`。先停止写入，根据该版本
发布说明判断旧应用是否仍兼容新结构；不兼容时应从升级前数据库备份恢复到新的数据库实例，
验证后再切换连接地址。

## 开发

```bash
uv sync --all-groups
uv run alembic upgrade head
uv run uvicorn apps.api.main:app --reload
```

```bash
pnpm --dir apps/web install --frozen-lockfile
pnpm --dir apps/web dev
```

常用检查：

```bash
uv run pytest
uv run ruff check .
uv run mypy packages apps
pnpm --dir apps/web test
pnpm --dir apps/web build
```

详细设计见：

- [架构说明](docs/architecture.md)
- [数据库设计](docs/data-model.md)
- [分阶段目标与假设](docs/implementation-plan.md)
- [部署与升级](docs/deployment.md)
- [备份与恢复](docs/backup-and-restore.md)
- [模型配置](docs/models.md)
- [对象存储配置](docs/object-storage.md)
- [PaddleOCR 配置](docs/paddleocr.md)
- [MCP 与 Skill 接入](docs/mcp.md)
- [测试与验收](docs/testing.md)
- [安全模型](docs/security.md)
- [已知限制与路线图](docs/roadmap.md)
