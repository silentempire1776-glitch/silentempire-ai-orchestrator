import redis, os
r = redis.from_url(os.getenv("REDIS_URL", "redis://app-redis-1:6379/0"))
for q in ["queue.mcp.memory","queue.mcp.crm","queue.mcp.llm_router","queue.mcp.filesystem","queue.mcp.infra"]:
    print(f"{q}: {r.llen(q)} items")
print("All MCP queues checked.")
