import { NextResponse } from "next/server"

export async function POST(req: Request) {
  try {
    const { message } = await req.json()
    if (!message) return NextResponse.json({ error: "no message" }, { status: 400 })

    const token = process.env.TELEGRAM_TOKEN || ""
    const chatId = process.env.TELEGRAM_CHAT_ID || ""

    if (!token || !chatId) {
      console.error("telegram-send: TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set")
      return NextResponse.json({ error: "Telegram env vars not set" }, { status: 500 })
    }

    const url = `https://api.telegram.org/bot${token}/sendMessage`
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text: message }),
    })

    const data = await resp.json()
    if (!data.ok) {
      console.error("telegram-send: API error", data)
      return NextResponse.json({ error: data.description }, { status: 500 })
    }

    return NextResponse.json({ ok: true, message_id: data.result?.message_id })
  } catch (e: any) {
    console.error("telegram-send error:", e.message)
    return NextResponse.json({ error: e.message }, { status: 500 })
  }
}
