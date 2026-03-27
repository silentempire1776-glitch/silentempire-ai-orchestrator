"use client"

import { useEffect, useState, useRef } from "react"
import AgentGraph from "../components/AgentGraph"

const ALL_AGENTS = [
  { id: "jarvis",   label: "Jarvis"    },
  { id: "research", label: "Research"  },
  { id: "revenue",  label: "Revenue"   },
  { id: "sales",    label: "Sales"     },
  { id: "growth",   label: "Growth"    },
  { id: "product",  label: "Product"   },
  { id: "legal",    label: "Legal"     },
  { id: "systems",  label: "Systems"   },
  { id: "code",     label: "Code"      },
  { id: "voice",    label: "Voice"     },
]

// These are the server-configured defaults from .env
// Used as fallback and displayed as "default" vs "override"
const SERVER_DEFAULTS: Record<string, string> = {
  jarvis:   "qwen/qwen3.5-122b-a10b",
  research: "qwen/qwen3.5-397b-a17b",
  revenue:  "nvidia/llama-3.3-nemotron-super-49b-v1",
  sales:    "mistralai/mistral-large-3-675b-instruct-2512",
  growth:   "nvidia/llama-3.3-nemotron-super-49b-v1",
  product:  "qwen/qwen3.5-397b-a17b",
  legal:    "nvidia/llama-3.3-nemotron-super-49b-v1",
  systems:  "qwen/qwen3-coder-480b-a35b-instruct",
  code:     "qwen/qwen3-coder-480b-a35b-instruct",
  voice:    "meta/llama-4-maverick-17b-128e-instruct",
}

const MODEL_OPTIONS = [
  // Fast & reliable
  "qwen/qwen3.5-122b-a10b",
  "meta/llama-4-maverick-17b-128e-instruct",
  "meta/llama-3.3-70b-instruct",
  // High quality
  "qwen/qwen3.5-397b-a17b",
  "nvidia/llama-3.3-nemotron-super-49b-v1",
  "mistralai/mistral-large-3-675b-instruct-2512",
  "moonshotai/kimi-k2.5",
  // Coding
  "qwen/qwen3-coder-480b-a35b-instruct",
  // Custom
  "__custom__",
]

const MODEL_LABELS: Record<string,string> = {
  "qwen/qwen3.5-122b-a10b":                       "qwen3.5-122b (fast)",
  "meta/llama-4-maverick-17b-128e-instruct":       "llama-4-maverick (fast)",
  "meta/llama-3.3-70b-instruct":                   "llama-3.3-70b (fast)",
  "qwen/qwen3.5-397b-a17b":                        "qwen3.5-397b (quality)",
  "nvidia/llama-3.3-nemotron-super-49b-v1":        "nemotron-49b (quality)",
  "mistralai/mistral-large-3-675b-instruct-2512":  "mistral-large-3 (quality)",
  "moonshotai/kimi-k2.5":                          "kimi-k2.5 (quality)",
  "qwen/qwen3-coder-480b-a35b-instruct":           "qwen3-coder-480b (coding)",
  "__custom__":                                    "Custom model…",
}

const C    = "rgb(156,172,194)"
const CDim = "rgb(120,135,155)"

type FeedEntry = {
  time: string
  who: string
  type: "system"|"agent"|"error"|"chain"|"metric"
  msg: string
}

