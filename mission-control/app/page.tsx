"use client"

import { useEffect, useState } from "react"

const AGENTS = ["jarvis","research","revenue","sales","growth","product","legal","systems","code","voice"]
const C    = "rgb(156,172,194)"
const CDim = "rgb(130,145,162)"

const AGENT_MODELS: Record<string,string> = {
  jarvis:"qwen3.5-122b", research:"kimi-k2.5", revenue:"qwen3.5-397b",
  sales:"llama-4-maverick", growth:"qwen3.5-397b", product:"qwen3-coder-480b",
  legal:"qwen3.5-397b", systems:"qwen3-coder-480b", code:"qwen3-coder-480b", voice:"llama-4-maverick",
}

type AState = "online_idle"|"working"|"error"
type AData  = { name:string; state:AState; tokToday:number; tokAvgDay:number; model:string; healthScore:number|null }

function Bar({v,max,col,empty}:{v:number;max:number;col:string;empty?:boolean}) {
  const pct = empty ? 0 : (max>0?Math.min(100,v/max*100):0)
  return (
    <div style={{height:"3px",background:"rgba(255,255,255,0.08)",borderRadius:"2px",overflow:"hidden"}}>
      <div style={{height:"100%",width:`${pct}%`,background:empty?"rgba(255,255,255,0.0)":col,borderRadius:"2px",transition:"width 0.6s"}}/>
    </div>
  )
}

function AgentRow({a,mx}:{a:AData;mx:number}) {
  const cfg:{[k:string]:{dot:string;glow:string;pulse:boolean;tc:string;tb:string;tbr:string;tl:string}} = {
    online_idle:{dot:"#22c55e",glow:"0 0 5px #22c55e",pulse:false,tl:"online",  tc:"#4ade80",tb:"rgba(34,197,94,0.12)",  tbr:"rgba(34,197,94,0.28)"},
    working:    {dot:"#f59e0b",glow:"0 0 7px #f59e0b",pulse:true, tl:"online",  tc:"#4ade80",tb:"rgba(34,197,94,0.12)",  tbr:"rgba(34,197,94,0.28)"},
    error:      {dot:"#ef4444",glow:"0 0 5px #ef4444",pulse:false,tl:"error",   tc:"#f87171",tb:"rgba(239,68,68,0.12)",  tbr:"rgba(239,68,68,0.28)"},
  }
  const c   = cfg[a.state] || cfg.online_idle
  const fmt = (n:number) => n>=1000?`${(n/1000).toFixed(1)}k`:n>0?String(n):"0"
  const hasData = a.tokToday > 0 || a.tokAvgDay > 0

  return (
    <div style={{padding:"9px 0",borderBottom:"1px solid rgba(255,255,255,0.05)"}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between"}}>
        <div style={{display:"flex",alignItems:"center",gap:"9px"}}>
          <div style={{width:"7px",height:"7px",borderRadius:"50%",flexShrink:0,
            background:c.dot,boxShadow:c.glow,
            animation:c.pulse?"pulse 1.4s ease-in-out infinite":"none"}}/>
          <div>
            <span style={{fontSize:"13px",color:C,textTransform:"capitalize",fontWeight:500}}>{a.name}</span>
            <div style={{fontSize:"9px",color:CDim,marginTop:"1px"}}>
              {a.model}
              {a.healthScore !== null && (
                <span style={{marginLeft:"6px",color:a.healthScore>=0.9?"#34d399":a.healthScore>=0.7?"#fbbf24":"#f87171",fontWeight:600}}>
                  ● {(a.healthScore*100).toFixed(0)}%
                </span>
              )}
            </div>
          </div>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:"5px"}}>
          <span style={{fontSize:"9px",padding:"2px 7px",borderRadius:"10px",fontWeight:600,
            background:c.tb,border:`1px solid ${c.tbr}`,color:c.tc}}>{c.tl}</span>
          {a.state==="working"&&(
            <span style={{fontSize:"9px",padding:"2px 7px",borderRadius:"10px",fontWeight:700,
              background:"rgba(245,158,11,0.18)",border:"1px solid rgba(245,158,11,0.38)",
              color:"#fbbf24",animation:"pulse 1.4s infinite"}}>⚡ working</span>
          )}
          <span style={{fontSize:"10px",color:CDim,fontVariantNumeric:"tabular-nums",minWidth:"28px",textAlign:"right"}}>
            {hasData?fmt(a.tokToday):"—"}
          </span>
        </div>
      </div>
      {/* Always show bars - empty placeholder if no data */}
      <div style={{marginTop:"5px",paddingLeft:"16px",display:"flex",flexDirection:"column",gap:"4px"}}>
        <div>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:"2px"}}>
            <span style={{fontSize:"9px",color:CDim}}>Today</span>
            <span style={{fontSize:"9px",color:CDim}}>{fmt(a.tokToday)}</span>
          </div>
          <Bar v={a.tokToday} max={mx} col="#7c3aed" empty={!hasData}/>
        </div>
        <div>
          <div style={{display:"flex",justifyContent:"space-between",marginBottom:"2px"}}>
            <span style={{fontSize:"9px",color:CDim}}>Daily Avg (7d)</span>
            <span style={{fontSize:"9px",color:CDim}}>{fmt(a.tokAvgDay)}</span>
          </div>
          <Bar v={a.tokAvgDay} max={mx} col="#4f46e5" empty={!hasData}/>
        </div>
      </div>
    </div>
  )
}

