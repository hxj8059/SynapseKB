# MCP 接入

## 创建令牌

在“访问令牌”页面创建 PAT。令牌只展示一次，数据库只保存 Hash。默认 Scope：

```text
kb:read document:read search:read agent:run wiki:read
```

写入文档需要 `document:write`，Wiki 管理需要 `wiki:admin`，且 Scope 不会扩大 App 内权限。
同一个含 `document:write` 的 PAT 也可以用于 REST 文档上传接口，适合批量上传和 OSS
预签名直传；MCP `document_upload` 仍保留 10MB 限制。

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

生产必须使用 HTTPS。服务端验证 Bearer Token、Origin、用户状态、Scope、知识库权限和速率，并为每次工具调用写审计日志。

## 本地 stdio 代理

令牌只通过环境变量传入，不写入代理配置：

```bash
export SYNAPSEKB_URL=https://synapsekb.example.com
export SYNAPSEKB_TOKEN=skbp_...
synapsekb-mcp
```

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
