"use client"
import { useEffect, useState } from "react"

const C    = "rgb(156,172,194)"
const CDim = "rgb(100,116,136)"

type ModelInfo = {
  model: string
  short_name: string
  available: boolean
  latency_ms: number
  performance_score: number
  assigned_to: string[]
  good_for: string[]
  history: { health_score?: number; avg_latency_ms?: number; success_count?: number; failure_count?: number }
  benchmark_run: string | null
}

const ROLE_COLORS: Record<string,string> = {
  jarvis:"#7c3aed", research:"#0891b2", revenue:"#059669", sales:"#d97706",
  growth:"#16a34a", product:"#7c3aed", legal:"#dc2626", systems:"#475569",
  code:"#2563eb", voice:"#9333ea",
}

function ScoreBar({ score }: { score: number }) {
  const color = score >= 80 ? "#22c55e" : score >= 60 ? "#f59e0b" : score >= 30 ? "#f97316" : "#ef4444"
  return (
    <div style={{ display:"flex", alignItems:"center", gap:"8px" }}>
      <div style={{ flex:1, height:"6px", background:"rgba(255,255,255,0.08)", borderRadius:"3px", overflow:"hidden" }}>
        <div style={{ height:"100%", width:`${score}%`, background:color, borderRadius:"3px", transition:"width 0.5s" }}/>
      </div>
      <span style={{ fontSize:"11px", color, fontWeight:700, minWidth:"36px", textAlign:"right" }}>{score.toFixed(0)}%</span>
    </div>
  )
}

