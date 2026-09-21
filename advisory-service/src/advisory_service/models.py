from datetime import datetime, timezone

from pydantic import BaseModel, Field


class AdviseResponse(BaseModel):
    metric: str = Field(..., description="Metrics gathered from Prometheus")
    response: str = Field(..., description="Response returned by the inference engine")
    event: str = Field(..., description="Action taken based on the response")


class CircuitBreakerPayload(BaseModel):
    """Pydantic model ensures type-safety and automatic JSON serialization."""

    target_service: str
    status: str
    reason: str
    timestamp: datetime = datetime.now(timezone.utc)
