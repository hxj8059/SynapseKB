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
