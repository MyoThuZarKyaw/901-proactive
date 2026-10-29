from contextlib import asynccontextmanager
import time
from typing import Dict, List, Optional
from fastapi import FastAPI, HTTPException
import joblib
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

# ==============================================================================
# 1. PYDANTIC SCHEMA: EXACT 20 TELEMETRY FEATURES
# ==============================================================================
class TelemetryPayload(BaseModel):
    service_name: Optional[str] = Field(
        default="inventory_service",
        description="For logging / routing only, not passed to RF",
    )
    # Raw Metrics
    target_cpu: float
    target_mem: float
    target_throughput: float
    target_latency: float
    target_error_rate: float
    target_live_threads: float
    target_active_requests: float

    # Velocity & Deltas
    latency_delta_30s: float
    latency_delta_60s: float
    mem_delta_60s: float
    cpu_delta_30s: float
    throughput_delta_30s: float
    latency_accel_30s: float

    # Rolling Statistics
    latency_rolling_mean_1m: float
    latency_std_1m: float
    throughput_rolling_mean_1m: float
    active_req_rolling_mean_1m: float

    # Relative Ratios
    latency_surge_ratio: float
    thread_pressure_ratio: float
    latency_zscore: float


class PredictionResponse(BaseModel):
    service_name: str
    predicted_state: int
    predicted_label: str
    confidence: float
    probabilities: Dict[str, float]
    inference_time_ms: float


# ==============================================================================
# 2. LIFESPAN: LOAD MODEL ON STARTUP
# ==============================================================================
ml_artifacts = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    model_path = "models/gateway_ai_model_x002.joblib"
    print(f"[*] Loading model from '{model_path}'...")
    try:
        artifact = joblib.load(model_path)
        ml_artifacts["model"] = artifact["model"]
        ml_artifacts["features"] = artifact["features"]
        ml_artifacts["target_mapping"] = artifact["target_mapping"]
        print(f"[✓] Model successfully loaded into memory!")
        print(f"[✓] Expected {len(ml_artifacts['features'])} features.")
    except Exception as e:
        print(f"[!] Error loading model: {e}")
        raise e
    yield
    ml_artifacts.clear()


app = FastAPI(
    title="ML Proactive Circuit Breaker Brain",
    version="1.0.0",
    lifespan=lifespan,
)

# ==============================================================================
# 3. ENDPOINTS
# ==============================================================================
@app.get("/health")
def health_check():
    return {
        "status": "UP",
        "model_loaded": "model" in ml_artifacts,
        "feature_count": (
            len(ml_artifacts["features"]) if "features" in ml_artifacts else 0
        ),
    }


@app.post("/predict", response_model=PredictionResponse)
def predict_service_health(payload: TelemetryPayload):
    if "model" not in ml_artifacts:
        raise HTTPException(status_code=500, detail="ML Model not initialized.")

    start_time = time.perf_counter()

    # Extract dictionary and build single-row DataFrame aligned to training feature order
    payload_dict = payload.model_dump()
    expected_features = ml_artifacts["features"]

    try:
        # Create input array in the exact feature column order
        input_data = pd.DataFrame(
            [[payload_dict[feat] for feat in expected_features]],
            columns=expected_features,
        )
    except KeyError as e:
        raise HTTPException(
            status_code=400, detail=f"Missing required feature: {e}"
        )

    # Inference
    model = ml_artifacts["model"]
    probs = model.predict_proba(input_data)[0]

    # Advisory Decision Thresholds (p_failed >= 0.50, p_degraded >= 0.40)
    # Class 0: Healthy, Class 1: Degraded, Class 2: Failed
    p_healthy = float(probs[0])
    p_degraded = float(probs[1]) if len(probs) > 1 else 0.0
    p_failed = float(probs[2]) if len(probs) > 2 else 0.0

    if p_failed >= 0.50:
        state = 2
    elif p_degraded >= 0.40:
        state = 1
    else:
        state = 0

    label_map = ml_artifacts["target_mapping"]
    predicted_label = label_map.get(state, "Unknown")
    confidence = max(probs)

    inference_ms = (time.perf_counter() - start_time) * 1000.0

    return PredictionResponse(
        service_name=payload.service_name,
        predicted_state=state,
        predicted_label=predicted_label,
        confidence=round(confidence, 4),
        probabilities={
            "Healthy": round(p_healthy, 4),
            "Degraded": round(p_degraded, 4),
            "Failed": round(p_failed, 4),
        },
        inference_time_ms=round(inference_ms, 2),
    )