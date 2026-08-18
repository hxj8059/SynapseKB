import uuid
from types import SimpleNamespace

import pytest
import synapsekb.wiki.health as wiki_health
from synapsekb.database.models import KnowledgeBase, WikiHealthJob
from synapsekb.wiki.entity_resolution import (
    canonicalize_wiki_entity_title,
    normalize_wiki_label,
    wiki_label_aliases,
)
from synapsekb.wiki.generator import (
    WIKI_COMPACT_RETRY_MAX_TOKENS,
    WIKI_GENERATION_MAX_TOKENS,
    _complete_chunk_batches,
    _evenly_sample,
)
from synapsekb.wiki.health import (
    WIKI_HEALTH_REVIEW_MAX_TOKENS,
    _apply_health_relation_proposal,
    _candidate_review_priority,
    automatic_merge_block_reason,
    compose_merged_markdown,
    is_auto_merge_eligible,
    is_high_precision_label_candidate,
    sanitize_wiki_health_report,
)
from synapsekb.wiki.structured import (
    parse_generated_wiki_graph,
    wiki_generation_system_prompt,
)


def test_evenly_sample_covers_document_start_middle_and_end() -> None:
    assert _evenly_sample(list(range(24)), 6) == [0, 5, 9, 14, 18, 23]
    assert _evenly_sample([1, 2], 6) == [1, 2]


def test_complete_wiki_batches_cover_every_chunk_once() -> None:
    chunks = list(range(37))

    batches = _complete_chunk_batches(chunks, batch_size=16)

    assert [len(batch) for batch in batches] == [16, 16, 5]
    assert [item for batch in batches for item in batch] == chunks


def test_wiki_model_output_limits_allow_long_structured_results() -> None:
    assert WIKI_GENERATION_MAX_TOKENS == 10_000
    assert WIKI_COMPACT_RETRY_MAX_TOKENS == 10_000
    assert WIKI_HEALTH_REVIEW_MAX_TOKENS == 8_000


def test_parse_generated_wiki_graph_normalizes_types_and_refs() -> None:
    graph = parse_generated_wiki_graph(
        r"""```json
        {
          "nodes": [
            {
              "key": "ai",
              "type": "行业",
              "title": "AI 产业链",
              "summary": "摘要",
              "markdown": "# AI 产业链\n\n2026 年产业链信息。[1]",
              "source_refs": [2, 1, 1, 0]
            },
            {
              "key": "chip",
              "type": "产品",
              "title": "AI 芯片",
              "summary": "摘要",
              "markdown": "# AI 芯片\n\n芯片产品与供给情况。[2]",
              "source_refs": [2]
            }
          ],
          "relations": [
            {
              "source_key": "ai",
              "target_key": "chip",
              "type": "包含",
              "evidence": "AI 产业链包含芯片环节",
              "source_refs": [2, 2]
            }
          ]
        }
        ```""",
        allowed_node_types=["行业", "产品"],
    )

    assert graph.nodes[0].source_refs == [1, 2]
    assert graph.relations[0].source_refs == [2]


def test_parse_generated_wiki_graph_accepts_safe_english_type_alias() -> None:
    graph = parse_generated_wiki_graph(
        """{
          "nodes": [{
            "key": "novo", "type": "company", "title": "Novo Nordisk",
            "summary": "药企", "markdown": "# Novo Nordisk\\n\\n该公司的管线和处方数据。[1]",
            "source_refs": [1]
          }],
          "relations": []
        }""",
        allowed_node_types=["管线", "公司"],
    )

    assert graph.nodes[0].node_type == "公司"


def test_parse_generated_wiki_graph_allows_a_batch_without_stable_entities() -> None:
    graph = parse_generated_wiki_graph(
        '{"nodes": [], "relations": []}',
        allowed_node_types=["产业主题", "个股"],
    )

    assert graph.nodes == []
    assert graph.relations == []


