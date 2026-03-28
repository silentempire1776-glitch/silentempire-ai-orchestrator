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

const SERVER_DEFAULTS: Record<string, string> = {
  jarvis:   "moonshotai/kimi-k2.5",
  research: "moonshotai/kimi-k2-thinking",
  revenue:  "moonshotai/kimi-k2.5",
  sales:    "moonshotai/kimi-k2.5",
  growth:   "moonshotai/kimi-k2.5",
  product:  "moonshotai/kimi-k2-instruct",
  legal:    "moonshotai/kimi-k2-thinking",
  systems:  "qwen/qwen3-coder-480b-a35b-instruct",
  code:     "qwen/qwen3-coder-480b-a35b-instruct",
  voice:    "meta/llama-4-maverick-17b-128e-instruct",
}

const MODEL_OPTIONS = [
  // ── NVIDIA / Free ──
  "moonshotai/kimi-k2.5",
  "moonshotai/kimi-k2-instruct",
  "moonshotai/kimi-k2-thinking",
  "meta/llama-4-maverick-17b-128e-instruct",
  "meta/llama-3.3-70b-instruct",
  "meta/llama-3.1-8b-instruct",
  "qwen/qwen3.5-397b-a17b",
  "qwen/qwen3.5-122b-a10b",
  "nvidia/llama-3.3-nemotron-super-49b-v1",
  "nvidia/llama-3.1-nemotron-ultra-253b-v1",
  "mistralai/mistral-large-3-675b-instruct-2512",
  "deepseek-ai/deepseek-v3.2",
  "qwen/qwen3-coder-480b-a35b-instruct",
  "mistralai/devstral-2-123b-instruct-2512",
  "qwen/qwen2.5-coder-32b-instruct",
  // ── Anthropic ──
  "claude-opus-4-6",
  "claude-sonnet-4-6",
  "claude-haiku-4-5-20251001",
  "claude-opus-4-5",
  "claude-sonnet-4-5",
  // ── OpenAI GPT-4.1 ──
  "gpt-4.1",
  "gpt-4.1-mini",
  "gpt-4.1-nano",
  "gpt-4o",
  "gpt-4o-mini",
  // ── OpenAI GPT-5.x ──
  "gpt-5",
  "gpt-5.4-2026-03-05",
  "gpt-5.4-mini-2026-03-17",
  "gpt-5.4-nano-2026-03-17",
  // ── OpenAI reasoning ──
  "o1",
  "o1-mini",
  "o3",
  "o3-mini",
  "o4-mini",
  // ── OpenAI Codex ──
  "codex-mini-latest",
  // ── Custom ──
  "__custom__",
]

