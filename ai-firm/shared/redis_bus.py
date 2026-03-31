import redis
import os
import json

# FORCE SINGLE REDIS (CRITICAL)
REDIS_URL = os.getenv("REDIS_URL", "redis://app-redis-1:6379/0")

r = redis.from_url(REDIS_URL)


# -------------------------------
# Durable Queue Mode
# -------------------------------

def enqueue(queue_name: str, message: dict):
    r.lpush(queue_name, json.dumps(message))


def dequeue_blocking(queue_name: str):
    _, data = r.brpop(queue_name)
    return json.loads(data)


# -------------------------------
# Optional Pub/Sub (legacy)
# -------------------------------

def publish(channel: str, message: dict):
    r.publish(channel, json.dumps(message))


def subscribe(channel: str):
    pubsub = r.pubsub()
    pubsub.subscribe(channel)
    return pubsub
