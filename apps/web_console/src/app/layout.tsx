import type { Metadata } from "next"
import Link from "next/link"
import "./globals.css"

export const metadata: Metadata = {
  title: "fiat-agent 控制台",
  description: "fiat-agent web console",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <nav className="topnav">
          <span className="brand">fiat-agent</span>
          <Link href="/sessions">会话</Link>
          <Link href="/rag">RAG</Link>
          <Link href="/approvals">审批</Link>
          <span className="spacer" />
          <span className="who">控制台</span>
        </nav>
        <main className="container">{children}</main>
      </body>
    </html>
  )
}
