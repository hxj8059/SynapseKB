# MCP 接入

## 创建令牌

在“访问令牌”页面创建 PAT。令牌只展示一次，数据库只保存 Hash。默认 Scope：

```text
kb:read document:read search:read agent:run wiki:read
```

写入文档需要 `document:write`，Wiki 管理需要 `wiki:admin`，且 Scope 不会扩大 App 内权限。
同一个含 `document:write` 的 PAT 也可以用于 REST 文档上传接口，适合批量上传和 OSS
预签名直传；MCP `document_upload` 仍保留 10MB 限制。

不再使用的有效令牌应先撤销，使其立即失效。已撤销或已过期的令牌可以从列表删除；删除
只清理令牌记录，创建、使用、撤销和删除事件仍保留在审计日志中。

## Remote Streamable HTTP

```json
{
  "mcpServers": {
    "synapsekb": {
      "url": "https://synapsekb.example.com/mcp",
      "headers": {
        "Authorization": "Bearer skbp_..."
      }
    }
  }
}
```

推荐使用 HTTPS。显式启用 `ALLOW_INSECURE_HTTP=true` 后也可连接
`http://<server-ip>[:port]/mcp`，但 Bearer Token、查询和返回内容不会被传输加密。服务端仍
验证 Bearer Token、Host、Origin、用户状态、Scope、知识库权限和速率，并为每次工具调用写
审计日志。

Codex 可以直接配置 Streamable HTTP：

```bash
export SYNAPSEKB_TOKEN='skbp_...'
codex mcp add synapsekb \
  --url 'http://203.0.113.10:8088/mcp' \
  --bearer-token-env-var SYNAPSEKB_TOKEN
codex mcp list
```

Skill 只描述工具选择、时间过滤与引用规则，不会自行建立连接。安装 Skill 后仍必须配置 MCP；
设置 `SYNAPSEKB_TOKEN` 的进程环境必须与启动 Codex 的环境一致。

## 本地 stdio 代理

令牌只通过环境变量传入，不写入代理配置：

```bash
export SYNAPSEKB_URL=https://synapsekb.example.com
export SYNAPSEKB_TOKEN=skbp_...
synapsekb-mcp
```

当服务器只有公网 IP + HTTP，并且你已经明确接受 Bearer Token 明文传输风险时，必须额外进行
一次显式授权；默认仍拒绝向远程 HTTP 地址发送令牌：

```bash
export SYNAPSEKB_URL=http://203.0.113.10:8088
export SYNAPSEKB_TOKEN=skbp_...
export SYNAPSEKB_ALLOW_INSECURE_HTTP=true
synapsekb-mcp
```

`SYNAPSEKB_URL` 可以填写服务根地址或完整 `/mcp` 地址，代理会统一规范化为一个 `/mcp`，不会
重复拼接。切换回 HTTPS 后应删除 `SYNAPSEKB_ALLOW_INSECURE_HTTP`。

客户端配置：

```json
{
  "mcpServers": {
    "synapsekb": {
      "command": "synapsekb-mcp",
      "env": {
        "SYNAPSEKB_URL": "https://synapsekb.example.com",
        "SYNAPSEKB_TOKEN": "${SYNAPSEKB_TOKEN}"
      }
    }
  }
}
```

长 Agent 任务使用 `agent_run_start`、`agent_run_get`、`agent_run_cancel`，不要让单次 MCP 调用等待五分钟。

`wiki_search` 是 Wiki 研究的默认入口。它使用知识库选定的 Embedding 模型，检索由“节点
标题 + 摘要前 800 字符”生成的页面节点向量，同时合并精确别名和关键词结果，返回
`rank/relevance_score/semantic_score/keyword_score/node_id`。相关性只用于候选排序，客户端模型
仍需根据标题、类型和摘要筛选真正相关的少量节点，再调用 `wiki_read` 和
`wiki_graph_neighbors` 读取正文、来源与一跳关系。Embedding 调用失败或节点向量尚未就绪时，
服务端自动返回 `retrieval_mode=keyword_fallback`，不会让整个 Wiki 查询失败。

`wiki_index` 只是有界分页目录工具，默认返回 100 个、最多 200 个目录项，并返回
`total/next_offset/type_counts`。只有明确浏览目录、按类型列出节点或查看统计时才调用；不要在
主题研究前先读第一页目录，也不要通过翻页遍历 Wiki 来发现相关内容。

检索与 Wiki 图工具的时间字段使用 `field/from_time/to_time/include_unknown`。日期时间
必须包含时区，默认 `field=source_time`；跨时期比较必须使用 `compare_periods` 的
两组独立范围。

## Skill 包

仓库包含四个可直接复制到 Codex/WorkBuddy Skill 目录的包：

- `skills/synapsekb-shared`
- `skills/synapsekb-rag-search`
- `skills/synapsekb-temporal-research`
- `skills/synapsekb-wiki`

共享 Skill 说明认证、权限和写操作确认；其他 Skill 分别约束原始检索/RAG 选择、
跨时期独立检索以及 Wiki/局部图读取。客户端仍必须配置上面的 MCP Server，Skill
本身不会保存访问令牌。

登录 SynapseKB 后，也可以点击左侧栏底部 API Key 右侧的“Skill 安装”入口。页面提供
四个独立 ZIP、合集 ZIP、当前部署对应的 MCP URL，以及 Codex 和 WorkBuddy 分平台安装步骤。
下载接口需要 App 登录态，未认证用户不能获取 Skill 包。

Codex 用户可以下载合集并解压到用户级目录：

```bash
mkdir -p "$HOME/.agents/skills"
unzip synapsekb-skills.zip -d "$HOME/.agents/skills"
```

WorkBuddy 按单个 Skill 包导入：在“专家・技能・连接器”中选择“添加技能 → 上传技能”，
逐个上传四个独立 ZIP。安装完成后仍需配置 Streamable HTTP MCP 和 Bearer Token。
