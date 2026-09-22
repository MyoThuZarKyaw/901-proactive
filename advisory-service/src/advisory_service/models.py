from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_serializer


class TelemetryMetrics(BaseModel):
    timestamp: int | None = None
    datetime_utc: str | None = None
    target_cpu: float
    target_mem: float
    target_throughput: float
    target_latency: float
    target_error_rate: float
    target_live_threads: float
    target_active_requests: float
    # Optional / Derived indicators
    latency_delta_30s: float | None = None
    latency_delta_60s: float | None = None
    latency_rolling_mean_1m: float | None = None
    latency_surge_ratio: float | None = None
    latency_zscore: float | None = None


class PredictionInput(BaseModel):
    service_name: str = Field(..., example="inventory_service")
    timestamp: int | None = Field(..., example=1789701157)
    features: dict[str, Any] | None


class PredictionStateProbabilities(BaseModel):
    healthy: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Probability that the service is operating normally",
        examples=[0.852],
    )
    degraded: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Probability that the service is experiencing performance degradation",
        examples=[0.124],
    )
    failed: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Probability that the service has failed or is in an outage",
        examples=[0.024],
    )


class PredictionOutputState(StrEnum):
    HEALTHY = "Healthy"
    DEGRADED = "Degraded"
    FAILED = "Failed"


class PredictionOutput(BaseModel):
    service_name: str = Field(
        ...,
        description="Target microservice identifier",
        examples=["inventory_service"],
    )
    prediction: int | str = Field(
        ...,
        description="Predicted class index or category identifier",
        examples=[0],
    )
    state: PredictionOutputState = Field(
        ...,
        description="Human-readable operational health state",
        examples=["Healthy"],
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Model confidence score for the winning class (0.0 to 1.0)",
        examples=[0.852],
    )
    probabilities: PredictionStateProbabilities = Field(
        ...,
        description="Multi-class probability distribution output",
    )


class AdvisoryEvent(BaseModel):
    target_service: str = Field(..., description="Targeted service name")
    status: PredictionOutputState = Field(..., description="Degraded or Failed?")
    reason: str = Field(None)  # Defaults to None (Optional)
    timestamp: datetime = datetime.now(timezone.utc)

    @field_serializer("target_service")
    def serialize_target_service(self, v: str) -> str:
        return v.replace("_", "-")


class AdviseResponse(BaseModel):
    # metric: TelemetryMetrics | None = Field(
    #     default=None,
    #     description="Structured telemetry metrics snapshot gathered from Prometheus",
    # )

    metric: dict[str, Any] | None = Field(
        default=None,
        description="Key-value dictionary of telemetry metrics gathered from Prometheus",
    )
    prediction: dict[str, Any] | None = Field(
        default=None,
        description="Key-value dictionary of predicted result return from Brain",
    )
    event: AdvisoryEvent | None = Field(
        ..., description="Advisory Action to be taken based on the response"
    )
