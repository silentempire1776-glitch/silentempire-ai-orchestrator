"use client"

import { useEffect, useRef, useState, useCallback } from "react"

type Role = "user" | "jarvis" | "error"
type Mode = "jarvis" | "sys" | "chain"

type Message = {
  id: string
  role: Role
  content: string
  timestamp: string
  mode?: Mode
  thinking?: boolean
}

type Session = {
  id: string
  name: string
  message_count: number
  created_at: string
  updated_at: string
}

const SYS_PREFIXES = ["run:", "read:", "write:", "list:", "logs:", "restart:", "exec:", "ps"]
const QUICK_PROMPTS = [
  { label: "System status", text: 'run: docker ps --format "{{.Names}} {{.Status}}"' },
  { label: "Orchestrator logs", text: "logs: jarvis-orchestrator" },
  { label: "Disk usage", text: "run: df -h /srv/silentempire" },
  { label: "What can you do?", text: "What can you help me with?" },
]

function uid() { return Math.random().toString(36).slice(2, 10) }
function detectMode(text: string): Mode {
  const t = text.trim().toLowerCase()
  for (const p of SYS_PREFIXES) { if (t.startsWith(p)) return "sys" }
  return "jarvis"
}

function extractReply(events: any[], mode: Mode): string {
  if (!events?.length) return ""
  const target = mode === "sys" ? "systems" : "jarvis"
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i]
    const agent = (e.agent || "").toLowerCase()
    if (agent && agent !== target) continue
    const out = e.output
    if (typeof out === "string" && out.trim() && out.trim() !== "step_started" && !out.startsWith("# CEO Summary")) {
      try {
        const p = JSON.parse(out.trim())
        if (p?.synthesis) return p.synthesis
        if (p?.stdout) return "```\n" + p.stdout.trim() + "\n```"
        if (p?.content) return p.content
        if (p?.text) return p.text
        if (p?.data?.synthesis) return p.data.synthesis
        if (p?.data?.stdout) return "```\n" + p.data.stdout.trim() + "\n```"
      } catch { return out.trim() }
    }
    const raw = e.data
    if (raw) {
      try {
        const d = typeof raw === "string" ? JSON.parse(raw) : raw
        const r = d?.meta?.results_by_agent?.[target]
        if (r) return r
      } catch {}
    }
  }
  return ""
}

