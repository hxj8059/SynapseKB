# 备份与恢复

一次可恢复的 SynapseKB 备份由三部分组成：

1. PostgreSQL 全量备份和连续 WAL；
2. 对象存储中原始文件与解析产物的版本；
3. 独立保管的 `CREDENTIAL_MASTER_KEY`。

Redis 不承载业务真值。恢复后未完成任务可以根据 PostgreSQL 状态重新排队。

## PostgreSQL

生产建议使用云数据库 PITR。自管实例可执行：

```bash
pg_dump --format=custom --no-owner --file=synapsekb.dump "$DATABASE_URL_SYNC"
```

恢复到新的空数据库：

```bash
createdb synapsekb_restore
pg_restore --clean --if-exists --no-owner \
  --dbname="$RESTORE_DATABASE_URL" synapsekb.dump
```

恢复后运行 `alembic current`，确认版本与应用镜像匹配。不要在未验证的恢复库上
直接运行破坏性降级。

## 对象存储

- 开启 Bucket 版本控制；
- 原始文档和 `parsed/` 产物使用与数据库一致的保留窗口；
- 禁止只备份数据库而遗漏对象；
- 恢复时优先恢复到新 Bucket，再切换 `STORAGE_BUCKET`；
- 抽样核对 `documents.object_key`、大小和 SHA-256。

## 主密钥

主密钥不得与数据库备份放在同一位置。丢失主密钥后，已保存的模型 API Key
无法恢复。轮换前应先实现密钥重加密流程，不能直接替换环境变量。

## 恢复验收

在隔离网络中完成以下检查后才能切换流量：

- 数据库迁移版本一致；
- 管理员登录、普通用户权限和 PAT 撤销状态正确；
- 随机原文可以下载且 Hash 匹配；
- 任选知识库执行关键词、向量和时间过滤检索；
- 已发布 Wiki 仍指向有效来源；
- 对失败/运行中任务执行显式重试，不重复写 Chunk；
- 重新生成一个临时 PAT，确认旧密钥未出现在日志。

至少每季度执行一次完整恢复演练，并记录恢复点目标和实际恢复时间。
