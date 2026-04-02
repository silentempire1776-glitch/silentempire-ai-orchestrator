# HEARTBEAT.md

When you receive a heartbeat, follow this checklist. If nothing needs attention, reply HEARTBEAT_OK.

## Check Order

### 1. Context Load
- Read recent `memory/` files
- Check `MEMORY.md` for important context
- Note anything significant from recent sessions

### 2. Active Work
- Any tasks left incomplete?
- Any deadlines approaching?
- Any blockers I should know about?

### 3. Maintenance
- Memory files need updating?
- Workspace need organizing?
- Anything I can clean up?

### 4. Proactive Opportunities
- See something that needs doing?
- Have a suggestion or idea?
- Notice a pattern worth mentioning?

## Time Awareness

### Active Hours (Adjust to your schedule)
- 7am - 11pm: Full checklist
- Run proactive work during these hours

### Quiet Hours
- 11pm - 7am: HEARTBEAT_OK unless urgent
- Define "urgent" for yourself

## When to Reach Out

**Do ping your human when:**
- Something is blocked and needs input
- An important deadline is approaching
- You completed something significant
- You found something they should know

**Don't ping when:**
- It's quiet hours and not urgent
- You just checked and nothing changed
- The update can wait for tomorrow
- You're just saying "nothing new"

## Proactive Work (Do Without Asking)

During heartbeats, you can:
- Update memory files
- Organize the workspace
- Draft content for review
- Research things you'll need
- Plan upcoming work

You should NOT:
- Send external messages
- Make purchases
- Post anything publicly
- Take irreversible actions

## If Nothing Needs Attention

Just reply: HEARTBEAT_OK

Don't force an update. Silence is fine.

---

<!-- 
TO CUSTOMIZE:
- Adjust Active/Quiet hours to your schedule
- Add specific things to check (email, calendar, projects)
- Define what counts as "urgent" for you
- Add project-specific heartbeat tasks
-->

### YouTube transcript + competitive intelligence (analyze a specific video):
[EXEC:bash]python3 /ai-firm/tools/youtube_transcript.py "https://www.youtube.com/watch?v=VIDEO_ID"[/EXEC]

### YouTube full pipeline (search + analyze all videos on a topic):
[EXEC:bash]python3 /ai-firm/tools/youtube_transcript.py --topic "asset protection trust divorce" --max 3[/EXEC]

---

## CLICKUP BUSINESS OS — HOW IT WORKS

Jarvis automatically scans ClickUp every 10 minutes (configurable in autonomy_config.json).

### What triggers agent dispatch:
When Curtis posts a comment on ANY task in the monitored lists, Jarvis:
1. Reads the full task (description + all custom fields + subtasks up to 7 levels deep)
2. Classifies which agent should handle it
3. Checks prerequisites (Priority Order field)
4. Dispatches the agent with full context
5. Posts an acknowledgment comment immediately
6. Posts a completion comment with report path when done
7. Updates the Deliverable and Action Items custom fields

### Monitored lists (all of COMMAND CENTER + Silent Vault Launch):
Current Sprint, Sprint Backlog, Active Blockers, 10K Roadmap,
Competitive Intelligence, Channel Strategy, GTM Playbooks,
Approvals Queue, Jarvis DMs, Research Vault, Lessons Learned,
Research & Strategy, Content & Assets, Execution & Sales

### How Curtis directs agents:
Just comment on any task. Jarvis reads it and acts.
- "Research this and give me a full competitive analysis" → research agent
- "Write the sales copy for this offer" → sales agent
- "Build the automation for this" → code agent
- "Pivot — instead of X, let's do Y" → Jarvis updates memory + re-dispatches

### Prerequisite enforcement:
Tasks with Priority Order 1 = foundational, always proceed.
Tasks with Priority Order 2+ = wait for Priority 1 tasks to be marked complete.
Disable by setting clickup.prerequisite_enforcement: false in autonomy_config.json.

### Dynamic custom fields:
Jarvis reads ALL custom fields on every task automatically.
Add new fields in ClickUp — Jarvis will see them on the next scan.
No code changes needed.

### Subtask depth:
Jarvis drills down up to 7 subtask levels for full context.
All subtask names and statuses are included in agent instructions.

---
