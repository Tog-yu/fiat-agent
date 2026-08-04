"use client"

import { ToolCallDetail } from "@/lib/api"

function statusLabel(s: string): { text: string; cls: string } {
  switch (s) {
    case "success":
      return { text: "成功", cls: "status-ok" }
    case "error":
      return { text: "失败", cls: "status-err" }
    case "pending_approval":
      return { text: "等待审批", cls: "status-pending" }
    case "approval_required":
      return { text: "需要审批", cls: "status-pending" }
    default:
      return { text: s, cls: "muted" }
  }
}

function summarizeArgs(args: Record<string, any>): string {
  const keys = Object.keys(args || {})
  if (keys.length === 0) return "（无参数）"
  return keys
    .map((k) => {
      const v = args[k]
      const s = typeof v === "string" ? v : JSON.stringify(v)
      return `${k}=${s.length > 60 ? s.slice(0, 60) + "…" : s}`
    })
    .join("  ")
}

export default function ToolCallTrace({ calls }: { calls: ToolCallDetail[] }) {
  if (!calls || calls.length === 0) return null
  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>工具调用轨迹</strong>
        <span className="stat">{calls.length} 次调用</span>
      </div>
      <table className="trace-table">
        <thead>
          <tr>
            <th>工具</th>
            <th>参数摘要</th>
            <th>状态</th>
            <th>耗时</th>
            <th>风险</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((c, i) => {
            const st = statusLabel(c.status)
            return (
              <tr key={i}>
                <td><code>{c.tool_name}</code></td>
                <td style={{ maxWidth: 360 }}>
                  <span className="stat">{summarizeArgs(c.arguments)}</span>
                </td>
                <td className={st.cls}>{st.text}</td>
                <td className="stat">
                  {c.duration_ms != null ? `${c.duration_ms.toFixed(1)} ms` : "—"}
                </td>
                <td>
                  {c.risk_level ? (
                    <span className={`pill risk-${c.risk_level}`}>{c.risk_level}</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
