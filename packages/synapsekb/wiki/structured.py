from __future__ import annotations

import json
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

_INVALID_COMPANY_TITLE = re.compile(
    r"^(?:本公司|公司|某公司|相关公司|头部公司|厂商|供应商)$|"
    r"[、/]|(?:与|和).*(?:公司|科技|集团)"
)
_DOCUMENT_FILENAME_TITLE = re.compile(
    r"\.(?:pdf|docx?|xlsx?|pptx?|md|txt|html?|jpe?g|png)$",
    flags=re.IGNORECASE,
)

WIKI_ENTITY_IDENTITY_RULES = """
实体判定以“两个页面能否共用同一个稳定定义”为准，不以名称相似、上下游相关或
内容相似为准。必须遵守以下规则：

1. 可合并的只有完全同一实体：中英文名、法定名与常用简称、明确缩写、异体/拼写变体，
   以及仅多了“行业、市场、赛道、产业链”观察范围后缀但核心定义不变的主题。
   例如“国内大模型/国产大模型”、“King Slide/川湖科技”、“ASML Holding/ASML”、
   “GLM-5.2/智谱AI GLM-5.2/GLM-5.2模型”、“3D堆叠芯片/3D堆叠芯片产业链”。
2. 系列、世代、版本、型号和具体配置必须分开建节点。系列本身与某个版本不是同一实体，
   不同版本之间也不得合并。例如 DeepSeek、DeepSeek V3、DeepSeek V4 是三个节点；
   AWS Trainium、Trainium 3、Trainium 4，Claude Mythos、Claude Mythos 5，Google TPU、TPU v9，
   NVIDIA GB300、GB300 NVL72 也必须分开，使用 version_of、configuration_of 等关系连接。
3. 上位类别与下位产品/规格不得合并。例如“AI用覆铜板/M9覆铜板”、
   “光纤光缆/G.657单模光纤”、“硅光/硅光芯片”、“MPO跳线/MPO连接器”是不同实体，
   应使用 subtype_of、part_of、uses 或 related_to 等关系。
4. 通用事物与特定应用范围不得仅因共享核心词就合并。例如“PSU（电源单元）/
   AI服务器电源”、“AI基础设施/AI算力基础设施”、“液冷系统/数据中心液冷”默认是 related，
   只有两页的定义和边界明确完全相同时才可合并。
5. 集团、子公司、品牌、上市证券不得仅因关联而合并，例如“三星/三星电机”。
   若 Wiki 的“个股”节点定义为发行人而非单独证券，同一发行人的公司名、英文名和 ADR 可合并。
6. 状态、趋势、观点和筛选结果不是稳定实体，例如“MLCC涨价”、“MLCC价格降幅放缓”、
   “国产存储厂商崛起”、“CCL涨价受益标的”。抽取时应把它们写入稳定核心节点的
   Markdown，并把公司与核心主题用有证据的关系连接。健康检查中，只能把状态页合入
   明确存在的稳定核心页；两个含义不同的状态页不得相互冒充同一实体。
   “AI资本开支2.0、AI资本开支上行周期、AI资本开支周期、AI资本开支热潮”中的
   `2.0/周期/热潮` 是主题阶段或状态修辞，不是产品版本，应合入“AI资本开支”；
   “AI资本开支与融资”这类组合观察页也不得长期作为平行实体，事实应分别沉淀到稳定主题。
7. 共享缩写不等于同一实体。括号释义冲突时必须 distinct，例如
   “NPO（近封装光学）/NPO（线性驱动可插拔光模块）”。
8. 通用产品或技术不因来源公司不同而拆成多个节点。例如胜宏科技文档中的 PCB 与
   沪电股份文档中的 PCB 应维护为同一个 PCB 节点，Markdown 按公司、时间和来源持续累积，
   公司与 PCB 通过有证据的生产、供应、客户或受益关系连接。只有品牌产品、专有型号或
   公司明确限定的产品系列才单独建节点。
9. 合并时规范标题优先使用稳定、完整、常见的正式名称；不得为了简短删除版本号、型号
   或配置。别名保留在节点别名中，不把同义名称继续建成平行节点。

合并前必须做反例检查：如果两页中的版本号、型号、产品边界、公司主体或括号释义可以同时成立
且彼此不等价，就不能 merge。无法确认完全同一时，优先 related 或 distinct。
健康维护时另有 fold_into：它不声称两个实体同义，只用于把状态、阶段、观点、组合观察等
不合格页面的 Markdown、来源和关系归并到稳定核心页并归档来源页。具体产品版本、型号和配置
不得 fold_into 上位产品系列。
""".strip()


class GeneratedWikiNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(min_length=1, max_length=80)
    node_type: str = Field(alias="type", min_length=1, max_length=30)
    title: str = Field(min_length=1, max_length=500)
    summary: str = Field(default="", max_length=2000)
    markdown: str = Field(min_length=20, max_length=200_000)
    source_refs: list[int] = Field(default_factory=list, max_length=100)
    existing_page_id: uuid.UUID | None = None

    @field_validator("key", "node_type", "title")
    @classmethod
    def strip_labels(cls, value: str) -> str:
        return value.strip()

    @field_validator("source_refs")
    @classmethod
    def normalize_source_refs(cls, value: list[int]) -> list[int]:
        return sorted({item for item in value if item > 0})


