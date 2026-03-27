"use client"

import { useState, useEffect, useRef } from "react"

const S = {
  page: { height: "100%", display: "flex", flexDirection: "column" as const, gap: "0", overflow: "hidden" },
  header: { padding: "16px 24px 12px", borderBottom: "1px solid rgba(255,255,255,0.05)" },
  title: { fontSize: "15px", fontWeight: 600, color: "#f1f5f9", marginBottom: "2px" },
  sub: { fontSize: "11px", color: "#334155" },
  inputRow: {
    padding: "12px 16px",
    display: "flex", gap: "10px", alignItems: "center",
    background: "rgba(15,23,42,0.8)", borderBottom: "1px solid rgba(255,255,255,0.05)",
  },
  input: {
    flex: 1, background: "#0d0d1a", border: "1px solid rgba(255,255,255,0.08)",
    color: "#e2e8f0", padding: "9px 14px", borderRadius: "10px", fontSize: "13px",
    outline: "none", fontFamily: "monospace",
  },
  runBtn: {
    padding: "9px 20px", borderRadius: "10px", fontSize: "13px", fontWeight: 500,
    background: "linear-gradient(135deg,#7c3aed,#4f46e5)", color: "white",
    border: "none", cursor: "pointer",
  },
  logArea: {
    flex: 1, overflow: "auto", padding: "16px 20px",
    fontFamily: "monospace", fontSize: "12px",
    background: "rgba(0,0,0,0.3)",
  },
  logLine: (msg: string) => ({
    padding: "2px 0", lineHeight: "1.6",
    color: msg.includes("ERROR") || msg.includes("error") ? "#f87171"
      : msg.includes("Job ID") ? "#34d399"
      : msg.startsWith("[") ? "#94a3b8"
      : "#94a3b8",
    borderBottom: "1px solid rgba(255,255,255,0.02)",
  }),
  statusBar: {
    padding: "8px 20px", borderTop: "1px solid rgba(255,255,255,0.05)",
    display: "flex", alignItems: "center", gap: "8px",
    background: "rgba(10,10,15,0.9)",
  },
}

export default function ConsolePage() {
  const [task, setTask] = useState("")
  const [logs, setLogs] = useState<string[]>([])
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const seenRef = useRef<Set<string>>(new Set())
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const ws = new WebSocket("wss://jarvis.silentempireai.com/api/ws/logs")
    wsRef.current = ws
    ws.onopen = () => setConnected(true)
    ws.onmessage = e => {
      if (seenRef.current.has(e.data)) return
      seenRef.current.add(e.data)
      setLogs(p => [...p.slice(-500), e.data])
    }
    ws.onerror = () => setConnected(false)
    ws.onclose = () => { setConnected(false); wsRef.current = null }
    return () => ws.close()
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [logs])

  const runTask = async () => {
    if (!task.trim()) return
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task }),
    })
    const data = await res.json()
    setLogs(p => [...p, `[${new Date().toLocaleTimeString()}] Queued — Job ID: ${data.job_id}`])
    setTask("")
  }

  return (
    <div style={S.page}>

      {/* Header */}
      <div style={S.header}>
        <div style={S.title}>Console</div>
        <div style={S.sub}>Run tasks and monitor live system output</div>
      </div>

      {/* Input */}
      <div style={S.inputRow}>
        <input
          value={task}
          onChange={e => setTask(e.target.value)}
          onKeyDown={e => { if (e.key === "Enter") runTask() }}
          placeholder="Enter task description…"
          style={S.input}
        />
        <button onClick={runTask} style={S.runBtn}>Run</button>
        <button
          onClick={() => setLogs([])}
          style={{ padding: "9px 14px", borderRadius: "10px", fontSize: "12px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", color: "#94a3b8", cursor: "pointer" }}
        >Clear</button>
      </div>

      {/* Log area */}
      <div style={S.logArea}>
        {logs.length === 0 ? (
          <div style={{ color: "#94a3b8", fontSize: "12px" }}>No output yet. Run a task or wait for live logs…</div>
        ) : (
          logs.map((l, i) => <div key={i} style={S.logLine(l)}>{l}</div>)
        )}
        <div ref={bottomRef} />
      </div>

      {/* Status bar */}
      <div style={S.statusBar}>
        <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: connected ? "#22c55e" : "#ef4444", boxShadow: connected ? "0 0 5px #22c55e" : "none" }} />
        <span style={{ fontSize: "11px", color: "#334155" }}>{connected ? "WebSocket connected" : "WebSocket disconnected"}</span>
        <span style={{ marginLeft: "auto", fontSize: "11px", color: "#475569" }}>{logs.length} lines</span>
      </div>
    </div>
  )
}
