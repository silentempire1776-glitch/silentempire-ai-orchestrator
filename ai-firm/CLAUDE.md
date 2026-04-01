# Silent Empire AI — Claude Code Context

## WHAT THIS IS
Autonomous AI agent company system running on a Hostinger VPS.
Two Docker Compose stacks serving a live production system.
All changes must be surgical, backward-compatible, and verified.

## CRITICAL RULES — READ BEFORE TOUCHING ANY FILE

### NEVER wipe files
- NEVER use `with open(path, "w")` on existing production files — this has wiped files to 0 bytes
- ALL file edits must use Python patcher scripts with exact string replacement:
  ```python
  content = Path(file).read_text()
  new_content = content.replace(OLD, NEW, 1)
  Path(file).write_text(new_content)
  ```
- ALWAYS verify OLD string exists in file before replacing

### ALWAYS backup before editing
```python
import shutil
shutil.copy2(target, f"{target}.bak.{datetime.now().strftime('%Y%m%d_%H%M')}")
```

### ALWAYS verify after patching
```python
verify = Path(file).read_text()
assert "expected_new_string" in verify, "Patch did not land"
```

### docker cp for containers (NOT volume mounts)
Most containers run from baked images — edits to host files don't auto-apply.
After editing host files, copy into the running container:
```bash
docker cp /srv/silentempire/ai-firm/orchestrator/main.py jarvis-orchestrator:/app/orchestrator/main.py
docker restart jarvis-orchestrator
```

### Large files (>60KB): copy to /tmp first
```bash
cp large_file.py /tmp/large_file.py
docker cp /tmp/large_file.py container:/app/large_file.py
```

---

## INFRASTRUCTURE

### Two Docker Compose stacks

**Stack 1 — App** (`/srv/silentempire/app`)
- `app-api-1` — FastAPI API, port 8000
- `app-worker-default-1` — Job worker, port 8001 (baked image, no volume mount)
- `app-worker-default-2-1` — Second worker (no port binding)
- `app-redis-1` — Redis 7
- `app-postgres-1` — Postgres 15
- `app-caddy-1` — Reverse proxy
- `mission-control` — Next.js UI, port 3000

**Stack 2 — AI Firm** (`/srv/silentempire/ai-firm`)
- `jarvis-orchestrator` — Main orchestrator (baked image)
- `research-agent`, `revenue-agent`, `sales-agent`, `growth-agent`
- `legal-agent`, `product-agent`, `systems-agent`, `code-agent`, `voice-agent`
- `mcp-llm-router`, `mcp-memory`, `mcp-crm`, `mcp-filesystem`, `mcp-infra`
- `tool-executor`, `jarvis-timeout-monitor`

### Key file paths
```
/srv/silentempire/ai-firm/orchestrator/main.py     # Jarvis orchestrator (cp to container after edit)
/srv/silentempire/ai-firm/agents/{name}/main.py    # Agent files (cp to container after edit)
/srv/silentempire/ai-firm/shared/job_runner.py     # Shared eval loop (cp to all agents after edit)
/srv/silentempire/ai-firm/shared/config_loader.py  # Business config loader
/srv/silentempire/ai-firm/config/business.json     # Company/product/market data (white-label)
/srv/silentempire/ai-firm/config/agents.json       # Per-agent role titles + deliverables
/srv/silentempire/ai-firm/config/doctrine_template.md  # Doctrine with {{variables}}
/srv/silentempire/app/ai_engine/providers/anthropic_provider.py  # Anthropic API (cp to worker after edit)
/srv/silentempire/app/services/workers/default/worker.py  # Job worker (cp to worker after edit)
/srv/silentempire/ai-firm/data/reports/            # Agent output reports
/srv/silentempire/ai-firm/data/memory/agents/      # Per-agent persistent memory
```

---

## DEPLOY SEQUENCES

