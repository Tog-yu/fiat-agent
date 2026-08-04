"use client"

import { useState } from "react"
import { Approval, decideApproval } from "@/lib/api"

export default function ApprovalCard({ approval }: { approval: Approval }) {
  const [busy, setBusy] = useState(false)
  const [reason, setReason] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState(approval.status)

  async function decide(action: "approve" | "reject") {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const a = await decideApproval(approval.id, action, reason || undefined)
      setState(a.status)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const decided = state !== "pending"

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <code>{approval.tool_name}</code>
          <span className={`pill risk-${approval.risk_level}`}>{approval.risk_level}</span>
          <span className="pill">{approval.environment}</span>
          {approval.dual_approval && <span className="pill">双审批</span>}
        </div>
        <span className={`stat ${decided ? "status-ok" : "status-pending"}`}>{state}</span>
      </div>

      <div style={{ marginTop: 8 }} className="stat">
        申请人：{approval.requester_id}
      </div>

      {/* Frozen params snapshot — display only, never editable by the page. */}
      <div style={{ marginTop: 8 }}>
        <div className="stat">参数摘要（冻结，不可篡改）</div>
        <pre className="code">{JSON.stringify(approval.params_summary, null, 2)}</pre>
      </div>

      {!decided ? (
        <div style={{ marginTop: 10 }}>
          <input
            placeholder="审批意见（可选）"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            style={{ width: "100%", marginBottom: 8 }}
          />
          <div className="row" style={{ gap: 8 }}>
            <button className="btn primary" onClick={() => decide("approve")} disabled={busy}>
              通过
            </button>
            <button className="btn danger" onClick={() => decide("reject")} disabled={busy}>
              拒绝
            </button>
          </div>
        </div>
      ) : (
        <div className="stat" style={{ marginTop: 8 }}>
          已由 {approval.approver_id || "—"} {state === "approved" ? "通过" : "拒绝"}
          {approval.reason ? `（${approval.reason}）` : ""}
        </div>
      )}

      {error && <p className="status-err">{error}</p>}
    </div>
  )
}
