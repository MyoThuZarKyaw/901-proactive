import json
from datetime import datetime, timezone

import redis


class RedisPublisherService:

    def __init__(self):
        self._r = redis.Redis(host="localhost", port=6379, decode_responses=True)

    def publish(self):
        # publish() returns an INTEGER: how many clients were listening
        subscribers = self._r.publish(
            "circuit-breaker-channel",
            json.dumps(
                {
                    "targetService": "payment-service",
                    "status": "DEGRADED",
                    "reason": "Average latency > 3500ms detected over last 10s",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
        )
        print(f" [✓] Alert sent. Received by {subscribers} subscriber(s).")
        return subscribers
