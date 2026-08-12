# API 说明

启动后访问 `/api/docs` 查看交互式 OpenAPI，原始 Schema 位于 `/api/openapi.json`。

## 认证

- `POST /api/v1/auth/login` 返回 15 分钟 Access JWT，并设置 HttpOnly Refresh Cookie。
- `POST /api/v1/auth/refresh` 旋转 Refresh Token；重用旧 Token 会撤销整个 Token Family。
- 业务 API 使用 `Authorization: Bearer <access-token>`。
- 文档上传的 `/documents/upload`、`/documents/uploads/init` 和
  `/documents/uploads/complete` 也接受 `skbp_` Personal Access Token，但必须包含
  `document:write` Scope。PAT 仍继承所属用户的 App 权限，当前知识库写操作仍要求管理员。
- 其他 REST API 继续只接受 JWT；MCP 与 REST PAT 请求均使用同一套过期、撤销和 Scope
  校验。服务端不会保存 PAT 明文。

## 时间检索

`POST /api/v1/search` 和 `POST /api/v1/rag/stream` 接受：

```json
{
  "query": "只看 2024 年的政策",
  "knowledge_base_ids": ["..."],
  "document_ids": [],
  "tag_ids": [],
  "time_filter": {
    "field": "source_time",
    "from": "2024-01-01T00:00:00+08:00",
    "to": "2024-12-31T23:59:59+08:00",
    "include_unknown": false
  },
  "top_k": 20
}
```

`time_filter` 同时进入关键词和向量候选查询。RAG 未显式传时间条件时会解析常见中文
时间表达；跨时期比较会执行多次独立检索。所有显式时间必须包含 UTC 偏移，无偏移
的日期时间请求会被拒绝。

## SSE

RAG 返回 `citation`、`retrieval.summary`、`assistant.delta`、`completed`。

Agent 返回：

```text
run.started
thinking.summary
assistant.delta
tool.started
tool.finished
citation
run.completed
run.cancelled
run.error
```

`thinking.summary` 只包含可审计摘要，不包含模型隐藏思维链。

## 文档

- `POST /api/v1/documents/upload`：开发环境小文件中转上传。
- `POST /api/v1/documents/uploads/init` 与 `/uploads/complete`：对象存储直传。
- `POST /api/v1/documents/import-url`：带 SSRF 防护的网页导入，不执行 JavaScript。
- `PATCH /api/v1/documents/{id}`：修改标题、`source_time` 和标签；时间同步到 Chunk。
- `GET /api/v1/documents/{id}/parsed`：读取解析 Markdown。
- `GET /api/v1/documents/{id}/chunks`：分页读取检索块。
- `POST /api/v1/documents/{id}/retry`、`cancel`：任务控制。
- `DELETE /api/v1/documents/{id}`：删除原文、解析产物、Chunk 和失效 Wiki 来源。

网页抓取每次重定向都会重新检查协议、端口和解析后的公网地址，并限制内容类型
和大小。内网、回环、链路本地和云元数据地址会被拒绝。

自动化上传可直接使用 PAT，无需先调用登录接口：

```bash
curl -X POST 'https://synapsekb.example.com/api/v1/documents/upload' \
  -H "Authorization: Bearer $SYNAPSEKB_TOKEN" \
  -F 'knowledge_base_id=<kb-id>' \
  -F 'file=@report.pdf;type=application/pdf'
```

PAT 使用会更新 `last_used_at`，并写入不包含令牌明文的审计日志。重复文件仍按知识库内
SHA-256 返回 `409`，上传成功后文档异步进入解析和索引任务。

## 对话

- `GET /api/v1/chat-sessions`：当前用户的对话历史；
- `GET/PATCH/DELETE /api/v1/chat-sessions/{id}`：读取、重命名和删除自己的对话；
- `GET /api/v1/chat-sessions/{id}/export`：导出含引用清单的 Markdown。

历史引用会尽可能保留 Chunk 定位；原始 Chunk 已随文档删除时仍显示保存的引用文本，
但不会伪造已经失效的文档链接。

## Agent 与 Wiki

Agent 使用 `POST /api/v1/agents/{agent_id}/runs` 启动，状态、步骤、取消和 SSE
事件分别位于 `/agents/runs/{run_id}` 下。

Wiki 生成使用 `POST /api/v1/wiki/generate`，任务状态和取消位于
`/wiki/jobs/{job_id}`。目录和页面 API 只返回当前发布版本；局部图搜索和邻居
查询同时对节点与边应用结构化时间过滤。

Wiki 维护接口：

- `POST /api/v1/wiki/health/check`：启动可取消的健康检查；
- `GET /api/v1/wiki/{kb_id}/health/latest`：读取最新报告与待确认提案；
- `POST /api/v1/wiki/{kb_id}/merge`：管理员确认后合并页面、来源与图关系；
- `POST /api/v1/wiki/{kb_id}/merges/{resolution_id}/undo`：撤销合并并恢复页面、节点、别名和关系；
- `GET /api/v1/wiki/{kb_id}/entity-resolutions`：读取持久化消歧与可撤销合并记录；
- `POST /api/v1/wiki/{kb_id}/similarity-decisions`：把候选持久标记为不同实体；
- `POST /api/v1/wiki/{kb_id}/relations`：管理员确认后补充双链关系；
- `GET /api/v1/wiki/{kb_id}/index.md`：当前发布内容目录；
- `GET /api/v1/wiki/{kb_id}/log.md`：追加式更新与健康检查日志。

健康报告只会自动合并模型高置信度确认的同一实体（正式名、简称、译名或拼写变体），
并为每次合并保存完整快照和 `llm_auto` 决策来源。版本、世代、型号或配置标记不一致
时不会自动合并，即使模型误报为同一实体。模型高置信判定为相关/不同的候选会自动写入
`distinct` 消歧记录，避免后续健康检查反复出现。低于自动门槛的
`similar_candidates` 仍进入人工复核队列。调用合并
接口时可带 `health_job_id`，处理后的候选会从该报告移除并写入 `applied_actions`。
`similarity-decisions` 当前只接受 `decision=distinct`；该结论会被后续健康检查过滤。
撤销只在目标页仍指向该次合并版本时执行；如果合并后又编辑或更新了目标页，接口返回
`409`，避免覆盖后续变更。

OCR 配置与真实文件测试位于 `/api/v1/settings/ocr`。对象存储配置与读写连通性测试
位于 `/api/v1/settings/storage`。两者都仅允许管理员访问，密钥字段只写不读。
