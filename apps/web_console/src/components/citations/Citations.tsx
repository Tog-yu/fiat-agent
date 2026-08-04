"use client"

import { RagQueryResult } from "@/lib/api"

function asCitation(r: Record<string, any>): Record<string, any> {
  // The RAG server emits JSON; we surface the known citation fields with
  // graceful fallbacks when a field is absent.
  return r && typeof r === "object" ? r : { text: String(r) }
}

export default function Citations({ result }: { result: RagQueryResult | null }) {
  if (!result) return null
  if (result.status !== "ok") {
    return (
      <div className="card">
        <strong>RAG 引用</strong>
        <p className={result.status === "unavailable" ? "status-err" : "status-pending"}>
          状态：{result.status}
          {result.error ? `（${result.error}）` : ""}
        </p>
      </div>
    )
  }

  const items = (result.results || []).map(asCitation)
  if (items.length === 0) {
    return (
      <div className="card">
        <strong>RAG 引用</strong>
        <p className="muted">无结果</p>
      </div>
    )
  }

  return (
    <div className="card">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>RAG 引用</strong>
        <span className="stat">{items.length} 条</span>
      </div>
      <div style={{ display: "grid", gap: 10 }}>
        {items.map((c, i) => (
          <div key={i} className="ev" style={{ borderLeftColor: "#8250df" }}>
            <div className="row wrap" style={{ gap: 6 }}>
              {c.collection && <span className="pill">{c.collection}</span>}
              {c.source && <span className="pill">{c.source}</span>}
              {c.chunk != null && <span className="pill">chunk {c.chunk}</span>}
              {c.score != null && (
                <span className="stat">score {Number(c.score).toFixed(3)}</span>
              )}
            </div>
            {c.text && <div style={{ marginTop: 6 }}>{c.text}</div>}
          </div>
        ))}
      </div>
      {result.images && result.images.length > 0 && (
        <div className="row wrap" style={{ marginTop: 10, gap: 8 }}>
          {result.images.map((img: any, i: number) => (
            <img
              key={i}
              src={img?.url || img?.data}
              alt={img?.alt || `img-${i}`}
              style={{ maxWidth: 160, maxHeight: 160, borderRadius: 8, border: "1px solid #e1e4e8" }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