### After editing orchestrator
```bash
docker cp /srv/silentempire/ai-firm/orchestrator/main.py jarvis-orchestrator:/app/orchestrator/main.py
docker restart jarvis-orchestrator
docker logs jarvis-orchestrator --tail 10
```

### After editing an agent
```bash
docker cp /srv/silentempire/ai-firm/agents/{name}/main.py {name}-agent:/app/main.py
docker restart {name}-agent
```

### After editing job_runner.py (copy to all agents)
```bash
AGENTS="research-agent revenue-agent sales-agent growth-agent legal-agent product-agent systems-agent code-agent"
for agent in $AGENTS; do
    docker cp /srv/silentempire/ai-firm/shared/job_runner.py ${agent}:/app/job_runner.py
done
```

### After editing worker or anthropic_provider
```bash
docker cp /srv/silentempire/app/ai_engine/providers/anthropic_provider.py app-worker-default-1:/app/ai_engine/providers/anthropic_provider.py
cd /srv/silentempire/app && docker compose restart worker-default
```

### Full ai-firm rebuild (only when Dockerfiles change)
```bash
cd /srv/silentempire/ai-firm && docker compose down && docker compose up -d --build
sleep 15
docker cp /srv/silentempire/ai-firm/orchestrator/main.py jarvis-orchestrator:/app/orchestrator/main.py
docker restart jarvis-orchestrator
```

---

## ARCHITECTURE PATTERNS

### Agent eval loop
All eval agents use submit_and_wait_with_eval:
```python
result_text = submit_and_wait_with_eval(AGENT_NAME, instruction, task_desc)
```
Memory auto-saves for scores >= 6.

### Business config (white-label)
All business data in /srv/silentempire/ai-firm/config/business.json.
Never hardcode "Silent Empire AI" or "Silent Vault" in agent logic.

### Model routing
- claude-* → Anthropic
- gpt-*, o1, o3, o4* → OpenAI
- Everything else → NVIDIA NIM
- Overrides in Redis: agent:model_override:{agent_name}

### Fail-fast philosophy
No silent fallbacks. No fabricated success. All errors surfaced.

---

## LONG-RUNNING TOOLS — SYSTEMD SERVICE PATTERN
Any tool that runs continuously (listener, poller, monitor, bot, daemon) MUST be
deployed as a systemd service — not just written as a script.

Follow the claude-bridge pattern exactly:

```ini
[Unit]
Description=Service description
After=network.target docker.service

[Service]
Type=simple
User=root
WorkingDirectory=/srv/silentempire/ai-firm/tools
Environment=ENV_VAR=value
ExecStart=/usr/bin/python3 /srv/silentempire/ai-firm/tools/your_tool.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Deploy commands:
```bash
# Write unit file
cat > /etc/systemd/system/your-service.service << 'EOF'
[unit file content]
EOF

systemctl daemon-reload
systemctl enable your-service
systemctl start your-service
systemctl is-active your-service   # verify: should print "active"
```

Existing persistent services on this VPS:
- `claude-bridge` — Claude Code HTTP bridge on port 9999
- `telegram-listener` — Telegram bot listener, forwards to Jarvis at localhost:8000

NEVER just write a script and stop. A long-running tool is not complete until it has:
1. The Python script written and tested
2. A systemd unit file at /etc/systemd/system/
3. Service enabled and started
4. Status verified as "active"

---

## FORBIDDEN PATTERNS
- with open(path, "w") on existing files → wipes to 0 bytes
- Guessing file contents without reading first
- Running full stack rebuild unnecessarily
- Hardcoding business names in agent logic
- Silent error swallowing

---

## VERIFICATION COMMANDS
```bash
docker ps | grep -c "Up"           # Should be 25
docker ps | grep Restarting        # Should be empty
docker logs jarvis-orchestrator --tail 20
docker logs app-worker-default-1 --tail 20
```

## LIVE URLS
- Mission Control: https://jarvis.silentempireai.com
- API: http://localhost:8000
- Claude Bridge: http://172.18.0.1:9999
