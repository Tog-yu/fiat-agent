"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import { getCurrentUser, CurrentUser } from "@/lib/api"

export default function HomePage() {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch((e) => setError(String(e)))
  }, [])

  return (
    <div>
      <div className="card">
        <h2 style={{ marginTop: 0 }}>欢迎使用 fiat-agent 控制台</h2>
        {error && <p className="status-err">无法加载用户信息：{error}</p>}
        {user && (
          <div className="row wrap">
            <span className="pill">{user.display_name}</span>
            <span className="pill">{user.environment}</span>
            {user.roles.map((r) => (
              <span key={r} className="pill">{r}</span>
            ))}
          </div>
        )}
      </div>
      <div className="row wrap">
        <Link className="btn primary" href="/sessions">进入会话</Link>
        <Link className="btn" href="/rag">RAG 检索</Link>
        <Link className="btn" href="/approvals">审批队列</Link>
      </div>
    </div>
  )
}
