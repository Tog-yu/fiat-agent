"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { AgentEvent, getEvents, sendMessage, ToolCallDetail } from "@/lib/api"
import ToolCallTrace from "@/components/tool-calls/ToolCallTrace"
import Link from "next/link"

function RunTrace({ events }: { events: AgentEvent[] }) {
  const graph = events.filter((e) => e.event_type !== "message")
  const toolCalls = events
    .filter((e) => e.event_type === "tool_call" && e.content?.calls)
    .flatMap((e) => (e.content?.calls as ToolCallDetail[]) || [])
  const pendingApproval = graph.find(
    (e) => e.event_type === "approval" && e.content?.approval_state === "PENDING",
  )
  if (graph.length === 0) return null
  return (
    <div className="card">
      <details open>
        <summary style={{ cursor: "pointer", fontWeight: 600 }}>运行轨迹</summary>
        <div style={{ marginTop: 8 }}>
          {pendingApproval && (
            <div className="ev approval">
              <span className="et">approval</span>
              <div>
                需要人工审批：{(pendingApproval.content?.pending || []).join(", ")}
                {pendingApproval.content?.approval_id && (
                  <>
                    {" "}
                    <Link href="/approvals">去审批 →</Link>
                  </>
                )}
              </div>
            </div>
          )}
          {graph
            .filter((e) => ["classify", "plan", "approval", "final"].includes(e.event_type))
            .map((e) => (
              <div key={e.event_id} className={`ev ${e.event_type}`}>
                <span className="et">{e.event_type}</span>
                <div className="stat">{JSON.stringify(e.content)}</div>
              </div>
            ))}
        </div>
      </details>
      <ToolCallTrace calls={toolCalls} />
    </div>
  )
}

export default function ChatPanel({ sessionId }: { sessionId: string }) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const evs = await getEvents(sessionId)
      setEvents(evs)
    } catch (e) {
      setError(String(e))
    }
  }, [sessionId])

  useEffect(() => {
    refresh()
    // Light polling so externally-decided approvals / late events show up.
    pollRef.current = setInterval(refresh, 3000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [refresh])

  const messages = events.filter((e) => e.event_type === "message")

  async function onSend() {
    const text = input.trim()
    if (!text || busy) return
    setBusy(true)
    setError(null)
    setInput("")
    try {
      await sendMessage(sessionId, text)
      await refresh()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div>
        {messages.map((m) => (
          <div key={m.event_id} className={`msg ${m.content?.role}`}>
            <div className="role">
              {m.content?.role === "user" ? "我" : "Agent"}
              {m.content?.task_type ? ` · ${m.content.task_type}` : ""}
              {m.content?.approval_state === "PENDING" ? " · 待审批" : ""}
            </div>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.content?.content || ""}</div>
          </div>
        ))}
        {messages.length === 0 && <p className="muted">还没有消息，发一条试试。</p>}
      </div>

      <RunTrace events={events} />

      {error && <p className="status-err">{error}</p>}

      <div className="card row" style={{ gap: 10 }}>
        <textarea
          rows={2}
          placeholder="输入消息，回车发送（Shift+Enter 换行）"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              onSend()
            }
          }}
        />
        <button className="btn primary" onClick={onSend} disabled={busy || !input.trim()}>
          {busy ? "运行中…" : "发送"}
        </button>
      </div>
    </div>
  )
}
