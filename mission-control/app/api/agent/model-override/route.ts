import { NextResponse } from "next/server"

export async function GET() {
  try {
    const backend = process.env.API_BASE_URL || "http://api:8000"
    const r = await fetch(`${backend}/agent/model-override`, {
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
    })
    if (!r.ok) throw new Error(`Backend returned ${r.status}`)
    const data = await r.json()
    return NextResponse.json(data)
  } catch (e) {
    // Return current env default if backend unreachable
    return NextResponse.json({
      jarvis: process.env.MODEL_JARVIS_ORCHESTRATOR || "moonshotai/kimi-k2.5",
      error: String(e)
    })
  }
}

export async function POST(req: Request) {
  try {
    const backend = process.env.API_BASE_URL || "http://api:8000"
    const body = await req.json()
    const r = await fetch(`${backend}/agent/model-override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
    })
    const data = await r.json()
    return NextResponse.json(data)
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}
