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