def test_parse_generated_wiki_graph_discards_invalid_relations_but_keeps_nodes() -> None:
    graph = parse_generated_wiki_graph(
        """{
          "nodes": [{
            "key": "ccl", "type": "产业主题", "title": "CCL",
            "summary": "摘要", "markdown": "# CCL\\n\\n这里是一段足够长度且带有引用的来源内容。[1]",
            "source_refs": [1]
          }],
          "relations": [
            {"source_key": "ccl", "target_key": "missing", "type": "关联",
             "evidence": "无效目标", "source_refs": [1]},
            {"source_key": "ccl", "target_key": "ccl", "type": "自关联",
             "evidence": "自关系", "source_refs": [1]}
          ]
        }""",
        allowed_node_types=["产业主题"],
    )

    assert [node.title for node in graph.nodes] == ["CCL"]
    assert graph.relations == []


def test_parse_generated_wiki_graph_discards_document_title_nodes() -> None:
    graph = parse_generated_wiki_graph(
        """{
          "nodes": [
            {
              "key": "report", "type": "产业主题", "title": "AI行业周报_20260725",
              "summary": "报告摘要",
              "markdown": "# AI行业周报\\n\\n这里是一段足够长度的报告摘录。[1]",
              "source_refs": [1]
            },
            {
              "key": "pdf", "type": "产业主题", "title": "research-report.pdf",
              "summary": "报告摘要", "markdown": "# 报告\\n\\n这里是一段足够长度的报告摘录。[1]",
              "source_refs": [1]
            },
            {
              "key": "pcb", "type": "产业主题", "title": "PCB",
              "summary": "稳定实体", "markdown": "# PCB\\n\\n这里是一段足够长度的实体内容。[1]",
              "source_refs": [1]
            }
          ],
          "relations": [{
            "source_key": "report", "target_key": "pcb", "type": "关联",
            "evidence": "报告谈及 PCB", "source_refs": [1]
          }]
        }""",
        allowed_node_types=["产业主题"],
        forbidden_titles={"AI行业周报_20260725"},
    )

    assert [node.title for node in graph.nodes] == ["PCB"]
    assert graph.relations == []


def test_parse_generated_wiki_graph_rejects_unconfigured_type() -> None:
    with pytest.raises(ValueError, match="未配置"):
        parse_generated_wiki_graph(
            """{
              "nodes": [{
                "key": "x", "type": "人物", "title": "某人",
                "summary": "", "markdown": "# 某人\\n\\n这里是足够长的来源内容。[1]",
                "source_refs": [1]
              }],
              "relations": []
            }""",
            allowed_node_types=["行业"],
        )


def test_parse_generated_wiki_graph_rejects_anonymous_company_node() -> None:
    with pytest.raises(ValueError, match="单一且明确"):
        parse_generated_wiki_graph(
            """{
              "nodes": [{
                "key": "company", "type": "个股", "title": "本公司",
                "summary": "摘要",
                "markdown": "# 本公司\\n\\n这里是一段足够长度且带有引用的来源内容。[1]",
                "source_refs": [1]
              }],
              "relations": []
            }""",
            allowed_node_types=["产业主题", "个股"],
        )


def test_generation_prompt_contains_domain_configuration() -> None:
    prompt = wiki_generation_system_prompt(
        node_types=["行业", "个股", "产品"],
        custom_prompt="个股节点使用证券简称作为标题。",
    )

    assert "行业、个股、产品" in prompt
    assert "证券简称" in prompt
    assert "同类产品" in prompt
    assert "CCL涨价受益标的" in prompt
    assert "CPO/NPO" in prompt
    assert "DeepSeek V3" in prompt
    assert "DeepSeek V4" in prompt
    assert "AI用覆铜板/M9覆铜板" in prompt
    assert "NPO（近封装光学）" in prompt
    assert "胜宏科技文档中的 PCB" in prompt
    assert "不得为了简短删除版本号" in prompt


@pytest.mark.parametrize(
    ("title", "canonical"),
    [
        ("PCB钻针行业", "PCB钻针"),
        ("PCB钻针赛道", "PCB钻针"),
        ("3D堆叠芯片产业链", "3D堆叠芯片"),
        ("CCL（覆铜板）市场", "CCL（覆铜板）"),
        ("CCL涨价受益标的", "CCL"),
        ("CCL行业产能扩张", "CCL"),
        ("AI行业红利期", "AI"),
        ("AI资本开支上行周期", "AI资本开支"),
        ("AI资本开支周期", "AI资本开支"),
        ("AI资本开支热潮", "AI资本开支"),
    ],
)
def test_topic_heading_is_canonicalized_to_reusable_entity(
    title: str,
    canonical: str,
) -> None:
    assert canonicalize_wiki_entity_title(title, node_type="产业主题") == canonical


