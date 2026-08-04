"use client"

import { useEffect, useState } from "react"
import { listApprovals, Approval } from "@/lib/api"
import ApprovalCard from "@/components/approvals/ApprovalCard"

export default function ApprovalsPage() {
  const [items, setItems] = useState<Approval[]>([])
  const [onlyPending, setOnlyPending] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [onlyPending])

  async function load() {
    try {
      setItems(await listApprovals(onlyPending ? "pending" : undefined))
    } catch (e) {
      setError(String(e))
    }
  }

  const pendingCount = items.filter((i) => i.status === "pending").length

  return (
    <div>
      <div className="card row" style={{ justifyContent: "space-between" }}>
        <div>
          <strong>审批队列</strong>
          <span className="stat"> · 待审批 {pendingCount}</span>
        </div>
        <label className="row" style={{ gap: 6 }}>
          <input
            type="checkbox"
            checked={onlyPending}
            onChange={(e) => setOnlyPending(e.target.checked)}
          />
          仅看待审批
        </label>
      </div>

      {error && <p className="status-err">{error}</p>}

      {items.length === 0 ? (
        <p className="muted">队列为空。</p>
      ) : (
        items.map((a) => <ApprovalCard key={a.id} approval={a} />)
      )}
    </div>
  )
}
