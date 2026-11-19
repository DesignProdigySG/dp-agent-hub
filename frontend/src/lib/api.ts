import type { ApprovalOut, TaskOut, TaskTemplate, Zone } from '../types/contract'

export interface NewTask {
  title: string
  description?: string
  agent_id: string
  params?: Record<string, unknown>
  scheduled_for?: string | null
  attachment_ids?: string[]
}

export interface MarketoChange {
  id: number
  task_id: string | null
  agent_id: string
  kind: string
  label: string
  object_id: string
  name: string
  action: string
  detail: string
  url: string | null
  created_at: string
}

export interface TaskChanges {
  title?: string
  description?: string
  params?: Record<string, unknown>
  scheduled_for?: string | null
  attachment_ids?: string[]
  remove_attachment_ids?: string[]
}

export interface Attachment {
  id: string
  filename: string
  mime: string
  size: number
  chars: number
  round: number
  created_at: string
}

export const ATTACHMENT_TYPES = '.md,.markdown,.txt,.csv,.pdf,.docx'

/** Upload one file (multipart); link it by passing its id with the task, schedule or feedback. */
export async function uploadAttachment(file: File): Promise<Attachment> {
  const body = new FormData()
  body.append('file', file)
  const res = await fetch('/api/attachments', { method: 'POST', credentials: 'same-origin', body })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, typeof detail === 'string' ? detail : 'Upload failed', detail)
  }
  return res.json()
}

export interface Me {
  authenticated: boolean
  setup_required: boolean
  public_read_access: boolean
}

export type FieldKind = 'text' | 'secret' | 'number' | 'bool' | 'select' | 'url'

export interface ConfigField {
  key: string
  group: string
  label: string
  kind: FieldKind
  help: string
  options: string[]
  placeholder: string
  source: 'ui' | 'env' | 'default'
  value: string | number | boolean | null
  is_set?: boolean
  hint?: string
}

export interface ConfigResponse {
  groups: { id: string; label: string; description: string }[]
  fields: ConfigField[]
  status: {
    database: 'postgres' | 'sqlite'
    marketo_error: string
    routes: Record<string, { models: string[]; blocked: string }>
    ingestion: IngestionStatus
  }
}

export interface TestResult {
  ok: boolean
  error?: string
  detail?: string
  rest?: TestResult
  mcp?: TestResult
  results?: { ok: boolean; model: string; error?: string; reply?: string; latency_ms?: number }[]
}

export interface IngestionStatus {
  source: string
  last_poll_at: string | null
  last_count: number
  last_error: string
  sources: Record<string, { last_poll_at: string | null; total: number; last_error: string; has_cursor: boolean }>
  lake: { enabled: boolean; last_write: string; last_error: string }
}

export interface ActivitySummary {
  days: number
  total: number
  engaged_leads: number
  by_type: { type: string; count: number }[]
  top_assets: { asset: string; count: number }[]
  per_day: { date: string; count: number }[]
}

export interface RecentActivity {
  id: number
  source: string
  lead_id: number | null
  type: string
  occurred_at: string
  asset: string | null
}

export interface KpiRow {
  date: string
  scope: string
  scope_id: string
  metric: string
  value: number | null
  text: string | null
}

export interface LlmUsage {
  days: number
  total_cost_usd: number
  calls: number
  by_model: { model: string; tier: string; calls: number; input_tokens: number; output_tokens: number; cost_usd: number; failures: number }[]
  per_day: { date: string; cost_usd: number; calls: number }[]
}

export type Risk = 'read' | 'write' | 'destructive' | 'internal'
export type Autonomy = 'approve_writes' | 'approve_destructive' | 'autonomous'
export type Tier = 'fast' | 'standard' | 'strong'

export interface AgentConfig {
  id: string
  name: string
  title: string
  color: string
  character: string
  workflow?: string
  home_zone: Zone
  model_tier: Tier
  enabled: boolean
  instructions: string
  tools: string[]
  skill_ids: string[]
  knowledge_ids: string[]
  memory_enabled: boolean
  autonomy: Autonomy
  max_steps: number
  templates: TaskTemplate[]
  created_at?: string
  updated_at?: string
}

export interface ToolInfo {
  name: string
  description: string
  risk: Risk
  group: string
  zone: Zone | null
}

export interface Skill {
  id: string
  name: string
  description: string
  body: string
  updated_at: string
}

export interface KnowledgeDoc {
  id: string
  title: string
  source: string
  chars: number
  chunks?: number
  embedding_model: string
  indexed_at: string | null
  index_error: string
  updated_at: string
  content?: string
}

export interface Memory {
  id: string
  text: string
  task_id: string | null
  updated_at: string
}

