"use client"

import React, { useEffect, useState, useRef } from "react"
import Editor from "@monaco-editor/react"

function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() || ""
  const map: Record<string, string> = {
    py: "python", ts: "typescript", tsx: "typescript", js: "javascript",
    jsx: "javascript", json: "json", md: "markdown", yml: "yaml",
    yaml: "yaml", sh: "shell", bash: "shell", css: "css",
    html: "html", toml: "toml", txt: "plaintext", env: "plaintext",
  }
  return map[ext] || "plaintext"
}

type FileEntry = { name: string; isDirectory: boolean }
type DeleteTarget = { path: string; isDirectory: boolean } | null

function parseBreadcrumbs(path: string): { label: string; path: string }[] {
  const crumbs = [{ label: "silentempire", path: "" }]
  if (!path) return crumbs
  const parts = path.split("/").filter(Boolean)
  let cum = ""
  for (const part of parts) {
    cum = cum ? `${cum}/${part}` : part
    crumbs.push({ label: part, path: cum })
  }
  return crumbs
}

export default function FilesPage() {
  const [files, setFiles]               = useState<FileEntry[]>([])
  const [path, setPath]                 = useState("")
  const [content, setContent]           = useState("")
  const [selectedFile, setSelectedFile] = useState("")
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget>(null)
  const [saveStatus, setSaveStatus]     = useState<"idle" | "saving" | "saved" | "error">("idle")
  const [searchQuery, setSearchQuery]   = useState("")
  const [searchResults, setSearchResults] = useState<{ path: string; line: number; content: string }[]>([])
  const [searching, setSearching]       = useState(false)
  const [newItemName, setNewItemName]   = useState("")
  const [newItemType, setNewItemType]   = useState<"file" | "folder" | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const loadFiles = async (newPath = "") => {
    try {
      const res = await fetch(`/api/files?path=${encodeURIComponent(newPath)}`)
      if (!res.ok) return
      const data = await res.json()
      // Backend returns files array; add directory detection
      const rawFiles = data.files || []
      setFiles(rawFiles)
      setPath(newPath)
      setSearchResults([])
    } catch {}
  }

  const openFile = async (filePath: string) => {
    try {
      const res = await fetch(`/api/files?path=${encodeURIComponent(filePath)}`)
      if (!res.ok) return
      const data = await res.json()
      if (data.files) {
        // It's a directory — navigate into it
        loadFiles(filePath)
        return
      }
      setContent(data.content || "")
      setSelectedFile(filePath)
      setSearchResults([])
    } catch {}
  }

  const saveFile = async () => {
    if (!selectedFile) return
    setSaveStatus("saving")
    try {
      const res = await fetch(`/api/file?path=${encodeURIComponent(selectedFile)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      })
      setSaveStatus(res.ok ? "saved" : "error")
    } catch { setSaveStatus("error") }
    setTimeout(() => setSaveStatus("idle"), 2000)
  }

  const deleteConfirmed = async () => {
    if (!deleteTarget) return
    try {
      if (deleteTarget.isDirectory) {
        // Delete folder via bash through MCP infra
        await fetch("/api/mcp/call", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            server: "infra",
            tool: "bash",
            params: { command: `rm -rf "/ai-firm/${deleteTarget.path}"`, timeout: 15 }
          })
        })
      } else {
        await fetch(`/api/file?path=${encodeURIComponent(deleteTarget.path)}`, { method: "DELETE" })
      }
      if (deleteTarget.path === selectedFile) { setSelectedFile(""); setContent("") }
      loadFiles(path)
    } catch {}
    setDeleteTarget(null)
  }

  const createItem = async () => {
    if (!newItemName.trim() || !newItemType) return
    const name = newItemName.trim()
    const newPath = path ? `${path}/${name}` : name

    if (newItemType === "file") {
      const res = await fetch(`/api/create-file?path=${encodeURIComponent(newPath)}`, { method: "POST" })
      if (res.ok) { loadFiles(path); openFile(newPath) }
    } else {
      // Create folder by writing a placeholder
      const keepPath = `${newPath}/.gitkeep`
      const res = await fetch(`/api/create-file?path=${encodeURIComponent(keepPath)}`, { method: "POST" })
      if (res.ok) loadFiles(path)
    }
    setNewItemName(""); setNewItemType(null)
  }

  const runSearch = async () => {
    if (!searchQuery.trim()) return
    setSearching(true); setSearchResults([])
    try {
      const res = await fetch("/api/mcp/call", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          server: "filesystem",
          tool: "search",
          params: {
            path: path ? `/ai-firm/${path}` : "/ai-firm",
            query: searchQuery,
            extensions: [".py", ".ts", ".tsx", ".js", ".md", ".json", ".yaml", ".sh", ".env", ".txt"]
          }
        })
      })
      if (res.ok) {
        const data = await res.json()
        setSearchResults(data.result || [])
      }
    } catch {}
    setSearching(false)
  }

  const goBack = () => {
    if (!path) return
    const parts = path.split("/"); parts.pop()
    loadFiles(parts.join("/"))
  }

  useEffect(() => { loadFiles() }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "s" && selectedFile) { e.preventDefault(); saveFile() }
      if ((e.metaKey || e.ctrlKey) && e.key === "f") { e.preventDefault(); setTimeout(() => searchRef.current?.focus(), 50) }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [selectedFile, content])

  const lang = getLanguage(selectedFile)
  const breadcrumbs = parseBreadcrumbs(path)

  const itemStyle = (fp: string, isDir: boolean): React.CSSProperties => ({
    display: "flex", alignItems: "center", gap: "7px", padding: "6px 14px", cursor: "pointer",
    fontSize: "12px", color: selectedFile === fp ? "#f1f5f9" : isDir ? "#cbd5e1" : "#94a3b8",
    background: selectedFile === fp ? "rgba(124,58,237,0.12)" : "transparent",
    borderLeft: selectedFile === fp ? "2px solid #7c3aed" : "2px solid transparent",
    transition: "background 0.1s",
  })

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", overflow: "hidden" }}>
      <style>{`.fi:hover{background:rgba(255,255,255,0.04)!important}.sr:hover{background:rgba(124,58,237,0.08)!important;cursor:pointer}`}</style>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "280px 1fr", overflow: "hidden" }}>

        {/* SIDEBAR */}
        <div style={{ background: "rgba(13,13,22,0.9)", borderRight: "1px solid rgba(255,255,255,0.05)", display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* Header */}
          <div style={{ padding: "12px 14px 8px", borderBottom: "1px solid rgba(255,255,255,0.05)" }}>
            <div style={{ fontSize: "10px", fontWeight: 700, color: "#64748b", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: "8px" }}>Workspace</div>

            {/* Search */}
            <div style={{ position: "relative", marginBottom: "8px" }}>
              <input
                ref={searchRef}
                value={searchQuery}
                onChange={e => setSearchQuery(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") runSearch() }}
                placeholder="Search files… (⌘F)"
                style={{ width: "100%", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: "8px", padding: "6px 28px 6px 10px", color: "#94a3b8", fontSize: "12px", outline: "none", boxSizing: "border-box" }}
              />
              <button onClick={runSearch} disabled={searching} style={{ position: "absolute", right: "6px", top: "50%", transform: "translateY(-50%)", background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "13px" }}>{searching ? "…" : "⌕"}</button>
            </div>

            {/* Breadcrumbs */}
            <div style={{ display: "flex", alignItems: "center", gap: "3px", flexWrap: "wrap" }}>
              {breadcrumbs.map((crumb, i) => (
                <React.Fragment key={crumb.path}>
                  {i > 0 && <span style={{ fontSize: "10px", color: "#1e293b" }}>/</span>}
                  <button onClick={() => loadFiles(crumb.path)} style={{ background: "none", border: "none", color: i === breadcrumbs.length - 1 ? "#94a3b8" : "#334155", fontSize: "11px", cursor: "pointer", padding: "0 2px" }}>{crumb.label}</button>
                </React.Fragment>
              ))}
            </div>
          </div>

          {/* Nav */}
          <div style={{ padding: "5px 10px", display: "flex", gap: "5px", borderBottom: "1px solid rgba(255,255,255,0.04)" }}>
            <button onClick={() => loadFiles("")} style={{ fontSize: "10px", padding: "3px 8px", borderRadius: "5px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", color: "#64748b", cursor: "pointer" }}>Root</button>
            <button onClick={goBack} style={{ fontSize: "10px", padding: "3px 8px", borderRadius: "5px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)", color: "#64748b", cursor: "pointer" }}>← Back</button>
          </div>

          {/* File list or search results */}
          <div style={{ flex: 1, overflow: "auto" }}>
            {searchResults.length > 0 ? (
              <div>
                <div style={{ padding: "6px 12px", fontSize: "10px", color: "#475569", borderBottom: "1px solid rgba(255,255,255,0.04)", display: "flex", justifyContent: "space-between" }}>
                  <span>{searchResults.length} results for "{searchQuery}"</span>
                  <button onClick={() => setSearchResults([])} style={{ background: "none", border: "none", color: "#475569", cursor: "pointer", fontSize: "11px" }}>✕</button>
                </div>
                {searchResults.map((r, i) => (
                  <div key={i} className="sr" onClick={() => openFile(r.path.replace("/ai-firm/", ""))} style={{ padding: "7px 12px", borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                    <div style={{ fontSize: "11px", color: "#94a3b8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.path.split("/").slice(-2).join("/")}</div>
                    <div style={{ fontSize: "10px", color: "#475569", marginTop: "1px" }}>Line {r.line}: <span style={{ color: "#64748b" }}>{r.content.slice(0, 55)}</span></div>
                  </div>
                ))}
              </div>
            ) : (
              files.map(file => {
                const fp = path ? `${path}/${file.name}` : file.name
                return (
                  <div key={fp} className="fi" onClick={() => file.isDirectory ? loadFiles(fp) : openFile(fp)} style={itemStyle(fp, file.isDirectory)}>
                    <span style={{ fontSize: "13px", flexShrink: 0 }}>{file.isDirectory ? "📁" : "📄"}</span>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>{file.name}</span>
                    {/* Delete button for each item */}
                    <button
                      onClick={e => { e.stopPropagation(); setDeleteTarget({ path: fp, isDirectory: file.isDirectory }) }}
                      style={{ background: "none", border: "none", color: "transparent", cursor: "pointer", fontSize: "11px", padding: "0 2px", flexShrink: 0 }}
                      className="del-btn"
                      title={`Delete ${file.isDirectory ? "folder" : "file"}`}
                    >✕</button>
                  </div>
                )
              })
            )}
          </div>

          {/* New item */}
          {newItemType ? (
            <div style={{ padding: "10px 12px", borderTop: "1px solid rgba(255,255,255,0.05)" }}>
              <div style={{ fontSize: "10px", color: "#475569", marginBottom: "5px" }}>New {newItemType}</div>
              <div style={{ display: "flex", gap: "5px" }}>
                <input
                  value={newItemName}
                  onChange={e => setNewItemName(e.target.value)}
                  onKeyDown={e => { if (e.key === "Enter") createItem(); if (e.key === "Escape") setNewItemType(null) }}
                  placeholder={newItemType === "file" ? "filename.py" : "folder-name"}
                  autoFocus
                  style={{ flex: 1, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(124,58,237,0.3)", borderRadius: "6px", color: "#e2e8f0", fontSize: "12px", padding: "5px 8px", outline: "none" }}
                />
                <button onClick={createItem} style={{ padding: "5px 8px", borderRadius: "6px", background: "rgba(124,58,237,0.2)", border: "1px solid rgba(124,58,237,0.35)", color: "#a78bfa", cursor: "pointer", fontSize: "12px" }}>✓</button>
                <button onClick={() => setNewItemType(null)} style={{ padding: "5px 8px", borderRadius: "6px", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "#64748b", cursor: "pointer", fontSize: "12px" }}>✕</button>
              </div>
            </div>
          ) : (
            <div style={{ padding: "8px 10px", borderTop: "1px solid rgba(255,255,255,0.05)", display: "flex", gap: "6px" }}>
              <button onClick={() => setNewItemType("file")} style={{ flex: 1, padding: "7px", borderRadius: "8px", fontSize: "11px", background: "rgba(124,58,237,0.1)", border: "1px solid rgba(124,58,237,0.2)", color: "#a78bfa", cursor: "pointer" }}>+ File</button>
              <button onClick={() => setNewItemType("folder")} style={{ flex: 1, padding: "7px", borderRadius: "8px", fontSize: "11px", background: "rgba(79,70,229,0.1)", border: "1px solid rgba(79,70,229,0.2)", color: "#818cf8", cursor: "pointer" }}>+ Folder</button>
            </div>
          )}
        </div>

        {/* EDITOR */}
        <div style={{ display: "flex", flexDirection: "column", overflow: "hidden", background: "#0a0a12" }}>
          <div style={{ padding: "10px 16px", borderBottom: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(13,13,22,0.95)", flexShrink: 0 }}>
            <span style={{ fontSize: "12px", color: "#94a3b8", fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{selectedFile || "No file selected"}</span>
            {selectedFile && (
              <div style={{ display: "flex", gap: "8px", flexShrink: 0 }}>
                <span style={{ fontSize: "10px", padding: "2px 8px", borderRadius: "10px", background: "rgba(124,58,237,0.15)", border: "1px solid rgba(124,58,237,0.2)", color: "#a78bfa" }}>{lang}</span>
                <span style={{ fontSize: "10px", color: "#334155" }}>⌘S save</span>
              </div>
            )}
          </div>

          <div style={{ flex: 1, overflow: "hidden" }}>
            <Editor
              height="100%"
              theme="vs-dark"
              language={lang}
              value={content}
              onChange={v => setContent(v || "")}
              options={{
                minimap: { enabled: false }, fontSize: 13,
                fontFamily: "'Fira Code','Cascadia Code','JetBrains Mono',monospace",
                wordWrap: "on", lineNumbers: "on", scrollBeyondLastLine: false,
                cursorBlinking: "smooth", smoothScrolling: true, tabSize: 2, padding: { top: 12 },
              }}
            />
          </div>

          <div style={{ padding: "8px 14px", borderTop: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "space-between", background: "rgba(10,10,15,0.95)", flexShrink: 0 }}>
            <span style={{ fontSize: "11px", color: saveStatus === "saved" ? "#34d399" : saveStatus === "error" ? "#f87171" : "#334155" }}>
              {saveStatus === "saving" ? "Saving…" : saveStatus === "saved" ? "✓ Saved" : saveStatus === "error" ? "Save failed" : selectedFile ? "Editing" : "Idle"}
            </span>
            <div style={{ display: "flex", gap: "8px" }}>
              <button onClick={saveFile} disabled={!selectedFile} style={{ padding: "7px 18px", borderRadius: "8px", fontSize: "12px", background: !selectedFile ? "rgba(255,255,255,0.04)" : "linear-gradient(135deg,#7c3aed,#4f46e5)", color: !selectedFile ? "#334155" : "white", border: "none", cursor: !selectedFile ? "not-allowed" : "pointer", fontWeight: 500 }}>Save</button>
              <button onClick={() => selectedFile && setDeleteTarget({ path: selectedFile, isDirectory: false })} disabled={!selectedFile} style={{ padding: "7px 18px", borderRadius: "8px", fontSize: "12px", background: "rgba(239,68,68,0.15)", border: "1px solid rgba(239,68,68,0.3)", color: !selectedFile ? "#334155" : "#f87171", cursor: !selectedFile ? "not-allowed" : "pointer" }}>Delete</button>
            </div>
          </div>
        </div>
      </div>

      {/* DELETE CONFIRM MODAL */}
      {deleteTarget && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.75)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}>
          <div style={{ background: "#0d0d1a", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "16px", padding: "24px", width: "420px" }}>
            <div style={{ fontSize: "14px", fontWeight: 600, color: "#f87171", marginBottom: "12px" }}>
              Delete {deleteTarget.isDirectory ? "Folder" : "File"}
            </div>
            <div style={{ fontSize: "13px", color: "#94a3b8", marginBottom: "8px", wordBreak: "break-all" }}>
              <span style={{ color: "#e2e8f0", fontFamily: "monospace" }}>{deleteTarget.path}</span>
            </div>
            {deleteTarget.isDirectory && (
              <div style={{ fontSize: "12px", color: "#f87171", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)", borderRadius: "8px", padding: "8px 12px", marginBottom: "16px" }}>
                ⚠️ This will permanently delete the entire folder and all its contents.
              </div>
            )}
            <div style={{ fontSize: "11px", color: "#475569", marginBottom: "20px" }}>This cannot be undone.</div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: "8px" }}>
              <button onClick={() => setDeleteTarget(null)} style={{ padding: "8px 16px", borderRadius: "8px", background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.08)", color: "#94a3b8", cursor: "pointer", fontSize: "13px" }}>Cancel</button>
              <button onClick={deleteConfirmed} style={{ padding: "8px 16px", borderRadius: "8px", background: "rgba(239,68,68,0.2)", border: "1px solid rgba(239,68,68,0.35)", color: "#f87171", cursor: "pointer", fontSize: "13px", fontWeight: 600 }}>
                Delete {deleteTarget.isDirectory ? "Folder" : "File"}
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`.fi:hover .del-btn{color:#475569!important}`}</style>
    </div>
  )
}