def test_topic_aliases_include_canonical_scope_free_name() -> None:
    aliases = wiki_label_aliases("CCL（覆铜板）市场", node_type="产业主题")

    assert "CCL（覆铜板）" in aliases
    assert "CCL" in aliases
    assert "覆铜板" in aliases


def test_company_title_is_not_rewritten_by_topic_rules() -> None:
    assert canonicalize_wiki_entity_title("市场科技", node_type="个股") == "市场科技"


def test_exact_alias_normalization_does_not_confuse_related_entities() -> None:
    assert normalize_wiki_label("纬颖（Wiwynn）") == "纬颖wiwynn"
    assert wiki_label_aliases("纬颖（Wiwynn）") == ["纬颖（Wiwynn）", "纬颖", "Wiwynn"]
    assert normalize_wiki_label("微容电子") != normalize_wiki_label("宇阳科技")


def test_company_alias_removes_only_legal_form_suffix() -> None:
    assert wiki_label_aliases("胜宏科技股份有限公司", node_type="个股") == [
        "胜宏科技股份有限公司",
        "胜宏科技",
    ]
    assert wiki_label_aliases("沪电股份", node_type="个股") == ["沪电股份"]


def test_parenthetical_related_chinese_term_is_not_registered_as_alias() -> None:
    assert wiki_label_aliases("算力卫星（卫星互联网）", node_type="行业") == [
        "算力卫星（卫星互联网）"
    ]


def test_fuzzy_identity_gate_rejects_related_entities() -> None:
    assert not is_high_precision_label_candidate("微容电子", "宇阳科技", 0.0)
    assert not is_high_precision_label_candidate("小尺寸MLCC", "高容MLCC", 0.25)
    assert not is_high_precision_label_candidate("IDC业务", "AIDC业务", 0.19)


def test_fuzzy_identity_gate_keeps_close_name_variants() -> None:
    assert is_high_precision_label_candidate("PCB", "PCB板", 0.50)
    assert is_high_precision_label_candidate("高容MLCC", "高容量MLCC", 0.50)
    assert is_high_precision_label_candidate("人工智能芯片", "人工智能晶片", 0.75)


def test_auto_merge_trusts_explicit_high_confidence_model_decision() -> None:
    candidate = {
        "candidate_source": "label_trigram",
        "left_label": "King Slide",
        "right_label": "川湖科技",
        "node_type": "个股",
    }

    assert is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 0.90,
            "identity_basis": "translation",
        },
    )
    assert not is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 0.899,
            "identity_basis": "translation",
        },
    )
    assert not is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 1.0,
            "identity_basis": "none",
        },
    )
    assert not is_auto_merge_eligible(
        candidate,
        {
            "classification": "distinct",
            "confidence": 1.0,
            "identity_basis": "translation",
        },
    )


def test_auto_merge_no_longer_requires_deterministic_alias_anchor() -> None:
    candidate = {
        "candidate_source": "alias_exact",
        "matched_alias": "卫星互联网",
        "left_label": "算力卫星（卫星互联网）",
        "right_label": "卫星互联网",
        "node_type": "行业",
    }

    assert is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 0.98,
            "identity_basis": "exact_alias",
        },
    )


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("DeepSeek", "DeepSeek V4"),
        ("DeepSeek V3", "DeepSeek V4"),
        ("AWS Trainium", "AWS Trainium 3"),
        ("AWS Trainium 3", "AWS Trainium 4"),
        ("NVIDIA Vera Rubin", "NVIDIA Vera Rubin Ultra"),
        ("NVIDIA GB300", "NVIDIA GB300 NVL72"),
        ("Claude Mythos", "Claude Mythos 5"),
    ],
)
def test_version_model_and_configuration_pairs_cannot_auto_merge(
    left: str,
    right: str,
) -> None:
    candidate = {
        "left_label": left,
        "right_label": right,
        "node_type": "产业主题",
    }
    decision = {
        "classification": "merge",
        "confidence": 0.99,
        "identity_basis": "scope_variant",
    }

    assert not is_auto_merge_eligible(candidate, decision)
    assert "版本、型号或配置" in str(automatic_merge_block_reason(candidate, decision))


