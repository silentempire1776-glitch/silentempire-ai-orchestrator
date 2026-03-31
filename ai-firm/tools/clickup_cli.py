#!/usr/bin/env python3
"""
ClickUp CLI for Silent Empire / Jarvis
Usage from EXEC tag:
  python3 /ai-firm/tools/clickup_cli.py list-all
  python3 /ai-firm/tools/clickup_cli.py list-tasks <list_id>
  python3 /ai-firm/tools/clickup_cli.py get-task <task_id>
  python3 /ai-firm/tools/clickup_cli.py create-task <list_id> "Title" "Description"
  python3 /ai-firm/tools/clickup_cli.py post-comment <task_id> "comment text"
  python3 /ai-firm/tools/clickup_cli.py complete-task <task_id>
  python3 /ai-firm/tools/clickup_cli.py get-comments <task_id>
  python3 /ai-firm/tools/clickup_cli.py find-list "List Name"
"""

import json, os, sys, urllib.request, urllib.error

CLICKUP_API = "https://api.clickup.com/api/v2"
TOKEN = os.environ.get("CLICKUP_TOKEN", "pk_198019841_HS354LOIQ9UQCUFKQKRQ5TJOIL4PFFKW")

def api(method, endpoint, data=None, _retries=3, _delay=1):
    import time
    url = f"{CLICKUP_API}{endpoint}"
    body = json.dumps(data).encode() if data else None
    for attempt in range(_retries):
        req = urllib.request.Request(url, data=body,
              headers={"Authorization": TOKEN, "Content-Type": "application/json"},
              method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()[:300]
            if attempt < _retries - 1 and e.code in (401, 429, 500, 502, 503, 504):
                time.sleep(_delay * (attempt + 1))
                continue
            print(f"API Error {e.code}: {err_body}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            if attempt < _retries - 1:
                time.sleep(_delay * (attempt + 1))
                continue
            print(f"API Error: {e}", file=sys.stderr)
            sys.exit(1)

def get_team_id():
    r = api("GET", "/team")
    teams = r.get("teams", [])
    if not teams:
        print("No teams found"); sys.exit(1)
    return teams[0]["id"]

def cmd_list_all():
    team_id = get_team_id()
    spaces = api("GET", f"/team/{team_id}/space?archived=false").get("spaces", [])
    for s in spaces:
        print(f"\n📁 SPACE: {s['name']} ({s['id']})")
        folders = api("GET", f"/space/{s['id']}/folder?archived=false").get("folders", [])
        for fo in folders:
            print(f"  📂 {fo['name']} ({fo['id']})")
            lists = api("GET", f"/folder/{fo['id']}/list?archived=false").get("lists", [])
            for li in lists:
                tc = li.get("task_count", "?")
                print(f"    📋 {li['name']} ({li['id']}) — {tc} tasks")
        # folderless lists
        flists = api("GET", f"/space/{s['id']}/list?archived=false").get("lists", [])
        for li in flists:
            print(f"  📋 {li['name']} ({li['id']})")

def cmd_list_tasks(list_id):
    tasks = api("GET", f"/list/{list_id}/task?archived=false").get("tasks", [])
    if not tasks:
        print("No tasks found.")
        return
    for t in tasks:
        status = t.get("status", {}).get("status", "unknown")
        assignees = ", ".join(a.get("username","?") for a in t.get("assignees",[]))
        print(f"  [{status}] {t['name']} ({t['id']}){' — '+assignees if assignees else ''}")

def cmd_get_task(task_id):
    t = api("GET", f"/task/{task_id}")
    print(f"Task: {t['name']}")
    print(f"Status: {t.get('status',{}).get('status','?')}")
    print(f"Description: {(t.get('description') or 'none')[:500]}")
    print(f"URL: {t.get('url','')}")

def cmd_create_task(list_id, title, desc=None):
    data = {"name": title}
    if desc: data["description"] = desc
    t = api("POST", f"/list/{list_id}/task", data)
    print(f"Created: {t['name']} ({t['id']})")
    print(f"URL: {t.get('url','')}")

def cmd_post_comment(task_id, text):
    api("POST", f"/task/{task_id}/comment", {"comment_text": text})
    print(f"Comment posted to {task_id}")

def cmd_complete_task(task_id):
    api("PUT", f"/task/{task_id}", {"status": "complete"})
    print(f"Task {task_id} marked complete")

def cmd_get_comments(task_id):
    comments = api("GET", f"/task/{task_id}/comment").get("comments", [])
    print(f"{len(comments)} comment(s):")
    for c in comments:
        user = c.get("user", {}).get("username", "?")
        text = c.get("comment_text", "")[:300]
        print(f"  @{user}: {text}")

def cmd_find_list(name):
    """Fuzzy-match a list name to its ID from live ClickUp data."""
    import difflib
    team_id = get_team_id()
    spaces = api("GET", f"/team/{team_id}/space?archived=false").get("spaces", [])
    candidates = {}
    for s in spaces:
        folders = api("GET", f"/space/{s['id']}/folder?archived=false").get("folders", [])
        for fo in folders:
            lists = api("GET", f"/folder/{fo['id']}/list?archived=false").get("lists", [])
            for li in lists:
                candidates[li["name"].lower()] = (li["name"], li["id"])
        flists = api("GET", f"/space/{s['id']}/list?archived=false").get("lists", [])
        for li in flists:
            candidates[li["name"].lower()] = (li["name"], li["id"])

    name_lower = name.lower().strip()

    # Exact match
    if name_lower in candidates:
        orig, lid = candidates[name_lower]
        print(f"MATCH: {orig} → {lid}")
        return

    # Fuzzy match
    keys = list(candidates.keys())
    matches = difflib.get_close_matches(name_lower, keys, n=3, cutoff=0.4)
    if matches:
        print(f"FUZZY MATCHES for '{name}':")
        for m in matches:
            orig, lid = candidates[m]
            print(f"  {orig} → {lid}")
        return

    print(f"NOT FOUND: No list matching '{name}'")
    print("Run list-all to see all available lists.")

cmds = {
    "list-all": lambda a: cmd_list_all(),
    "list-tasks": lambda a: cmd_list_tasks(a[0]),
    "get-task": lambda a: cmd_get_task(a[0]),
    "create-task": lambda a: cmd_create_task(a[0], a[1], a[2] if len(a)>2 else None),
    "post-comment": lambda a: cmd_post_comment(a[0], a[1]),
    "complete-task": lambda a: cmd_complete_task(a[0]),
    "get-comments": lambda a: cmd_get_comments(a[0]),
    "find-list": lambda a: cmd_find_list(a[0]),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in cmds:
        print("Commands: " + ", ".join(cmds.keys()))
        sys.exit(1)
    cmds[args[0]](args[1:])