function MD({ text }: { text: string }) {
  const lines = text.split("\n")
  const nodes: React.ReactNode[] = []
  let inCode = false, codeLines: string[] = [], key = 0
  for (const line of lines) {
    if (line.startsWith("```")) {
      if (inCode) { nodes.push(<div key={key++} style={{ background: "rgba(0,0,0,0.45)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "8px", padding: "12px 16px", margin: "8px 0", fontFamily: "monospace", fontSize: "12px", color: "#86efac", overflowX: "auto", whiteSpace: "pre" }}>{codeLines.join("\n")}</div>); codeLines = []; inCode = false }
      else { inCode = true }
      continue
    }
    if (inCode) { codeLines.push(line); continue }
    if (line.startsWith("### ")) nodes.push(<div key={key++} style={{ fontSize: "12px", fontWeight: 600, color: "#a78bfa", marginTop: "12px", marginBottom: "3px" }}>{line.slice(4)}</div>)
    else if (line.startsWith("## ")) nodes.push(<div key={key++} style={{ fontSize: "13px", fontWeight: 600, color: "#7dd3fc", marginTop: "14px", marginBottom: "4px" }}>{line.slice(3)}</div>)
    else if (line.startsWith("# ")) nodes.push(<div key={key++} style={{ fontSize: "14px", fontWeight: 700, color: "#f1f5f9", marginTop: "16px", marginBottom: "5px" }}>{line.slice(2)}</div>)
    else if (line.match(/^[-•*] /)) nodes.push(<div key={key++} style={{ display: "flex", gap: "8px", fontSize: "13px", color: "#cbd5e1", lineHeight: "1.6", margin: "2px 0" }}><span style={{ color: "#7c3aed", flexShrink: 0 }}>·</span><span dangerouslySetInnerHTML={{ __html: bf(ic(line.slice(2))) }} /></div>)
    else if (line.trim() === "") nodes.push(<div key={key++} style={{ height: "5px" }} />)
    else nodes.push(<div key={key++} style={{ fontSize: "13px", color: "#cbd5e1", lineHeight: "1.65", margin: "1px 0" }} dangerouslySetInnerHTML={{ __html: bf(ic(line)) }} />)
  }
  if (inCode && codeLines.length) nodes.push(<div key={key++} style={{ background: "rgba(0,0,0,0.45)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "8px", padding: "12px 16px", margin: "8px 0", fontFamily: "monospace", fontSize: "12px", color: "#86efac", overflowX: "auto", whiteSpace: "pre" }}>{codeLines.join("\n")}</div>)
  return <div>{nodes}</div>
}
function bf(t: string) { return t.replace(/\*\*(.*?)\*\*/g, '<strong style="color:#f1f5f9;font-weight:600">$1</strong>') }
function ic(t: string) { return t.replace(/`([^`]+)`/g, '<code style="background:rgba(124,58,237,0.15);color:#a78bfa;padding:1px 5px;border-radius:4px;font-size:11px;font-family:monospace">$1</code>') }

function Thinking() {
  return (
    <div style={{ display: "flex", gap: "5px", alignItems: "center", padding: "4px 0" }}>
      {[0,1,2].map(i => <div key={i} style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#7c3aed", animation: "throb 1.4s ease-in-out infinite", animationDelay: `${i*0.2}s` }} />)}
      <style>{`@keyframes throb{0%,100%{transform:scale(1);opacity:0.4}50%{transform:scale(1.4);opacity:1}}`}</style>
    </div>
  )
}

export default function ChatPage() {
  const [mounted, setMounted]           = useState(false)
  const [messages, setMessages]         = useState<Message[]>([])
  const [input, setInput]               = useState("")
  const [loading, setLoading]           = useState(false)
  const [sessions, setSessions]         = useState<Session[]>([])
  const [activeId, setActiveId]         = useState<string>("")
  const [showSessions, setShowSessions] = useState(false)
  const [editingId, setEditingId]       = useState<string | null>(null)
  const [editName, setEditName]         = useState("")
  const [syncing, setSyncing]           = useState(false)
  const bottomRef   = useRef<HTMLDivElement>(null)
  const pollRef     = useRef<NodeJS.Timeout | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    setMounted(true)
    loadSessions()
  }, [])

  const loadSessions = async () => {
    try {
      const r = await fetch("/api/sessions")
      const data = await r.json()
      setSessions(data)
      const savedId = localStorage.getItem("jarvis_active_session")
      if (data.length === 0) {
        await createNewSession()
      } else {
        const target = data.find((s: Session) => s.id === savedId) || data[0]
        await switchToSession(target.id)
      }
    } catch {
      await createNewSession()
    }
  }

  const createNewSession = async (name?: string) => {
    try {
      const r = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name || `Chat ${new Date().toLocaleDateString()}` }),
      })
      const s = await r.json()
      setSessions(prev => [s, ...prev])
      setActiveId(s.id)
      setMessages([])
      localStorage.setItem("jarvis_active_session", s.id)
      setShowSessions(false)
      return s
    } catch { return null }
  }

  const switchToSession = async (id: string) => {
    try {
      const r = await fetch(`/api/sessions/${id}`)
      const s = await r.json()
      setActiveId(id)
      setMessages((s.messages || []).map((m: any) => ({ ...m, timestamp: m.timestamp || new Date().toISOString() })))
      localStorage.setItem("jarvis_active_session", id)
      setShowSessions(false)
      if (pollRef.current) clearInterval(pollRef.current)
      setLoading(false)
    } catch {}
  }

  const saveMessages = useCallback((msgs: Message[], sessionId: string) => {
    if (!sessionId) return
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    saveTimerRef.current = setTimeout(async () => {
      try {
        setSyncing(true)
        await fetch(`/api/sessions/${sessionId}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: msgs.filter(m => !m.thinking) }),
        })
        const r = await fetch("/api/sessions")
        setSessions(await r.json())
      } catch {}
      finally { setSyncing(false) }
    }, 1500)
  }, [])

  useEffect(() => {
    if (!mounted || !activeId) return
    saveMessages(messages, activeId)
  }, [messages, activeId, mounted])

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }) }, [messages])

  const clearSession = async () => {
    if (pollRef.current) clearInterval(pollRef.current)
    setLoading(false)
    setMessages([])
    if (activeId) {
      await fetch(`/api/sessions/${activeId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: [] }),
      })
    }
  }

  const deleteSession = async (id: string) => {
    await fetch(`/api/sessions/${id}`, { method: "DELETE" })
    const remaining = sessions.filter(s => s.id !== id)
    if (remaining.length === 0) {
      await createNewSession()
    } else {
      setSessions(remaining)
      if (id === activeId) await switchToSession(remaining[0].id)
    }
  }

  const renameSession = async (id: string, name: string) => {
    await fetch(`/api/sessions/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    })
    setSessions(prev => prev.map(s => s.id === id ? { ...s, name } : s))
    setEditingId(null)
  }

  const poll = (chainId: string, thinkingId: string, mode: Mode) => {
    let n = 0
    pollRef.current = setInterval(async () => {
      n++
      try {
        const r = await fetch(`/api/chains/${chainId}`)
        if (!r.ok) return
        const d = await r.json()
        const reply = extractReply(d.events || [], mode)
        if (reply) {
          clearInterval(pollRef.current!)
          setMessages(p => p.map(m => m.id === thinkingId ? { ...m, thinking: false, content: reply, role: "jarvis" } : m))
          setLoading(false)
        } else if (n >= 90) {
          clearInterval(pollRef.current!)
          setMessages(p => p.map(m => m.id === thinkingId ? { ...m, thinking: false, content: "No response. Please try again.", role: "error" } : m))
          setLoading(false)
        }
      } catch {}
    }, 2000)
  }

  const send = useCallback(async (overrideText?: string) => {
    const text = (overrideText ?? input).trim()
    if (!text || loading) return
    const mode = detectMode(text)
    const thinkId = uid()
    const now = new Date().toISOString()
    setMessages(p => [
      ...p,
      { id: uid(), role: "user", content: text, timestamp: now, mode },
      { id: thinkId, role: "jarvis", content: "", timestamp: now, thinking: true, mode },
    ])
    setInput("")
    setLoading(true)
    if (textareaRef.current) textareaRef.current.style.height = "24px"
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, mode }),
      })
      const d = await r.json()
      poll(d.chain_id, thinkId, mode)
    } catch {
      setMessages(p => p.map(m => m.id === thinkId ? { ...m, thinking: false, content: "Connection error.", role: "error" } : m))
      setLoading(false)
    }
  }, [input, loading])

  const activeSession = sessions.find(s => s.id === activeId)
  if (!mounted) return null

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#0a0a0f" }}>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "8px 16px", borderBottom: "1px solid rgba(255,255,255,0.05)", background: "rgba(13,13,22,0.95)", gap: "10px", flexShrink: 0 }}>
        <div style={{ position: "relative", flex: 1, minWidth: 0 }}>
          <button onClick={() => setShowSessions(!showSessions)} style={{ display: "flex", alignItems: "center", gap: "8px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "8px", padding: "6px 12px", cursor: "pointer", color: "#cbd5e1", fontSize: "13px", maxWidth: "260px" }}>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{activeSession?.name || "New Chat"}</span>
            <span style={{ color: "#475569", fontSize: "10px", flexShrink: 0 }}>▾</span>
          </button>

          {showSessions && (
            <div style={{ position: "absolute", top: "calc(100% + 6px)", left: 0, width: "300px", background: "#0d0d1a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "12px", zIndex: 100, overflow: "hidden", boxShadow: "0 8px 32px rgba(0,0,0,0.6)" }}>
              <div style={{ padding: "10px 12px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
                <button onClick={() => createNewSession()} style={{ width: "100%", padding: "8px 12px", borderRadius: "8px", background: "rgba(124,58,237,0.15)", border: "1px solid rgba(124,58,237,0.25)", color: "#a78bfa", fontSize: "12px", cursor: "pointer", fontWeight: 500 }}>+ New Chat</button>
              </div>
              <div style={{ maxHeight: "300px", overflowY: "auto" }}>
                {sessions.map(s => (
                  <div key={s.id} style={{ display: "flex", alignItems: "center", gap: "6px", padding: "8px 12px", background: s.id === activeId ? "rgba(124,58,237,0.1)" : "transparent", borderLeft: s.id === activeId ? "2px solid #7c3aed" : "2px solid transparent", cursor: "pointer" }}>
                    {editingId === s.id ? (
                      <input value={editName} onChange={e => setEditName(e.target.value)} onBlur={() => renameSession(s.id, editName || s.name)} onKeyDown={e => { if (e.key === "Enter") renameSession(s.id, editName || s.name) }} autoFocus style={{ flex: 1, background: "rgba(255,255,255,0.08)", border: "1px solid rgba(124,58,237,0.3)", borderRadius: "4px", color: "#e2e8f0", fontSize: "12px", padding: "3px 6px", outline: "none" }} />
                    ) : (
                      <div onClick={() => switchToSession(s.id)} style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "12px", color: s.id === activeId ? "#e2e8f0" : "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</div>
                        <div style={{ fontSize: "10px", color: "#334155", marginTop: "1px" }}>{s.message_count} messages · {new Date(s.updated_at).toLocaleDateString()}</div>
                      </div>
                    )}
                    <button onClick={() => { setEditingId(s.id); setEditName(s.name) }} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "13px", padding: "2px 5px" }} title="Rename">✎</button>
                    <button onClick={() => deleteSession(s.id)} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "13px", padding: "2px 5px" }} title="Delete">✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
          {syncing && <span style={{ fontSize: "10px", color: "#334155" }}>syncing…</span>}
          <span style={{ fontSize: "9px", border: "1px solid rgba(34,197,94,0.3)", color: "#22c55e", padding: "2px 6px", borderRadius: "10px" }}>☁ cloud</span>
          <button onClick={clearSession} style={{ fontSize: "12px", color: "#94a3b8", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "6px", padding: "5px 12px", cursor: "pointer", fontWeight: 500 }}>Clear</button>
          <button onClick={() => createNewSession()} style={{ fontSize: "12px", color: "#a78bfa", background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", borderRadius: "6px", padding: "5px 12px", cursor: "pointer", fontWeight: 500 }}>+ New</button>
        </div>
      </div>

      {showSessions && <div onClick={() => setShowSessions(false)} style={{ position: "fixed", inset: 0, zIndex: 99 }} />}

      <div style={{ flex: 1, overflowY: "auto", padding: "24px 0 16px" }}>
        <div style={{ maxWidth: "720px", margin: "0 auto", padding: "0 16px", display: "flex", flexDirection: "column", gap: "22px" }}>

          {messages.length === 0 && (
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "20px", paddingTop: "60px", textAlign: "center" }}>
              <div style={{ width: "52px", height: "52px", borderRadius: "16px", background: "linear-gradient(135deg,rgba(124,58,237,0.2),rgba(79,70,229,0.2))", border: "1px solid rgba(124,58,237,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "22px" }}>✦</div>
              <div>
                <div style={{ fontSize: "17px", fontWeight: 600, color: "#f1f5f9", marginBottom: "8px" }}>How can Jarvis help?</div>
                <div style={{ fontSize: "13px", color: "#475569", lineHeight: "1.6", maxWidth: "360px" }}>
                  Ask anything, or use{" "}
                  <code style={{ background: "rgba(124,58,237,0.15)", color: "#a78bfa", padding: "1px 5px", borderRadius: "4px", fontSize: "11px" }}>run:</code>{" "}
                  <code style={{ background: "rgba(124,58,237,0.15)", color: "#a78bfa", padding: "1px 5px", borderRadius: "4px", fontSize: "11px" }}>logs:</code>{" "}
                  for system commands.
                </div>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center" }}>
                {QUICK_PROMPTS.map(p => (
                  <button key={p.label} onClick={() => send(p.text)} style={{ background: "rgba(15,23,42,0.8)", border: "1px solid rgba(255,255,255,0.08)", color: "#94a3b8", fontSize: "12px", padding: "8px 14px", borderRadius: "20px", cursor: "pointer" }}>{p.label}</button>
                ))}
              </div>
            </div>
          )}

          {messages.map(msg => (
            <div key={msg.id}>
              {msg.role === "user" ? (
                <div style={{ display: "flex", justifyContent: "flex-end" }}>
                  <div style={{ maxWidth: "72%", background: "rgba(124,58,237,0.15)", border: "1px solid rgba(124,58,237,0.25)", borderRadius: "18px 18px 4px 18px", padding: "11px 16px", fontSize: "13px", color: "#e2e8f0", lineHeight: "1.6", whiteSpace: "pre-wrap" }}>{msg.content}</div>
                </div>
              ) : (
                <div style={{ display: "flex", gap: "12px", alignItems: "flex-start" }}>
                  <div style={{ width: "30px", height: "30px", minWidth: "30px", borderRadius: "10px", background: msg.role === "error" ? "rgba(239,68,68,0.15)" : "linear-gradient(135deg,rgba(124,58,237,0.3),rgba(79,70,229,0.3))", border: msg.role === "error" ? "1px solid rgba(239,68,68,0.3)" : "1px solid rgba(124,58,237,0.3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "12px", color: msg.role === "error" ? "#f87171" : "#a78bfa", marginTop: "2px" }}>
                    {msg.role === "error" ? "!" : "✦"}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "5px" }}>
                      <span style={{ fontSize: "12px", fontWeight: 600, color: msg.role === "error" ? "#f87171" : "#a78bfa" }}>{msg.role === "error" ? "Error" : msg.mode === "sys" ? "Systems" : "Jarvis"}</span>
                      {msg.mode === "sys" && msg.role !== "error" && <span style={{ fontSize: "9px", background: "rgba(234,179,8,0.1)", color: "#fbbf24", border: "1px solid rgba(234,179,8,0.2)", padding: "1px 6px", borderRadius: "10px" }}>⚡ EXEC</span>}
                      <span style={{ fontSize: "10px", color: "#334155" }}>{new Date(msg.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                    </div>
                    {msg.thinking ? <Thinking /> : msg.role === "error" ? <div style={{ fontSize: "13px", color: "#f87171" }}>{msg.content}</div> : <MD text={msg.content} />}
                  </div>
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      <div style={{ padding: "10px 16px 18px", background: "#0a0a0f", flexShrink: 0 }}>
        <div style={{ maxWidth: "720px", margin: "0 auto" }}>
          <div style={{ background: "#1a1a2a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "16px", padding: "10px 12px", display: "flex", alignItems: "flex-end", gap: "10px" }}>
            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
              onInput={e => { const t = e.target as HTMLTextAreaElement; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px" }}
              disabled={loading}
              placeholder="Message Jarvis…"
              rows={1}
              style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: "#e2e8f0", fontSize: "14px", lineHeight: "1.5", resize: "none", minHeight: "22px", maxHeight: "160px", fontFamily: "inherit", opacity: loading ? 0.5 : 1 }}
            />
            <button onClick={() => send()} disabled={loading || !input.trim()} style={{ width: "34px", height: "34px", minWidth: "34px", borderRadius: "10px", background: loading || !input.trim() ? "rgba(255,255,255,0.06)" : "linear-gradient(135deg,#7c3aed,#4f46e5)", border: "none", cursor: loading || !input.trim() ? "not-allowed" : "pointer", display: "flex", alignItems: "center", justifyContent: "center" }}>
              {loading ? <div style={{ width: "14px", height: "14px", borderRadius: "50%", border: "2px solid rgba(255,255,255,0.2)", borderTopColor: "white", animation: "spin 0.7s linear infinite" }} /> : <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2" fill="white"/></svg>}
            </button>
          </div>
          <div style={{ textAlign: "center", fontSize: "11px", color: "#1e293b", marginTop: "6px" }}>
            Enter to send · Shift+Enter for new line · <span style={{ color: "#334155" }}>Sessions sync across all devices</span>
          </div>
        </div>
      </div>

      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}
