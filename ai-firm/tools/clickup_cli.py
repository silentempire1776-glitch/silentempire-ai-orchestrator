#!/usr/bin/env python3
"""
ClickUp CLI for Silent Empire / Jarvis

AVAILABLE COMMANDS:
  list-all                                         List all spaces, folders, and lists
  find-list "List Name"                            Fuzzy-match a list name to its ID
  list-tasks <list_id>                             List tasks in a list
  get-task <task_id>                               Full task detail (name, desc, status, priority, assignees,
                                                   due date, tags, custom fields, attachments, watchers, url)
  get-custom-fields <task_id>                      List custom fields with field_id, name, type, value
  create-task <list_id> "Title" ["Description"]   Create a new task
  update-task <task_id> [--name "..."] [--status "..."] [--priority N] [--due "YYYY-MM-DD"]
                                                   Update task fields (priority: 1=urgent 2=high 3=normal 4=low)
  update-description <task_id> "New description"  Update task description
  set-custom-field <task_id> <field_id> "value"   Set a custom field value
  complete-task <task_id>                          Mark task complete
  post-comment <task_id> "text"                    Post a comment
  get-comments <task_id>                           List comments with IDs, author, date
  reply-comment <task_id> <comment_id> "text"     Reply to a specific comment (threaded if supported)
  list-attachments <task_id>                       List all attachments
  attach-url <task_id> "url" ["title"]             Attach a URL to a task via comment
"""

import json, os, sys, time, urllib.request, urllib.error
from datetime import datetime

CLICKUP_API = "https://api.clickup.com/api/v2"
# Support both env var names; hardcoded fallback for this deployment
# CLICKUP_OS_PATCH
def _load_token() -> str:
    """Load ClickUp token from env var or .env file."""
    # Check environment first
    t = os.environ.get("CLICKUP_API_TOKEN") or os.environ.get("CLICKUP_TOKEN")
    if t:
        return t
    # Fall back to reading .env files directly
    for env_path in [
        "/srv/silentempire/ai-firm/.env",
        "/srv/silentempire/app/.env",
    ]:
        try:
            for line in open(env_path):
                line = line.strip()
                if line.startswith("CLICKUP_TOKEN=") or line.startswith("CLICKUP_API_TOKEN="):
                    return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""

TOKEN = _load_token()

HELP = __doc__


# ── HTTP layer ───────────────────────────────────────────────────────────────