export default function AgentsPage() {
  const [selectedAgent, setSelectedAgent]   = useState<any>(null)
  const [defaultChatMode, setDefaultChatMode] = useState<"jarvis"|"chain">("jarvis")
  const [overrides, setOverrides]           = useState<Record<string,string>>({})
  const [feed, setFeed]                     = useState<FeedEntry[]>([])
  const [agentStates, setAgentStates]       = useState<Record<string,string>>({})
  const [modelHealth, setModelHealth]       = useState<Record<string,any>>({})
  const [metrics, setMetrics]               = useState<any>({})
  const feedRef = useRef<HTMLDivElement>(null)
  const seenEvents = useRef<Set<string>>(new Set())

  // Load saved overrides from localStorage
  useEffect(() => {
    const saved = localStorage.getItem("agent_model_overrides")
    if (saved) {
      try { setOverrides(JSON.parse(saved)) } catch {}
    }
    const savedMode = localStorage.getItem("default_chat_mode")
    if (savedMode === "jarvis" || savedMode === "chain") setDefaultChatMode(savedMode as any)
  }, [])

  useEffect(() => {
    localStorage.setItem("default_chat_mode", defaultChatMode)
  }, [defaultChatMode])

  useEffect(() => {
    localStorage.setItem("agent_model_overrides", JSON.stringify(overrides))
  }, [overrides])

  // Poll agent states + model health + metrics
  useEffect(() => {
    const loadStatic = async () => {
      try {
        const [hR, mR] = await Promise.all([
          fetch("/api/metrics/model_health").catch(() => null),
          fetch("/api/metrics/llm").catch(() => null),
        ])
        if (hR?.ok) {
          const h = await hR.json()
          setModelHealth(h.models || {})
        }
        if (mR?.ok) {
          const m = await mR.json()
          setMetrics(m)
        }
      } catch {}
    }

    loadStatic()
    const t1 = setInterval(loadStatic, 15000)

    const pollLive = async () => {
      try {
        const r = await fetch("/api/metrics/agents/live")
        if (r.ok) {
          const d = await r.json()
          setAgentStates(d.states || {})
        }
      } catch {}
    }
    pollLive()
    const t2 = setInterval(pollLive, 3000)

    return () => { clearInterval(t1); clearInterval(t2) }
  }, [])

  // Live feed — polls recent chain events and metrics
  useEffect(() => {
    const pollFeed = async () => {
      try {
        const entries: FeedEntry[] = []
        const now = new Date()
        const timeStr = now.toLocaleTimeString()

        // Get recent chain events
        const evR = await fetch("/api/metrics/agents").catch(() => null)
        if (evR?.ok) {
          const evData = await evR.json()
          const states = evData.states || {}
          const todayMap = evData.today || {}

          // Agent state changes
          Object.entries(states).forEach(([agent, state]) => {
            const key = `${agent}-${state}-${Math.floor(Date.now()/10000)}`
            if (!seenEvents.current.has(key)) {
              seenEvents.current.add(key)
              if (state === "working") {
                entries.push({ time: timeStr, who: agent, type: "agent", msg: `⚡ ${agent} is now working` })
              }
            }
          })

          // Token milestones
          Object.entries(todayMap).forEach(([agent, data]: [string, any]) => {
            const tt = data.tokens_total || 0
            if (tt > 0) {
              const key = `tok-${agent}-${Math.floor(tt/1000)}`
              if (!seenEvents.current.has(key) && seenEvents.current.size > 0) {
                seenEvents.current.add(key)
                entries.push({ time: timeStr, who: agent, type: "metric", msg: `${agent} used ${tt >= 1000 ? (tt/1000).toFixed(1)+"k" : tt} tokens today` })
              }
            }
          })
        }

        // Get recent chain_events from API
        const chainR = await fetch("/api/metrics/agents/live").catch(() => null)
        if (chainR?.ok) {
          const cd = await chainR.json()
          const states = cd.states || {}
          Object.entries(states).forEach(([agent, state]) => {
            const key = `live-${agent}-${state}-${Math.floor(Date.now()/5000)}`
            if (!seenEvents.current.has(key)) {
              seenEvents.current.add(key)
              if (state === "working") {
                const model = SERVER_DEFAULTS[agent] || "unknown"
                entries.push({
                  time: timeStr, who: agent, type: "agent",
                  msg: `${agent} started — model: ${model.split("/").pop()}`
                })
              } else if (state === "idle" && agentStates[agent] === "working") {
                entries.push({
                  time: timeStr, who: agent, type: "system",
                  msg: `${agent} completed task`
                })
              }
            }
          })
        }

        // System heartbeat every 30s
        const heartbeatKey = `heartbeat-${Math.floor(Date.now()/30000)}`
        if (!seenEvents.current.has(heartbeatKey)) {
          seenEvents.current.add(heartbeatKey)
          const workingAgents = Object.entries(agentStates).filter(([,s]) => s === "working").map(([a]) => a)
          if (workingAgents.length > 0) {
            entries.push({ time: timeStr, who: "SYSTEM", type: "system", msg: `Active agents: ${workingAgents.join(", ")}` })
          } else {
            entries.push({ time: timeStr, who: "SYSTEM", type: "system", msg: `All agents idle — awaiting tasks` })
          }
        }

        if (entries.length > 0) {
          setFeed(prev => {
            const combined = [...prev, ...entries].slice(-50) // keep last 50
            return combined
          })
          // Auto-scroll
          setTimeout(() => {
            if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
          }, 100)
        }
      } catch {}
    }

    // Initial seed
    setFeed([{
      time: new Date().toLocaleTimeString(),
      who: "SYSTEM",
      type: "system",
      msg: "Live feed connected — monitoring all agents"
    }])
    seenEvents.current.add("init")

    pollFeed()
    const t = setInterval(pollFeed, 5000)
    return () => clearInterval(t)
  }, [agentStates])

  const getModelForAgent = (agentId: string) => overrides[agentId] || SERVER_DEFAULTS[agentId] || ""
  const isOverridden = (agentId: string) => !!overrides[agentId] && overrides[agentId] !== SERVER_DEFAULTS[agentId]

  const setOverride = (agentId: string, value: string) => {
    setOverrides(prev => ({ ...prev, [agentId]: value }))
  }

  const clearOverride = (agentId: string) => {
    setOverrides(prev => {
      const next = { ...prev }
      delete next[agentId]
      return next
    })
  }

  const getHealthForAgent = (agentId: string) => {
    const model = getModelForAgent(agentId)
    return modelHealth[model] || null
  }

  const feedColor = (type: FeedEntry["type"]) => {
    if (type === "agent")  return "#a78bfa"
    if (type === "error")  return "#f87171"
    if (type === "chain")  return "#34d399"
    if (type === "metric") return "#7dd3fc"
    return CDim
  }

  return (
    <div style={{ height:"100%", display:"flex", flexDirection:"column", gap:"12px", padding:"16px", overflowY:"auto" }}>

      {/* FULL-WIDTH AGENT GRAPH */}
      <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", height:"420px", flexShrink:0 }}>
        <AgentGraph onSelect={setSelectedAgent} />
      </div>

      {/* BOTTOM: Agent Control LEFT + Live Feed RIGHT */}
      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"12px", flex:1, minHeight:0 }}>

        {/* AGENT CONTROL */}
        <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", overflowY:"auto" }}>

          <div style={{ fontSize:"10px", color:C, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:"14px" }}>Agent Control</div>

          {/* Default Chat Mode */}
          <div style={{ marginBottom:"16px" }}>
            <div style={{ fontSize:"11px", color:C, marginBottom:"6px" }}>Default Chat Mode</div>
            <select
              value={defaultChatMode}
              onChange={e => setDefaultChatMode(e.target.value as any)}
              style={{ width:"100%", background:"rgba(255,255,255,0.04)", border:"1px solid rgba(124,58,237,0.25)", borderRadius:"8px", color:C, padding:"7px 10px", fontSize:"12px", outline:"none" }}
            >
              <option value="jarvis">Jarvis Chat (default)</option>
              <option value="chain">Executive Chain</option>
            </select>
          </div>

          {/* Model Per Agent */}
          <div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"10px" }}>
              <div style={{ fontSize:"11px", color:C }}>Default Model Per Agent</div>
              <button
                onClick={() => setOverrides({})}
                style={{ fontSize:"10px", padding:"3px 8px", borderRadius:"6px", background:"rgba(124,58,237,0.12)", border:"1px solid rgba(124,58,237,0.25)", color:"#a78bfa", cursor:"pointer" }}
              >Reset All</button>
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:"6px" }}>
              {ALL_AGENTS.map(a => {
                const current  = getModelForAgent(a.id)
                const overridden = isOverridden(a.id)
                const health   = getHealthForAgent(a.id)
                const agState  = agentStates[a.id]
                const shortModel = current.split("/").pop() || current

                return (
                  <div key={a.id} style={{ padding:"8px 10px", borderRadius:"8px", background:"rgba(255,255,255,0.02)", border:`1px solid ${overridden ? "rgba(245,158,11,0.3)" : "rgba(255,255,255,0.06)"}` }}>
                    <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"5px" }}>
                      <div style={{ display:"flex", alignItems:"center", gap:"7px" }}>
                        <div style={{ width:"6px", height:"6px", borderRadius:"50%", background: agState==="working" ? "#f59e0b" : "#22c55e", boxShadow: agState==="working" ? "0 0 5px #f59e0b" : "0 0 4px #22c55e" }}/>
                        <span style={{ fontSize:"12px", color:C, fontWeight:500 }}>{a.label}</span>
                        {overridden && <span style={{ fontSize:"9px", color:"#fbbf24", background:"rgba(245,158,11,0.15)", border:"1px solid rgba(245,158,11,0.3)", padding:"1px 5px", borderRadius:"8px" }}>override</span>}
                      </div>
                      <div style={{ display:"flex", alignItems:"center", gap:"6px" }}>
                        {health && (
                          <span style={{ fontSize:"9px", color: health.health_score>=0.9?"#34d399":health.health_score>=0.7?"#fbbf24":"#f87171", fontWeight:600 }}>
                            ● {(health.health_score*100).toFixed(0)}%
                          </span>
                        )}
                        {overridden && (
                          <button
                            onClick={() => clearOverride(a.id)}
                            style={{ fontSize:"9px", padding:"1px 5px", borderRadius:"5px", background:"rgba(239,68,68,0.12)", border:"1px solid rgba(239,68,68,0.25)", color:"#f87171", cursor:"pointer" }}
                          >✕ clear</button>
                        )}
                      </div>
                    </div>

                    <div style={{ display:"flex", flexDirection:"column", gap:"4px" }}>
                      <select
                        value={MODEL_OPTIONS.includes(current) ? current : "__custom__"}
                        onChange={e => {
                          if (e.target.value === "__custom__") return
                          setOverride(a.id, e.target.value)
                        }}
                        style={{ width:"100%", background:"rgba(0,0,0,0.4)", border:`1px solid ${overridden?"rgba(245,158,11,0.4)":"rgba(255,255,255,0.1)"}`, borderRadius:"6px", color: overridden ? "#fbbf24" : C, padding:"6px 8px", fontSize:"11px", outline:"none", cursor:"pointer" }}
                      >
                        {MODEL_OPTIONS.map(m => (
                          <option key={m} value={m} style={{ background:"#0a0e1a" }}>
                            {m === "__custom__" ? "Custom model…" : (MODEL_LABELS[m] || m.split("/").pop())}
                          </option>
                        ))}
                      </select>
                      {/* Custom model input — shown when model not in list */}
                      {!MODEL_OPTIONS.filter(m=>m!=="__custom__").includes(current) && (
                        <input
                          value={current}
                          onChange={e => setOverride(a.id, e.target.value)}
                          placeholder="custom model id..."
                          style={{ width:"100%", background:"rgba(0,0,0,0.3)", border:"1px solid rgba(245,158,11,0.35)", borderRadius:"6px", color:"#fbbf24", padding:"5px 8px", fontSize:"10px", outline:"none", fontFamily:"monospace", boxSizing:"border-box" }}
                        />
                      )}
                    </div>

                    {/* Show server default if overridden */}
                    {overridden && (
                      <div style={{ fontSize:"9px", color:"#475569", marginTop:"3px" }}>
                        default: {SERVER_DEFAULTS[a.id]?.split("/").pop()}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            <div style={{ fontSize:"9px", color:"#334155", marginTop:"10px" }}>
              Overrides stored locally. Yellow border = active override. Health % from live model tracking.
            </div>
          </div>
        </div>

        {/* LIVE SYSTEM FEED */}
        <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", display:"flex", flexDirection:"column", minHeight:0 }}>

          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"12px", flexShrink:0 }}>
            <div style={{ fontSize:"10px", color:C, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.1em" }}>Live System Feed</div>
            <div style={{ display:"flex", alignItems:"center", gap:"8px" }}>
              <div style={{ width:"6px", height:"6px", borderRadius:"50%", background:"#22c55e", boxShadow:"0 0 5px #22c55e", animation:"pulse 2s infinite" }}/>
              <button
                onClick={() => { setFeed([]); seenEvents.current.clear() }}
                style={{ fontSize:"9px", padding:"2px 7px", borderRadius:"5px", background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:CDim, cursor:"pointer" }}
              >Clear</button>
            </div>
          </div>

          {/* Token summary */}
          <div style={{ display:"flex", gap:"8px", marginBottom:"10px", flexShrink:0, flexWrap:"wrap" }}>
            {Object.entries((metrics.by_agent_today || {}) as Record<string,any>).slice(0,4).map(([agent, data]: [string, any]) => (
              <div key={agent} style={{ fontSize:"9px", padding:"3px 8px", borderRadius:"8px", background:"rgba(124,58,237,0.1)", border:"1px solid rgba(124,58,237,0.2)", color:"#a78bfa" }}>
                {agent}: {data.tokens_total >= 1000 ? `${(data.tokens_total/1000).toFixed(1)}k` : data.tokens_total} tok
              </div>
            ))}
          </div>

          {/* Feed scroll area */}
          <div
            ref={feedRef}
            style={{ flex:1, overflowY:"auto", display:"flex", flexDirection:"column", gap:"3px" }}
          >
            {feed.length === 0 && (
              <div style={{ fontSize:"11px", color:"#334155" }}>Waiting for activity…</div>
            )}
            {feed.map((entry, i) => (
              <div key={i} style={{ display:"flex", gap:"8px", alignItems:"flex-start", padding:"4px 0", borderBottom:"1px solid rgba(255,255,255,0.03)" }}>
                <span style={{ fontSize:"9px", color:"#334155", flexShrink:0, minWidth:"52px", marginTop:"1px" }}>{entry.time}</span>
                <span style={{ fontSize:"9px", color:feedColor(entry.type), flexShrink:0, minWidth:"52px", textTransform:"capitalize", fontWeight:600 }}>{entry.who}</span>
                <span style={{ fontSize:"11px", color:entry.type==="error"?"#f87171":C, lineHeight:"1.4" }}>{entry.msg}</span>
              </div>
            ))}
          </div>
        </div>

      </div>

      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
    </div>
  )
}
