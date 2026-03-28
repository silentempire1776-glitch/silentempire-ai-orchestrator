"use client"
import { useEffect, useState } from "react"

const C    = "rgb(156,172,194)"
const CDim = "rgb(140,155,172)"

type ModelInfo = {
  model: string; short_name: string; available: boolean
  latency_ms: number; performance_score: number
  assigned_to: string[]; good_for: string[]
  history: { health_score?:number; avg_latency_ms?:number; success_count?:number; failure_count?:number }
  benchmark_run: string|null
}

const ROLE_COLORS: Record<string,string> = {
  jarvis:"#7c3aed", research:"#0891b2", revenue:"#059669", sales:"#d97706",
  growth:"#16a34a", product:"#7c3aed", legal:"#dc2626", systems:"#475569",
  code:"#2563eb", voice:"#9333ea",
}

// 25% lighter versions for "good for" tags
const ROLE_COLORS_LIGHT: Record<string,string> = {
  jarvis:"#a78bfa", research:"#38bdf8", revenue:"#34d399", sales:"#fbbf24",
  growth:"#4ade80", product:"#a78bfa", legal:"#f87171", systems:"#94a3b8",
  code:"#60a5fa", voice:"#c084fc",
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "#22c55e" : score >= 60 ? "#f59e0b" : score >= 30 ? "#f97316" : "#ef4444"
  return (
    <div style={{ display:"flex", alignItems:"center", gap:"8px" }}>
      <div style={{ flex:1, height:"6px", background:"rgba(255,255,255,0.08)", borderRadius:"3px", overflow:"hidden" }}>
        <div style={{ height:"100%", width:`${score}%`, background:color, borderRadius:"3px", transition:"width 0.5s" }}/>
      </div>
      <span style={{ fontSize:"12px", color, fontWeight:700, minWidth:"38px", textAlign:"right" }}>{score.toFixed(0)}%</span>
    </div>
  )
}

function Tag({ label, color, bg, border }: { label:string; color:string; bg:string; border:string }) {
  return (
    <span style={{
      fontSize:"12px", fontWeight:700, padding:"3px 9px", borderRadius:"10px",
      background: bg, border:`1px solid ${border}`, color,
      letterSpacing:"0.01em",
    }}>{label}</span>
  )
}

