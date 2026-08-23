export type User = {
  id: string;
  email: string;
  display_name: string;
  role: "admin" | "user";
  is_active: boolean;
  timezone: string;
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
};

export type KnowledgeBase = {
  id: string;
  name: string;
  description: string;
  visibility: "all" | "users";
  embedding_model_id: string | null;
  embedding_dimensions: number;
  rag_chat_model_id: string | null;
  source_time_chat_model_id: string | null;
  rerank_model_id: string | null;
  rag_max_output_tokens: number;
  wiki_chat_model_id: string | null;
  wiki_health_chat_model_id: string | null;
  wiki_enabled: boolean;
  wiki_health_check_enabled: boolean;
  wiki_health_check_interval_hours: number;
  wiki_node_types: string[];
  wiki_generation_prompt: string;
  created_at: string;
  updated_at: string;
};

export type Document = {
  id: string;
  knowledge_base_id: string;
  title: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  status: string;
  source_time: string | null;
  page_count: number | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
};

export type ProviderModel = {
  id: string;
  name: string;
  kind: "chat" | "embedding" | "rerank" | "ocr";
  provider: string;
  base_url: string;
  model_name: string;
  timeout_seconds: number;
  max_concurrency: number;
  embedding_dimensions: number | null;
  config: Record<string, unknown>;
  is_enabled: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
};

export type OcrSettings = {
  base_url: string | null;
  default_model: "PP-OCRv6" | "PaddleOCR-VL-1.6" | "PP-StructureV3";
  timeout_seconds: number;
  max_concurrency: number;
  has_api_key: boolean;
  source: "database" | "environment";
};

export type OcrTestResult = {
  ok: boolean;
  task_id: string;
  page_count: number;
  markdown_preview: string;
  metadata: Record<string, unknown>;
};

export type StorageSettings = {
  backend: "local" | "s3" | "oss" | "cos";
  local_storage_path: string;
  bucket: string;
  endpoint: string | null;
  internal_endpoint: string | null;
  use_internal_endpoint: boolean;
  region: string;
  force_path_style: boolean;
  key_prefix: string;
  has_access_key: boolean;
  has_secret_key: boolean;
  source: "database" | "environment";
};

export type StorageTestResult = {
  ok: boolean;
  backend: string;
  bucket: string;
  latency_ms: number;
  presigned_upload_supported: boolean;
};

export type ModelTestResult = {
  ok: boolean;
  kind: string;
  latency_ms: number;
  details: Record<string, unknown>;
};

export type SearchCitation = {
  citation_number: number;
  chunk_id: string;
  document_id: string;
  knowledge_base_id: string;
  knowledge_base_name: string;
  document_name: string;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  original_text: string;
  source_time: string | null;
  score: number;
};

export type KnowledgeBaseOverview = {
  knowledge_bases: Array<{
    id: string;
    name: string;
    description: string;
    document_count: number;
    ready_document_count: number;
  }>;
  total_document_count: number;
  recent_documents: Array<{
    id: string;
    knowledge_base_id: string;
    knowledge_base_name: string;
    title: string;
    status: string;
    source_time: string | null;
    created_at: string;
  }>;
};

export type ChatSession = {
  id: string;
  title: string;
  mode: string;
  created_at: string;
  updated_at: string;
};

export type ChatCitation = {
  citation_number: number;
  chunk_id: string | null;
  document_id: string | null;
  document_title: string;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  original_text: string;
  source_time: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  model_id: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  latency_ms: number | null;
  retrieval_params: Record<string, unknown>;
  created_at: string;
  citations: ChatCitation[];
};

export type ChatSessionDetail = ChatSession & {
  messages: ChatMessage[];
};

export type DocumentChunk = {
  id: string;
  ordinal: number;
  content: string;
  token_count: number;
  page_from: number | null;
  page_to: number | null;
  section: string | null;
  source_time: string | null;
  created_at: string;
  updated_at: string;
};

export type ProcessingJob = {
  id: string;
  document_id: string;
  job_type: string;
  status: string;
  progress: number;
  stage: string | null;
  attempt: number;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
};

export type Agent = {
  id: string;
  name: string;
  avatar: string | null;
  description: string;
  system_prompt: string;
  chat_model_id: string;
  visibility: "all" | "users";
  max_steps: number;
  max_tokens: number;
  tool_decision_max_tokens: number;
  timeout_seconds: number;
  recommended_questions: string[];
  is_enabled: boolean;
  created_at: string;
  updated_at: string;
};