const MODEL_LABELS: Record<string,string> = {
  "moonshotai/kimi-k2.5":                          "kimi-k2.5 (quality)",
  "moonshotai/kimi-k2-instruct":                   "kimi-k2-instruct (quality)",
  "moonshotai/kimi-k2-thinking":                   "kimi-k2-thinking (reasoning)",
  "meta/llama-4-maverick-17b-128e-instruct":       "llama-4-maverick (fast)",
  "meta/llama-3.3-70b-instruct":                   "llama-3.3-70b (fast)",
  "meta/llama-3.1-8b-instruct":                    "llama-3.1-8b (fast)",
  "qwen/qwen3.5-397b-a17b":                        "qwen3.5-397b (quality)",
  "qwen/qwen3.5-122b-a10b":                        "qwen3.5-122b (fast)",
  "nvidia/llama-3.3-nemotron-super-49b-v1":        "nemotron-49b (quality)",
  "nvidia/llama-3.1-nemotron-ultra-253b-v1":       "nemotron-ultra-253b (quality)",
  "mistralai/mistral-large-3-675b-instruct-2512":  "mistral-large-3 (quality)",
  "deepseek-ai/deepseek-v3.2":                     "deepseek-v3.2 (quality)",
  "qwen/qwen3-coder-480b-a35b-instruct":           "qwen3-coder-480b (coding)",
  "mistralai/devstral-2-123b-instruct-2512":       "devstral-123b (coding)",
  "qwen/qwen2.5-coder-32b-instruct":               "qwen2.5-coder-32b (coding)",
  "__custom__":                                    "Custom model...",
  // Anthropic
  "claude-opus-4-6":                               "claude-opus-4-6 (Anthropic best $5/M)",
  "claude-sonnet-4-6":                             "claude-sonnet-4-6 (Anthropic $3/M)",
  "claude-haiku-4-5-20251001":                     "claude-haiku-4-5 (Anthropic fast $1/M)",
  "claude-opus-4-5":                               "claude-opus-4-5 (Anthropic $5/M)",
  "claude-sonnet-4-5":                             "claude-sonnet-4-5 (Anthropic $3/M)",
  // OpenAI GPT-4.1
  "gpt-4.1":                                       "gpt-4.1 (OpenAI $2/M)",
  "gpt-4.1-mini":                                  "gpt-4.1-mini (OpenAI $0.4/M)",
  "gpt-4.1-nano":                                  "gpt-4.1-nano (OpenAI $0.1/M)",
  "gpt-4o":                                        "gpt-4o (OpenAI $5/M)",
  "gpt-4o-mini":                                   "gpt-4o-mini (OpenAI $0.15/M)",
  // OpenAI GPT-5.x
  "gpt-5":                                         "gpt-5 (OpenAI $1.25/M)",
  "gpt-5.4-2026-03-05":                            "gpt-5.4 (OpenAI flagship $2.5/M)",
  "gpt-5.4-mini-2026-03-17":                       "gpt-5.4-mini (OpenAI fast)",
  "gpt-5.4-nano-2026-03-17":                       "gpt-5.4-nano (OpenAI fastest)",
  // OpenAI reasoning
  "o1":                                            "o1 (OpenAI reasoning $15/M)",
  "o1-mini":                                       "o1-mini (OpenAI reasoning $3/M)",
  "o3":                                            "o3 (OpenAI reasoning $10/M)",
  "o3-mini":                                       "o3-mini (OpenAI reasoning $1.1/M)",
  "o4-mini":                                       "o4-mini (OpenAI reasoning fast $1.1/M)",
  "codex-mini-latest":                             "codex-mini (OpenAI coding $1.5/M)",
  "claude-sonnet-4-5":                             "claude-sonnet-4-5 (Anthropic)",
  "claude-haiku-4-5-20251001":                     "claude-haiku-4-5 (Anthropic fast)",
  "claude-opus-4-6":                               "claude-opus-4-6 (Anthropic best)",
  // OpenAI
  "gpt-4.1":                                       "gpt-4.1 (OpenAI)",
  "gpt-4.1-mini":                                  "gpt-4.1-mini (OpenAI fast)",
  "gpt-4.1-nano":                                  "gpt-4.1-nano (OpenAI fastest)",
  "gpt-4o":                                        "gpt-4o (OpenAI)",
  "gpt-4o-mini":                                   "gpt-4o-mini (OpenAI fast)",
  "o1":                                            "o1 (OpenAI reasoning)",
  "o1-mini":                                       "o1-mini (OpenAI reasoning fast)",
  "o3":                                            "o3 (OpenAI reasoning best)",
  "o3-mini":                                       "o3-mini (OpenAI reasoning)",
  "o4-mini":                                       "o4-mini (OpenAI reasoning fast)",
  "codex-mini-latest":                             "codex-mini (OpenAI coding)",
  // OpenAI GPT-5.x
  "gpt-5.4":                                       "gpt-5.4 (OpenAI flagship)",
  "gpt-5.4-mini":                                  "gpt-5.4-mini (OpenAI fast)",
  "gpt-5.4-nano":                                  "gpt-5.4-nano (OpenAI fastest)",
  "gpt-5":                                         "gpt-5 (OpenAI)",
}


