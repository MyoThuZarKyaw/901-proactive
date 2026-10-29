import json
import logging
from typing import Any

import pandas as pd
import redis.asyncio as aioredis
from pydantic import BaseModel

from advisory_service.exceptions import ApplicationException
from advisory_service.models import (
    PredictionInput,
    PredictionOutput,
    PredictionOutputState,
    PredictionStateProbabilities,
)

logger = logging.getLogger(__name__)


class RedisPublisherService:

    def __init__(self, redis_client: aioredis.Redis):
        self._r = redis_client

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


class PredictionService:

    def __init__(self, predition_model_bundle: Any):
        self.bundle = predition_model_bundle
        self.model = self.bundle["model"]
        self.feature_cols = self.bundle["features"]
        logger.info(
            f"Model loaded successfully! Features count: {len(self.feature_cols)}"
        )

    def predict_health(self, payload: PredictionInput) -> PredictionOutput:
        if self.model is None:
            raise ApplicationException(
                status_code=500, message="Prediction model is not available."
            )

        try:
            # Convert incoming dictionary to a DataFrame
            df_input = pd.DataFrame([payload.features])

            # Ensure all required model features are present; default missing ones to 0.0
            for col in self.feature_cols:
                if col not in df_input.columns:
                    df_input[col] = 0.0

            # Align column order strictly to what the model was trained on
            X = df_input[self.feature_cols]

            # Run inference
            pred_class = int(self.model.predict(X)[0])
            probabilities = self.model.predict_proba(X)[0]
            confidence = float(max(probabilities))

            state_map = {
                0: PredictionOutputState.HEALTHY,
                1: PredictionOutputState.DEGRADED,
                2: PredictionOutputState.FAILED,
            }

            return PredictionOutput(
                service_name=payload.service_name,
                prediction=pred_class,
                state=state_map.get(pred_class, "Unknown"),
                confidence=round(confidence, 3),
                probabilities=PredictionStateProbabilities(
                    healthy=round(float(probabilities[0]), 3),
                    degraded=round(float(probabilities[1]), 3),
                    failed=round(float(probabilities[2]), 3),
                ),
            )

        except Exception as e:
            raise ApplicationException(
                status_code=500, message=f"Inference error: {e!s}"
            )
