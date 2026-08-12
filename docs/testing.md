# 测试与验收

## 本地快速检查

```bash
uv run ruff check .
uv run mypy packages apps
uv run pytest
pnpm --dir apps/web test -- --run
pnpm --dir apps/web build
pnpm --dir apps/web exec playwright test
```

默认测试不需要真实模型或 OCR 密钥。`provider=mock` 只用于 Embedding 确定性测试；
Chat、Rerank、Agent 与 Wiki 不会把 Mock 结果当成真实成功。

## PostgreSQL + pgvector 集成测试

Docker daemon 可用时执行：

```bash
RUN_DOCKER_TESTS=1 uv run pytest -m integration
```

测试会启动临时 `pgvector/pgvector` 容器、执行 Alembic 初始迁移并验证核心表。

## 检索负载基线

先准备已授权、已完成 Embedding 的隔离数据集，再执行：

```bash
RUN_LOAD_TESTS=1 \
SYNAPSEKB_LOAD_URL=https://staging.example.com \
SYNAPSEKB_LOAD_TOKEN=skbp_... \
SYNAPSEKB_LOAD_KB_ID=00000000-0000-0000-0000-000000000000 \
SYNAPSEKB_LOAD_REQUESTS=1000 \
SYNAPSEKB_LOAD_CONCURRENCY=30 \
uv run pytest -m load tests/load
```

默认阈值是检索 P95 小于 1000 ms，可用 `SYNAPSEKB_LOAD_P95_MS` 调整。测试必须对
预生产或隔离环境执行，禁止把测试流量直接指向生产。
