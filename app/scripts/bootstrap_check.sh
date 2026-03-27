#!/usr/bin/env bash
set -euo pipefail
echo "== containers =="
docker ps --format "table {{.Names}}\t{{.Status}}" | egrep "app-api-1|app-worker-default-1|app-postgres-1|app-redis-1|app-caddy-1" || true
echo
echo "== health =="
curl -fsS http://127.0.0.1:8000/health; echo
echo
echo "== redis queues =="
docker exec app-redis-1 redis-cli LLEN "queue:orchestrator"
docker exec app-redis-1 redis-cli LLEN "queue:default"
docker exec app-redis-1 redis-cli LLEN "queue:dead"
echo
echo "== db latest =="
docker exec -i app-postgres-1 psql -U silent -d silentempire -c \
"select id,status,provider,model_used,updated_at from jobs order by updated_at desc limit 5;"
echo
echo "== pricing rows =="
docker exec -i app-postgres-1 psql -U silent -d silentempire -c \
"select provider,model,input_cost_per_1k_tokens,output_cost_per_1k_tokens from provider_pricing order by provider,model;"
