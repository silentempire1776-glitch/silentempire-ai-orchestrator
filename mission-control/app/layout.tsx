"use client"

import "./globals.css"
import Link from "next/link"
import { useState } from "react"

const navItems = [
  { href: "/", label: "Dashboard", icon: "⊞" },
  { href: "/chat", label: "Chat", icon: "✦" },
  { href: "/agents", label: "Agents", icon: "◈" },
  { href: "/console", label: "Console", icon: "⌘" },
  { href: "/files", label: "Files", icon: "◻" },
]

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <html lang="en">
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet" />
        <style>{`
          * { box-sizing: border-box; margin: 0; padding: 0; }
          body { font-family: 'Inter', sans-serif; background: #0a0a0f; color: #e2e8f0; }
          html, body, #__next { height: 100%; }

          .nav-link {
            display: flex; align-items: center; gap: 10px;
            padding: 9px 12px; border-radius: 8px;
            color: #94a3b8; font-size: 13px; text-decoration: none;
            transition: background 0.15s, color 0.15s;
          }
          .nav-link:hover { background: rgba(255,255,255,0.06); color: #f1f5f9; }
          .nav-icon { font-size: 13px; opacity: 0.7; }

          /* Sidebar overlay on mobile */
          .sidebar-overlay {
            display: none;
            position: fixed; inset: 0;
            background: rgba(0,0,0,0.6);
            z-index: 40;
          }
          .sidebar-overlay.open { display: block; }

          /* Sidebar */
          .sidebar {
            width: 216px; min-width: 216px;
            background: #0d0d16;
            border-right: 1px solid rgba(255,255,255,0.05);
            display: flex; flex-direction: column;
            transition: transform 0.25s ease;
            z-index: 50;
          }

          /* Mobile hamburger */
          .hamburger {
            display: none;
            background: none; border: none;
            color: #94a3b8; font-size: 20px;
            cursor: pointer; padding: 4px 8px;
            line-height: 1;
          }

          @media (max-width: 768px) {
            .hamburger { display: block; }
            .sidebar {
              position: fixed; top: 0; left: 0; height: 100vh;
              transform: translateX(-100%);
            }
            .sidebar.open { transform: translateX(0); }
            .top-title { font-size: 13px !important; }
          }

          ::-webkit-scrollbar { width: 5px; }
          ::-webkit-scrollbar-track { background: transparent; }
          ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 3px; }
        `}</style>
      </head>
      <body>
        <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>

          {/* Mobile overlay */}
          <div
            className={`sidebar-overlay ${navOpen ? "open" : ""}`}
            onClick={() => setNavOpen(false)}
          />

          {/* ── SIDEBAR ── */}
          <div className={`sidebar ${navOpen ? "open" : ""}`}>
            {/* Logo */}
            <div style={{ padding: "16px 16px 12px", borderBottom: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                <div style={{
                  width: "30px", height: "30px", borderRadius: "9px",
                  background: "linear-gradient(135deg, #7c3aed, #4f46e5)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: "14px", color: "white", fontWeight: "700", flexShrink: 0,
                }}>J</div>
                <div>
                  <div style={{ fontSize: "13px", fontWeight: "600", color: "#f1f5f9", lineHeight: 1 }}>Jarvis</div>
                  <div style={{ fontSize: "10px", color: "#475569", marginTop: "3px" }}>Silent Empire AI</div>
                </div>
              </div>
              {/* Close button — mobile only */}
              <button
                onClick={() => setNavOpen(false)}
                style={{ background: "none", border: "none", color: "#475569", fontSize: "18px", cursor: "pointer", padding: "2px 6px", display: "none" }}
                className="close-nav"
              >✕</button>
            </div>

            {/* Nav */}
            <nav style={{ flex: 1, padding: "10px 8px", display: "flex", flexDirection: "column", gap: "1px" }}>
              {navItems.map(item => (
                <Link key={item.href} href={item.href} className="nav-link" onClick={() => setNavOpen(false)}>
                  <span className="nav-icon">{item.icon}</span>
                  {item.label}
                </Link>
              ))}
            </nav>

            {/* Status footer */}
            <div style={{ padding: "12px 16px", borderTop: "1px solid rgba(255,255,255,0.05)", display: "flex", alignItems: "center", gap: "7px" }}>
              <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "#22c55e", boxShadow: "0 0 5px #22c55e", flexShrink: 0 }} />
              <span style={{ fontSize: "11px", color: "#64748b" }}>All systems online</span>
            </div>
          </div>

          {/* ── MAIN ── */}
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
            {/* Top bar */}
            <div style={{
              height: "46px", minHeight: "46px",
              borderBottom: "1px solid rgba(255,255,255,0.05)",
              padding: "0 16px",
              display: "flex", alignItems: "center", justifyContent: "space-between",
              background: "rgba(10,10,15,0.9)",
              gap: "10px",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                {/* Hamburger — mobile only */}
                <button className="hamburger" onClick={() => setNavOpen(true)}>☰</button>
                <span className="top-title" style={{ fontSize: "13px", color: "#cbd5e1", fontWeight: "500" }}>Mission Control</span>
                <div style={{ width: "4px", height: "4px", borderRadius: "50%", background: "#22c55e" }} />
                <span style={{ fontSize: "11px", color: "#475569" }}>Online</span>
              </div>
              <span style={{ fontSize: "11px", color: "#1e293b" }}>v2</span>
            </div>

            {/* Page content */}
            <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
              {children}
            </main>
          </div>

        </div>
      </body>
    </html>
  )
}
