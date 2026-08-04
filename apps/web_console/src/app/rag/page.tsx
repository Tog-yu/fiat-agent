"use client"

import { useState } from "react"
import { queryRag, RagQueryResult } from "@/lib/api"
import Citations from "@/components/citations/Citations"

export default function RagPage() {
  const [query, setQuery] = useState("")
  const [result, setResult] = useState<RagQueryResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function onSearch() {
    const q = query.trim()
    if (!q || busy) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await queryRag(q, { top_k: 5 }))
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card">
        <strong>RAG 检索</strong>
        <div className="row" style={{ gap: 10, marginTop: 8 }}>
          <input
            placeholder="输入检索问题"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            style={{ flex: 1 }}
            onKeyDown={(e) => {
              if (e.key === "Enter") onSearch()
            }}
          />
          <button className="btn primary" onClick={onSearch} disabled={busy || !query.trim()}>
            {busy ? "检索中…" : "检索"}
          </button>
        </div>
        {error && <p className="status-err">{error}</p>}
      </div>

      <Citations result={result} />
    </div>
  )
}
