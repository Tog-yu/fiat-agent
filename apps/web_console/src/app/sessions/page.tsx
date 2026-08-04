"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { createSession, listSessions, Session } from "@/lib/api"

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([])
  const [title, setTitle] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      setSessions(await listSessions())
    } catch (e) {
      setError(String(e))
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function onCreate() {
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      const s = await createSession(title.trim() || "新会话")
      setTitle("")
      // Jump straight into the new chat.
      window.location.href = `/sessions/${s.session_id}`
    } catch (e) {
      setError(String(e))
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="card row" style={{ gap: 10 }}>
        <input
          placeholder="会话标题"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="btn primary" onClick={onCreate} disabled={busy}>
          {busy ? "创建中…" : "新建会话"}
        </button>
      </div>

      {error && <p className="status-err">{error}</p>}

      {sessions.length === 0 ? (
        <p className="muted">还没有会话。</p>
      ) : (
        sessions.map((s) => (
          <Link
            key={s.session_id}
            href={`/sessions/${s.session_id}`}
            style={{ textDecoration: "none", color: "inherit" }}
          >
            <div className="card row" style={{ justifyContent: "space-between" }}>
              <div>
                <strong>{s.title || "(无标题)"}</strong>
                <div className="row wrap" style={{ marginTop: 4 }}>
                  {s.task_type && <span className="pill">{s.task_type}</span>}
                  <span className="pill">{s.environment}</span>
                  <span className="pill">{s.status}</span>
                </div>
              </div>
              <span className="stat">{s.updated_at?.slice(0, 19)?.replace("T", " ")}</span>
            </div>
          </Link>
        ))
      )}
    </div>
  )
}
