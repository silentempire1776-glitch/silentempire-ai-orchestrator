# Silent Empire AI — VPS Infrastructure

This repository contains the Silent Empire AI autonomous agent system.

## Stack
- FastAPI backend + PostgreSQL + Redis
- Jarvis orchestrator + 10 specialist agents
- Mission Control UI (Next.js)
- Docker Compose on Hostinger VPS (Ubuntu 22.04)

## Structure
- `/srv/silentempire/app` — API, worker, Mission Control UI
- `/srv/silentempire/ai-firm` — Jarvis orchestrator + agents

## Access
- Mission Control: https://jarvis.silentempireai.com
