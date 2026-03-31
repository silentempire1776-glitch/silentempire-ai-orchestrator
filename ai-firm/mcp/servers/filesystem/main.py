"""
=========================================================
MCP Filesystem Server — Silent Empire
Gives agents controlled access to:
  - Code files (write apps, features, tools)
  - Contract/document templates
  - Configuration files
  - Log inspection

Tools:
  read(path)                            → {content, size, modified}
  write(path, content)                  → {status, path}
  list(path)                            → [{name, is_dir, size}]
  delete(path)                          → {status}
  exists(path)                          → bool
  search(path, query)                   → [{path, line, content}]
  read_template(template_name)          → str
  write_template(template_name, content)→ {status}
  list_templates()                      → [str]
=========================================================
"""

import os
import sys
import glob
import json
from datetime import datetime
from typing import Any

sys.path.insert(0, "/ai-firm")

from mcp.shared.mcp_protocol import MCPServer

# --------------------------------------------------
# ALLOWED PATHS — security boundary
# --------------------------------------------------

ALLOWED_ROOTS = [
    "/ai-firm",
    "/srv/silentempire/mission-control",
]

TEMPLATE_DIR = "/ai-firm/shared/templates"
os.makedirs(TEMPLATE_DIR, exist_ok=True)


def _assert_allowed(path: str) -> str:
    """Resolve path and assert it's within an allowed root."""
    path = os.path.realpath(path)
    for root in ALLOWED_ROOTS:
        if path.startswith(root):
            return path
    raise PermissionError(f"Path not allowed: {path}")


# --------------------------------------------------
# TOOL IMPLEMENTATIONS
# --------------------------------------------------

def tool_read(params: dict) -> dict:
    path = _assert_allowed(params.get("path", ""))

    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")

    if os.path.isdir(path):
        raise IsADirectoryError(f"Path is directory: {path}")

    stat = os.stat(path)
    with open(path, "r", errors="replace") as f:
        content = f.read()

    return {
        "content": content,
        "size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "path": path,
    }


def tool_write(params: dict) -> dict:
    path    = _assert_allowed(params.get("path", ""))
    content = params.get("content", "")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w") as f:
        f.write(content)

    return {"status": "written", "path": path, "bytes": len(content)}


def tool_list(params: dict) -> list:
    path = _assert_allowed(params.get("path", "/ai-firm"))

    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")

    entries = []
    for name in sorted(os.listdir(path)):
        full = os.path.join(path, name)
        stat = os.stat(full)
        entries.append({
            "name": name,
            "path": full,
            "is_dir": os.path.isdir(full),
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return entries


def tool_delete(params: dict) -> dict:
    path = _assert_allowed(params.get("path", ""))

    if not os.path.exists(path):
        raise FileNotFoundError(f"Not found: {path}")

    os.remove(path)
    return {"status": "deleted", "path": path}


def tool_exists(params: dict) -> bool:
    try:
        path = _assert_allowed(params.get("path", ""))
        return os.path.exists(path)
    except PermissionError:
        return False


def tool_search(params: dict) -> list:
    """
    Search for text within files under a path.
    Used by agents to find relevant code before modifying it.
    """
    root  = _assert_allowed(params.get("path", "/ai-firm"))
    query = params.get("query", "").lower()

    if not query:
        return []

    results = []
    extensions = params.get("extensions", [".py", ".md", ".json", ".txt", ".yaml"])

    for ext in extensions:
        pattern = f"{root}/**/*{ext}"
        for filepath in glob.glob(pattern, recursive=True):
            try:
                with open(filepath, "r", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if query in line.lower():
                            results.append({
                                "path": filepath,
                                "line": i,
                                "content": line.strip()[:200],
                            })
                            if len(results) >= 50:  # cap results
                                return results
            except Exception:
                continue

    return results


def tool_read_template(params: dict) -> str:
    name = params.get("template_name", "").strip("/")
    if not name:
        raise ValueError("template_name required")

    path = os.path.join(TEMPLATE_DIR, name)
    _assert_allowed(path)

    if not os.path.exists(path):
        raise FileNotFoundError(f"Template not found: {name}")

    with open(path, "r") as f:
        return f.read()


def tool_write_template(params: dict) -> dict:
    name    = params.get("template_name", "").strip("/")
    content = params.get("content", "")

    if not name:
        raise ValueError("template_name required")

    path = os.path.join(TEMPLATE_DIR, name)
    _assert_allowed(path)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)

    return {"status": "written", "template": name}


def tool_list_templates(params: dict) -> list:
    templates = []
    for root, dirs, files in os.walk(TEMPLATE_DIR):
        for fname in files:
            full = os.path.join(root, fname)
            rel  = os.path.relpath(full, TEMPLATE_DIR)
            templates.append(rel)
    return sorted(templates)


# --------------------------------------------------
# SERVER ASSEMBLY
# --------------------------------------------------

class FilesystemServer(MCPServer):
    def __init__(self):
        super().__init__("filesystem")
        self.register_tool("read",            tool_read)
        self.register_tool("write",           tool_write)
        self.register_tool("list",            tool_list)
        self.register_tool("delete",          tool_delete)
        self.register_tool("exists",          tool_exists)
        self.register_tool("search",          tool_search)
        self.register_tool("read_template",   tool_read_template)
        self.register_tool("write_template",  tool_write_template)
        self.register_tool("list_templates",  tool_list_templates)


if __name__ == "__main__":
    server = FilesystemServer()
    server.run()