export default function ModelsPage() {
  const [models, setModels]       = useState<ModelInfo[]>([])
  const [benchmarkRun, setBRun]   = useState<string|null>(null)
  const [loading, setLoading]     = useState(true)
  const [filter, setFilter]       = useState<"all"|"available"|"unavailable">("available")
  const [runningBench, setRunning] = useState(false)
  const [available, setAvailable] = useState(0)

  const load = async () => {
    try {
      const r = await fetch("/api/metrics/models/summary")
      if (r.ok) {
        const d = await r.json()
        setModels(d.models || [])
        setBRun(d.benchmark_run)
        setAvailable(d.available || 0)
      }
    } catch {}
    setLoading(false)
  }

  const runBenchmark = async () => {
    setRunning(true)
    try {
      await fetch("/api/metrics/model_benchmark/run", { method:"POST" })
      setTimeout(() => { load(); setRunning(false) }, 90000)
    } catch { setRunning(false) }
  }

  useEffect(() => { load() }, [])

  const filtered = models.filter(m =>
    filter === "all" ? true : filter === "available" ? m.available : !m.available
  )

  return (
    <div style={{ padding:"20px 24px", height:"100%", overflowY:"auto", background:"#07080f" }}>
      <style>{`
        .model-card { transition: border-color 0.2s, box-shadow 0.2s; }
        .model-card:hover { border-color: rgba(124,58,237,0.35) !important; box-shadow: 0 0 20px rgba(124,58,237,0.08) !important; }
        .filter-btn { transition: all 0.15s; }
        .filter-btn:hover { background: rgba(255,255,255,0.06) !important; }
      `}</style>

      {/* Header */}
      <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between", marginBottom:"20px", gap:"16px", flexWrap:"wrap" }}>
        <div>
          <h1 style={{ fontSize:"18px", fontWeight:700, color:"#f1f5f9", marginBottom:"4px" }}>Model Health</h1>
          <p style={{ fontSize:"12px", color:C }}>
            {available}/{models.length} models available
            {benchmarkRun && (
              <span style={{ marginLeft:"10px", color:CDim }}>
                Last benchmark: {new Date(benchmarkRun).toLocaleString()}
              </span>
            )}
          </p>
        </div>
        <div style={{ display:"flex", gap:"8px", flexWrap:"wrap" }}>
          {(["available","unavailable","all"] as const).map(f => (
            <button key={f} className="filter-btn" onClick={() => setFilter(f)}
              style={{ padding:"6px 14px", borderRadius:"8px", fontSize:"12px", cursor:"pointer", fontWeight:500,
                background: filter===f ? "rgba(124,58,237,0.2)" : "rgba(255,255,255,0.04)",
                border: filter===f ? "1px solid rgba(124,58,237,0.4)" : "1px solid rgba(255,255,255,0.08)",
                color: filter===f ? "#a78bfa" : C }}>
              {f.charAt(0).toUpperCase()+f.slice(1)}
            </button>
          ))}
          <button onClick={runBenchmark} disabled={runningBench}
            style={{ padding:"6px 16px", borderRadius:"8px", fontSize:"12px", fontWeight:600,
              cursor:runningBench?"not-allowed":"pointer",
              background: runningBench ? "rgba(255,255,255,0.04)" : "rgba(124,58,237,0.15)",
              border:"1px solid rgba(124,58,237,0.3)", color: runningBench ? CDim : "#a78bfa" }}>
            {runningBench ? "Running (~90s)…" : "⟳ Run Benchmark"}
          </button>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display:"flex", gap:"20px", marginBottom:"18px", flexWrap:"wrap" }}>
        {([["#22c55e","80–100% Excellent"],["#f59e0b","60–79% Good"],["#f97316","30–59% Degraded"],["#ef4444","0–29% Poor / Offline"]] as const).map(([color,label]) => (
          <div key={label} style={{ display:"flex", alignItems:"center", gap:"7px" }}>
            <div style={{ width:"10px", height:"10px", borderRadius:"2px", background:color, flexShrink:0 }}/>
            <span style={{ fontSize:"11px", color:CDim }}>{label}</span>
          </div>
        ))}
      </div>

      {loading ? (
        <div style={{ color:C, fontSize:"13px" }}>Loading benchmark data…</div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign:"center", paddingTop:"60px" }}>
          <div style={{ fontSize:"13px", color:C, marginBottom:"12px" }}>No benchmark data yet.</div>
          <button onClick={runBenchmark}
            style={{ padding:"8px 20px", borderRadius:"8px", background:"rgba(124,58,237,0.15)", border:"1px solid rgba(124,58,237,0.3)", color:"#a78bfa", cursor:"pointer", fontSize:"13px" }}>
            Run Benchmark Now →
          </button>
        </div>
      ) : (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(340px, 1fr))", gap:"12px" }}>
          {filtered.map(m => (
            <div key={m.model} className="model-card" style={{
              background:"rgba(10,14,26,0.95)",
              border:`1px solid ${m.available ? "rgba(255,255,255,0.08)" : "rgba(239,68,68,0.12)"}`,
              borderRadius:"14px", padding:"16px 18px",
              opacity: m.available ? 1 : 0.55,
            }}>
              {/* Header row */}
              <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between", marginBottom:"12px" }}>
                <div style={{ flex:1, minWidth:0, paddingRight:"10px" }}>
                  <div style={{ fontSize:"14px", fontWeight:700, color:"#f1f5f9",
                    overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }} title={m.model}>
                    {m.short_name}
                  </div>
                  <div style={{ fontSize:"11px", color:CDim, marginTop:"2px" }}>
                    {m.model.split("/")[0]}
                  </div>
                </div>
                <div style={{ flexShrink:0 }}>
                  {m.available ? (
                    <span style={{ fontSize:"11px", padding:"3px 9px", borderRadius:"10px",
                      background:"rgba(34,197,94,0.1)", border:"1px solid rgba(34,197,94,0.3)",
                      color:"#4ade80", fontWeight:600 }}>
                      {m.latency_ms}ms
                    </span>
                  ) : (
                    <span style={{ fontSize:"11px", padding:"3px 9px", borderRadius:"10px",
                      background:"rgba(239,68,68,0.1)", border:"1px solid rgba(239,68,68,0.25)",
                      color:"#f87171", fontWeight:600 }}>
                      offline
                    </span>
                  )}
                </div>
              </div>

              {/* Performance score */}
              <div style={{ marginBottom:"12px" }}>
                <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:"6px" }}>
                  <span style={{ fontSize:"11px", color:C, fontWeight:600 }}>Performance Score</span>
                  {(m.history?.success_count != null) && (
                    <span style={{ fontSize:"10px", color:CDim }}>
                      {m.history.success_count}✓ {m.history.failure_count || 0}✗
                    </span>
                  )}
                </div>
                <ScoreBar score={m.performance_score} />
              </div>

              {/* Currently assigned to */}
              {m.assigned_to.length > 0 && (
                <div style={{ marginBottom:"10px" }}>
                  <div style={{ fontSize:"10px", color:C, fontWeight:700, marginBottom:"6px",
                    textTransform:"uppercase", letterSpacing:"0.09em" }}>
                    Currently Assigned To
                  </div>
                  <div style={{ display:"flex", gap:"5px", flexWrap:"wrap" }}>
                    {m.assigned_to.map(role => (
                      <Tag key={role} label={role}
                        color={ROLE_COLORS_LIGHT[role] || "rgb(156,172,194)"}
                        bg={`${ROLE_COLORS[role] || "#475569"}28`}
                        border={`${ROLE_COLORS[role] || "#475569"}55`}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Good for */}
              {m.good_for.length > 0 && (
                <div>
                  <div style={{ fontSize:"10px", color:C, fontWeight:700, marginBottom:"6px",
                    textTransform:"uppercase", letterSpacing:"0.09em" }}>
                    Good For
                  </div>
                  <div style={{ display:"flex", gap:"5px", flexWrap:"wrap" }}>
                    {m.good_for.slice(0,8).map(role => (
                      <Tag key={role} label={role}
                        color="rgb(156,172,194)"
                        bg="rgba(255,255,255,0.05)"
                        border="rgba(255,255,255,0.12)"
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
