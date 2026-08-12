---
name: synapsekb-shared
description: Configure and safely use a SynapseKB MCP connection, select authorized knowledge bases, choose between search, RAG, and Agent workflows, and preserve citations. Use whenever another SynapseKB skill needs shared authentication, permission, error-handling, or write-confirmation rules.
---

# SynapseKB Shared

Use these rules for every SynapseKB MCP workflow.

## Authenticate

1. Read the remote MCP URL from the user's configuration.
2. Read the Personal Access Token from an environment variable or the host tool's secure secret store.
3. Never place the token in prompts, logs, source files, shell history, or generated reports.
4. If authentication fails, ask the user to create or replace a token in SynapseKB. Do not request their password.

The normal remote endpoint is `https://<synapsekb-host>/mcp`. A local `synapsekb-mcp` stdio proxy may be used when the host cannot connect to Streamable HTTP directly.

## Select the knowledge scope

1. Call `kb_list` before the first scoped operation unless the user supplied stable knowledge-base IDs.
2. Match names carefully and keep the selected `knowledge_base_ids` explicit.
3. If two knowledge bases have similar names, present the matches and ask the user to choose.
4. Never infer access to a knowledge base that `kb_list` does not return.
5. Preserve any user-supplied `document_ids` and `tag_ids`.

## Choose the workflow

- Use `knowledge_search` to discover, inspect, quote, or verify raw evidence.
- Use `rag_answer` for a direct synthesized answer with citations and no multi-step investigation.
- Use `agent_run_start` for a bounded multi-step analysis, timeline investigation, Wiki-plus-document research, or a request requiring several knowledge tools.
- Use `agent_run_get` to poll a long Agent run and `agent_run_cancel` when the user asks to stop it.
- Use Wiki tools when the user asks for curated topic pages, navigation, backlinks, or graph relationships.

Do not use SynapseKB's Agent as a web-search, browser, shell, Python, or external-business-system agent.

## Preserve evidence

Keep each returned citation linked to its citation number. Show the document title, page or section when available, quoted evidence, and `source_time`. Mark missing `source_time` as unknown. Never replace `source_time` with `created_at`.

When evidence conflicts, report the conflict and cite both sources. Do not silently merge different effective periods.

## Handle time

Whenever the user mentions a date, period, relative time, latest version, or historical comparison, pass a structured time filter. Default to `field=source_time` and `include_unknown=false`. Do not rely on dates embedded only in the query text.

Use the `synapsekb-temporal-research` skill for relative dates and period comparisons.

## Protect writes

Treat these as writes:

- `document_upload`
- any token with `document:write`
- Agent or Wiki administration
- Wiki regeneration, publishing, rollback, or deletion

Explain the target and effect, then obtain user confirmation immediately before a material write unless the user already gave a precise, explicit instruction for that write. Read-only tools do not require confirmation.

## Recover from errors

- On `401`, replace or reconfigure the token.
- On `403`, do not retry with broader scope; explain the required permission.
- On `404`, refresh IDs with the relevant list or index tool.
- On `409`, inspect the existing resource or active job before retrying.
- On `429`, honor the retry delay and reduce polling frequency.
- On timeout, do not assume failure. Query the run or job status before starting a duplicate.
- Preserve the request filters and citation context when retrying.
