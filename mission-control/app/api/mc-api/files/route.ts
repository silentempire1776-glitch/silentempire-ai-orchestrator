import { NextResponse } from "next/server"
import fs from "fs"
import path from "path"

export async function GET(req: Request) {
  try {
    const { searchParams } = new URL(req.url)
    const reqPath = searchParams.get("path") || ""

    // 🔥 THIS IS THE FIX
    const baseDir = process.cwd()

    const targetPath = path.join(baseDir, reqPath)

    if (!fs.existsSync(targetPath)) {
      return NextResponse.json({ files: [] })
    }

    const items = fs.readdirSync(targetPath, { withFileTypes: true })

    const files = items.map((item) => ({
      name: item.name,
      isDirectory: item.isDirectory(),
    }))

    return NextResponse.json({ files })

  } catch (err) {
    console.error("FILES API ERROR:", err)
    return NextResponse.json({ files: [] })
  }
}
