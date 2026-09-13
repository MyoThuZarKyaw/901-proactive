from contextlib import asynccontextmanager
from datetime import datetime
import os
from typing import Dict, Optional
from fastapi import FastAPI, HTTPException
import joblib
import pandas as pd
from pydantic import BaseModel, Field

# Expected feature column order
FEATURE_COLUMNS = [
    "cluster_cpu",
    "cluster_mem",
    "cluster_throughput",
    "cluster_error_rate",
    "caller_cpu",
    "caller_mem",
    "target_cpu",
    "target_mem",
    "target_error_rate",
    "latency_ratio",
    "cb_failure_rate",
    "cb_slow_call_rate",
]

MODEL_PATH = "cb_controller_model.joblib"
model_pipeline = None


# Load model at startup
@asynccontextmanager
async def lifespan(app: FastAPI):
    global model_pipeline
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(
            f"Model file '{MODEL_PATH}' not found! Place it in the project root."
        )
    print(f"Loading model pipeline from {MODEL_PATH}...")
    model_pipeline = joblib.load(MODEL_PATH)
    print("Model loaded successfully!")
    yield


app = FastAPI(
    title="Reactive Circuit Breaker AI Controller",
    description="Autonomous AI Agent evaluating microservice telemetry and recommending CB actuation.",
    version="1.0.0",
    lifespan=lifespan,
)


# --- 1. Define Request Body Schema ---
class TelemetryRequest(BaseModel):
    # Optional metadata for tracking/logging in responses
    cb_name: Optional[str] = Field(
        default="paymentService", description="Name of the Circuit Breaker"
    )

    # 1. Global Context
    cluster_cpu: float = Field(..., ge=0.0, le=100.0, example=1.2)
    cluster_mem: float = Field(..., ge=0.0, le=1.0, example=0.88)
    cluster_throughput: float = Field(..., ge=0.0, example=85.0)
    cluster_error_rate: float = Field(..., ge=0.0, le=1.0, example=0.0)

    # 2. Caller Context (order_service)
    caller_cpu: float = Field(..., ge=0.0, le=100.0, example=1.8)
    caller_mem: float = Field(..., ge=0.0, le=1.0, example=0.86)

    # 3. Local Target Context (inventory or payment)
    target_cpu: float = Field(..., ge=0.0, le=100.0, example=1.5)
    target_mem: float = Field(..., ge=0.0, le=1.0, example=0.95)
    target_error_rate: float = Field(..., ge=0.0, le=1.0, example=0.0)
    latency_ratio: float = Field(
        ..., ge=0.0, description="target_latency / threshold", example=0.75
    )

    # 4. Resilience4j Internal State
    cb_failure_rate: float = Field(..., ge=0.0, le=100.0, example=0.0)
    cb_slow_call_rate: float = Field(..., ge=0.0, le=100.0, example=35.0)


# --- 2. Define Response Schema ---
class PredictionResponse(BaseModel):
    cb_name: str
    decision: str  # HEALTHY, DEGRADED, or FAILED
    action: str  # Recommended operational action
    anomaly_score: float  # P(Degraded) + P(Failed)
    probabilities: Dict[str, float]
    evaluated_at: str


# --- 3. Prediction Endpoint ---
@app.post("/predict", response_model=PredictionResponse)
def predict_circuit_breaker(payload: TelemetryRequest):
    if model_pipeline is None:
        raise HTTPException(status_code=503, detail="Model is not loaded.")

    # 1. Convert payload to DataFrame with strict column order
    input_data = {col: [getattr(payload, col)] for col in FEATURE_COLUMNS}
    input_df = pd.DataFrame(input_data)

    # 2. Get class probabilities
    probs_array = model_pipeline.predict_proba(input_df)[0]
    classes = model_pipeline.classes_
    probs = {
        cls: round(float(prob), 4) for cls, prob in zip(classes, probs_array)
    }

    prob_healthy = probs.get("Healthy", 0.0)
    prob_degraded = probs.get("Degraded", 0.0)
    prob_failed = probs.get("Failed", 0.0)

    # Combined anomaly probability (solves the 3-way vote-splitting issue)
    total_anomaly = round(prob_degraded + prob_failed, 4)

    # 3. Hierarchical Gating Decision Logic
    # --- Updated Hierarchical Decision Policy ---
    # 1. Healthy Zone: Normal operation
    if prob_healthy >= 0.50:
        decision = "HEALTHY"
        action = "NO_ACTION"

    # 2. Catastrophic Failure Zone: Requires HIGH confidence (>= 50%) to trip breaker
    elif prob_failed >= 0.50:
        decision = "FAILED"
        action = "TRIP_CIRCUIT_BREAKER"

    # 3. Degraded / Warning Zone:
    # System is abnormal (Healthy < 50%), but failure confidence has not reached 50% yet
    else:
        decision = "DEGRADED"
        action = "ADAPT_THRESHOLD"

    return PredictionResponse(
        cb_name=payload.cb_name,
        decision=decision,
        action=action,
        anomaly_score=total_anomaly,
        probabilities=probs,
        evaluated_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


# --- 4. Health Check Endpoint ---
@app.get("/health")
def health_check():
    return {"status": "UP", "model_loaded": model_pipeline is not None}