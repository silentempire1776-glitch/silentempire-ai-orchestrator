"use client"
import { useEffect, useState, useCallback, useRef } from "react"

type Card = {
  id: string; kanban_col: string; status: string; agent: string
  model: string; chain_id: string; instruction: string
  tokens_input: number; tokens_output: number; cost_usd: number
  quality_score: number | null; eval_loops: number
  report_path: string; gdrive_url: string; has_deliverable: boolean
  result_summary: string; error_message: string | null
  duration_sec: number | null; clickup_task_id: string
  clickup_task_name: string; clickup_priority: string
  created_at: string | null; started_at: string | null; completed_at: string | null
  type?: string; retry_count?: number; updated_at?: string | null
  chain_target?: string; chain_summary?: string
  chain_steps?: {agent:string; step_status:string; step_started:string|null; step_completed:string|null}[]
}

const COLS = [
  { id: "backlog",     label: "Backlog",     color: "#64748b" },
  { id: "queue",       label: "Queue",       color: "#3b82f6" },
  { id: "in_progress", label: "In Progress", color: "#f59e0b" },
  { id: "review",      label: "Review",      color: "#8b5cf6" },
  { id: "done",        label: "Done",        color: "#10b981" },
  { id: "failed",      label: "Failed",      color: "#ef4444" },
]

const AGENT_COLORS: Record<string,string> = {
  research:"#60a5fa",revenue:"#34d399",sales:"#fbbf24",growth:"#22d3ee",
  legal:"#f472b6",product:"#a78bfa",systems:"#fb923c",code:"#4ade80",
  voice:"#e879f9",jarvis:"#94a3b8",
}

function fmtCost(n: number) { return n ? `$${n.toFixed(4)}` : "" }
function fmtDur(s: number | null) {
  if (!s) return ""
  return s < 60 ? `${Math.round(s)}s` : `${Math.round(s/60)}m`
}