def test_same_model_version_can_merge_across_brand_prefixes() -> None:
    candidate = {
        "left_label": "GLM-5.2模型",
        "right_label": "智谱AI GLM-5.2",
        "node_type": "产业主题",
    }

    assert is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 0.98,
            "identity_basis": "official_name",
        },
    )


def test_rhetorical_topic_2_0_is_not_treated_as_a_product_version() -> None:
    candidate = {
        "left_label": "AI资本开支",
        "right_label": "AI资本开支2.0",
        "node_type": "产业主题",
    }

    assert is_auto_merge_eligible(
        candidate,
        {
            "classification": "merge",
            "confidence": 0.98,
            "identity_basis": "scope_variant",
        },
    )


def test_observation_page_is_prioritized_for_model_cleanup_review() -> None:
    observation = {
        "left_label": "AI资本开支",
        "right_label": "AI资本开支2.0",
        "node_type": "产业主题",
        "candidate_source": "label_trigram",
        "similarity": 0.55,
    }
    generic_overlap = {
        "left_label": "AI用覆铜板",
        "right_label": "M9覆铜板",
        "node_type": "产业主题",
        "candidate_source": "label_trigram",
        "similarity": 0.95,
    }

    assert _candidate_review_priority(observation) > _candidate_review_priority(generic_overlap)


def test_non_entity_observation_page_can_fold_into_stable_core() -> None:
    candidate = {
        "left_label": "AI资本开支",
        "right_label": "AI资本开支与融资",
        "node_type": "产业主题",
    }

    assert is_auto_merge_eligible(
        candidate,
        {
            "classification": "fold_into",
            "confidence": 0.95,
            "identity_basis": "non_entity_view",
        },
    )


@pytest.mark.asyncio
async def test_llm_review_auto_resolves_identity_but_keeps_version_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProvider:
        async def chat_json(self, *_args: object, **_kwargs: object) -> str:
            return """{
              "similarity_decisions": [
                {
                  "candidate_id": "1", "classification": "merge",
                  "canonical": "right", "confidence": 0.97,
                  "identity_basis": "translation", "relation_type": "none",
                  "relation_direction": "none", "reason": "同一公司的中英文名称"
                },
                {
                  "candidate_id": "2", "classification": "related",
                  "canonical": "left", "confidence": 0.98,
                  "identity_basis": "none", "relation_type": "version_of",
                  "relation_direction": "right_to_left", "reason": "V4 是独立版本"
                }
              ],
              "orphan_links": []
            }"""

        async def close(self) -> None:
            return None

    model_id = uuid.uuid4()

    async def fake_resolve(*_args: object) -> SimpleNamespace:
        return SimpleNamespace(id=model_id)

    monkeypatch.setattr(wiki_health, "resolve_wiki_health_model", fake_resolve)
    monkeypatch.setattr(wiki_health, "create_provider", lambda _model: FakeProvider())
    left_company_id = uuid.uuid4()
    right_company_id = uuid.uuid4()
    deepseek_id = uuid.uuid4()
    deepseek_v4_id = uuid.uuid4()
    candidates = [
        {
            "candidate_id": "1",
            "left_page_id": str(left_company_id),
            "right_page_id": str(right_company_id),
            "left_label": "King Slide",
            "right_label": "川湖科技",
            "node_type": "个股",
        },
        {
            "candidate_id": "2",
            "left_page_id": str(deepseek_id),
            "right_page_id": str(deepseek_v4_id),
            "left_label": "DeepSeek",
            "right_label": "DeepSeek V4",
            "node_type": "产业主题",
        },
    ]
    knowledge_base = KnowledgeBase(
        name="AI 产业链",
        wiki_node_types=["产业主题", "个股"],
    )
    job = WikiHealthJob()

    proposals, error = await wiki_health._llm_review(
        SimpleNamespace(),  # type: ignore[arg-type]
        knowledge_base,
        job,
        candidates,
        [],
        [],
        {},
    )

    assert error is None
    assert job.model_id == model_id
    merge = next(item for item in proposals if item["type"] == "merge_pages")
    assert merge["auto_apply"] is True
    assert merge["target_page_id"] == str(right_company_id)
    assert any(
        item["type"] == "mark_distinct" and item["auto_apply"] is True
        for item in proposals
    )
    version_relation = next(item for item in proposals if item["type"] == "add_relation")
    assert version_relation["source_page_id"] == str(deepseek_v4_id)
    assert version_relation["target_page_id"] == str(deepseek_id)
    assert version_relation["relation_type"] == "version_of"