export type AgentRun = {
  id: string;
  agent_id: string;
  user_id: string;
  session_id: string | null;
  status: string;
  query: string;
  resolved_time_summary: string | null;
  result: string | null;
  citations: {
    citation_number: number;
    chunk_id: string | null;
    document_id: string;
    knowledge_base_id: string | null;
    knowledge_base_name: string | null;
    document_name: string;
    page_from: number | null;
    page_to: number | null;
    section: string | null;
    original_text: string;
    source_time: string | null;
    score: number | null;
  }[];
  error_summary: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AgentRunSummary = Pick<
  AgentRun,
  | "id"
  | "agent_id"
  | "status"
  | "query"
  | "error_summary"
  | "started_at"
  | "finished_at"
  | "created_at"
  | "updated_at"
>;

export type AgentRunHistory = {
  items: AgentRunSummary[];
  total: number;
  limit: number;
  offset: number;
};

export type WikiPageSummary = {
  id: string;
  space_id: string;
  parent_id: string | null;
  slug: string;
  title: string;
  summary: string;
  sort_order: number;
  source_time: string | null;
  current_version_id: string | null;
  is_archived: boolean;
  merged_into_page_id: string | null;
  node_type: string | null;
  created_at: string;
  updated_at: string;
};

export type WikiIndexItem = Pick<
  WikiPageSummary,
  "id" | "parent_id" | "title" | "node_type" | "source_time" | "updated_at"
>;

export type WikiIndexPage = {
  items: WikiIndexItem[];
  space_id: string;
  total: number;
  total_published: number;
  limit: number;
  offset: number;
  published_version: number;
  type_counts: Array<{ type: string; count: number }>;
};

export type WikiPageContent = WikiPageSummary & {
  content: string;
  version_number: number;
  protected_blocks: string[];
  sources: {
    document_id: string;
    document_name: string | null;
    chunk_id: string | null;
    paragraph_key: string;
    evidence_text: string;
    source_time: string | null;
  }[];
};

export type WikiPageVersion = {
  id: string;
  page_id: string;
  version_number: number;
  content: string;
  protected_blocks: string[];
  change_summary: string;
  is_manual: boolean;
  source_time: string | null;
  created_at: string;
  updated_at: string;
};

export type WikiJob = {
  id: string;
  space_id: string;
  model_id: string | null;
  status: string;
  generation_id: string;
  affected_document_ids: string[];
  candidate_version: number | null;
  quality_report: Record<string, unknown>;
  change_summary: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
};

export type WikiHealthJob = {
  id: string;
  space_id: string;
  model_id: string | null;
  status: string;
  trigger: "manual" | "scheduled";
  auto_repair: boolean;
  report: Record<string, unknown>;
  proposed_actions: Record<string, unknown>[];
  applied_actions: Record<string, unknown>[];
  error_summary: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type WikiSimilarityCandidate = {
  candidate_id: string;
  left_page_id: string;
  left_label: string;
  left_summary?: string;
  left_source_count?: number;
  right_page_id: string;
  right_label: string;
  right_summary?: string;
  right_source_count?: number;
  model_classification?: "merge" | "fold_into" | "related" | "distinct";
  model_confidence?: number;
  model_reason?: string;
  node_type: string;
  similarity: number;
  candidate_source: "alias_exact" | "label_trigram" | "embedding_cosine";
};

export type WikiEntityResolution = {
  id: string;
  decision: "merge" | "distinct" | "reverted";
  left_page_id: string;
  left_title: string | null;
  right_page_id: string;
  right_title: string | null;
  canonical_page_id: string | null;
  canonical_title: string | null;
  reason: string;
  decision_source: "manual" | "llm_auto";
  merge_group_id: string | null;
  reverted_at: string | null;
  created_at: string;
  updated_at: string;
};

export type WikiGraph = {
  meta?: {
    mode: "local" | "overview";
    total_nodes: number;
    total_edges: number;
    matched_nodes: number;
    returned_nodes: number;
    returned_edges: number;
    limit: number;
    truncated: boolean;
  };
  nodes: {
    id: string;
    type: string;
    label: string;
    page_id: string | null;
    document_id: string | null;
    source_time: string | null;
    metadata: Record<string, unknown>;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    type: string;
    evidence: string;
    source_time: string | null;
    source_document_id: string | null;
    source_page_id: string | null;
  }[];
};

export type OperationTask = {
  id: string;
  task_type: string;
  resource_id: string;
  status: string;
  stage: string | null;
  progress: number | null;
  model_id: string | null;
  model_name: string | null;
  summary: string | null;
  error_summary: string | null;
  created_at: string;
  updated_at: string;
};
