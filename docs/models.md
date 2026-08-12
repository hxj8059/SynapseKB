# 模型配置

SynapseKB 将 Chat、Embedding、Rerank 分开保存。所有提供方均通过统一的
OpenAI-compatible 适配层调用；OCR 使用独立 PaddleOCR 官方云 API。管理员可以
先创建多个 Chat 模型，再按业务模块分别绑定，不再使用“第一个已启用模型”
这种隐式选择。

## 模块级模型绑定

| 业务模块 | 配置位置 | 模型类型 | 说明 |
| --- | --- | --- | --- |
| 文档向量化 | 知识库设置 | Embedding | 影响向量维度，切换后需重建已有 Chunk 向量 |
| 普通 RAG 问答 | 知识库设置 | Chat | 可单独设置最终回答上限，默认 8000 Token |
| 检索重排 | 知识库设置 | Rerank | 只对该知识库的候选进行重排 |
| Wiki 生成 / 更新 | 知识库设置 | Chat | 优先选择结构化输出稳定的模型 |
| Wiki 健康检查 / 语义复核 | 知识库设置 | Chat | 可与 Wiki 生成模型不同，旧数据自动回退到 Wiki 生成模型 |
| 知识分析 Agent | Agent 编辑器 | Chat | 每个 Agent 独立绑定，并独立设置步数、最终输出 Token 和超时 |

Agent 的中间工具调用会使用受限的单步配额，但最终答案使用 Agent 配置的
完整输出配额，不再按最大步数均分。对分析型 Agent 建议 12000 Token；如果
实际模型上下文较小，可降为 8000。所有 Chat 入口都检查 `finish_reason`，
达到长度上限时会明确报错，不会将被截断的内容伪装成 `completed`。

## 预设

| 提供方 | Base URL |
| --- | --- |
| OpenAI | `https://api.openai.com/v1` |
| DeepSeek | `https://api.deepseek.com/v1` |
| 通义千问 / DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| Ollama | `http://host.docker.internal:11434/v1` |
| 其他兼容服务 | 管理员明确填写 |

管理员在“模型设置”中分别填写配置名称、类别、Base URL、模型名、API Key、
请求超时、最大并发和 Embedding 维度。API Key 使用 AES-GCM 加密后写入
PostgreSQL，响应和普通日志均不返回密钥。

SynapseKB 允许在生产环境使用 HTTP 模型网关，适用于只在受信 VPC 或内网中
可达的私有网关。系统会记录一条不含密钥、Prompt 和文档内容的安全警告，
但不会拒绝模型配置或调用。如果请求会经过公网或不受信网络，仍建议在网关前
增加 HTTPS 反向代理，因为该链路会承载 API Key、Prompt 和文档证据。

DashScope 的 `qwen3-rerank` 使用单独的
`https://dashscope.aliyuncs.com/compatible-api/v1` Base URL；管理页面在选择
DashScope + Rerank 时会自动切换。`qwen3.7-text-embedding` 默认返回 1024 维，
SynapseKB V1 配置为 1536 维并在请求中显式传递 `dimensions=1536`，以匹配数据库
`vector(1536)`。DashScope Embedding 调用自动按单批最多 20 条拆分。

## 连接测试

`POST /api/v1/models/{model_id}/test` 根据模型类别执行：

- Chat：请求短 JSON，并报告 `finish_reason`、最终内容是否存在、reasoning token，
  以及 `enable_thinking=false` 是否被网关实际执行；
- Embedding：生成向量并返回实际维度；
- Rerank：对两段测试文本排序。

知识库必须关联一个启用的 Embedding 模型后才能处理文档。当前首版迁移固定
`vector(1536)`，配置其他维度会在写入前明确失败；切换维度需要专门迁移并重建
HNSW 索引。

每个知识库必须显式选择上表中需要的模型。Wiki 任务在入队时把选择固化到
`wiki_update_jobs.model_id` 或 `wiki_health_jobs.model_id`，所以修改知识库设置不会偷偷
改变已入队任务；任务中心会展示实际模型。

“请求关闭推理”是 OpenAI-compatible 扩展参数，不等于模型能力保证。部分代理网关
会忽略 `enable_thinking=false`。SynapseKB 不记录隐藏推理正文，只记录 reasoning token/
字符数并在连接测试中给出警告。结构化 Wiki 生成发现 `finish_reason=length` 时会先做
一次更小材料、更多输出余量的紧凑重试；仍失败才对单文档使用真实来源摘录保底。

混合召回使用知识库显式绑定的 Rerank 模型。Rerank 服务不可用时，系统记录
结构化错误并回退到 RRF 排序，不丢弃已经召回的证据。

`provider=mock` 只用于无真实密钥的自动化测试，不能执行 Chat、Rerank、Agent
或 Wiki 生成，也不会在产品中伪装为真实模型结果。

## 调用观测

模型适配层输出不含正文和密钥的结构化指标：操作类型、模型名、耗时、批大小，
以及提供方返回时的 Token 数。费用可依据模型配置中的价格元数据在外部
OpenTelemetry/日志流水线计算；默认不猜测供应商价格。
