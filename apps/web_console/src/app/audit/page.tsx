"use client"

import { useEffect, useState } from "react"
import { AuditEvent, listAudit } from "@/lib/api"

const RISKS = ["", "L1", "L2", "L3", "L4", "L5"]
const TYPES = ["", "tool_call", "policy_decision", "approval", "model_usage"]

function typeLabel(t: string): string {
  return (
    {
      tool_call: "工具调用",
      policy_decision: "策略决策",
      approval: "审批",
      model_usage: "模型用量",
      generic: "通用",
    }[t] || t
  )
}

export default function AuditPage() {
  const [filters, setFilters] = useState({
    actor_id: "",
    tool_name: "",
    risk_level: "",
    type: "",
    from_ts: "",
    to_ts: "",
  })
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<AuditEvent | null>(null)

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const q = {
        actor_id: filters.actor_id || undefined,
        tool_name: filters.tool_name || undefined,
        risk_level: filters.risk_level || undefined,
        type: filters.type || undefined,
        from_ts: filters.from_ts || undefined,
        to_ts: filters.to_ts || undefined,
        limit: 300,
      }
      setEvents(await listAudit(q))
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function set<K extends keyof typeof filters>(k: K, v: string) {
    setFilters((f) => ({ ...f, [k]: v }))
  }

  const counts = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.type] = (acc[e.type] || 0) + 1
    return acc
  }, {})

  return (
    <div>
      <div className="card">
        <strong>审计查询</strong>
        <div className="row wrap" style={{ gap: 8, marginTop: 8 }}>
          <input placeholder="用户 ID" value={filters.actor_id} onChange={(e) => set("actor_id", e.target.value)} />
          <input placeholder="工具名" value={filters.tool_name} onChange={(e) => set("tool_name", e.target.value)} />
          <select value={filters.risk_level} onChange={(e) => set("risk_level", e.target.value)}>
            {RISKS.map((r) => (
              <option key={r} value={r}>{r || "风险等级"}</option>
            ))}
          </select>
          <select value={filters.type} onChange={(e) => set("type", e.target.value)}>
            {TYPES.map((t) => (
              <option key={t} value={t}>{t ? typeLabel(t) : "事件类型"}</option>
            ))}
          </select>
          <input type="datetime-local" value={filters.from_ts} onChange={(e) => set("from_ts", e.target.value)} />
          <input type="datetime-local" value={filters.to_ts} onChange={(e) => set("to_ts", e.target.value)} />
          <button className="btn primary" onClick={load} disabled={busy}>
            {busy ? "查询中…" : "查询"}
          </button>
        </div>
        <div className="row wrap" style={{ marginTop: 8 }}>
          <span className="stat">共 {events.length} 条</span>
          {Object.entries(counts).map(([k, v]) => (
            <span key={k} className="pill">{typeLabel(k)} {v}</span>
          ))}
        </div>
        {error && <p className="status-err">{error}</p>}
      </div>

      <div className="card">
        <table className="trace-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>类型</th>
              <th>用户</th>
              <th>工具</th>
              <th>风险</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id} style={{ cursor: "pointer" }} onClick={() => setSelected(e)}>
                <td className="stat">{e.timestamp.slice(0, 19).replace("T", " ")}</td>
                <td>{typeLabel(e.type)}</td>
                <td>{e.actor_id || "—"}</td>
                <td>{e.tool_name || "—"}</td>
                <td>
                  {e.risk_level ? (
                    <span className={`pill risk-${e.risk_level}`}>{e.risk_level}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  {e.allowed === true && <span className="status-ok">允许</span>}
                  {e.allowed === false && <span className="status-err">拒绝</span>}
                  {e.allowed === null && <span className="muted">—</span>}
                </td>
              </tr>
            ))}
            {events.length === 0 && (
              <tr><td colSpan={6} className="muted">无记录</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>审计链路详情</strong>
            <button className="btn" onClick={() => setSelected(null)}>关闭</button>
          </div>
          <div className="stat" style={{ marginTop: 6 }}>
            ID：{selected.id} · {selected.environment}
          </div>
          {selected.reason && <div className="stat">原因：{selected.reason}</div>}
          <pre className="code" style={{ marginTop: 8 }}>
            {JSON.stringify(selected.metadata, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