def test_legacy_semantic_candidates_are_hidden_from_health_report() -> None:
    original = {
        "similar_candidates": [
            {"candidate_source": "embedding_cosine", "similarity": 0.83},
            {"candidate_source": "label_trigram", "similarity": 0.72},
        ],
        "summary": {"similar_candidates": 2},
    }

    sanitized = sanitize_wiki_health_report(original)

    assert len(sanitized["similar_candidates"]) == 1
    assert sanitized["summary"]["similar_candidates"] == 1
    assert sanitized["candidate_policy"]["legacy_semantic_candidates_hidden"] == 1
    assert original["summary"]["similar_candidates"] == 2


def test_applied_relation_proposal_is_removed_from_health_job() -> None:
    proposal_id = uuid.uuid4()
    source_page_id = uuid.uuid4()
    target_page_id = uuid.uuid4()
    edge_id = uuid.uuid4()
    job = WikiHealthJob(
        report={"summary": {"proposed_actions": 1}},
        proposed_actions=[
            {
                "id": str(proposal_id),
                "type": "add_relation",
                "source_page_id": str(source_page_id),
                "target_page_id": str(target_page_id),
                "relation_type": "related_to",
                "reason": "服务器 CPU 是产业链组成部分",
            }
        ],
        applied_actions=[],
    )

    applied = _apply_health_relation_proposal(
        job,
        proposal_id=proposal_id,
        source_page_id=source_page_id,
        target_page_id=target_page_id,
        relation_type="related_to",
        edge_id=edge_id,
    )

    assert applied is True
    assert job.proposed_actions == []
    assert job.report["summary"]["proposed_actions"] == 0
    assert job.applied_actions[0]["edge_id"] == str(edge_id)


def test_generated_node_can_only_reuse_a_provided_matching_history_page() -> None:
    page_id = uuid.uuid4()
    graph = parse_generated_wiki_graph(
        f'''{{
          "nodes": [{{
            "key": "mlcc", "type": "产品", "title": "高容量 MLCC",
            "summary": "摘要", "markdown": "# 高容量 MLCC\\n\\n这里是足够长的来源内容。[1]",
            "source_refs": [1], "existing_page_id": "{page_id}"
          }}],
          "relations": []
        }}''',
        allowed_node_types=["产品"],
        allowed_existing_pages={page_id: "产品"},
    )

    assert graph.nodes[0].existing_page_id == page_id


def test_generated_node_rejects_unprovided_history_page() -> None:
    with pytest.raises(ValueError, match="未提供"):
        parse_generated_wiki_graph(
            f'''{{
              "nodes": [{{
                "key": "x", "type": "产品", "title": "产品 X",
                "summary": "摘要", "markdown": "# 产品 X\\n\\n这里是足够长的来源内容。[1]",
                "source_refs": [1], "existing_page_id": "{uuid.uuid4()}"
              }}],
              "relations": []
            }}''',
            allowed_node_types=["产品"],
            allowed_existing_pages={},
        )


def test_merge_markdown_keeps_both_pages_and_deduplicates_identical_body() -> None:
    merged = compose_merged_markdown(
        "AI 芯片",
        "# AI 芯片\n\n目标页事实。[1]",
        [
            ("人工智能芯片", "# 人工智能芯片\n\n补充事实。[2]"),
            ("重复页", "# 重复页\n\n目标页事实。[1]"),
        ],
    )

    assert merged.startswith("# AI 芯片")
    assert "## 合并自：人工智能芯片" in merged
    assert "补充事实。[2]" in merged
    assert "## 合并自：重复页" not in merged
