#!/usr/bin/env python3
"""
Silent Empire AI — Google Drive & Docs CLI
==========================================
Follows exact same OAuth pattern as OpenClaw google_api_cli.py.
Tokens stored at: /ai-firm/config/secrets/google/

COMMANDS:
  auth-url                          Print OAuth URL (open in browser)
  exchange <CODE>                   Exchange auth code for token
  refresh                           Refresh access token

  drive-list-folder <folder_id>     List files in a folder
  drive-search <query>              Search files by name
  drive-mkdir <name> [parent_id]    Create folder
  drive-upload <file> [parent_id]   Upload file
  drive-create-doc <file> <title> [parent_id]   Create Google Doc from markdown file
  drive-read-doc <file_id>          Read Google Doc as text
  drive-update-doc <file_id> <file> Append content to Google Doc
  drive-link <file_id>              Get shareable link

  agent-save <agent> <file> <title> Save agent report as Google Doc in correct folder

AGENT FOLDER MAP (pre-configured from your Drive):
  research  → 02 - Research & Intelligence (19e8m0wEtMZDUzebth9FLZxnRy-FLhCBB)
  sales     → 04 - Marketing & Content    (1GqJkdBQXiqCBEeBjaKxTOjBsFexD00My)
  revenue   → 05 - Products & Offers      (11fMeB3tnEHXL28x-nW32aC2dnw4tmo-I)
  legal     → 06 - Legal & Compliance     (1AwItxc82Aol_h2RKA-NvHABZvBPtiw9W)
  product   → 05 - Products & Offers      (11fMeB3tnEHXL28x-nW32aC2dnw4tmo-I)
  growth    → 04 - Marketing & Content    (1GqJkdBQXiqCBEeBjaKxTOjBsFexD00My)
  systems   → 07 - Development & IT       (1bk6_b9ftIWXIAnZR73FCQX7q_apwooLN)
  code      → 07 - Development & IT       (1bk6_b9ftIWXIAnZR73FCQX7q_apwooLN)
  strategy  → 01 - Strategy & Vision      (1ndHYe0imrM_0l5VaJY248A0HD0rdARMY)
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import urllib.error

# ── Paths ─────────────────────────────────────────────────────────────────────

SECRETS_DIR   = "/ai-firm/config/secrets/google"
CREDS_PATH    = f"{SECRETS_DIR}/credentials.json"
TOKEN_PATH    = f"{SECRETS_DIR}/token.json"
DRIVE_BASE    = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD  = "https://www.googleapis.com/upload/drive/v3"
DOCS_BASE     = "https://docs.googleapis.com/v1"

# ── Agent → Drive folder mapping — loaded from business.json ──────────────────
# Edit /ai-firm/config/business.json → google_drive section
# No code changes needed when Drive structure changes.

# DYNAMIC_DRIVE_CONFIG
def _load_drive_config() -> dict:
    """Load Drive folder config from business.json. Falls back to root folder."""
    for path in [
        "/ai-firm/config/business.json",
        "/ai-firm/config/business.json",
    ]:
        try:
            import json as _json
            data = _json.loads(open(path).read())
            return data.get("google_drive", {})
        except Exception:
            pass
    return {}

def _get_drive_cfg() -> dict:
    return _load_drive_config()

def _get_agent_folder(agent: str) -> str:
    cfg = _get_drive_cfg()
    folders = cfg.get("agent_folders", {})
    return folders.get(agent.lower(), folders.get("default", cfg.get("root_folder", "")))

def _get_folder_name(folder_id: str) -> str:
    cfg = _get_drive_cfg()
    return cfg.get("folder_names", {}).get(folder_id, folder_id)

def _get_root_folder() -> str:
    return _get_drive_cfg().get("root_folder", "")

def _get_creds_path() -> str:
    return _get_drive_cfg().get(
        "credentials_path",
        "/ai-firm/config/secrets/google/credentials.json"
    )

def _get_token_path() -> str:
    return _get_drive_cfg().get(
        "token_path",
        "/ai-firm/config/secrets/google/token.json"
    )

# Legacy compatibility — used by functions that reference these directly
AGENT_FOLDERS = {}  # Now loaded dynamically via _get_agent_folder()
ROOT_FOLDER   = ""  # Now loaded dynamically via _get_root_folder()

# OAuth scopes needed
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

# ── OAuth helpers ─────────────────────────────────────────────────────────────

def die(msg: str, code: int = 1):
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def load_json(path: str) -> dict:
    if not os.path.exists(path):
        die(f"File not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(path, 0o600)


def token_post(url: str, form: dict) -> dict:
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_access_token() -> str:
    """Get valid access token, refreshing if needed."""
    if not os.path.exists(TOKEN_PATH):
        die(f"No token found. Run: python3 {__file__} auth-url  then exchange <code>")

    creds_data = load_json(CREDS_PATH)
    creds = creds_data.get("installed") or creds_data.get("web") or creds_data
    tok = load_json(TOKEN_PATH)

    obtained_at = int(tok.get("obtained_at", 0))
    expires_in  = int(tok.get("expires_in", 3600))
    access_token = tok.get("access_token", "")

    # Refresh if expired or near expiry
    if not access_token or (obtained_at and time.time() > (obtained_at + expires_in - 90)):
        rt = tok.get("refresh_token")
        if not rt:
            die("No refresh_token. Re-run auth-url and exchange.")

        new_tok = token_post(
            creds.get("token_uri", "https://oauth2.googleapis.com/token"),
            {
                "client_id":     creds.get("client_id"),
                "client_secret": creds.get("client_secret"),
                "refresh_token": rt,
                "grant_type":    "refresh_token",
            }
        )
        if "error" in new_tok:
            die(f"Token refresh failed: {new_tok}")

        tok.update(new_tok)
        tok["obtained_at"] = int(time.time())
        save_json(TOKEN_PATH, tok)
        access_token = tok["access_token"]

    return access_token


def api(method: str, url: str, body=None, headers=None, expect_json=True):
    """Make an authenticated API request."""
    hdrs = headers or {}
    hdrs["Authorization"] = f"Bearer {get_access_token()}"
    if body is not None and "Content-Type" not in hdrs:
        hdrs["Content-Type"] = "application/json"
        if isinstance(body, dict):
            body = json.dumps(body).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
            if not expect_json:
                return data
            return json.loads(data.decode("utf-8")) if data else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        die(f"HTTP {e.code} on {url}: {err[:500]}")


# ── Auth commands ─────────────────────────────────────────────────────────────

def cmd_auth_url():
    try:
        creds_data = load_json(_get_creds_path())
    except Exception:
        creds_data = load_json(CREDS_PATH)
    creds = creds_data.get("installed") or creds_data.get("web") or creds_data
    client_id  = creds.get("client_id")
    auth_uri   = creds.get("auth_uri", "https://accounts.google.com/o/oauth2/auth")
    redirect   = (creds.get("redirect_uris") or ["http://localhost"])[0]

    params = {
        "client_id":     client_id,
        "redirect_uri":  redirect,
        "scope":         " ".join(SCOPES),
        "response_type": "code",
        "access_type":   "offline",
        "prompt":        "consent",
    }
    url = auth_uri + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    print("Open this URL in your browser:")
    print(url)
    print("\nAfter authorizing, copy the 'code' parameter from the redirect URL.")
    print(f"Then run: python3 {__file__} exchange <CODE>")


def cmd_exchange(code: str):
    try:
        creds_data = load_json(_get_creds_path())
        _tok_path  = _get_token_path()
    except Exception:
        creds_data = load_json(CREDS_PATH)
        _tok_path  = TOKEN_PATH
    creds = creds_data.get("installed") or creds_data.get("web") or creds_data
    redirect = (creds.get("redirect_uris") or ["http://localhost"])[0]

    tok = token_post(
        creds.get("token_uri", "https://oauth2.googleapis.com/token"),
        {
            "code":          code,
            "client_id":     creds.get("client_id"),
            "client_secret": creds.get("client_secret"),
            "redirect_uri":  redirect,
            "grant_type":    "authorization_code",
        }
    )
    if "error" in tok:
        die(f"Exchange failed: {tok}")

    tok["obtained_at"] = int(time.time())
    try:
        save_json(_tok_path, tok)
        print(f"✅ Token saved to {_tok_path}")
    except Exception:
        save_json(TOKEN_PATH, tok)
        print(f"✅ Token saved to {TOKEN_PATH}")
    print(f"   Has refresh_token: {'refresh_token' in tok}")
    print(f"   Scopes: {tok.get('scope','?')}")


def cmd_refresh():
    token = get_access_token()
    print(f"✅ Token valid: {token[:20]}...")


# ── Drive commands ────────────────────────────────────────────────────────────

def cmd_drive_list_folder(folder_id: str):
    """List all files in a Drive folder."""
    params = urllib.parse.urlencode({
        "q":        f"'{folder_id}' in parents and trashed=false",
        "pageSize": "100",
        "fields":   "files(id,name,mimeType,modifiedTime,size,webViewLink)",
    })
    result = api("GET", f"{DRIVE_BASE}/files?{params}")
    files = result.get("files", [])
    print(f"Files in folder ({len(files)} total):")
    for f in files:
        size = f.get("size", "")
        size_str = f" ({int(size)//1024}KB)" if size else ""
        print(f"  [{f['mimeType'].split('.')[-1]}] {f['name']}{size_str}")
        print(f"    ID: {f['id']}")
        print(f"    Link: {f.get('webViewLink','?')}")


def cmd_drive_search(query: str):
    """Search files by name."""
    safe_q = query.replace("'", "\\'")
    params = urllib.parse.urlencode({
        "q":        f"name contains '{safe_q}' and trashed=false",
        "pageSize": "20",
        "fields":   "files(id,name,mimeType,parents,webViewLink,modifiedTime)",
    })
    result = api("GET", f"{DRIVE_BASE}/files?{params}")
    files = result.get("files", [])
    print(json.dumps(files, indent=2))


def cmd_drive_mkdir(name: str, parent_id: str = None):
    """Create a folder in Drive."""
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    result = api("POST", f"{DRIVE_BASE}/files", body=meta)
    print(f"✅ Folder created: {result['name']} ({result['id']})")
    return result["id"]


def cmd_drive_create_doc(file_path: str, title: str, parent_id: str = None) -> dict:
    """
    Upload a markdown/text file and convert to Google Doc.
    Returns {id, name, url}
    """
    if not os.path.exists(file_path):
        die(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    meta = {"name": title}
    if parent_id:
        meta["parents"] = [parent_id]

    # Multipart upload with convert=true → native Google Doc
    boundary = "silentempire_boundary_2026"
    multipart = (
        f"--{boundary}\r\n"
        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(meta)}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    url = f"{DRIVE_UPLOAD}/files?uploadType=multipart&convert=true"
    headers = {"Content-Type": f"multipart/related; boundary={boundary}"}

    result = api("POST", url, body=multipart, headers=headers)
    doc_id = result.get("id", "")
    doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"

    print(f"✅ Google Doc created: {title}")
    print(f"   ID:  {doc_id}")
    print(f"   URL: {doc_url}")
    return {"id": doc_id, "name": title, "url": doc_url}


def cmd_drive_read_doc(file_id: str) -> str:
    """Export a Google Doc as plain text."""
    params = urllib.parse.urlencode({"mimeType": "text/plain"})
    data = api("GET", f"{DRIVE_BASE}/files/{file_id}/export?{params}", expect_json=False)
    text = data.decode("utf-8", errors="replace")
    print(text)
    return text


def cmd_drive_link(file_id: str) -> str:
    """Get the shareable link for a file."""
    result = api("GET", f"{DRIVE_BASE}/files/{file_id}?fields=id,name,webViewLink")
    link = result.get("webViewLink", f"https://docs.google.com/document/d/{file_id}/edit")
    print(f"Name: {result.get('name','?')}")
    print(f"Link: {link}")
    return link


def cmd_drive_update_doc(file_id: str, file_path: str):
    """Append content from a file to an existing Google Doc via Docs API."""
    if not os.path.exists(file_path):
        die(f"File not found: {file_path}")

    content = open(file_path, "r", encoding="utf-8").read()

    # Use Docs API batchUpdate to append text
    body = {
        "requests": [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": "\n\n" + content,
                }
            }
        ]
    }
    result = api("POST", f"{DOCS_BASE}/documents/{file_id}:batchUpdate", body=body)
    print(f"✅ Doc updated: {file_id}")
    return result


# ── Agent save — the main workflow function ───────────────────────────────────

def cmd_agent_save(agent: str, file_path: str, title: str) -> dict:
    """
    Save an agent report as a Google Doc in the correct Drive folder.
    This is the primary function called by agents after completing tasks.

    Returns {id, name, url, folder} for posting to ClickUp.
    """
    # Dynamic lookup from business.json — no hardcoding
    folder_id   = _get_agent_folder(agent)
    folder_name = _get_folder_name(folder_id)

    result = cmd_drive_create_doc(file_path, title, folder_id)
    result["folder"] = folder_name
    result["folder_id"] = folder_id

    # Print structured output for ClickUp comment
    print(f"\n📁 GOOGLE DRIVE DELIVERABLE")
    print(f"Document: {title}")
    print(f"URL: {result['url']}")
    print(f"Folder: {folder_name}")
    print(f"Local: {file_path}")

    return result


# ── CLI dispatcher ────────────────────────────────────────────────────────────

COMMANDS = {
    "auth-url":          lambda a: cmd_auth_url(),
    "exchange":          lambda a: cmd_exchange(a[0]),
    "refresh":           lambda a: cmd_refresh(),
    "drive-list-folder": lambda a: cmd_drive_list_folder(a[0]),
    "drive-search":      lambda a: cmd_drive_search(a[0]),
    "drive-mkdir":       lambda a: cmd_drive_mkdir(a[0], a[1] if len(a) > 1 else None),
    "drive-create-doc":  lambda a: cmd_drive_create_doc(a[0], a[1], a[2] if len(a) > 2 else None),
    "drive-read-doc":    lambda a: cmd_drive_read_doc(a[0]),
    "drive-update-doc":  lambda a: cmd_drive_update_doc(a[0], a[1]),
    "drive-link":        lambda a: cmd_drive_link(a[0]),
    "agent-save":        lambda a: cmd_agent_save(a[0], a[1], a[2]),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in COMMANDS:
        print(__doc__)
        sys.exit(0 if not args else 1)
    COMMANDS[args[0]](args[1:])