export interface SearchHit {
  doc_id: string
  title: string
  content: string
  score: number
}

export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

/** Called on any 401 so the app can show the sign-in screen. */
let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    credentials: 'same-origin',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: unknown = res.statusText
    try {
      detail = (await res.json()).detail
    } catch {
      /* keep statusText */
    }
    if (res.status === 401 && !path.startsWith('/auth/')) onUnauthorized()
    const message = typeof detail === 'string' ? detail : res.status === 422 ? 'Some values are invalid' : JSON.stringify(detail)
    throw new ApiError(res.status, message, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

// Task and approval changes come back over the WebSocket too; callers needn't merge results.
export interface WorkflowLogRow {
  id: number
  thread_id: string
  item_id: string
  status: string
  action: string
  score: number | null
  tool_result: string
  summary: string
  data: Record<string, unknown>
  marketo_url: string | null
  created_at: string
}

export type HealthDimension = 'uniqueness' | 'completeness' | 'normalization' | 'accuracy' | 'contactability' | 'recency' | 'engagement'
export const HEALTH_DIMENSIONS: HealthDimension[] = ['uniqueness', 'completeness', 'normalization', 'accuracy', 'contactability', 'recency', 'engagement']

export interface HealthKpis {
  total: number
  dimensions: Record<HealthDimension | 'overall', { avg: number; buckets: number[]; ge80: number }>
  thresholds: { accuracy_gt_80: number; engagement_gt_60: number; overall_gt_70: number }
  contactability: { unreachable_email: number; invalid_phone: number; free_email_only: number; usable: number; email_and_phone: number }
  duplicates: { groups: number; records_in_groups: number; redundant: number; matched_on: Record<string, number> }
  engagement_levels: Record<'hot' | 'warm' | 'cold' | 'dormant', number>
  stale: number
  fillable: number
  issues: { code: string; dim: string; label: string; leads: number }[]
  sources: { source: string; leads: number; duplicates: number; low_accuracy: number; overall: number }[]
  cohorts: { year: number; leads: number; completeness: number; accuracy: number; overall: number }[]
  field_fill: Record<string, number>
  weights: Record<string, number>
  notes: Record<string, string>
}

export interface HealthScan {
  id: string
  task_id: string
  status: 'running' | 'done' | 'failed'
  phase: string
  counts: Record<string, unknown>
  error: string
  started_at: string
  finished_at: string | null
  overall: number | null
  total: number | null
  params: Record<string, unknown>
  kpis: HealthKpis
  report: string
}

export interface HealthIssue {
  dim: string
  code: string
  message: string
  field?: string
  fix?: unknown
}

export interface ScanLead {
  lead_id: number
  marketo_url: string | null
  lead: Record<string, string | null>
  scores: Record<HealthDimension | 'overall', number>
  engagement_level: string
  reach: string
  dup_group: string
  dup_role: string
  issues: HealthIssue[]
}

export interface DuplicateGroup {
  group: string
  members: { lead_id: number; marketo_url: string | null; role: string; lead: Record<string, string | null>; completeness: number; matched_on: string }[]
}

export type RepeatKind = 'interval' | 'daily' | 'weekly'

export interface ScheduleIn {
  agent_id: string
  title: string
  description: string
  params: Record<string, unknown>
  kind: RepeatKind
  every_minutes: number
  at_time: string
  weekdays: number[]
  tz: string
  enabled: boolean
  attachment_ids?: string[]
}

export interface Schedule extends ScheduleIn {
  attachments?: Attachment[]
  id: string
  next_run_at: string | null
  last_run_at: string | null
  last_task_id: string | null
  last_note: string
  description_text: string
  upcoming: string[]
}

export interface ScenePiece {
  piece: string
  color: string
  x: number
  y: number
  z: number
  rot: number
}

export interface SceneLayout {
  pieces: ScenePiece[] | null // null = the default decor
  version: number
  updated_at: string | null
}

export interface ReportKpi {
  key: string
  label: string
  unit: 'score' | 'pct' | 'count' | 'usd'
  better: 'up' | 'down' | null
  help: string
  value: number
  display: string
  previous: number | null
  delta: number | null
  trend: 'up' | 'down' | 'flat' | null
  good: boolean | null
  change: string
  series: { at: string; value: number }[]
}

export interface AgentReport {
  agent_id: string
  headline: { text: string; at: string; task_id: string | null } | null
  compare: string | null
  kpis: ReportKpi[]
  highlights: { text: string; good: boolean | null }[]
  activity: { days: number; tasks_done: number; tasks_failed: number; approvals: number; cost_usd: number; last_done_at: string | null; previous: { tasks_done: number; tasks_failed: number; approvals: number; cost_usd: number } }
  reports: number
  marketo: MarketoChange[]
}

export interface DesignVersion {
  id: string
  kind: 'landing_page' | 'email' | 'form'
  name: string
  version: number
  round: number
  subject: string
  preheader: string
  spec: { fields?: { fieldId: string; label: string; required?: boolean; type?: string }[]; button?: string; notes?: string }
  marketo: { form_id?: number; snippet_id?: number; email_id?: number; email_template_id?: number; landing_page_id?: number; landing_page_template_id?: number; email_version?: number; landing_page_version?: number }
  checks: { errors: string[]; warnings: string[] }
  created_at: string
}

export interface DesignGroup {
  kind: DesignVersion['kind']
  name: string
  versions: DesignVersion[] // newest first
}

export interface SceneVersion {
  id: number
  version: number
  pieces: number
  saved_at: string
  replaced_at: string
}

export interface TaskMessage {
  id: number
  task_id: string
  author_id: string // an agent's id, or "you"
  author_name: string
  kind: string // handoff | handed_on | your_turn | reply | approved | changes | rejected | feedback | note | result
  text: string
  created_at: string
}

export const api = {
  taskMessages: (id: string) => request<TaskMessage[]>('GET', `/tasks/${id}/messages`),
  postMessage: (id: string, text: string) => request<TaskMessage>('POST', `/tasks/${id}/messages`, { text }),
  scene: () => request<SceneLayout>('GET', '/scene'),
  saveScene: (pieces: ScenePiece[] | null, baseVersion: number) => request<SceneLayout>('PUT', '/scene', { pieces, base_version: baseVersion }),
  sceneHistory: () => request<SceneVersion[]>('GET', '/scene/history'),
  restoreScene: (id: number, baseVersion: number) => request<SceneLayout>('POST', `/scene/history/${id}/restore`, { base_version: baseVersion }),
  me: () => request<Me>('GET', '/auth/me'),
  login: (password: string) => request<Me>('POST', '/auth/login', { password }),
  logout: () => request<Me>('POST', '/auth/logout'),
  setup: (code: string, password: string) => request<Me>('POST', '/auth/setup', { code, password }),
  changePassword: (current: string, next: string) => request<{ ok: boolean }>('POST', '/auth/password', { current, new: next }),

  createTask: (t: NewTask) => request<TaskOut>('POST', '/tasks', t),
  runTaskNow: (id: string) => request<TaskOut>('POST', `/tasks/${id}/run`),
  updateTask: (id: string, changes: TaskChanges) => request<TaskOut>('PATCH', `/tasks/${id}`, changes),
  requeueTask: (id: string, changes: TaskChanges = {}) => request<TaskOut>('POST', `/tasks/${id}/requeue`, changes),
  archiveTask: (id: string) => request<TaskOut>('POST', `/tasks/${id}/archive`),
  unarchiveTask: (id: string) => request<TaskOut>('POST', `/tasks/${id}/unarchive`),
  deleteTask: (id: string) => request<void>('DELETE', `/tasks/${id}`),
  taskLog: (id: string) => request<WorkflowLogRow[]>('GET', `/tasks/${id}/log`),
  agentReport: (id: string) => request<AgentReport>('GET', `/agents/${id}/report`),
  taskMarketo: (id: string) => request<{ changes: MarketoChange[]; links_configured: boolean }>('GET', `/tasks/${id}/marketo`),
  taskDesigns: (id: string) => request<DesignGroup[]>('GET', `/tasks/${id}/designs`),
  design: (id: string, mode: 'preview' | 'export' = 'preview') => request<DesignVersion & { html: string }>('GET', `/designs/${id}?mode=${mode}`),
  taskFeedback: (id: string, feedback: string, attachmentIds: string[] = []) =>
    request<{ round: number; status: string }>('POST', `/tasks/${id}/feedback`, { feedback, attachment_ids: attachmentIds }),
  taskAttachments: (id: string) => request<Attachment[]>('GET', `/tasks/${id}/attachments`),
  readAttachment: (id: string) => request<Attachment & { text: string; truncated: boolean }>('GET', `/attachments/${id}`),
  deleteAttachment: (id: string) => request<void>('DELETE', `/attachments/${id}`),
  keepAttachment: (id: string, title = '') => request<{ id: string; title: string }>('POST', `/attachments/${id}/keep`, { title }),
  healthScan: (id: string) => request<HealthScan>('GET', `/data-health/scans/${id}`),
  healthScanLeads: (id: string, q: { sort: string; issue?: string; offset?: number; limit?: number }) =>
    request<{ total: number; rows: ScanLead[] }>('GET', `/data-health/scans/${id}/leads?${new URLSearchParams({ sort: q.sort, limit: String(q.limit ?? 25), offset: String(q.offset ?? 0), ...(q.issue ? { issue: q.issue } : {}) })}`),
  healthScanDuplicates: (id: string, offset = 0) =>
    request<{ total: number; groups: DuplicateGroup[] }>('GET', `/data-health/scans/${id}/duplicates?limit=20&offset=${offset}`),
  schedules: () => request<Schedule[]>('GET', '/schedules'),
  createSchedule: (body: ScheduleIn) => request<Schedule>('POST', '/schedules', body),
  updateSchedule: (id: string, body: ScheduleIn) => request<Schedule>('PUT', `/schedules/${id}`, body),
  deleteSchedule: (id: string) => request<void>('DELETE', `/schedules/${id}`),
  runSchedule: (id: string) => request<Schedule>('POST', `/schedules/${id}/run`),
  /** `selected`: approve only these (tool calls by position, a workflow's picks by ID); the rest go back with the comment. */
  decide: (id: string, approved: boolean, comment: string, edits?: Record<number, Record<string, unknown>>, choice?: string, selected?: number[]) =>
    request<ApprovalOut>('POST', `/approvals/${id}/decision`, { approved, comment, edits, choice, selected }),

  getConfig: () => request<ConfigResponse>('GET', '/config'),
  updateConfig: (changes: Record<string, unknown>) => request<ConfigResponse>('PUT', '/config', { changes }),
  testConnection: (target: 'marketo' | 'llm' | 'datastreams' | 'datalake' | 'email', model?: string) =>
    request<TestResult>('POST', `/config/test/${target}`, model ? { model } : {}),

  activities: (days: number) => request<ActivitySummary>('GET', `/insights/activities?days=${days}`),
  recentActivities: (limit = 25) => request<RecentActivity[]>('GET', `/insights/activities/recent?limit=${limit}`),
  kpis: (days: number) => request<KpiRow[]>('GET', `/insights/kpis?days=${days}`),
  llmUsage: (days: number) => request<LlmUsage>('GET', `/insights/llm?days=${days}`),
  snapshotNow: () => request<{ date: string; metrics: number }>('POST', '/insights/snapshot'),

  agentConfig: (id: string) => request<AgentConfig>('GET', `/agents/${id}/config`),
  createAgent: (a: Partial<AgentConfig>) => request<AgentConfig>('POST', '/agents', a),
  updateAgent: (id: string, changes: Partial<AgentConfig>) => request<AgentConfig>('PUT', `/agents/${id}`, changes),
  deleteAgent: (id: string) => request<void>('DELETE', `/agents/${id}`),
  tools: () => request<{ tools: ToolInfo[]; mcp_error: string }>('GET', '/tools'),

  memories: (agentId: string) => request<Memory[]>('GET', `/agents/${agentId}/memories`),
  addMemory: (agentId: string, text: string) => request<Memory>('POST', `/agents/${agentId}/memories`, { text }),
  editMemory: (agentId: string, id: string, text: string) => request<Memory>('PUT', `/agents/${agentId}/memories/${id}`, { text }),
  deleteMemory: (agentId: string, id: string) => request<void>('DELETE', `/agents/${agentId}/memories/${id}`),

  skills: () => request<Skill[]>('GET', '/skills'),
  createSkill: (s: Pick<Skill, 'name' | 'description' | 'body'>) => request<Skill>('POST', '/skills', s),
  updateSkill: (id: string, s: Pick<Skill, 'name' | 'description' | 'body'>) => request<Skill>('PUT', `/skills/${id}`, s),
  deleteSkill: (id: string) => request<void>('DELETE', `/skills/${id}`),

  knowledge: () => request<{ docs: KnowledgeDoc[]; vector_search: boolean }>('GET', '/knowledge'),
  knowledgeDoc: (id: string) => request<KnowledgeDoc>('GET', `/knowledge/${id}`),
  createDoc: (d: { title: string; source: string; content: string }) => request<KnowledgeDoc>('POST', '/knowledge', d),
  updateDoc: (id: string, d: { title: string; source: string; content: string }) => request<KnowledgeDoc>('PUT', `/knowledge/${id}`, d),
  deleteDoc: (id: string) => request<void>('DELETE', `/knowledge/${id}`),
  reindex: () => request<{ reindexed: number }>('POST', '/knowledge/reindex'),
  searchKnowledge: (query: string, k = 5) => request<{ mode: string; results: SearchHit[] }>('POST', '/knowledge/search', { query, k }),
}
