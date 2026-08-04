"use client"

import { useParams } from "next/navigation"
import Link from "next/link"
import ChatPanel from "@/components/chat/ChatPanel"

export default function SessionChatPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id
  if (!id) return <p className="muted">缺少会话 ID</p>
  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <Link className="btn" href="/sessions">← 返回会话列表</Link>
        <span className="stat">会话 {id}</span>
      </div>
      <ChatPanel sessionId={id} />
    </div>
  )
}