export default function KanbanPage() {
  const [cards, setCards] = useState<Card[]>([])
  const [queues, setQueues] = useState<Record<string,number>>({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")
  const [filterAgent, setFilterAgent] = useState("")
  const [filterStatus, setFilterStatus] = useState("")
  const [modalCard, setModalCard] = useState<Card|null>(null)
  const [filterDeliverable, setFilterDeliverable] = useState(false)
  const [filterModel, setFilterModel] = useState("")
  const [archiveOpen, setArchiveOpen] = useState(false)
  const [lastUpdate, setLastUpdate] = useState("")
  const boardRef = useRef<HTMLDivElement>(null)
  const dragState = useRef<{dragging:boolean;startX:number;startY:number;scrollLeft:number;scrollTop:number}>({dragging:false,startX:0,startY:0,scrollLeft:0,scrollTop:0})

  const load = useCallback(async () => {
    try {
      const [r1, r2] = await Promise.all([
        fetch("/api/kanban/cards?limit=500"),
        fetch("/api/kanban/queues"),
      ])
      if (r1.ok) { const d = await r1.json(); setCards(d.cards||[]) }
      if (r2.ok) { const d = await r2.json(); setQueues(d.queues||{}) }
      setLastUpdate(new Date().toLocaleTimeString())
    } catch(e) { console.error(e) }
    setLoading(false)
  }, [])

  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t) }, [load])

  // Left-click drag-to-scroll on board
  const onBoardMouseDown = (e: React.MouseEvent) => {
    if (e.button !== 0) return
    const el = boardRef.current; if (!el) return
    dragState.current = {dragging:true, startX:e.pageX-el.offsetLeft, startY:e.pageY-el.offsetTop, scrollLeft:el.scrollLeft, scrollTop:el.scrollTop}
    el.style.cursor = "grabbing"
  }
  const onBoardMouseMove = (e: React.MouseEvent) => {
    const s = dragState.current; if (!s.dragging) return
    const el = boardRef.current; if (!el) return
    e.preventDefault()
    el.scrollLeft = s.scrollLeft - (e.pageX - el.offsetLeft - s.startX)
  }
  const onBoardMouseUp = () => {
    dragState.current.dragging = false
    if (boardRef.current) boardRef.current.style.cursor = "grab"
  }

  const agents = Array.from(new Set(cards.map(c=>c.agent).filter(Boolean))).sort()
  const models = Array.from(new Set(cards.map(c=>c.model).filter(Boolean))).sort()

  const filtered = cards.filter(c => {
    if (filterAgent && c.agent !== filterAgent) return false
    if (filterStatus && c.status !== filterStatus) return false
    if (filterModel && c.model !== filterModel) return false
    if (filterDeliverable && !c.has_deliverable) return false
    if (search) {
      const q = search.toLowerCase()
      return c.instruction?.toLowerCase().includes(q) ||
             c.agent?.toLowerCase().includes(q) ||
             c.chain_id?.toLowerCase().includes(q) ||
             c.clickup_task_name?.toLowerCase().includes(q) ||
             c.id?.toLowerCase().includes(q)
    }
    return true
  })

  const resolveCol = (c: Card) => {
    if (c.status === "failed" || c.status === "cancelled") return "failed"
    return c.kanban_col
  }

  const thirtyDaysAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000)

  const byCol = (col: string) => filtered
    .filter(c => {
      if (resolveCol(c) !== col) return false
      if (col === "done") {
        const ts = c.completed_at || c.created_at
        if (!ts) return true
        return new Date(ts) >= thirtyDaysAgo
      }
      return true
    })
    .sort((a, b) => (new Date(b.created_at||0).getTime()) - (new Date(a.created_at||0).getTime()))

  const archiveCards = filtered
    .filter(c => {
      if (resolveCol(c) !== "done") return false
      const ts = c.completed_at || c.created_at
      if (!ts) return false
      return new Date(ts) < thirtyDaysAgo
    })
    .sort((a, b) => (new Date(b.created_at||0).getTime()) - (new Date(a.created_at||0).getTime()))

  const totalQueued = Object.entries(queues)
    .filter(([k]) => k.startsWith("queue.agent.") && !k.includes(".retry"))
    .reduce((s,[,v]) => s+v, 0)

  const fmtTs = (ts: string|null|undefined) => {
    if (!ts) return null
    const d = new Date(ts)
    return {date: d.toLocaleDateString("en-US",{month:"short",day:"numeric",year:"numeric"}), time: d.toLocaleTimeString("en-US",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}
  }

  return (
    <div style={{height:"100vh",display:"flex",flexDirection:"column",background:"#0d0d16",color:"#e2e8f0",fontFamily:"monospace"}}>
      
      {/* Header */}
      <div style={{padding:"12px 20px",borderBottom:"1px solid #1e1e30",background:"#0a0a12",flexShrink:0}}>
        <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:10}}>
          <span style={{fontSize:15,fontWeight:700,letterSpacing:"0.1em",color:"#7c3aed"}}>◈ AGENT KANBAN</span>
          {totalQueued > 0 && <span style={{background:"#f59e0b22",border:"1px solid #f59e0b55",color:"#f59e0b",fontSize:11,padding:"2px 8px",borderRadius:4}}>{totalQueued} in redis queues</span>}
          <span style={{fontSize:11,color:"#4b5563",marginLeft:"auto"}}>updated {lastUpdate} · {filtered.length} cards</span>
          <button onClick={load} style={{background:"#1e1e30",border:"1px solid #2d2d45",color:"#94a3b8",padding:"4px 12px",borderRadius:6,cursor:"pointer",fontSize:12}}>↺</button>
        </div>
        <div style={{display:"flex",gap:8,flexWrap:"wrap"}}>
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search..." style={{flex:"1 1 200px",background:"#1a1a2e",border:"1px solid #2d2d45",color:"#e2e8f0",padding:"5px 10px",borderRadius:6,fontSize:12,fontFamily:"monospace"}} />
          <select value={filterAgent} onChange={e=>setFilterAgent(e.target.value)} style={{background:"#1a1a2e",border:"1px solid #2d2d45",color:"#94a3b8",padding:"5px 8px",borderRadius:6,fontSize:12}}>
            <option value="">All Agents</option>
            {agents.map(a=><option key={a} value={a}>{a}</option>)}
          </select>
          <select value={filterStatus} onChange={e=>setFilterStatus(e.target.value)} style={{background:"#1a1a2e",border:"1px solid #2d2d45",color:"#94a3b8",padding:"5px 8px",borderRadius:6,fontSize:12}}>
            <option value="">All Status</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
          <button onClick={()=>setFilterDeliverable(f=>!f)} style={{background:filterDeliverable?"#1e3a1e":"#1a1a2e",border:`1px solid ${filterDeliverable?"#10b98160":"#2d2d45"}`,color:filterDeliverable?"#34d399":"#4b5563",padding:"5px 10px",borderRadius:6,cursor:"pointer",fontSize:11,fontFamily:"monospace"}}>
            📎 Has Deliverable
          </button>
          <select value={filterModel} onChange={e=>setFilterModel(e.target.value)} style={{background:"#1a1a2e",border:"1px solid #2d2d45",color:"#94a3b8",padding:"5px 8px",borderRadius:6,fontSize:11,maxWidth:160}}>
            <option value="">All Models</option>
            {models.map(m=><option key={m} value={m}>{m.split("/").pop()?.slice(0,24)}</option>)}
          </select>
          {(search||filterAgent||filterStatus||filterModel||filterDeliverable) && <button onClick={()=>{setSearch("");setFilterAgent("");setFilterStatus("");setFilterModel("");setFilterDeliverable(false)}} style={{background:"#2d1515",border:"1px solid #5a2020",color:"#f87171",padding:"5px 10px",borderRadius:6,cursor:"pointer",fontSize:11}}>✕ Clear</button>}
        </div>
      </div>

      {/* Board — left-click draggable */}
      {loading ? (
        <div style={{flex:1,display:"flex",alignItems:"center",justifyContent:"center",color:"#4b5563"}}>Loading...</div>
      ) : (
        <div
          ref={boardRef}
          onMouseDown={onBoardMouseDown}
          onMouseMove={onBoardMouseMove}
          onMouseUp={onBoardMouseUp}
          onMouseLeave={onBoardMouseUp}
          style={{flex:1,display:"flex",overflowX:"auto",overflowY:"hidden",cursor:"grab",userSelect:"none"}}
        >
          {COLS.map(col => {
            const colCards = byCol(col.id)
            return (
              <div key={col.id} style={{flex:"0 0 300px",display:"flex",flexDirection:"column",borderRight:"1px solid #1e1e30",height:"100%"}}>
                {/* Col header */}
                <div style={{padding:"10px 14px",background:"#0f0f1a",borderBottom:"1px solid #1e1e30",display:"flex",alignItems:"center",gap:8,flexShrink:0}}>
                  <span style={{color:col.color,fontSize:12}}>●</span>
                  <span style={{fontSize:11,fontWeight:700,color:"#94a3b8",letterSpacing:"0.08em",textTransform:"uppercase"}}>{col.label}</span>
                  <span style={{marginLeft:"auto",background:col.color+"22",border:`1px solid ${col.color}44`,color:col.color,fontSize:10,padding:"1px 6px",borderRadius:10,fontWeight:700}}>{colCards.length}</span>
                </div>
                {/* Cards — each card has flexShrink:0 so they never compress */}
                <div style={{flex:1,overflowY:"auto",padding:8,display:"flex",flexDirection:"column",gap:6}}>
                  {colCards.length === 0 && <div style={{color:"#2d3748",fontSize:11,textAlign:"center",padding:20,flexShrink:0}}>empty</div>}
                  {colCards.map(card => {
                    const ac = AGENT_COLORS[card.agent]||"#94a3b8"
                    const isFail = card.status === "failed"
                    const isRun = card.status === "running" || card.status === "pending"
                    return (
                      <div key={card.id} onClick={()=>setModalCard(card)}
                        style={{
                          flexShrink:0,
                          background: isFail?"#200f0f":isRun?"#1a1400":"#1c1c2e",
                          border:`1px solid ${isFail?"#5a1f1f":isRun?"#6b5000":"#2d2d45"}`,
                          borderRadius:8,cursor:"pointer",
                          boxShadow:"0 2px 4px rgba(0,0,0,0.5)",
                        }}>
                        <div style={{padding:"10px 12px"}}>
                          <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:6}}>
                            {card.agent && <span style={{background:ac+"30",border:`1px solid ${ac}70`,color:ac,fontSize:10,padding:"2px 6px",borderRadius:3,fontWeight:700,letterSpacing:"0.05em",textTransform:"uppercase"}}>{card.agent}</span>}
                            <span style={{fontSize:10,padding:"2px 6px",borderRadius:3,background:isFail?"#5a1f1f":isRun?"#5a4a00":"#1e3a2e",color:isFail?"#fca5a5":isRun?"#fcd34d":"#86efac"}}>{card.status}</span>
                            {card.has_deliverable && <span style={{fontSize:11}}>📎</span>}
                            {isRun && <span style={{width:6,height:6,borderRadius:"50%",background:"#f59e0b",display:"inline-block"}} />}
                            <span style={{marginLeft:"auto",fontSize:9,color:"#374151"}}>{card.id.slice(0,8)}</span>
                          </div>
                          <div style={{fontSize:11,color:"#e2e8f0",lineHeight:1.4,marginBottom:6,fontWeight:500}}>
                            {(card.clickup_task_name || card.instruction || card.agent || "—").slice(0,120)}
                          </div>
                          {card.clickup_task_id && (
                            <div style={{marginBottom:5}}>
                              <a href={`https://app.clickup.com/t/${card.clickup_task_id}`} target="_blank" rel="noopener noreferrer"
                                onClick={e=>e.stopPropagation()}
                                style={{fontSize:10,color:"#60a5fa",textDecoration:"none"}}>
                                ⧉ {card.clickup_task_name||card.clickup_task_id}
                              </a>
                            </div>
                          )}
                          <div style={{display:"flex",gap:4,flexWrap:"wrap"}}>
                            {card.model && <span style={{fontSize:10,color:"#94a3b8",background:"#1e1e35",border:"1px solid #3d3d60",padding:"1px 5px",borderRadius:3}}>{card.model.split("/").pop()?.slice(0,18)}</span>}
                            {card.quality_score != null && <span style={{fontSize:10,padding:"1px 5px",borderRadius:3,background:card.quality_score>=7?"#0f291f":"#291a0f",color:card.quality_score>=7?"#86efac":"#fcd34d",border:`1px solid ${card.quality_score>=7?"#16a34a":"#d97706"}`}}>Q:{card.quality_score}/10</span>}
                            {card.cost_usd > 0 && <span style={{fontSize:10,color:"#94a3b8",background:"#1e1e35",border:"1px solid #3d3d60",padding:"1px 5px",borderRadius:3}}>{fmtCost(card.cost_usd)}</span>}
                            {card.duration_sec != null && <span style={{fontSize:10,color:"#94a3b8",background:"#1e1e35",border:"1px solid #3d3d60",padding:"1px 5px",borderRadius:3}}>{fmtDur(card.duration_sec)}</span>}
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}

          {/* Archive column */}
          <div style={{flex:"0 0 300px",display:"flex",flexDirection:"column",borderRight:"1px solid #1e1e30",height:"100%"}}>
            <div onClick={()=>setArchiveOpen(o=>!o)} style={{padding:"10px 14px",background:"#0f0f1a",borderBottom:"1px solid #1e1e30",display:"flex",alignItems:"center",gap:8,flexShrink:0,cursor:"pointer",userSelect:"none"}}>
              <span style={{color:"#374151",fontSize:12}}>●</span>
              <span style={{fontSize:11,fontWeight:700,color:"#4b5563",letterSpacing:"0.08em",textTransform:"uppercase"}}>Archive</span>
              <span style={{fontSize:9,color:"#374151",marginLeft:2}}>&gt;30d</span>
              <span style={{marginLeft:"auto",background:"#37415122",border:"1px solid #37415144",color:"#4b5563",fontSize:10,padding:"1px 6px",borderRadius:10,fontWeight:700}}>{archiveCards.length}</span>
              <span style={{color:"#374151",fontSize:11,marginLeft:4}}>{archiveOpen?"▲":"▼"}</span>
            </div>
            <div style={{flex:1,overflowY:"auto",padding:archiveOpen?8:0,display:"flex",flexDirection:"column",gap:6}}>
              {!archiveOpen && <div style={{color:"#1e293b",fontSize:10,textAlign:"center",padding:"14px 8px",cursor:"pointer",flexShrink:0}} onClick={()=>setArchiveOpen(true)}>click header to expand</div>}
              {archiveOpen && archiveCards.length===0 && <div style={{color:"#2d3748",fontSize:11,textAlign:"center",padding:20,flexShrink:0}}>no archived cards</div>}
              {archiveOpen && archiveCards.map(card=>{
                const ac=AGENT_COLORS[card.agent]||"#94a3b8"
                return (
                  <div key={card.id} onClick={()=>setModalCard(card)} style={{flexShrink:0,background:"#141420",border:"1px solid #22223a",borderRadius:8,cursor:"pointer",opacity:0.75}}>
                    <div style={{padding:"10px 12px"}}>
                      <div style={{display:"flex",alignItems:"center",gap:6,marginBottom:6}}>
                        {card.agent && <span style={{background:ac+"20",border:`1px solid ${ac}40`,color:ac,fontSize:9,padding:"1px 5px",borderRadius:3,fontWeight:700,textTransform:"uppercase"}}>{card.agent}</span>}
                        <span style={{fontSize:9,padding:"1px 5px",borderRadius:3,background:"#1e3a2e",color:"#6ee7b7"}}>{card.status}</span>
                        {card.has_deliverable && <span style={{fontSize:11}}>📎</span>}
                        <span style={{marginLeft:"auto",fontSize:9,color:"#374151"}}>{card.id.slice(0,8)}</span>
                      </div>
                      <div style={{fontSize:11,color:"#6b7280",lineHeight:1.4,marginBottom:6}}>{(card.clickup_task_name||card.instruction||card.agent||"—").slice(0,80)}</div>
                      <div style={{display:"flex",gap:4,flexWrap:"wrap"}}>
                        {card.quality_score!=null && <span style={{fontSize:9,padding:"1px 4px",borderRadius:3,background:"#0f291f",color:"#6ee7b7",border:"1px solid #065f46"}}>Q:{card.quality_score}/10</span>}
                        {card.cost_usd>0 && <span style={{fontSize:9,color:"#374151",background:"#1a1a2e",border:"1px solid #2d2d45",padding:"1px 4px",borderRadius:3}}>{fmtCost(card.cost_usd)}</span>}
                        {(card.completed_at||card.created_at) && <span style={{fontSize:9,color:"#374151",background:"#1a1a2e",border:"1px solid #2d2d45",padding:"1px 4px",borderRadius:3}}>{new Date((card.completed_at||card.created_at)!).toLocaleDateString()}</span>}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      )}

      {/* Detail Modal */}
      {modalCard && (() => {
        const mc = modalCard
        const ac = AGENT_COLORS[mc.agent]||"#94a3b8"
        const isFail = mc.status === "failed"
        const isRun = mc.status === "running" || mc.status === "pending"
        return (
          <div onClick={e=>{if(e.target===e.currentTarget)setModalCard(null)}}
            style={{position:"fixed",inset:0,zIndex:50,background:"rgba(0,0,0,0.85)",backdropFilter:"blur(4px)",display:"flex",alignItems:"center",justifyContent:"center",padding:16}}>
            <div style={{width:"100%",maxWidth:860,maxHeight:"92vh",overflowY:"auto",background:"#13131e",border:`1px solid ${ac}40`,borderRadius:16,boxShadow:"0 25px 60px rgba(0,0,0,0.9)"}}>

              {/* Sticky header */}
              <div style={{position:"sticky",top:0,zIndex:10,background:"#13131e",padding:"16px 24px",borderBottom:"1px solid #1e1e30",display:"flex",alignItems:"center",gap:10}}>
                <span style={{width:12,height:12,borderRadius:"50%",background:ac,display:"inline-block",flexShrink:0}} />
                <span style={{background:ac+"20",border:`1px solid ${ac}40`,color:ac,fontSize:12,padding:"3px 8px",borderRadius:3,fontWeight:700,letterSpacing:"0.05em",textTransform:"uppercase"}}>{mc.agent}</span>
                <span style={{fontSize:12,padding:"3px 8px",borderRadius:3,background:isFail?"#5a1f1f":isRun?"#5a4a00":"#1e3a2e",color:isFail?"#f87171":isRun?"#fbbf24":"#6ee7b7"}}>{mc.status}</span>
                {mc.clickup_priority && <span style={{fontSize:11,color:"#6b7280",background:"#1a1a2e",border:"1px solid #2d2d45",padding:"2px 6px",borderRadius:3}}>{mc.clickup_priority}</span>}
                {mc.type && <span style={{fontSize:11,color:"#4b5563",background:"#1a1a2e",border:"1px solid #2d2d45",padding:"2px 6px",borderRadius:3}}>{mc.type}</span>}
                <button onClick={()=>setModalCard(null)} style={{marginLeft:"auto",background:"#1e1e30",border:"1px solid #2d2d45",color:"#94a3b8",width:32,height:32,borderRadius:6,cursor:"pointer",fontSize:16,display:"flex",alignItems:"center",justifyContent:"center"}}>✕</button>
              </div>

              <div style={{padding:"20px 24px",display:"flex",flexDirection:"column",gap:16}}>

                {/* IDs */}
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                  <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Job ID</div>
                    <div style={{fontSize:12,color:"#9ca3af",fontFamily:"monospace",wordBreak:"break-all"}}>{mc.id}</div>
                  </div>
                  {mc.chain_id && <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Chain ID</div>
                    <div style={{fontSize:12,color:"#9ca3af",fontFamily:"monospace",wordBreak:"break-all"}}>{mc.chain_id}</div>
                  </div>}
                </div>

                {/* Timestamps */}
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
                  {([["Created",mc.created_at],["Started",mc.started_at],["Completed",mc.completed_at]] as [string,string|null][]).map(([lbl,ts])=>{
                    const f=fmtTs(ts)
                    return (
                      <div key={lbl} style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                        <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>{lbl}</div>
                        {f ? (<><div style={{fontSize:14,color:"#cbd5e1",fontWeight:600}}>{f.date}</div><div style={{fontSize:12,color:"#64748b",marginTop:2}}>{f.time}</div></>) : <div style={{fontSize:13,color:"#374151"}}>—</div>}
                      </div>
                    )
                  })}
                </div>

                {/* Performance */}
                <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Performance</div>
                  <div style={{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:8}}>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",textAlign:"center"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5}}>Duration</div>
                      <div style={{fontSize:18,fontWeight:700,color:"#e2e8f0"}}>{fmtDur(mc.duration_sec)||"—"}</div>
                    </div>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",textAlign:"center"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5}}>Cost</div>
                      <div style={{fontSize:18,fontWeight:700,color:"#00ff88",textShadow:"0 0 10px #00ff8870,0 0 20px #00ff8840"}}>{fmtCost(mc.cost_usd)||"—"}</div>
                    </div>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",textAlign:"center"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5}}>Tokens In</div>
                      <div style={{fontSize:18,fontWeight:700,color:"#e2e8f0"}}>{mc.tokens_input||"—"}</div>
                    </div>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",textAlign:"center"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5}}>Tokens Out</div>
                      <div style={{fontSize:18,fontWeight:700,color:"#e2e8f0"}}>{mc.tokens_output||"—"}</div>
                    </div>
                  </div>
                  <div style={{marginTop:8,background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:8,textTransform:"uppercase",letterSpacing:"0.05em"}}>Quality Score &amp; Eval Loops</div>
                    <div style={{display:"flex",alignItems:"center",gap:10}}>
                      {mc.quality_score != null ? (<>
                        <div style={{flex:1,height:8,background:"#1e1e30",borderRadius:99,overflow:"hidden"}}>
                          <div style={{height:"100%",width:`${mc.quality_score*10}%`,background:mc.quality_score>=8?"#10b981":mc.quality_score>=6?"#f59e0b":"#ef4444",borderRadius:99}} />
                        </div>
                        <span style={{fontSize:16,fontWeight:700,color:mc.quality_score>=8?"#10b981":mc.quality_score>=6?"#f59e0b":"#ef4444"}}>{mc.quality_score}/10</span>
                      </>) : <span style={{fontSize:13,color:"#374151",flex:1}}>No quality score recorded</span>}
                      <span style={{fontSize:12,color:mc.eval_loops>0?"#f59e0b":"#374151",background:"#1e1e30",padding:"2px 8px",borderRadius:4}}>{mc.eval_loops||0} eval loops</span>
                    </div>
                  </div>
                </div>

                {/* Model + retry + updated */}
                <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr",gap:8}}>
                  {mc.model && <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Model</div>
                    <div style={{fontSize:13,color:"#9ca3af",fontFamily:"monospace"}}>{mc.model}</div>
                  </div>}
                  <div style={{background:(mc.retry_count??0)>0?"#291a0f":"#1a1a2e",border:(mc.retry_count??0)>0?"1px solid #92400e40":"none",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Retries</div>
                    <div style={{fontSize:16,fontWeight:700,color:(mc.retry_count??0)>0?"#fbbf24":"#374151"}}>{mc.retry_count??0}</div>
                  </div>
                  {mc.updated_at && <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Updated</div>
                    <div style={{fontSize:13,color:"#64748b"}}>{fmtTs(mc.updated_at)?.date}</div>
                    <div style={{fontSize:11,color:"#374151"}}>{fmtTs(mc.updated_at)?.time}</div>
                  </div>}
                </div>

                {/* ClickUp section */}
                <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>ClickUp</div>
                  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8,marginBottom:mc.clickup_task_name?8:0}}>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Task ID</div>
                      <div style={{fontSize:12,color:"#9ca3af",fontFamily:"monospace"}}>{mc.clickup_task_id||"—"}</div>
                    </div>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Priority</div>
                      <div style={{fontSize:13,color:"#9ca3af"}}>{mc.clickup_priority||"—"}</div>
                    </div>
                    <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px"}}>
                      <div style={{fontSize:11,color:"#4b5563",marginBottom:5,textTransform:"uppercase",letterSpacing:"0.05em"}}>Has Deliverable</div>
                      <div style={{fontSize:14,fontWeight:700,color:mc.has_deliverable?"#34d399":"#4b5563"}}>{mc.has_deliverable?"✓ Yes":"✗ No"}</div>
                    </div>
                  </div>
                  {mc.clickup_task_name && <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",display:"flex",alignItems:"center",gap:10}}>
                    <span style={{fontSize:14,color:"#e2e8f0",flex:1}}>{mc.clickup_task_name}</span>
                    <a href={`https://app.clickup.com/t/${mc.clickup_task_id}`} target="_blank" rel="noopener noreferrer"
                      style={{fontSize:12,color:"#60a5fa",border:"1px solid #3b82f640",background:"#3b82f610",padding:"4px 10px",borderRadius:4,textDecoration:"none",whiteSpace:"nowrap"}}>Open ↗</a>
                  </div>}
                </div>

                {/* Deliverable paths — always shown */}
                <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Deliverable</div>
                  {mc.gdrive_url ? <div style={{background:"#0f291f",border:"1px solid #06573640",borderRadius:8,padding:"10px 14px",display:"flex",alignItems:"center",gap:10,marginBottom:mc.report_path?6:0}}>
                    <span style={{fontSize:16}}>📄</span>
                    <span style={{fontSize:13,color:"#34d399",flex:1}}>Google Drive Document</span>
                    <a href={mc.gdrive_url} target="_blank" rel="noopener noreferrer"
                      style={{fontSize:12,color:"#34d399",border:"1px solid #10b98140",background:"#10b98110",padding:"4px 10px",borderRadius:4,textDecoration:"none",whiteSpace:"nowrap"}}>View Doc ↗</a>
                  </div> : <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",fontSize:13,color:"#374151"}}>No Google Drive document</div>}
                  {mc.report_path ? <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",fontSize:12,color:"#64748b",wordBreak:"break-all",marginTop:mc.gdrive_url?0:0}}>💾 {mc.report_path}</div>
                  : !mc.gdrive_url && null}
                </div>

                {/* Chain context */}
                {(mc.chain_target || mc.chain_summary) && <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Chain Context</div>
                  {mc.chain_target && <div style={{background:"#1a1a2e",borderRadius:8,padding:"10px 14px",marginBottom:6,display:"flex",gap:10}}>
                    <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",minWidth:48,paddingTop:2}}>Target</div>
                    <div style={{fontSize:14,color:"#cbd5e1"}}>{mc.chain_target}</div>
                  </div>}
                  {mc.chain_summary && <div style={{background:"#1a1a2e",borderRadius:8,padding:"12px 14px"}}>
                    <div style={{fontSize:11,color:"#4b5563",marginBottom:8,textTransform:"uppercase",letterSpacing:"0.05em"}}>CEO Summary</div>
                    <div style={{fontSize:14,color:"#9ca3af",lineHeight:1.7,maxHeight:200,overflowY:"auto",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{mc.chain_summary}</div>
                  </div>}
                </div>}

                {/* Chain steps */}
                {mc.chain_steps && mc.chain_steps.length > 0 && <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Chain Steps ({mc.chain_steps.length})</div>
                  <div style={{display:"flex",flexDirection:"column",gap:4}}>
                    {mc.chain_steps.map((step,i)=>{
                      const sc=AGENT_COLORS[step.agent]||"#94a3b8"
                      return (
                        <div key={i} style={{background:"#1a1a2e",borderRadius:6,padding:"8px 14px",display:"flex",alignItems:"center",gap:10}}>
                          <span style={{width:7,height:7,borderRadius:"50%",background:sc,flexShrink:0,display:"inline-block"}} />
                          <span style={{fontSize:13,color:sc,fontWeight:700,textTransform:"uppercase",minWidth:70}}>{step.agent}</span>
                          <span style={{fontSize:12,padding:"2px 7px",borderRadius:3,background:step.step_status==="completed"?"#1e3a2e":step.step_status==="running"?"#5a4a00":"#1a1a2e",color:step.step_status==="completed"?"#6ee7b7":step.step_status==="running"?"#fbbf24":"#6b7280"}}>{step.step_status}</span>
                          {step.step_started && <span style={{marginLeft:"auto",fontSize:11,color:"#374151"}}>{new Date(step.step_started).toLocaleTimeString("en-US",{hour:"2-digit",minute:"2-digit"})}</span>}
                        </div>
                      )
                    })}
                  </div>
                </div>}

                {/* Task instructions — scrollable */}
                {mc.instruction && <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Task Instructions</div>
                  <div style={{background:"#1a1a2e",borderRadius:8,padding:"14px 16px",fontSize:14,color:"#cbd5e1",lineHeight:1.8,maxHeight:320,overflowY:"auto",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{mc.instruction}</div>
                </div>}

                {/* Result summary — scrollable */}
                {mc.result_summary && <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Result / Output</div>
                  <div style={{background:"#1a1a2e",borderRadius:8,padding:"14px 16px",fontSize:14,color:"#9ca3af",lineHeight:1.8,maxHeight:400,overflowY:"auto",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{mc.result_summary}</div>
                </div>}

                {/* Error */}
                {mc.error_message && <div>
                  <div style={{fontSize:11,color:"#ef4444",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Error</div>
                  <div style={{background:"#200f0f",border:"1px solid #5a1f1f",borderRadius:8,padding:"14px 16px",fontSize:13,color:"#f87171",fontFamily:"monospace",lineHeight:1.6,maxHeight:200,overflowY:"auto",whiteSpace:"pre-wrap",wordBreak:"break-word"}}>{mc.error_message}</div>
                </div>}

                {/* Training feedback buttons */}
                <div>
                  <div style={{fontSize:11,color:"#4b5563",textTransform:"uppercase",letterSpacing:"0.05em",marginBottom:8}}>Training Feedback</div>
                  <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
                    <button onClick={async()=>{await fetch(`/api/kanban/feedback/${mc.id}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rating:"poor",job_id:mc.id,agent:mc.agent,model:mc.model})});alert("Marked as poor quality")}}
                      style={{background:"#2d1515",border:"1px solid #5a2020",color:"#f87171",padding:"10px 8px",borderRadius:8,cursor:"pointer",fontSize:12,fontFamily:"monospace"}}>
                      👎 Poor Quality
                    </button>
                    <button onClick={async()=>{await fetch(`/api/kanban/feedback/${mc.id}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rating:"acceptable",job_id:mc.id,agent:mc.agent,model:mc.model})});alert("Marked as acceptable")}}
                      style={{background:"#1a1a2e",border:"1px solid #2d2d45",color:"#94a3b8",padding:"10px 8px",borderRadius:8,cursor:"pointer",fontSize:12,fontFamily:"monospace"}}>
                      👌 Acceptable
                    </button>
                    <button onClick={async()=>{await fetch(`/api/kanban/feedback/${mc.id}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({rating:"elite",job_id:mc.id,agent:mc.agent,model:mc.model})});alert("Saved to agent memory as elite example")}}
                      style={{background:"#0f291f",border:"1px solid #065f46",color:"#34d399",padding:"10px 8px",borderRadius:8,cursor:"pointer",fontSize:12,fontFamily:"monospace"}}>
                      ⭐ Elite
                    </button>
                  </div>
                  <div style={{marginTop:6,fontSize:10,color:"#374151",textAlign:"center"}}>Elite saves output to agent memory. Poor flags for review.</div>
                </div>

                {/* Kill button */}
                {isRun && <button onClick={async()=>{if(!confirm("Kill this job?"))return;await fetch(`/api/kanban/kill/${mc.id}`,{method:"POST"});setModalCard(null);load()}}
                  style={{background:"#2d1515",border:"1px solid #5a2020",color:"#f87171",padding:"12px",borderRadius:8,cursor:"pointer",fontSize:14,fontFamily:"monospace",width:"100%"}}>
                  ✕ Kill Job
                </button>}
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
