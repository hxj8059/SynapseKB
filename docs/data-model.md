# 数据库设计

## 通用规则

- 主键：UUID。
- 时间：`TIMESTAMPTZ`，数据库保存绝对时间，展示按用户时区转换。
- `created_at`/`updated_at` 由服务端维护；文档内容性变更必须更新 `updated_at`。
- 可筛选实体的 `source_time` 可空。不得用 `created_at` 回填。
- API Key 使用 AES-256-GCM 密文；PAT 和 Refresh Token 只保存 SHA-256 Hash。
- 删除知识库/文档使用明确级联；审计记录不级联删除。

## 核心关系

| 表 | 关键字段与约束 |
| --- | --- |
| `users` | email 唯一、password_hash、role、is_active |
| `refresh_tokens` | token_hash 唯一、user_id、expires_at、revoked_at |
| `personal_access_tokens` | token_hash 唯一、scopes、expires_at、revoked_at、last_used_at |
| `knowledge_bases` | name、visibility、embedding_model_id、wiki_chat_model_id、Wiki 健康检查周期 |
| `knowledge_base_members` | `(knowledge_base_id,user_id)` 唯一 |
| `documents` | kb_id、object_key、sha256、status、source_time、三个时间字段 |
| `document_tags` | tag 表及文档-标签关联表 |
| `processing_jobs` | document_id、type、status、idempotency_key 唯一、progress、cancel_requested_at |
| `chunks` | document_id、kb_id、content、page、section、embedding、search_vector、三个时间字段 |
| `models` | kind、provider、base_url、model_name、encrypted_api_key、max_concurrency |
| `chat_sessions/messages/citations` | 用户会话、SSE 最终消息、检索参数与可定位引用 |
| `agents` | 系统提示、模型、步骤/Token/超时限制、visibility |
| `agent_runs/steps` | 状态、可展示摘要、工具参数/结果摘要、取消与恢复信息 |
| `wiki_spaces/pages/versions/sources` | 当前发布版本指针、页面版本和段落级来源 |
| `wiki_nodes/edges` | 页面/文档/主题、证据、节点语义向量、三个时间字段 |
| `wiki_node_aliases` | 节点规范名、历史名和合并别名；按 `(space_id, normalized_alias)` 检索 |
| `wiki_entity_resolutions` | 管理员消歧结论、合并组、可逆结构快照和撤销时间，避免重复提示 |
| `wiki_update_jobs` | 固化的 model_id、影响范围、候选版本、质检与发布状态 |
| `wiki_health_jobs` | 周期/手动触发、健康报告、语义修复提案、已应用机械修复 |
| `audit_logs` | actor、action、resource、request_id、脱敏 metadata |
| `system_settings` | 受控系统设置，不存任意秘密 |

## Chunk 索引

V1 为 1536 维向量：

```sql
CREATE INDEX chunks_embedding_hnsw_idx
ON chunks USING hnsw (embedding vector_cosine_ops);

CREATE INDEX chunks_search_vector_idx
ON chunks USING gin (search_vector);

CREATE INDEX chunks_kb_source_time_idx
ON chunks (knowledge_base_id, source_time);
```

`created_at`、`updated_at` 和 `document_id` 建立同类组合索引。Chunk 冗余文档三个时间字段，以避免百万级查询每次回表过滤；更新文档时间时必须在同一事务同步 Chunk。

## 权限查询原则

知识库可访问条件固定为：

```sql
visibility = 'all'
OR EXISTS (
  SELECT 1 FROM knowledge_base_members
  WHERE knowledge_base_id = ...
  AND user_id = :current_user_id
)
```

管理员可绕过资源成员过滤，但仍记录审计。PAT Scope 只作为额外 `AND` 条件。
