#!/usr/bin/env bash
set -euo pipefail

echo "== API health =="
curl -fsS https://jarvis.silentempireai.com/api/health; echo

echo
echo "== ai-firm containers =="
docker ps --format "table {{.Names}}\t{{.Status}}" | egrep "jarvis-orchestrator|research-agent|revenue-agent|sales-agent|growth-agent|product-agent|legal-agent|systems-agent|jarvis-timeout-monitor" || true

echo
echo "== orchestrator env =="
docker exec -it jarvis-orchestrator bash -lc "echo API_BASE_URL=\$API_BASE_URL" || true

echo
echo "== redis queues =="
docker exec app-redis-1 redis-cli LLEN "queue.orchestrator" || true
docker exec app-redis-1 redis-cli LLEN "queue.orchestrator.results" || true
docker exec app-redis-1 redis-cli LLEN "queue.orchestrator.dlq" 2>/dev/null || true
docker exec app-redis-1 redis-cli LLEN "queue:orchestrator" || true
docker exec app-redis-1 redis-cli LLEN "queue:default" || true

echo
echo "== orchestrator recent (fallback since-startup if container is new) =="

STARTED_AT="$(docker inspect -f '{{.State.StartedAt}}' jarvis-orchestrator 2>/dev/null || true)"
echo "StartedAt: $STARTED_AT"

# Always show last 120 lines (even if --since would return nothing)
docker logs --tail=120 jarvis-orchestrator | egrep -n "Dispatching to|Result received from|Chain complete|HTTPError|/jobs|chain_id" || true
