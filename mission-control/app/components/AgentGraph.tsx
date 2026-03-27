"use client"

import React, { useEffect, useState, useCallback, useRef } from "react"
import ReactFlow, { Background, Controls, Node, Edge, Handle, Position } from "reactflow"
import "reactflow/dist/style.css"

const MAX_RETRIES = 3
const STALL_THRESHOLD = 10000
const RETRY_COOLDOWN = 4000

const FIXED_AGENTS = [
  { id: "jarvis",   label: "Jarvis" },
  { id: "research", label: "Research" },
  { id: "revenue",  label: "Revenue" },
  { id: "sales",    label: "Sales" },
  { id: "growth",   label: "Growth" },
  { id: "product",  label: "Product" },
  { id: "legal",    label: "Legal" },
  { id: "systems",  label: "Systems" },
  { id: "code",     label: "Code" },
  { id: "voice",    label: "Voice" },
]

// ── CUSTOM NODE ──
function AgentNode({ data }: { data: any }) {
  const isWorking = data.state === "working"
  const isError   = data.state === "error"
  const isJarvis  = data.id === "jarvis"

  return (
    <div style={{
      background: isWorking
        ? "rgba(34,197,94,0.12)"
        : isError
        ? "rgba(239,68,68,0.12)"
        : isJarvis
        ? "rgba(124,58,237,0.2)"
        : "rgba(10,14,25,0.85)",
      color: "#e2e8f0",
      border: isWorking
        ? "1.5px solid rgba(34,197,94,0.7)"
        : isError
        ? "1.5px solid rgba(239,68,68,0.6)"
        : isJarvis
        ? "1.5px solid rgba(124,58,237,0.8)"
        : "1px solid rgba(168,85,247,0.35)",
      borderRadius: "12px",
      padding: "10px 14px",
      fontSize: "12px",
      backdropFilter: "blur(10px)",
      boxShadow: isWorking
        ? "0 0 16px rgba(34,197,94,0.3)"
        : isJarvis
        ? "0 0 14px rgba(124,58,237,0.25)"
        : "0 0 8px rgba(168,85,247,0.1)",
      minWidth: "90px",
      textAlign: "center",
      transition: "all 0.3s ease",
      animation: isWorking ? "nodeGlow 2s ease-in-out infinite" : "none",
    }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />

      <div style={{ fontWeight: 600, color: isWorking ? "#4ade80" : isJarvis ? "#c4b5fd" : "#e2e8f0", fontSize: "12px", marginBottom: "3px" }}>
        {data.label}
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "4px" }}>
        <div style={{
          width: "5px", height: "5px", borderRadius: "50%",
          background: isWorking ? "#22c55e" : isError ? "#ef4444" : "#334155",
          boxShadow: isWorking ? "0 0 6px #22c55e" : "none",
          animation: isWorking ? "dot-pulse 1.5s ease-in-out infinite" : "none",
        }} />
        <span style={{ fontSize: "9px", color: isWorking ? "#4ade80" : isError ? "#f87171" : "#475569" }}>
          {isWorking ? "working" : isError ? "error" : "idle"}
        </span>
      </div>

      {data.chain && (
        <div style={{ fontSize: "9px", color: "#475569", marginTop: "2px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "90px" }}>
          {data.chain.slice(0, 8)}…
        </div>
      )}

      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  )
}

const nodeTypes = { agentNode: AgentNode }

function buildFixedGraph(agentStates: Record<string, any>): { n: Node[]; e: Edge[] } {
  const n: Node[] = [
    { id: "jarvis",   type: "agentNode", position: { x: 380, y: 20  }, data: { id: "jarvis",   label: "Jarvis",   state: agentStates.jarvis?.status   || "idle", chain: agentStates.jarvis?.chain_id } },
    { id: "research", type: "agentNode", position: { x: 60,  y: 160 }, data: { id: "research", label: "Research", state: agentStates.research?.status || "idle", chain: agentStates.research?.chain_id } },
    { id: "revenue",  type: "agentNode", position: { x: 200, y: 160 }, data: { id: "revenue",  label: "Revenue",  state: agentStates.revenue?.status  || "idle", chain: agentStates.revenue?.chain_id } },
    { id: "sales",    type: "agentNode", position: { x: 340, y: 160 }, data: { id: "sales",    label: "Sales",    state: agentStates.sales?.status    || "idle", chain: agentStates.sales?.chain_id } },
    { id: "growth",   type: "agentNode", position: { x: 480, y: 160 }, data: { id: "growth",   label: "Growth",   state: agentStates.growth?.status   || "idle", chain: agentStates.growth?.chain_id } },
    { id: "code",     type: "agentNode", position: { x: 620, y: 160 }, data: { id: "code",     label: "Code",     state: agentStates.code?.status     || "idle", chain: agentStates.code?.chain_id } },
    { id: "product",  type: "agentNode", position: { x: 100, y: 300 }, data: { id: "product",  label: "Product",  state: agentStates.product?.status  || "idle", chain: agentStates.product?.chain_id } },
    { id: "legal",    type: "agentNode", position: { x: 280, y: 300 }, data: { id: "legal",    label: "Legal",    state: agentStates.legal?.status    || "idle", chain: agentStates.legal?.chain_id } },
    { id: "systems",  type: "agentNode", position: { x: 460, y: 300 }, data: { id: "systems",  label: "Systems",  state: agentStates.systems?.status  || "idle", chain: agentStates.systems?.chain_id } },
    { id: "voice",    type: "agentNode", position: { x: 640, y: 300 }, data: { id: "voice",    label: "Voice",    state: agentStates.voice?.status    || "idle", chain: agentStates.voice?.chain_id } },
  ]

  const e: Edge[] = FIXED_AGENTS
    .filter(a => a.id !== "jarvis")
    .map(a => {
      const isActive = agentStates[a.id]?.status === "working"
      return {
        id: `jarvis-${a.id}`,
        source: "jarvis",
        target: a.id,
        animated: isActive,
        style: { stroke: isActive ? "#22c55e" : "rgba(168,85,247,0.2)", strokeWidth: isActive ? 2 : 1 },
      }
    })

  return { n, e }
}

export default function AgentGraph({ onSelect }: { onSelect?: (node: any) => void }) {
  const [nodes, setNodes]           = useState<Node[]>([])
  const [edges, setEdges]           = useState<Edge[]>([])
  const [agentState, setAgentState] = useState<Record<string, any>>({})
  const [retries, setRetries]       = useState<Record<string, number>>({})
  const [lastAction, setLastAction] = useState<Record<string, number>>({})

  const callOperator = async (endpoint: string, payload: any) => {
    try {
      await fetch(`/api/operator/${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
    } catch {}
  }

  // Build graph whenever agent state changes
  useEffect(() => {
    const { n, e } = buildFixedGraph(agentState)
    setNodes(n)
    setEdges(e)
  }, [agentState])

  // Poll /metrics/agents/live every 3s for real agent state
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const r = await fetch("/api/metrics/agents/live")
        if (!r.ok) return
        const d = await r.json()
        const sm: Record<string, string> = d.states ?? {}
        const updates: Record<string, any> = {}
        Object.entries(sm).forEach(([agent, state]) => {
          updates[agent] = { status: state, updated: Date.now() }
        })
        // Mark agents not in response as idle
        setAgentState(prev => {
          const next = { ...prev }
          Object.keys(prev).forEach(ag => {
            if (!(ag in sm)) next[ag] = { ...prev[ag], status: "idle" }
          })
          Object.entries(updates).forEach(([ag, val]) => { next[ag] = val })
          return next
        })
      } catch {}
    }, 3000)
    return () => clearInterval(interval)
  }, [])

  // Self-heal engine
  useEffect(() => {
    const interval = setInterval(() => {
      const now = Date.now()
      Object.entries(agentState).forEach(([agent, state]: any) => {
        const last = lastAction[agent] || 0
        const retryCount = retries[agent] || 0
        if (now - last < RETRY_COOLDOWN) return
        if (state.status === "error" && retryCount < MAX_RETRIES) {
          callOperator("retry", { agent, chain_id: state.chain_id })
          setRetries(p => ({ ...p, [agent]: retryCount + 1 }))
          setLastAction(p => ({ ...p, [agent]: now }))
        }
        if (state.updated && now - state.updated > STALL_THRESHOLD && state.status !== "error") {
          callOperator("restart", { agent })
          setLastAction(p => ({ ...p, [agent]: now }))
        }
      })
    }, 2000)
    return () => clearInterval(interval)
  }, [agentState, retries, lastAction])

  const onNodeClick = useCallback((e: any, node: Node) => {
    if (onSelect) onSelect(node)
  }, [onSelect])

  return (
    <>
      <style>{`
        @keyframes nodeGlow { 0%,100%{box-shadow:0 0 16px rgba(34,197,94,0.3)} 50%{box-shadow:0 0 28px rgba(34,197,94,0.6)} }
        @keyframes dot-pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(1.3)} }
        .react-flow__controls { background: rgba(10,14,25,0.9) !important; border: 1px solid rgba(255,255,255,0.08) !important; }
        .react-flow__controls button { background: transparent !important; border-bottom: 1px solid rgba(255,255,255,0.06) !important; color: #64748b !important; }
        .react-flow__controls button:hover { background: rgba(255,255,255,0.05) !important; }
      `}</style>
      <div style={{ width: "100%", height: "100%", minHeight: "300px" }}>
        <ReactFlow
          style={{ width: "100%", height: "100%" }}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.2 }}
          onNodeClick={onNodeClick}
          minZoom={0.3}
          maxZoom={2}
        >
          <Controls showInteractive={false} />
          <Background gap={20} color="rgba(255,255,255,0.03)" />
        </ReactFlow>
      </div>
    </>
  )
}
