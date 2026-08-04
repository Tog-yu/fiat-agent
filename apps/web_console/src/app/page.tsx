"use client";

import { useEffect, useState } from "react";
import { getCurrentUser, type CurrentUser } from "../lib/api";

export default function Home() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getCurrentUser()
      .then(setUser)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24 }}>
      <h1>fiat-agent 控制台</h1>
      {error && <p style={{ color: "crimson" }}>错误：{error}</p>}
      {user && (
        <dl>
          <dt>用户</dt>
          <dd>{user.actor_id}</dd>
          <dt>角色</dt>
          <dd>{user.roles.join(", ")}</dd>
          <dt>环境</dt>
          <dd>{user.environment}</dd>
        </dl>
      )}
      {!user && !error && <p>加载中…</p>}
    </main>
  );
}
