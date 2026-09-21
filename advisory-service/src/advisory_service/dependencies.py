from fastapi import Request

from .services import RedisPublisherService


def get_redis_publisher(request: Request) -> RedisPublisherService:
    # Uses the single Redis client created once during app startup
    return RedisPublisherService(redis_client=request.app.state.redis)
