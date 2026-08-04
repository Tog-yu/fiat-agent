// Typed client for the fiat-agent backend. All endpoints are served from the
// same origin in dev (next.config.mjs rewrites /api/* -> 127.0.0.1:8000).

export interface CurrentUser {
  actor_id: string
  display_name: string
  roles: string[]
  environment: string
  scopes: string[]
}

export interface Session {
  session_id: string
  title: string
  task_type: string | null
  environment: string
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface SendMessageResponse {
  session_id: string
  final_answer: string | null
  task_type: string | null
  approval_state: string
  pending_tools: string[]
}

export interface AgentEvent {
  event_id: string
  event_type: string
  seq: number
  content: Record<string, any> | null
  created_at: string | null
}

export interface ToolCallDetail {
  tool_name: string
  arguments: Record<string, any>
  status: string
  risk_level: string | null
  duration_ms: number | null
}

export interface RagCitation {
  collection?: string
  source?: string
  chunk?: string
  score?: number
  [key: string]: any
}

export interface RagQueryResult {
  status: string
  query: string
  collection: string | null
  top_k: number
  results: Record<string, any>[]
  images: any[]
  raw_metadata: any
  error?: string
}

export interface RagCollection {
  name?: string
  collection?: string
  [key: string]: any
}

export interface Approval {
  id: string
  requester_id: string
  tool_name: string
  params_summary: Record<string, any>
  risk_level: string
  environment: string
  status: string
  dual_approval: boolean
  first_approver_id: string | null
  second_approver_id: string | null
  approver_id: string | null
  reason: string | null
  decided_at: string | null
}

async function jsonFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`请求失败 ${res.status}: ${text || res.statusText}`)
  }
  return (await res.json()) as T
}

export async function getCurrentUser(): Promise<CurrentUser> {
  return jsonFetch<CurrentUser>("/api/users/me")
}

export async function listSessions(): Promise<Session[]> {
  const r = await jsonFetch<{ sessions: Session[] }>("/api/agent/sessions")
  return r.sessions
}

export async function createSession(title: string, taskType?: string): Promise<Session> {
  return jsonFetch<Session>("/api/agent/sessions", {
    method: "POST",
    body: JSON.stringify({ title, task_type: taskType ?? null }),
  })
}

export async function getEvents(sessionId: string): Promise<AgentEvent[]> {
  const r = await jsonFetch<{ session_id: string; events: AgentEvent[] }>(
    `/api/agent/sessions/${sessionId}/events`,
  )
  return r.events
}

export async function sendMessage(
  sessionId: string,
  content: string,
): Promise<SendMessageResponse> {
  return jsonFetch<SendMessageResponse>(
    `/api/agent/sessions/${sessionId}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
  )
}

export async function queryRag(
  query: string,
  opts?: { top_k?: number; collection?: string },
): Promise<RagQueryResult> {
  return jsonFetch<RagQueryResult>("/api/rag/query", {
    method: "POST",
    body: JSON.stringify({ query, top_k: opts?.top_k ?? 5, collection: opts?.collection ?? null }),
  })
}

export async function listCollections(): Promise<{ status: string; collections: RagCollection[] }> {
  return jsonFetch("/api/rag/collections")
}

export async function listApprovals(status?: string): Promise<Approval[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ""
  return jsonFetch<Approval[]>(`/api/approvals${qs}`)
}

export async function decideApproval(
  id: string,
  action: "approve" | "reject",
  reason?: string,
): Promise<Approval> {
  return jsonFetch<Approval>(`/api/approvals/${id}/${action}`, {
    method: "POST",
    body: JSON.stringify({ reason: reason ?? null }),
  })
}

export interface AuditEvent {
  id: string
  timestamp: string
  type: string
  actor_id: string
  roles: string[]
  environment: string
  tool_name: string | null
  action: string | null
  allowed: boolean | null
  reason: string | null
  risk_level: string | null
  metadata: Record<string, any>
}

export interface AuditQuery {
  actor_id?: string
  tool_name?: string
  risk_level?: string
  type?: string
  from_ts?: string
  to_ts?: string
  limit?: number
}

export async function listAudit(q: AuditQuery = {}): Promise<AuditEvent[]> {
  const params = new URLSearchParams()
  if (q.actor_id) params.set("actor_id", q.actor_id)
  if (q.tool_name) params.set("tool_name", q.tool_name)
  if (q.risk_level) params.set("risk_level", q.risk_level)
  if (q.type) params.set("type", q.type)
  if (q.from_ts) params.set("from_ts", q.from_ts)
  if (q.to_ts) params.set("to_ts", q.to_ts)
  if (q.limit) params.set("limit", String(q.limit))
  const qs = params.toString()
  return jsonFetch<AuditEvent[]>(`/api/audit${qs ? `?${qs}` : ""}`)
}