export default function Home() {
  const [jm,setJm]           = useState<any>({})
  const [agents,setAgents]   = useState<AData[]>(
    AGENTS.map(n=>({name:n,state:"online_idle" as AState,tokToday:0,tokAvgDay:0,model:AGENT_MODELS[n]||"—",healthScore:null}))
  )
  const [mData,setMData]     = useState<{t:Record<string,number>;y:Record<string,number>;w:Record<string,number>}>({t:{},y:{},w:{}})
  const [monthCost,setMC]    = useState(0)
  const [todayCost,setTC]    = useState(0)
  const [tokTotal,setTokTotal]= useState(0)
  const [reqToday,setReq]    = useState(0)
  const [updated,setUpdated] = useState<Date|null>(null)

  const load = async () => {
    try {
      const [mR,uR,lR,hR] = await Promise.all([
        fetch("/api/metrics"),
        fetch("/api/metrics/usage"),
        fetch("/api/metrics/llm").catch(()=>null),
        fetch("/api/metrics/model_health").catch(()=>null),
      ])
      const m = mR.ok?await mR.json():{}
      const u = uR.ok?await uR.json():{}
      const l = lR&&lR.ok?await lR.json():{}
      const h = hR&&hR.ok?await hR.json():{}
      const modelHealthMap = (h.models||{}) as Record<string,any>

      setJm(m)
      setTC(u.last_24_hours?.cost_usd??0)
      setTokTotal((u.all_time?.tokens_input??0)+(u.all_time?.tokens_output??0))
      setMC(l.month_cost??0)
      setReq(l.total_requests_today??0)

      // Model charts from /metrics/llm
      const mt = l.by_model_today    ?? {}
      const my = l.by_model_yesterday?? {}
      const mw = l.by_model_week     ?? {}
      setMData({
        t: Object.fromEntries(Object.entries(mt as Record<string,any>).map(([k,v])=>[k,(v as any).tokens_total??0])),
        y: Object.fromEntries(Object.entries(my as Record<string,any>).map(([k,v])=>[k,(v as any).tokens_total??0])),
        w: Object.fromEntries(Object.entries(mw as Record<string,any>).map(([k,v])=>[k,(v as any).tokens_total??0])),
      })

      // Agent token data from /metrics/llm by_agent
      const at  = (l.by_agent_today ?? {}) as Record<string,any>
      const aw  = (l.by_agent_week  ?? {}) as Record<string,any>

      // Agent live states from /metrics/agents/live
      let sm: Record<string,string> = {}
      try {
        const sr = await fetch("/api/metrics/agents/live")
        if (sr.ok) { const sd = await sr.json(); sm = sd.states??{} }
      } catch {}

      // Build model->health lookup
      const agentModelLookup: Record<string,string> = {
        jarvis:"qwen/qwen3.5-122b-a10b", research:"qwen/qwen3.5-397b-a17b",
        revenue:"nvidia/llama-3.3-nemotron-super-49b-v1", sales:"mistralai/mistral-large-3-675b-instruct-2512",
        growth:"nvidia/llama-3.3-nemotron-super-49b-v1", product:"qwen/qwen3.5-397b-a17b",
        legal:"nvidia/llama-3.3-nemotron-super-49b-v1", systems:"qwen/qwen3-coder-480b-a35b-instruct",
        code:"qwen/qwen3-coder-480b-a35b-instruct", voice:"meta/llama-4-maverick-17b-128e-instruct",
      }
      setAgents(AGENTS.map(n => {
        const fullModel = agentModelLookup[n] || AGENT_MODELS[n] || ""
        const mh = modelHealthMap[fullModel]
        const healthScore = mh ? mh.health_score : null
        return {
          name:      n,
          state:     (sm[n]==="working"?"working":"online_idle") as AState,
          tokToday:  at[n]?.tokens_total ?? 0,
          tokAvgDay: Math.round((aw[n]?.tokens_total ?? 0) / 7),
          model:     fullModel.split("/").pop() || "—",
          healthScore,
        }
      }))

      setUpdated(new Date())
    } catch(e) { console.error(e) }
  }

  const pollLive = async () => {
    try {
      const r = await fetch("/api/metrics/agents/live")
      if(!r.ok) return
      const d = await r.json()
      const sm = d.states??{}
      setAgents(p=>p.map(a=>({
        ...a,
        state:(sm[a.name]==="working"?"working":a.state==="error"?"error":"online_idle") as AState
      })))
    } catch {}
  }

  useEffect(()=>{
    load()
    const t1=setInterval(load,15000)
    const t2=setInterval(pollLive,3000)
    return()=>{clearInterval(t1);clearInterval(t2)}
  },[])

  const working   = agents.filter(a=>a.state==="working").length
  const mx        = Math.max(...agents.map(a=>Math.max(a.tokToday,a.tokAvgDay)),1)
  const allModels = Array.from(new Set([...Object.keys(mData.t),...Object.keys(mData.w)])).slice(0,5)
  const maxW      = Math.max(...allModels.map(m=>mData.w[m]??0),1)
  const fmt       = (n:number) => n>=1000?`${(n/1000).toFixed(1)}k`:n>0?String(n):"—"
  const activeTasks = (jm.running_jobs??0)+(jm.pending_jobs??0)

  const card:React.CSSProperties = {
    background:"rgba(10,14,26,0.9)",border:"1px solid rgba(255,255,255,0.08)",
    borderRadius:"12px",padding:"16px 18px",display:"flex",flexDirection:"column",gap:"6px"
  }

  return (
    <div style={{padding:"22px 26px",height:"100%",overflowY:"auto"}}>
      <style>{`@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>

      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"18px"}}>
        <div>
          <h1 style={{fontSize:"18px",fontWeight:700,color:"#f1f5f9",marginBottom:"2px"}}>Mission Control</h1>
          <p style={{fontSize:"11px",color:CDim}}>Silent Empire AI — autonomous agent infrastructure</p>
        </div>
        <div style={{display:"flex",alignItems:"center",gap:"8px"}}>
          {updated&&<span style={{fontSize:"10px",color:CDim}}>{updated.toLocaleTimeString()}</span>}
          <div style={{width:"7px",height:"7px",borderRadius:"50%",background:"#22c55e",boxShadow:"0 0 6px #22c55e"}}/>
        </div>
      </div>

      <div style={{background:"rgba(124,58,237,0.07)",border:"1px solid rgba(124,58,237,0.15)",borderRadius:"12px",padding:"18px 22px",marginBottom:"18px"}}>
        <div style={{display:"flex",alignItems:"center",gap:"8px",flexWrap:"wrap",marginBottom:"6px"}}>
          <div style={{width:"7px",height:"7px",borderRadius:"50%",background:"#22c55e",boxShadow:"0 0 8px #22c55e",animation:"pulse 2s infinite"}}/>
          <span style={{fontSize:"10px",color:"#34d399",fontWeight:700,letterSpacing:"0.1em",textTransform:"uppercase"}}>All Systems Operational</span>
          {working>0&&<span style={{fontSize:"10px",color:"#fbbf24",fontWeight:600,background:"rgba(245,158,11,0.15)",border:"1px solid rgba(245,158,11,0.3)",padding:"1px 8px",borderRadius:"10px",animation:"pulse 1.4s infinite"}}>⚡ {working} agent{working>1?"s":""} working</span>}
        </div>
        <h2 style={{fontSize:"18px",fontWeight:700,color:"#f1f5f9",marginBottom:"3px"}}>Your AI Company Is Running</h2>
        <p style={{fontSize:"12px",color:C,lineHeight:"1.6"}}>{AGENTS.length} agents online — researching, executing, building autonomously 24/7.</p>
      </div>

      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:"8px",marginBottom:"8px"}}>
        {[
          {label:"Today's Cost",      value:`$${todayCost.toFixed(4)}`, accent:"#a78bfa", sub:"Last 24 hours"},
          {label:"Current Month Cost", value:`$${monthCost.toFixed(4)}`, accent:"#7dd3fc", sub:new Date().toLocaleString("default",{month:"long",year:"numeric"})},
          {label:"Total Tokens",       value:tokTotal>0?fmt(tokTotal):"—", accent:"#34d399", sub:"All time"},
        ].map(s=>(
          <div key={s.label} style={card}>
            <div style={{fontSize:"10px",color:C,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.1em"}}>{s.label}</div>
            <div style={{fontSize:"22px",fontWeight:700,color:s.accent,lineHeight:1,fontVariantNumeric:"tabular-nums"}}>{s.value}</div>
            <div style={{fontSize:"10px",color:CDim}}>{s.sub}</div>
          </div>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:"8px",marginBottom:"18px"}}>
        {[
          {label:"Active Tasks",    value:activeTasks||"—",  accent:"#fbbf24", sub:"Running + queued"},
          {label:"Requests Today",  value:reqToday||"—",     accent:"#7dd3fc", sub:"LLM calls today"},
          {label:"Failed Tasks",    value:jm.failed_jobs??"—",accent:(jm.failed_jobs??0)>0?"#f87171":C, sub:"Errors"},
        ].map(s=>(
          <div key={s.label} style={card}>
            <div style={{fontSize:"10px",color:C,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.1em"}}>{s.label}</div>
            <div style={{fontSize:"22px",fontWeight:700,color:s.accent,lineHeight:1,fontVariantNumeric:"tabular-nums"}}>{s.value}</div>
            <div style={{fontSize:"10px",color:CDim}}>{s.sub}</div>
          </div>
        ))}
      </div>

      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"12px"}}>

        <div style={{...card,gap:0}}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:"10px"}}>
            <div style={{fontSize:"10px",color:C,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.1em"}}>Agent Roster</div>
            <div style={{fontSize:"9px",color:CDim}}>Green=online · ⚡=working · Red=error</div>
          </div>
          {agents.map(a=><AgentRow key={a.name} a={a} mx={mx}/>)}
        </div>

        <div style={{display:"flex",flexDirection:"column",gap:"12px"}}>

          <div style={{...card,flex:1}}>
            <div style={{fontSize:"10px",color:C,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:"12px"}}>Top Models by Token Use</div>
            {allModels.length===0?(
              <div style={{fontSize:"12px",color:CDim}}>Send messages to Jarvis to populate token data.</div>
            ):allModels.map((model,i)=>{
              const colors=["#7c3aed","#4f46e5","#6366f1","#8b5cf6","#a78bfa"]
              const col=colors[i]||colors[4]
              const td=mData.t[model]??0, yd=mData.y[model]??0, wk=mData.w[model]??0
              return (
                <div key={model} style={{marginBottom:"14px"}}>
                  <div style={{display:"flex",justifyContent:"space-between",marginBottom:"5px"}}>
                    <span style={{fontSize:"11px",color:C,overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap",maxWidth:"68%"}} title={model}>{model.split("/").pop()}</span>
                    <span style={{fontSize:"10px",color:CDim,flexShrink:0}}>{fmt(wk)} wk</span>
                  </div>
                  {([["Today",td,col],["Yesterday",yd,`${col}99`],["This Week",wk,`${col}55`]] as [string,number,string][]).map(([lbl,val,c2])=>(
                    <div key={lbl} style={{marginBottom:"3px"}}>
                      <div style={{display:"flex",justifyContent:"space-between"}}>
                        <span style={{fontSize:"9px",color:CDim}}>{lbl}</span>
                        <span style={{fontSize:"9px",color:CDim,fontVariantNumeric:"tabular-nums"}}>{fmt(val)}</span>
                      </div>
                      <div style={{height:"3px",background:"rgba(255,255,255,0.07)",borderRadius:"2px",overflow:"hidden",marginTop:"2px"}}>
                        <div style={{height:"100%",width:`${Math.min(100,(val/maxW)*100)}%`,background:c2,borderRadius:"2px",transition:"width 0.5s"}}/>
                      </div>
                    </div>
                  ))}
                </div>
              )
            })}
          </div>

          <div style={card}>
            <div style={{fontSize:"10px",color:C,fontWeight:700,textTransform:"uppercase",letterSpacing:"0.1em",marginBottom:"10px"}}>Quick Actions</div>
            {[{label:"Open Chat",href:"/chat",color:"#7c3aed"},{label:"View Agents",href:"/agents",color:"#4f46e5"},{label:"File Browser",href:"/files",color:"#059669"}].map(a=>(
              <a key={a.label} href={a.href} style={{textDecoration:"none",display:"block",marginBottom:"6px"}}>
                <div style={{padding:"10px 14px",borderRadius:"9px",background:"rgba(255,255,255,0.02)",border:"1px solid rgba(255,255,255,0.07)",display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                  <span style={{fontSize:"13px",color:C}}>{a.label}</span>
                  <span style={{color:a.color,fontSize:"15px"}}>→</span>
                </div>
              </a>
            ))}
          </div>

        </div>
      </div>
    </div>
  )
}