class GeneratedWikiRelation(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    source_key: str = Field(min_length=1, max_length=80)
    target_key: str = Field(min_length=1, max_length=80)
    relation_type: str = Field(alias="type", min_length=1, max_length=40)
    evidence: str = Field(min_length=1, max_length=4000)
    source_refs: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("source_key", "target_key", "relation_type", "evidence")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("source_refs")
    @classmethod
    def normalize_source_refs(cls, value: list[int]) -> list[int]:
        return sorted({item for item in value if item > 0})


class GeneratedWikiGraph(BaseModel):
    # A material batch may legitimately contain only disclosures, table headers,
    # or other text that should not become a durable Wiki entity.
    nodes: list[GeneratedWikiNode] = Field(default_factory=list, max_length=24)
    relations: list[GeneratedWikiRelation] = Field(default_factory=list, max_length=80)


def parse_generated_wiki_graph(
    response: str,
    *,
    allowed_node_types: list[str],
    allowed_existing_pages: dict[uuid.UUID, str] | None = None,
    forbidden_titles: set[str] | None = None,
) -> GeneratedWikiGraph:
    text = response.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Wiki 模型没有返回 JSON 对象")
    graph = GeneratedWikiGraph.model_validate(json.loads(text[start : end + 1]))
    normalized_forbidden_titles = {
        title.strip().casefold() for title in (forbidden_titles or set()) if title.strip()
    }
    graph.nodes = [
        node
        for node in graph.nodes
        if node.title.strip().casefold() not in normalized_forbidden_titles
        and not _DOCUMENT_FILENAME_TITLE.search(node.title.strip())
    ]
    allowed = {item.casefold(): item for item in allowed_node_types}
    keys: set[str] = set()
    for node in graph.nodes:
        canonical_type = allowed.get(node.node_type.casefold())
        if canonical_type is None:
            raise ValueError(f"模型返回了未配置的节点类型：{node.node_type}")
        node.node_type = canonical_type
        if node.node_type in {"个股", "公司", "企业"} and _INVALID_COMPANY_TITLE.search(
            node.title.strip()
        ):
            raise ValueError(f"个股节点必须是单一且明确的公司主体：{node.title}")
        if node.key in keys:
            raise ValueError(f"模型返回了重复节点 key：{node.key}")
        if node.existing_page_id is not None:
            existing_type = (allowed_existing_pages or {}).get(node.existing_page_id)
            if existing_type is None:
                raise ValueError("模型引用了未提供的历史 Wiki 页面")
            if existing_type.casefold() != node.node_type.casefold():
                raise ValueError("模型复用的历史 Wiki 页面类型不匹配")
        keys.add(node.key)
    # A malformed relation must not discard otherwise valid entity nodes. The
    # relation is optional derived data and can be regenerated during a later
    # Wiki update or health check.
    graph.relations = [
        relation
        for relation in graph.relations
        if relation.source_key in keys
        and relation.target_key in keys
        and relation.source_key != relation.target_key
    ]
    return graph


def wiki_generation_system_prompt(
    *,
    node_types: list[str],
    custom_prompt: str,
) -> str:
    types = "、".join(node_types)
    custom = custom_prompt.strip() or "无额外领域规则。"
    return f"""你是私有知识库的 Wiki 节点抽取器。只能依据输入材料，不得补充外部知识。

允许的节点类型只有：{types}。
领域规则：
{custom}

项目级实体同一性规则：
{WIKI_ENTITY_IDENTITY_RULES}

请只输出一个 JSON 对象，不要输出代码围栏或解释。结构必须是：
{{
  "nodes": [
    {{
      "key": "本次结果内唯一稳定键",
      "type": "上述允许类型之一",
      "title": "节点名称",
      "summary": "简短摘要",
      "markdown": "完整中文 Markdown，事实后保留 [材料编号] 引用，并明确时间",
      "source_refs": [1, 2],
      "existing_page_id": "仅当候选目录中存在同一实体时填写其 page_id，否则为 null"
    }}
  ],
  "relations": [
    {{
      "source_key": "源节点 key",
      "target_key": "目标节点 key",
      "type": "简洁关系名称",
      "evidence": "关系证据摘要",
      "source_refs": [1]
    }}
  ]
}}

每个节点必须是能跨文档持续维护、可复用的实体，不是报告标题、观点、状态、筛选结果或句子。
没有稳定实体时返回 {{"nodes": [], "relations": []}}，不得用文档标题或摘录充当节点。
宁可不提取节点，也不要为了数量制造节点；每批最多 5 个节点，
每个节点 Markdown 控制在 120～350 个中文字符，关系最多 12 条。
行业、赛道、市场、产业链、板块只是观察范围，不单独成节点：
“3D堆叠芯片产业链”“PCB钻针行业”“PCB钻针赛道”应分别命名为
“3D堆叠芯片”“PCB钻针”“PCB钻针”。
“厂商”“供应商”“受益标的”“产能扩张”“竞争格局”等是角色、状态或观点，
必须写入核心节点 Markdown，或拆成核心节点与个股节点之间有证据的关系；
例如“CCL涨价受益标的”不能作为节点，应创建 CCL、相关个股并使用“受益于”关系。
个股节点必须且只能表示一个明确的公司或证券主体，标题使用公司名或证券简称；
“A、B、C供货格局”“A与B推理优化”不能作为个股节点，应拆分公司节点并建立关系。
标题含“与/和/及/、//”并表达多个实体时，必须拆成多个节点再建立关系，
不得创建“CPO与OCS”“CPO/NPO”一类组合节点。
同一事物只创建一个节点；没有直接证据的关系不要输出。
历史候选只用于实体消歧：只有名称或别名和身份都一致时才能填写 existing_page_id。
同一行业、同类产品、上下游公司或内容相似不代表同一实体，禁止因此复用页面。
尤其不得复用不同版本、世代、型号、配置或上下位产品的历史页面。
每个节点 Markdown 必须能独立阅读，JSON 保持紧凑。"""