// Top recommended models per agent role (quality-first)
const AGENT_RECOMMENDED: Record<string, {model:string; reason:string; provider:string}[]> = {
  jarvis: [
    {model:"moonshotai/kimi-k2.5",         reason:"Best quality/speed balance", provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Excellent reasoning",         provider:"anthropic"},
    {model:"gpt-4.1",                      reason:"Strong general purpose",      provider:"openai"},
  ],
  research: [
    {model:"moonshotai/kimi-k2-thinking",  reason:"Deep reasoning",              provider:"nvidia"},
    {model:"claude-opus-4-6",              reason:"Best analysis quality",       provider:"anthropic"},
    {model:"o3-mini",                      reason:"Strong reasoning",            provider:"openai"},
  ],
  revenue: [
    {model:"moonshotai/kimi-k2.5",         reason:"Strong financial analysis",   provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Excellent for strategy",      provider:"anthropic"},
    {model:"gpt-4.1",                      reason:"Strong business reasoning",   provider:"openai"},
  ],
  sales: [
    {model:"moonshotai/kimi-k2.5",         reason:"Persuasive output quality",   provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Natural conversational tone", provider:"anthropic"},
    {model:"gpt-4.1",                      reason:"Strong copy generation",      provider:"openai"},
  ],
  growth: [
    {model:"moonshotai/kimi-k2.5",         reason:"Creative strategy",           provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Innovative thinking",         provider:"anthropic"},
    {model:"gpt-4.1",                      reason:"Good marketing output",       provider:"openai"},
  ],
  product: [
    {model:"moonshotai/kimi-k2-instruct",  reason:"Best instruction following",  provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Strong product thinking",     provider:"anthropic"},
    {model:"gpt-4.1",                      reason:"Solid product reasoning",     provider:"openai"},
  ],
  legal: [
    {model:"moonshotai/kimi-k2-thinking",  reason:"Deep legal reasoning",        provider:"nvidia"},
    {model:"claude-opus-4-6",              reason:"Best accuracy for legal",     provider:"anthropic"},
    {model:"o1",                           reason:"Strong reasoning for law",    provider:"openai"},
  ],
  systems: [
    {model:"qwen/qwen3-coder-480b-a35b-instruct", reason:"Best for infra/code", provider:"nvidia"},
    {model:"claude-sonnet-4-6",            reason:"Strong technical reasoning",  provider:"anthropic"},
    {model:"codex-mini-latest",            reason:"Purpose-built for code",      provider:"openai"},
  ],
  code: [
    {model:"qwen/qwen3-coder-480b-a35b-instruct", reason:"Best coding model",   provider:"nvidia"},
    {model:"claude-sonnet-4-5",            reason:"Excellent code generation",   provider:"anthropic"},
    {model:"codex-mini-latest",            reason:"Purpose-built for code",      provider:"openai"},
  ],
  voice: [
    {model:"meta/llama-4-maverick-17b-128e-instruct", reason:"Fastest response", provider:"nvidia"},
    {model:"claude-haiku-4-5-20251001",    reason:"Fast + high quality",         provider:"anthropic"},
    {model:"gpt-4.1-nano",                 reason:"Fastest OpenAI model",        provider:"openai"},
  ],
}

const PROVIDER_COLORS: Record<string,string> = {
  nvidia: "#76b900", openai: "#10a37f", anthropic: "#d97757"
}

const C    = "rgb(156,172,194)"
const CDim = "rgb(140,155,172)"

type FeedEntry = {
  id: string
  time: string
  who: string
  type: "system"|"agent"|"error"|"chain"|"metric"
  msg: string
}

export default function AgentsPage() {
  const [defaultChatMode, setDefaultChatMode] = useState<"jarvis"|"chain">("jarvis")
  const [overrides, setOverrides]           = useState<Record<string,string>>({})
  const [feed, setFeed]                     = useState<FeedEntry[]>([])
  const [agentStates, setAgentStates]       = useState<Record<string,string>>({})
  const [benchmarkData, setBenchmarkData]   = useState<Record<string,any>>({})
  const [metrics, setMetrics]               = useState<any>({})
  const feedRef  = useRef<HTMLDivElement>(null)
  const feedIds  = useRef<Set<string>>(new Set())

  useEffect(() => {
    const saved = localStorage.getItem("agent_model_overrides")
    if (saved) { try { setOverrides(JSON.parse(saved)) } catch {} }
    const savedMode = localStorage.getItem("default_chat_mode")
    if (savedMode === "jarvis" || savedMode === "chain") setDefaultChatMode(savedMode as any)
  }, [])

  useEffect(() => { localStorage.setItem("default_chat_mode", defaultChatMode) }, [defaultChatMode])
  useEffect(() => { localStorage.setItem("agent_model_overrides", JSON.stringify(overrides)) }, [overrides])

  // Append entries without wiping existing feed
  const appendFeed = (entries: FeedEntry[]) => {
    const fresh = entries.filter(e => !feedIds.current.has(e.id))
    if (!fresh.length) return
    fresh.forEach(e => feedIds.current.add(e.id))
    setFeed(prev => [...prev, ...fresh].slice(-100))
    setTimeout(() => {
      if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight
    }, 80)
  }

  // Load benchmark health + metrics
  useEffect(() => {
    const load = async () => {
      try {
        const [bR, mR] = await Promise.all([
          fetch("/api/metrics/models/summary").catch(() => null),
          fetch("/api/metrics/llm").catch(() => null),
        ])
        if (bR?.ok) {
          const bd = await bR.json()
          const bmap: Record<string,any> = {}
          for (const m of (bd.models || [])) { bmap[m.model] = m }
          setBenchmarkData(bmap)
        }
        if (mR?.ok) {
          const md = await mR.json()
          setMetrics(md)
        }
      } catch {}
    }
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
  }, [])

  // Poll live agent states
  useEffect(() => {
    const poll = async () => {
      try {
        const r = await fetch("/api/metrics/agents/live")
        if (r.ok) {
          const d = await r.json()
          setAgentStates(d.states || {})
        }
      } catch {}
    }
    poll()
    const t = setInterval(poll, 3000)
    return () => clearInterval(t)
  }, [])

  // Live feed - accumulates, never resets
  useEffect(() => {
    // Seed once
    const seedId = "seed-init"
    if (!feedIds.current.has(seedId)) {
      feedIds.current.add(seedId)
      setFeed([{ id: seedId, time: new Date().toLocaleTimeString(), who: "SYSTEM", type: "system", msg: "Live feed connected — monitoring all agents" }])
    }

    const poll = async () => {
      try {
        const now = new Date()
        const timeStr = now.toLocaleTimeString()
        const entries: FeedEntry[] = []

        const r = await fetch("/api/metrics/agents/live").catch(() => null)
        if (r?.ok) {
          const d = await r.json()
          const states = d.states || {}
          Object.entries(states).forEach(([agent, state]) => {
            if (state === "working") {
              const key = `working-${agent}-${Math.floor(Date.now()/8000)}`
              entries.push({ id: key, time: timeStr, who: agent, type: "agent", msg: `⚡ ${agent} is working — ${(SERVER_DEFAULTS[agent]||"").split("/").pop()}` })
            }
          })
        }

        const evR = await fetch("/api/metrics/agents").catch(() => null)
        if (evR?.ok) {
          const evData = await evR.json()
          const todayMap = evData.today || {}
          Object.entries(todayMap).forEach(([agent, data]: [string, any]) => {
            const tt = data.tokens_total || 0
            if (tt > 0) {
              const key = `tok-${agent}-${Math.floor(tt/500)}`
              entries.push({ id: key, time: timeStr, who: agent, type: "metric",
                msg: `${agent}: ${tt >= 1000 ? (tt/1000).toFixed(1)+"k" : tt} tokens today` })
            }
          })
        }

        // Heartbeat every 60s
        const hbKey = `hb-${Math.floor(Date.now()/60000)}`
        entries.push({ id: hbKey, time: timeStr, who: "SYSTEM", type: "system", msg: `Monitoring ${ALL_AGENTS.length} agents` })

        appendFeed(entries)
      } catch {}
    }

    poll()
    const t = setInterval(poll, 8000)
    return () => clearInterval(t)
  }, [])

  const getModelForAgent = (id: string) => overrides[id] || SERVER_DEFAULTS[id] || ""
  const isOverridden     = (id: string) => !!overrides[id] && overrides[id] !== SERVER_DEFAULTS[id]
  const setOverride      = (id: string, v: string) => setOverrides(p => ({ ...p, [id]: v }))
  const clearOverride    = (id: string) => setOverrides(p => { const n={...p}; delete n[id]; return n })

  const getHealth = (agentId: string) => {
    const model = getModelForAgent(agentId)
    const bData = benchmarkData[model] || {}
    if (bData.performance_score != null) {
      return { score: Number(bData.performance_score), latency: bData.latency_ms || 0 }
    }
    return null
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

      <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", height:"420px", flexShrink:0 }}>
        <AgentGraph onSelect={() => {}} />
      </div>

      <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:"12px", flex:1, minHeight:0 }}>

        {/* AGENT CONTROL */}
        <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", overflowY:"auto" }}>
          <div style={{ fontSize:"11px", color:C, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.1em", marginBottom:"14px" }}>Agent Control</div>

          <div style={{ marginBottom:"16px" }}>
            <div style={{ fontSize:"12px", color:C, marginBottom:"6px" }}>Default Chat Mode</div>
            <select value={defaultChatMode} onChange={e => setDefaultChatMode(e.target.value as any)}
              style={{ width:"100%", background:"rgba(255,255,255,0.04)", border:"1px solid rgba(124,58,237,0.25)", borderRadius:"8px", color:C, padding:"7px 10px", fontSize:"12px", outline:"none" }}>
              <option value="jarvis">Jarvis Chat (default)</option>
              <option value="chain">Executive Chain</option>
            </select>
          </div>

          <div>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"10px" }}>
              <div style={{ fontSize:"12px", color:C, fontWeight:600 }}>Default Model Per Agent</div>
              <button onClick={() => setOverrides({})}
                style={{ fontSize:"11px", padding:"3px 8px", borderRadius:"6px", background:"rgba(124,58,237,0.12)", border:"1px solid rgba(124,58,237,0.25)", color:"#a78bfa", cursor:"pointer" }}>
                Reset All
              </button>
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:"6px" }}>
              {ALL_AGENTS.map(a => {
                const current    = getModelForAgent(a.id)
                const overridden = isOverridden(a.id)
                const health     = getHealth(a.id)
                const agState    = agentStates[a.id]

                return (
                  <div key={a.id} style={{ padding:"9px 11px", borderRadius:"9px", background:"rgba(255,255,255,0.02)", border:`1px solid ${overridden ? "rgba(245,158,11,0.3)" : "rgba(255,255,255,0.06)"}` }}>
                    <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"6px" }}>
                      <div style={{ display:"flex", alignItems:"center", gap:"7px" }}>
                        <div style={{ width:"7px", height:"7px", borderRadius:"50%",
                          background: agState==="working" ? "#f59e0b" : "#22c55e",
                          boxShadow: agState==="working" ? "0 0 5px #f59e0b" : "0 0 4px #22c55e" }}/>
                        <span style={{ fontSize:"13px", color:"rgb(200,210,225)", fontWeight:600 }}>{a.label}</span>
                        {overridden && <span style={{ fontSize:"10px", color:"#fbbf24", background:"rgba(245,158,11,0.15)", border:"1px solid rgba(245,158,11,0.3)", padding:"1px 6px", borderRadius:"8px" }}>override</span>}
                      </div>
                      <div style={{ display:"flex", alignItems:"center", gap:"6px" }}>
                        {health && (
                          <span style={{ fontSize:"11px", fontWeight:700,
                            color: health.score>=80?"#34d399":health.score>=60?"#fbbf24":"#f87171" }}>
                            {health.score.toFixed(0)}%
                          </span>
                        )}
                        {health && health.latency > 0 && (
                          <span style={{ fontSize:"10px", color:CDim }}>{health.latency}ms</span>
                        )}
                        {overridden && (
                          <button onClick={() => clearOverride(a.id)}
                            style={{ fontSize:"10px", padding:"1px 6px", borderRadius:"5px", background:"rgba(239,68,68,0.12)", border:"1px solid rgba(239,68,68,0.25)", color:"#f87171", cursor:"pointer" }}>
                            ✕ clear
                          </button>
                        )}
                      </div>
                    </div>

                    <select
                      value={MODEL_OPTIONS.includes(current) ? current : "__custom__"}
                      onChange={e => { if (e.target.value !== "__custom__") setOverride(a.id, e.target.value) }}
                      style={{ width:"100%", background:"rgba(0,0,0,0.4)", border:`1px solid ${overridden?"rgba(245,158,11,0.4)":"rgba(255,255,255,0.1)"}`, borderRadius:"6px", color: overridden ? "#fbbf24" : C, padding:"6px 8px", fontSize:"12px", outline:"none", cursor:"pointer" }}>
                      {MODEL_OPTIONS.map(m => (
                        <option key={m} value={m} style={{ background:"#0a0e1a" }}>
                          {m === "__custom__" ? "Custom model..." : (MODEL_LABELS[m] || m.split("/").pop())}
                        </option>
                      ))}
                    </select>

                    {!MODEL_OPTIONS.filter(m=>m!=="__custom__").includes(current) && (
                      <input value={current} onChange={e => setOverride(a.id, e.target.value)}
                        placeholder="custom model id..."
                        style={{ width:"100%", marginTop:"4px", background:"rgba(0,0,0,0.3)", border:"1px solid rgba(245,158,11,0.35)", borderRadius:"6px", color:"#fbbf24", padding:"5px 8px", fontSize:"11px", outline:"none", fontFamily:"monospace", boxSizing:"border-box" }}/>
                    )}

                    {overridden && (
                      <div style={{ fontSize:"10px", color:CDim, marginTop:"3px" }}>
                        default: {SERVER_DEFAULTS[a.id]?.split("/").pop()}
                      </div>
                    )}

                    {/* Recommended models for this agent */}
                    {AGENT_RECOMMENDED[a.id] && (
                      <div style={{ marginTop:"8px" }}>
                        <div style={{ fontSize:"9px", color:CDim, textTransform:"uppercase", letterSpacing:"0.08em", marginBottom:"4px", fontWeight:700 }}>Top Picks</div>
                        <div style={{ display:"flex", flexDirection:"column", gap:"3px" }}>
                          {AGENT_RECOMMENDED[a.id].map(rec => (
                            <div key={rec.model}
                              onClick={() => setOverride(a.id, rec.model)}
                              style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
                                padding:"4px 8px", borderRadius:"6px", cursor:"pointer",
                                background: current===rec.model ? "rgba(124,58,237,0.12)" : "rgba(255,255,255,0.02)",
                                border: current===rec.model ? "1px solid rgba(124,58,237,0.3)" : "1px solid rgba(255,255,255,0.05)",
                                transition:"all 0.15s" }}>
                              <div>
                                <span style={{ fontSize:"10px", color: current===rec.model ? "#a78bfa" : C, fontWeight:600 }}>
                                  {rec.model.split("/").pop()}
                                </span>
                                <span style={{ fontSize:"9px", color:CDim, marginLeft:"6px" }}>{rec.reason}</span>
                              </div>
                              <span style={{ fontSize:"9px", fontWeight:700, padding:"1px 5px", borderRadius:"4px",
                                color: PROVIDER_COLORS[rec.provider] || CDim,
                                background: `${PROVIDER_COLORS[rec.provider] || "#475569"}18`,
                                border: `1px solid ${PROVIDER_COLORS[rec.provider] || "#475569"}33` }}>
                                {rec.provider}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
            <div style={{ fontSize:"10px", color:CDim, marginTop:"10px" }}>
              Yellow border = active override · Health % from benchmark
            </div>
          </div>
        </div>

        {/* LIVE SYSTEM FEED */}
        <div style={{ background:"rgba(10,14,26,0.9)", border:"1px solid rgba(255,255,255,0.08)", borderRadius:"12px", padding:"16px", display:"flex", flexDirection:"column", minHeight:0 }}>
          <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"12px", flexShrink:0 }}>
            <div style={{ fontSize:"11px", color:C, fontWeight:700, textTransform:"uppercase", letterSpacing:"0.1em" }}>Live System Feed</div>
            <div style={{ display:"flex", alignItems:"center", gap:"8px" }}>
              <div style={{ width:"6px", height:"6px", borderRadius:"50%", background:"#22c55e", boxShadow:"0 0 5px #22c55e", animation:"pulse 2s infinite" }}/>
              <button onClick={() => { setFeed([]); feedIds.current.clear() }}
                style={{ fontSize:"10px", padding:"2px 8px", borderRadius:"5px", background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:CDim, cursor:"pointer" }}>
                Clear
              </button>
            </div>
          </div>

          {/* Token chips */}
          <div style={{ display:"flex", gap:"6px", marginBottom:"10px", flexShrink:0, flexWrap:"wrap" }}>
            {Object.entries((metrics.by_agent_today || {}) as Record<string,any>).slice(0,6).map(([agent, data]: [string, any]) => (
              <div key={agent} style={{ fontSize:"10px", padding:"3px 9px", borderRadius:"8px", background:"rgba(124,58,237,0.1)", border:"1px solid rgba(124,58,237,0.2)", color:"#a78bfa" }}>
                {agent}: {data.tokens_total >= 1000 ? `${(data.tokens_total/1000).toFixed(1)}k` : data.tokens_total} tok
              </div>
            ))}
          </div>

          <div ref={feedRef} style={{ flex:1, overflowY:"auto", display:"flex", flexDirection:"column", gap:"2px" }}>
            {feed.map((entry, i) => (
              <div key={entry.id || i} style={{ display:"flex", gap:"8px", alignItems:"flex-start", padding:"4px 0", borderBottom:"1px solid rgba(255,255,255,0.03)" }}>
                <span style={{ fontSize:"10px", color:CDim, flexShrink:0, minWidth:"54px", marginTop:"1px" }}>{entry.time}</span>
                <span style={{ fontSize:"10px", color:feedColor(entry.type), flexShrink:0, minWidth:"54px", textTransform:"capitalize", fontWeight:600 }}>{entry.who}</span>
                <span style={{ fontSize:"12px", color:entry.type==="error"?"#f87171":C, lineHeight:"1.4" }}>{entry.msg}</span>
              </div>
            ))}
          </div>
        </div>

      </div>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
    </div>
  )
}
