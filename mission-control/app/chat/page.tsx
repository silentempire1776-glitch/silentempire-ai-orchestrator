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
  liked?: boolean | null  // true=liked, false=disliked, null=neutral
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

// ── MARKDOWN ──
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
    </div>
  )
}

// ── ICON BUTTONS ──
function IconBtn({ title, onClick, children, active }: { title: string; onClick: () => void; children: React.ReactNode; active?: boolean }) {
  return (
    <button onClick={onClick} title={title} style={{
      background: active ? "rgba(124,58,237,0.2)" : "rgba(255,255,255,0.04)",
      border: active ? "1px solid rgba(124,58,237,0.35)" : "1px solid rgba(255,255,255,0.08)",
      cursor: "pointer", padding: "4px 8px", borderRadius: "6px",
      color: active ? "#a78bfa" : "rgb(156,172,194)", fontSize: "13px",
      display: "flex", alignItems: "center", transition: "all 0.15s",
      opacity: 1,
    }}
      onMouseEnter={e => {
        const el = e.currentTarget as HTMLElement
        el.style.color = "#ffffff"
        el.style.background = active ? "rgba(124,58,237,0.3)" : "rgba(255,255,255,0.10)"
        el.style.borderColor = active ? "rgba(124,58,237,0.5)" : "rgba(255,255,255,0.18)"
      }}
      onMouseLeave={e => {
        const el = e.currentTarget as HTMLElement
        el.style.color = active ? "#a78bfa" : "rgb(156,172,194)"
        el.style.background = active ? "rgba(124,58,237,0.2)" : "rgba(255,255,255,0.04)"
        el.style.borderColor = active ? "rgba(124,58,237,0.35)" : "rgba(255,255,255,0.08)"
      }}
    >{children}</button>
  )
}