def api(method, endpoint, data=None, _retries=3, _delay=2):
    """Make a ClickUp API request. Exits with error on failure."""
    url = f"{CLICKUP_API}{endpoint}"
    body = json.dumps(data).encode() if data is not None else None
    for attempt in range(_retries):
        req = urllib.request.Request(
            url, data=body,
            headers={"Authorization": TOKEN, "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()[:500]
            if e.code == 429 and attempt < _retries - 1:
                wait = _delay * (2 ** attempt)
                print(f"Rate limited (429). Retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code in (500, 502, 503, 504) and attempt < _retries - 1:
                time.sleep(_delay)
                continue
            print(f"HTTP {e.code}: {err_body}", file=sys.stderr)
            sys.exit(1)
        except Exception as exc:
            if attempt < _retries - 1:
                time.sleep(_delay)
                continue
            print(f"Request error: {exc}", file=sys.stderr)
            sys.exit(1)


def api_try(method, endpoint, data=None):
    """Like api() but returns (True, result) or (False, error_str) instead of sys.exit."""
    url = f"{CLICKUP_API}{endpoint}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=body,
        headers={"Authorization": TOKEN, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()[:300]
        return False, f"HTTP {e.code}: {err_body}"
    except Exception as exc:
        return False, str(exc)


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_team_id():
    r = api("GET", "/team")
    teams = r.get("teams", [])
    if not teams:
        print("No teams found.")
        sys.exit(1)
    return teams[0]["id"]


def fmt_ts(ms):
    """Format millisecond timestamp to readable date."""
    if not ms:
        return "none"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ms)


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_list_all():
    team_id = get_team_id()
    spaces = api("GET", f"/team/{team_id}/space?archived=false").get("spaces", [])
    for s in spaces:
        print(f"\nSPACE: {s['name']} ({s['id']})")
        folders = api("GET", f"/space/{s['id']}/folder?archived=false").get("folders", [])
        for fo in folders:
            print(f"  FOLDER: {fo['name']} ({fo['id']})")
            lists = api("GET", f"/folder/{fo['id']}/list?archived=false").get("lists", [])
            for li in lists:
                print(f"    LIST: {li['name']} ({li['id']}) — {li.get('task_count', '?')} tasks")
        flists = api("GET", f"/space/{s['id']}/list?archived=false").get("lists", [])
        for li in flists:
            print(f"  LIST: {li['name']} ({li['id']})")


def cmd_find_list(name):
    """Fuzzy-match a list name to its ID."""
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
    if name_lower in candidates:
        orig, lid = candidates[name_lower]
        print(f"MATCH: {orig} → {lid}")
        return

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


def cmd_list_tasks(list_id):
    tasks = api("GET", f"/list/{list_id}/task?archived=false").get("tasks", [])
    if not tasks:
        print("No tasks found.")
        return
    for t in tasks:
        status = t.get("status", {}).get("status", "unknown")
        assignees = ", ".join(a.get("username", "?") for a in t.get("assignees", []))
        print(f"  [{status}] {t['name']} ({t['id']}){' — ' + assignees if assignees else ''}")


def cmd_get_task(task_id):
    t = api("GET", f"/task/{task_id}?include_subtasks=true&custom_task_ids=false")
    print(f"ID:          {t['id']}")
    print(f"Name:        {t['name']}")
    print(f"Status:      {t.get('status', {}).get('status', '?')}")
    priority = t.get("priority") or {}
    print(f"Priority:    {priority.get('priority', 'none')}")
    assignees = ", ".join(a.get("username", "?") for a in t.get("assignees", []))
    print(f"Assignees:   {assignees or 'none'}")
    print(f"Due Date:    {fmt_ts(t.get('due_date'))}")
    tags = ", ".join(tg.get("name", "") for tg in t.get("tags", []))
    print(f"Tags:        {tags or 'none'}")
    watchers = ", ".join(w.get("username", "?") for w in t.get("watchers", []))
    print(f"Watchers:    {watchers or 'none'}")
    print(f"URL:         {t.get('url', '')}")
    print(f"\nDescription:\n{t.get('description') or '(none)'}")

    cfields = t.get("custom_fields", [])
    if cfields:
        print(f"\nCustom Fields ({len(cfields)}):")
        for cf in cfields:
            val = cf.get("value")
            print(f"  [{cf['id']}] {cf['name']} ({cf.get('type', '?')}): {val if val is not None else '(empty)'}")

    attachments = t.get("attachments", [])
    if attachments:
        print(f"\nAttachments ({len(attachments)}):")
        for att in attachments:
            name = att.get("title") or att.get("file_name") or "untitled"
            print(f"  {name} — {att.get('url', '?')} (added {fmt_ts(att.get('date'))})")

    subtasks = t.get("subtasks", [])
    if subtasks:
        print(f"\nSubtasks ({len(subtasks)}):")
        for st in subtasks:
            print(f"  [{st.get('status', {}).get('status', '?')}] {st['name']} ({st['id']})")


def cmd_get_custom_fields(task_id):
    t = api("GET", f"/task/{task_id}?custom_task_ids=false")
    cfields = t.get("custom_fields", [])
    if not cfields:
        print("No custom fields on this task.")
        return
    print(f"Custom Fields for task {task_id} ({len(cfields)} total):")
    for cf in cfields:
        val = cf.get("value")
        print(f"\n  Field ID:   {cf['id']}")
        print(f"  Name:       {cf['name']}")
        print(f"  Type:       {cf.get('type', '?')}")
        print(f"  Value:      {val if val is not None else '(empty)'}")


def cmd_update_description(task_id, description):
    api("PUT", f"/task/{task_id}", {"description": description})
    print(f"Description updated for task {task_id}")


def cmd_set_custom_field(task_id, field_id, value):
    # Auto-cast value to appropriate type
    payload_value = value
    if value.lower() in ("true", "false"):
        payload_value = value.lower() == "true"
    else:
        try:
            payload_value = int(value)
        except ValueError:
            try:
                payload_value = float(value)
            except ValueError:
                payload_value = value

    api("POST", f"/task/{task_id}/field/{field_id}", {"value": payload_value})
    print(f"Custom field {field_id} set to '{value}' on task {task_id}")


def cmd_create_task(list_id, title, desc=None):
    data = {"name": title}
    if desc:
        data["description"] = desc
    t = api("POST", f"/list/{list_id}/task", data)
    print(f"Created: {t['name']} ({t['id']})")
    print(f"URL: {t.get('url', '')}")


def cmd_update_task(task_id, raw_args):
    """Update task with --name, --status, --priority, --due flags."""
    data = {}
    i = 0
    while i < len(raw_args):
        flag = raw_args[i]
        if flag == "--name" and i + 1 < len(raw_args):
            data["name"] = raw_args[i + 1]
            i += 2
        elif flag == "--status" and i + 1 < len(raw_args):
            data["status"] = raw_args[i + 1]
            i += 2
        elif flag == "--priority" and i + 1 < len(raw_args):
            try:
                data["priority"] = int(raw_args[i + 1])
            except ValueError:
                print(f"Priority must be 1-4 (1=urgent, 2=high, 3=normal, 4=low)", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif flag == "--due" and i + 1 < len(raw_args):
            try:
                dt = datetime.strptime(raw_args[i + 1], "%Y-%m-%d")
                data["due_date"] = int(dt.timestamp() * 1000)
            except ValueError:
                print(f"Invalid date: '{raw_args[i+1]}'. Use YYYY-MM-DD", file=sys.stderr)
                sys.exit(1)
            i += 2
        else:
            print(f"Unknown flag: {flag}. Valid: --name --status --priority --due", file=sys.stderr)
            sys.exit(1)

    if not data:
        print("No fields specified. Use --name, --status, --priority, --due")
        sys.exit(1)

    api("PUT", f"/task/{task_id}", data)
    print(f"Task {task_id} updated: {', '.join(f'{k}={v}' for k, v in data.items())}")


def cmd_complete_task(task_id):
    api("PUT", f"/task/{task_id}", {"status": "complete"})
    print(f"Task {task_id} marked complete")


def cmd_post_comment(task_id, text):
    api("POST", f"/task/{task_id}/comment", {"comment_text": text})
    print(f"Comment posted to task {task_id}")


def cmd_get_comments(task_id):
    comments = api("GET", f"/task/{task_id}/comment").get("comments", [])
    print(f"{len(comments)} comment(s) on task {task_id}:")
    for c in comments:
        cid = c.get("id", "?")
        user = c.get("user", {}).get("username", "?")
        date = fmt_ts(c.get("date"))
        text = c.get("comment_text", "")[:400]
        print(f"\n  Comment ID: {cid}")
        print(f"  Author:     @{user}")
        print(f"  Date:       {date}")
        print(f"  Text:       {text}")


def cmd_reply_comment(task_id, comment_id, reply_text):
    """Reply to a comment — tries threaded reply, falls back to regular comment."""
    ok, result = api_try("POST", f"/comment/{comment_id}/reply", {"comment_text": reply_text})
    if ok:
        print(f"Threaded reply posted to comment {comment_id}")
        return
    # Threaded replies not supported or endpoint differs — fallback
    print(f"Threaded reply failed ({result}), falling back to regular comment...")
    fallback = f"> Replying to comment {comment_id}:\n\n{reply_text}"
    api("POST", f"/task/{task_id}/comment", {"comment_text": fallback})
    print(f"Reply posted to task {task_id} as regular comment with reply prefix")


def cmd_list_attachments(task_id):
    t = api("GET", f"/task/{task_id}?custom_task_ids=false")
    attachments = t.get("attachments", [])
    if not attachments:
        print("No attachments found.")
        return
    print(f"Attachments for task {task_id} ({len(attachments)} total):")
    for att in attachments:
        name = att.get("title") or att.get("file_name") or "untitled"
        url = att.get("url", "?")
        added = fmt_ts(att.get("date"))
        print(f"\n  Filename:  {name}")
        print(f"  URL:       {url}")
        print(f"  Added:     {added}")


def cmd_attach_url(task_id, url, title=None):
    """Attach a URL to a task by posting it as a formatted comment."""
    comment_text = f"[{title}]({url})" if title else url
    api("POST", f"/task/{task_id}/comment", {"comment_text": comment_text})
    print(f"URL attached to task {task_id}: {url}")


# ── Dispatch ─────────────────────────────────────────────────────────────────

CMDS = {
    "list-all":           lambda a: cmd_list_all(),
    "find-list":          lambda a: cmd_find_list(a[0]),
    "list-tasks":         lambda a: cmd_list_tasks(a[0]),
    "get-task":           lambda a: cmd_get_task(a[0]),
    "get-custom-fields":  lambda a: cmd_get_custom_fields(a[0]),
    "create-task":        lambda a: cmd_create_task(a[0], a[1], a[2] if len(a) > 2 else None),
    "update-task":        lambda a: cmd_update_task(a[0], a[1:]),
    "update-description": lambda a: cmd_update_description(a[0], a[1]),
    "set-custom-field":   lambda a: cmd_set_custom_field(a[0], a[1], a[2]),
    "complete-task":      lambda a: cmd_complete_task(a[0]),
    "post-comment":       lambda a: cmd_post_comment(a[0], a[1]),
    "get-comments":       lambda a: cmd_get_comments(a[0]),
    "reply-comment":      lambda a: cmd_reply_comment(a[0], a[1], a[2]),
    "list-attachments":   lambda a: cmd_list_attachments(a[0]),
    "attach-url":         lambda a: cmd_attach_url(a[0], a[1], a[2] if len(a) > 2 else None),
}

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in CMDS:
        print(HELP)
        sys.exit(0 if not args else 1)
    CMDS[args[0]](args[1:])