export default function ModelsPage() {
  const [models, setModels]       = useState<ModelInfo[]>([])
  const [benchmarkRun, setBRun]   = useState<string|null>(null)
  const [loading, setLoading]     = useState(true)
  const [filter, setFilter]       = useState<"all"|"available"|"unavailable">("available")
  const [runningBench, setRunning] = useState(false)

  const load = async () => {
    try {
      const r = await fetch("/api/metrics/models/summary")
      if (r.ok) {
        const d = await r.json()
        setModels(d.models || [])
        setBRun(d.benchmark_run)
      }
    } catch {}
    setLoading(false)
  }

  const runBenchmark = async () => {
    setRunning(true)
    try {
      await fetch("/api/metrics/model_benchmark/run", { method:"POST" })
      // Poll for results
      await new Promise(r => setTimeout(r, 5000))
      await load()
    } catch {}
    setRunning(false)
  }

  useEffect(() => { load() }, [])

  const filtered = models.filter(m =>
    filter === "all" ? true : filter === "available" ? m.available : !m.available
  )

  const available = models.filter(m => m.available).length

  return (
    <div style={{ padding:"20px 24px", height:"100%", overflowY:"auto" }}>
      {/* Header */}
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:"20px" }}>
        <div>
          <h1 style={{ fontSize:"18px", fontWeight:700, color:"#f1f5f9", marginBottom:"2px" }}>Model Health</h1>
          <p style={{ fontSize:"11px", color:CDim }}>
            Live benchmark results — {available}/{models.length} models available
            {benchmarkRun && <span style={{ marginLeft:"8px" }}>· Last run: {new Date(benchmarkRun).toLocaleString()}</span>}
          </p>
        </div>
        <div style={{ display:"flex", gap:"8px" }}>
          {["available","unavailable","all"].map(f => (
            <button key={f} onClick={() => setFilter(f as any)}
              style={{ padding:"5px 12px", borderRadius:"8px", fontSize:"11px", cursor:"pointer",
                background: filter===f ? "rgba(124,58,237,0.2)" : "rgba(255,255,255,0.04)",
                border: filter===f ? "1px solid rgba(124,58,237,0.4)" : "1px solid rgba(255,255,255,0.08)",
                color: filter===f ? "#a78bfa" : C }}>
              {f.charAt(0).toUpperCase()+f.slice(1)}
            </button>
          ))}
          <button onClick={runBenchmark} disabled={runningBench}
            style={{ padding:"5px 14px", borderRadius:"8px", fontSize:"11px", cursor:runningBench?"not-allowed":"pointer",
              background: runningBench ? "rgba(255,255,255,0.04)" : "rgba(124,58,237,0.15)",
              border:"1px solid rgba(124,58,237,0.3)", color:"#a78bfa" }}>
            {runningBench ? "Running…" : "⟳ Run Benchmark"}
          </button>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display:"flex", gap:"16px", marginBottom:"16px", flexWrap:"wrap" }}>
        {[["#22c55e","80-100% Excellent"],["#f59e0b","60-79% Good"],["#f97316","30-59% Degraded"],["#ef4444","0-29% Poor / Offline"]].map(([color,label]) => (
          <div key={label} style={{ display:"flex", alignItems:"center", gap:"6px" }}>
            <div style={{ width:"10px", height:"10px", borderRadius:"2px", background:color }}/>
            <span style={{ fontSize:"10px", color:CDim }}>{label}</span>
          </div>
        ))}
      </div>

      {loading ? (
        <div style={{ color:CDim, fontSize:"13px" }}>Loading benchmark data…</div>
      ) : filtered.length === 0 ? (
        <div style={{ color:CDim, fontSize:"13px" }}>
          No benchmark data yet.{" "}
          <button onClick={runBenchmark} style={{ color:"#a78bfa", background:"none", border:"none", cursor:"pointer", fontSize:"13px" }}>
            Run benchmark now →
          </button>
        </div>
      ) : (
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(340px, 1fr))", gap:"10px" }}>
          {filtered.map(m => (
            <div key={m.model} style={{
              background:"rgba(10,14,26,0.9)",
              border:`1px solid ${m.available ? "rgba(255,255,255,0.08)" : "rgba(239,68,68,0.15)"}`,
              borderRadius:"12px", padding:"14px 16px",
              opacity: m.available ? 1 : 0.6,
            }}>
              {/* Model name + status */}
              <div style={{ display:"flex", alignItems:"flex-start", justifyContent:"space-between", marginBottom:"10px" }}>
                <div style={{ flex:1, minWidth:0 }}>
                  <div style={{ fontSize:"13px", fontWeight:600, color:"#e2e8f0", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }} title={m.model}>
                    {m.short_name}
                  </div>
                  <div style={{ fontSize:"9px", color:"#334155", marginTop:"2px", overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
                    {m.model.split("/")[0]}
                  </div>
                </div>
                <div style={{ display:"flex", alignItems:"center", gap:"6px", flexShrink:0, marginLeft:"8px" }}>
                  {m.available ? (
                    <span style={{ fontSize:"9px", padding:"2px 7px", borderRadius:"10px", background:"rgba(34,197,94,0.1)", border:"1px solid rgba(34,197,94,0.25)", color:"#4ade80" }}>
                      {m.latency_ms}ms
                    </span>
                  ) : (
                    <span style={{ fontSize:"9px", padding:"2px 7px", borderRadius:"10px", background:"rgba(239,68,68,0.1)", border:"1px solid rgba(239,68,68,0.25)", color:"#f87171" }}>
                      offline
                    </span>
                  )}
                </div>
              </div>

              {/* Performance score */}
              <div style={{ marginBottom:"10px" }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:"4px" }}>
                  <span style={{ fontSize:"10px", color:C }}>Performance Score</span>
                  {m.history?.success_count != null && (
                    <span style={{ fontSize:"9px", color:CDim }}>
                      {m.history.success_count}✓ {m.history.failure_count}✗ historical
                    </span>
                  )}
                </div>
                <ScoreBar score={m.performance_score} />
              </div>

              {/* Currently assigned to */}
              {m.assigned_to.length > 0 && (
                <div style={{ marginBottom:"8px" }}>
                  <div style={{ fontSize:"9px", color:CDim, marginBottom:"4px", textTransform:"uppercase", letterSpacing:"0.08em" }}>Currently assigned to</div>
                  <div style={{ display:"flex", gap:"4px", flexWrap:"wrap" }}>
                    {m.assigned_to.map(role => (
                      <span key={role} style={{ fontSize:"9px", padding:"2px 7px", borderRadius:"10px",
                        background:`${ROLE_COLORS[role] || "#475569"}22`,
                        border:`1px solid ${ROLE_COLORS[role] || "#475569"}55`,
                        color: ROLE_COLORS[role] || C, fontWeight:600 }}>
                        {role}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Good for */}
              {m.good_for.length > 0 && (
                <div>
                  <div style={{ fontSize:"9px", color:CDim, marginBottom:"4px", textTransform:"uppercase", letterSpacing:"0.08em" }}>Good for</div>
                  <div style={{ display:"flex", gap:"4px", flexWrap:"wrap" }}>
                    {m.good_for.slice(0,6).map(role => (
                      <span key={role} style={{ fontSize:"9px", padding:"2px 7px", borderRadius:"10px",
                        background:"rgba(255,255,255,0.04)", border:"1px solid rgba(255,255,255,0.08)", color:CDim }}>
                        {role}
                      </span>
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