export default function ChatPage() {
  const [mounted, setMounted]             = useState(false)
  const [messages, setMessages]           = useState<Message[]>([])
  const [input, setInput]                 = useState("")
  const [loading, setLoading]             = useState(false)
  const [sessions, setSessions]           = useState<Session[]>([])
  const [activeId, setActiveId]           = useState<string>("")
  const [showSessions, setShowSessions]   = useState(false)
  const [editingId, setEditingId]         = useState<string | null>(null)
  const [editName, setEditName]           = useState("")
  const [syncing, setSyncing]             = useState(false)
  const [editMsgId, setEditMsgId]         = useState<string | null>(null)
  const [editMsgText, setEditMsgText]     = useState("")
  const [copiedId, setCopiedId]           = useState<string | null>(null)
  const [attachedFile, setAttachedFile]   = useState<File | null>(null)
  const [attachPreview, setAttachPreview] = useState<string>("")
  const [attachedImage, setAttachedImage] = useState<{url:string;b64:string;name:string;type:string}|null>(null)
  const [retryingId, setRetryingId]       = useState<string | null>(null)
  const bottomRef    = useRef<HTMLDivElement>(null)
  const pollRef      = useRef<NodeJS.Timeout | null>(null)
  const textareaRef  = useRef<HTMLTextAreaElement>(null)
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

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
      if (data.length === 0) { await createNewSession() }
      else {
        const target = data.find((s: Session) => s.id === savedId) || data[0]
        await switchToSession(target.id)
      }
    } catch { await createNewSession() }
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
      setActiveId(s.id); setMessages([])
      localStorage.setItem("jarvis_active_session", s.id)
      setShowSessions(false); return s
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
    setLoading(false); setMessages([])
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
    if (remaining.length === 0) { await createNewSession() }
    else { setSessions(remaining); if (id === activeId) await switchToSession(remaining[0].id) }
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

  // ── EXPORT ──
  const exportChat = () => {
    const lines = messages
      .filter(m => !m.thinking)
      .map(m => {
        const who = m.role === "user" ? "USER" : m.mode === "sys" ? "SYSTEMS" : "JARVIS"
        const time = new Date(m.timestamp).toLocaleString()
        return `[${time}] ${who}:\n${m.content}\n`
      })
      .join("\n---\n\n")

    const sessionName = sessions.find(s => s.id === activeId)?.name || "chat"
    const blob = new Blob([lines], { type: "text/plain" })
    const url = URL.createObjectURL(blob)
    const a = document.createElement("a")
    a.href = url
    a.download = `${sessionName.replace(/[^a-z0-9]/gi, "_")}_${new Date().toISOString().slice(0,10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── COPY ──
  const copyMessage = async (id: string, content: string) => {
    await navigator.clipboard.writeText(content)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  // ── LIKE / DISLIKE ──
  const toggleLike = (id: string, val: boolean) => {
    setMessages(p => p.map(m => m.id === id ? { ...m, liked: m.liked === val ? null : val } : m))
  }

  // ── EDIT USER MESSAGE ──
  const startEditMsg = (id: string, content: string) => {
    setEditMsgId(id)
    setEditMsgText(content)
  }

  const submitEditMsg = async () => {
    if (!editMsgId || !editMsgText.trim()) return
    const text = editMsgText.trim()
    const mode = detectMode(text)

    // Replace the message and remove everything after it
    setMessages(p => {
      const idx = p.findIndex(m => m.id === editMsgId)
      if (idx < 0) return p
      return p.slice(0, idx)
    })

    setEditMsgId(null)
    setEditMsgText("")
    await send(text)
  }

  // ── RETRY ──
  const retryMessage = async (msgId: string) => {
    // Find the user message before this Jarvis message
    const idx = messages.findIndex(m => m.id === msgId)
    if (idx < 0) return
    let userMsg: Message | null = null
    for (let i = idx - 1; i >= 0; i--) {
      if (messages[i].role === "user") { userMsg = messages[i]; break }
    }
    if (!userMsg) return

    setRetryingId(msgId)
    // Remove the old Jarvis response
    setMessages(p => p.filter(m => m.id !== msgId))
    await send(userMsg.content)
    setRetryingId(null)
  }

  // ── FILE ATTACH ──
  const handleImageAttach = async (file: File) => {
    const url = URL.createObjectURL(file)
    const b64 = await new Promise<string>((res) => {
      const reader = new FileReader()
      reader.onload = () => res((reader.result as string).split(",")[1])
      reader.readAsDataURL(file)
    })
    setAttachedImage({ url, b64, name: file.name, type: file.type })
  }

  const handleFileAttach = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setAttachedFile(file)
    const reader = new FileReader()
    reader.onload = ev => setAttachPreview(ev.target?.result as string || "")
    if (file.type.startsWith("text/") || file.name.endsWith(".py") || file.name.endsWith(".ts") || file.name.endsWith(".json") || file.name.endsWith(".md")) {
      reader.readAsText(file)
    } else {
      setAttachPreview(`[Binary file: ${file.name}]`)
    }
  }

  // ── POLL ──
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

  // ── SEND ──
  const send = useCallback(async (overrideText?: string) => {
    let text = (overrideText ?? input).trim()
    if (!text || loading) return

    // Prepend file content if attached
    if (attachedFile && attachPreview) {
      text = `File: ${attachedFile.name}\n\`\`\`\n${attachPreview.slice(0, 3000)}\n\`\`\`\n\n${text}`
      setAttachedFile(null)
      setAttachPreview("")
    }

    const mode = detectMode(text)
    const thinkId = uid()
    const now = new Date().toISOString()
    setMessages(p => [
      ...p,
      { id: uid(), role: "user", content: overrideText ?? input, timestamp: now, mode },
      { id: thinkId, role: "jarvis", content: "", timestamp: now, thinking: true, mode },
    ])
    setInput("")
    setLoading(true)
    if (textareaRef.current) textareaRef.current.style.height = "24px"
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          mode,
          ...(attachedImage ? { image_b64: attachedImage.b64, image_type: attachedImage.type, image_name: attachedImage.name } : {})
        }),
      })
      const d = await r.json()
      poll(d.chain_id, thinkId, mode)
    } catch {
      setMessages(p => p.map(m => m.id === thinkId ? { ...m, thinking: false, content: "Connection error.", role: "error" } : m))
      setLoading(false)
    }
  }, [input, loading, attachedFile, attachPreview])

  const activeSession = sessions.find(s => s.id === activeId)
  if (!mounted) return null

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#0a0a0f" }}>
      <style>{`
        @keyframes throb{0%,100%{transform:scale(1);opacity:0.4}50%{transform:scale(1.4);opacity:1}}
        @keyframes spin{to{transform:rotate(360deg)}}
        .msg-actions{opacity:0;transition:opacity 0.15s}
        .msg-wrap:hover .msg-actions{opacity:1}
      `}</style>

      {/* ── HEADER ── */}
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
                    <button onClick={() => { setEditingId(s.id); setEditName(s.name) }} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "13px", padding: "2px 5px" }}>✎</button>
                    <button onClick={() => deleteSession(s.id)} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "13px", padding: "2px 5px" }}>✕</button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "6px", flexShrink: 0 }}>
          {syncing && <span style={{ fontSize: "10px", color: "#334155" }}>syncing…</span>}
          <button onClick={exportChat} title="Export conversation" style={{ fontSize: "11px", color: "#64748b", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: "6px", padding: "5px 10px", cursor: "pointer" }}>↓ Export</button>
          <button onClick={clearSession} style={{ fontSize: "12px", color: "#94a3b8", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "6px", padding: "5px 12px", cursor: "pointer", fontWeight: 500 }}>Clear</button>
          <button onClick={() => createNewSession()} style={{ fontSize: "12px", color: "#a78bfa", background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", borderRadius: "6px", padding: "5px 12px", cursor: "pointer", fontWeight: 500 }}>+ New</button>
        </div>
      </div>

      {showSessions && <div onClick={() => setShowSessions(false)} style={{ position: "fixed", inset: 0, zIndex: 99 }} />}

      {/* ── MESSAGES ── */}
      <div
        onDrop={e => { e.preventDefault(); const f=e.dataTransfer.files[0]; if(f) { if(f.type.startsWith("image/")) handleImageAttach(f); else { const re2 = new FileReader(); re2.onload = ev => { setAttachedFile(f); setAttachPreview(ev.target?.result as string || "") }; re2.readAsText(f) } } }}
        onDragOver={e => e.preventDefault()}
        style={{ flex: 1, overflowY: "auto", padding: "24px 0 16px" }}>
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

          {messages.map((msg, msgIdx) => (
            <div key={msg.id} className="msg-wrap">
              {msg.role === "user" ? (
                <div style={{ display: "flex", justifyContent: "flex-end", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                  {/* Edit mode */}
                  {editMsgId === msg.id ? (
                    <div style={{ width: "72%", display: "flex", flexDirection: "column", gap: "6px" }}>
                      <textarea
                        value={editMsgText}
                        onChange={e => setEditMsgText(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitEditMsg() } if (e.key === "Escape") setEditMsgId(null) }}
                        autoFocus
                        style={{ background: "rgba(124,58,237,0.12)", border: "1px solid rgba(124,58,237,0.4)", borderRadius: "12px", padding: "10px 14px", color: "#e2e8f0", fontSize: "13px", lineHeight: "1.6", outline: "none", resize: "none", minHeight: "60px", fontFamily: "inherit" }}
                      />
                      <div style={{ display: "flex", gap: "6px", justifyContent: "flex-end" }}>
                        <button onClick={() => setEditMsgId(null)} style={{ fontSize: "11px", padding: "4px 10px", borderRadius: "6px", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "#64748b", cursor: "pointer" }}>Cancel</button>
                        <button onClick={submitEditMsg} style={{ fontSize: "11px", padding: "4px 10px", borderRadius: "6px", background: "rgba(124,58,237,0.2)", border: "1px solid rgba(124,58,237,0.35)", color: "#a78bfa", cursor: "pointer" }}>Send Edit</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div style={{ maxWidth: "72%", background: "rgba(124,58,237,0.15)", border: "1px solid rgba(124,58,237,0.25)", borderRadius: "18px 18px 4px 16px", padding: "11px 16px", fontSize: "13px", color: "#e2e8f0", lineHeight: "1.6" }}>
                    {(msg as any).imageUrl && <img src={(msg as any).imageUrl} alt="attachment" style={{ maxWidth: "220px", borderRadius: "8px", marginBottom: "6px", display: "block" }} />}
                    {msg.content}
                  </div>
                      <div className="msg-actions" style={{ display: "flex", gap: "2px" }}>
                        <IconBtn title="Edit message" onClick={() => startEditMsg(msg.id, msg.content)}>✎</IconBtn>
                        <IconBtn title="Copy" onClick={() => copyMessage(msg.id, msg.content)}>{copiedId === msg.id ? "✓" : "⎘"}</IconBtn>
                      </div>
                    </>
                  )}
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

                    {/* Action row for Jarvis messages */}
                    {!msg.thinking && msg.role === "jarvis" && (
                      <div className="msg-actions" style={{ display: "flex", gap: "2px", marginTop: "6px" }}>
                        <IconBtn title="Copy" onClick={() => copyMessage(msg.id, msg.content)}>{copiedId === msg.id ? "✓" : "⎘"}</IconBtn>
                        <IconBtn title="Thumbs up" onClick={() => toggleLike(msg.id, true)} active={msg.liked === true}>👍</IconBtn>
                        <IconBtn title="Thumbs down" onClick={() => toggleLike(msg.id, false)} active={msg.liked === false}>👎</IconBtn>
                        <IconBtn title="Retry" onClick={() => retryMessage(msg.id)}>{retryingId === msg.id ? "⟳" : "↺"}</IconBtn>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      </div>

      {/* ── ATTACHED FILE PREVIEW ── */}
      {attachedImage && (
        <div style={{ padding: "8px 16px", borderTop: "1px solid rgba(255,255,255,0.05)", background: "rgba(124,58,237,0.06)", display: "flex", alignItems: "center", gap: "10px" }}>
          <img src={attachedImage.url} alt="preview" style={{ height: "44px", borderRadius: "6px", objectFit: "cover" }} />
          <span style={{ fontSize: "11px", color: "rgb(156,172,194)", flex: 1 }}>{attachedImage.name}</span>
          <button onClick={() => setAttachedImage(null)} style={{ background: "none", border: "none", color: "rgb(100,116,136)", cursor: "pointer", fontSize: "14px" }}>✕</button>
        </div>
      )}
      {attachedFile && (
        <div style={{ maxWidth: "720px", margin: "0 auto", padding: "0 16px", width: "100%" }}>
          <div style={{ background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.25)", borderRadius: "10px", padding: "8px 12px", marginBottom: "6px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <span style={{ fontSize: "14px" }}>📎</span>
              <span style={{ fontSize: "12px", color: "#a78bfa" }}>{attachedFile.name}</span>
              <span style={{ fontSize: "10px", color: "#475569" }}>({(attachedFile.size / 1024).toFixed(1)} KB)</span>
            </div>
            <button onClick={() => { setAttachedFile(null); setAttachPreview("") }} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "14px" }}>✕</button>
          </div>
        </div>
      )}

      {/* ── INPUT ── */}
      <div style={{ padding: "10px 16px 18px", background: "#0a0a0f", flexShrink: 0 }}>
        <div style={{ maxWidth: "720px", margin: "0 auto" }}>
          <div style={{ background: "#1a1a2a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "16px", padding: "10px 12px", display: "flex", alignItems: "flex-end", gap: "8px" }}>
            {/* File attach button */}
            <button onClick={() => fileInputRef.current?.click()} title="Attach file" style={{ background: "transparent", border: "none", cursor: "pointer", color: "#334155", fontSize: "16px", padding: "0 2px", paddingBottom: "2px", display: "flex", alignItems: "center" }}>
              📎
            </button>
            <input ref={fileInputRef} type="file" style={{ display: "none" }} onChange={handleFileAttach} />

            <textarea
              ref={textareaRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
              onPaste={e => { for(const item of Array.from(e.clipboardData.items)) { if(item.type.startsWith("image/")) { const f=item.getAsFile(); if(f){handleImageAttach(f);e.preventDefault()} } } }}
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
            Enter to send · Shift+Enter for new line · 📎 attach files
          </div>
        </div>
      </div>
    </div>
  )
}
