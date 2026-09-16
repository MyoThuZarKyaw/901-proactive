import json
import logging
from typing import Any

import redis.asyncio as aioredis
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class RedisPublisherService:

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client
        #  docker exec -it redis redis-cli ping
        #  docker exec -it redis redis-cli SUBSCRIBE circuit-breaker-channel
        #  docker exec -it redis redis-cli PUBLISH circuit-breaker-channel "payment-service"

    async def publish(
        self,
        channel: str,
        payload: BaseModel | dict[str, Any],
    ) -> int:
        """Publish a JSON payload to a Redis channel asynchronously."""
        if isinstance(payload, BaseModel):
            message = payload.model_dump_json()
        else:
            message = json.dumps(payload)

        try:
            # Non-blocking async publish
            subscribers: int = await self._r.publish(channel, message)
            logger.info(
                "Alert sent to channel '%s'. Received by %d subscriber(s).",
                channel,
                subscribers,
            )
            return subscribers
        except aioredis.RedisError as e:
            logger.error("Failed to publish message to Redis: %s", str(e))
            raise
