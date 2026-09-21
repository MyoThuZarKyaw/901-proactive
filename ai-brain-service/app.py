from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import joblib
import pandas as pd
import sklearn  # Add this just to check if scikit-learn is found

app = FastAPI(
    title="Proactive Gateway Brain Service",
    description="Microservice providing ML-driven health state predictions for microservices.",
    version="1.0.0"
)

# ==============================================================================
# 1. LOAD MODEL GLOBALLY (Outside of any Pydantic schema)
# ==============================================================================
MODEL_BUNDLE_FILE = "models/proactive_gateway_mdv3_v1.joblib"
print(f"[*] Loading model bundle: {MODEL_BUNDLE_FILE} ...")

try:
    bundle = joblib.load(MODEL_BUNDLE_FILE)
    model = bundle["model"]
    feature_cols = bundle["features"]
    print(f"[✓] Model loaded successfully! Features count: {len(feature_cols)}")
except Exception as e:
    print(f"[X] Failed to load model bundle: {e}")
    model = None
    feature_cols = []


# ==============================================================================
# 2. PYDANTIC REQUEST SCHEMA (Only validates the incoming JSON body)
# ==============================================================================
class PredictionRequest(BaseModel):
    service_name: str = Field(..., example="inventory_service")
    timestamp: int = Field(..., example=1789701157)
    features: dict


# ==============================================================================
# 3. API ENDPOINTS
# ==============================================================================
@app.post("/predict", summary="Predict Service Health State")
def predict_health(payload: PredictionRequest):
    if model is None:
        raise HTTPException(status_code=500, detail="Model is not loaded on the server.")

    try:
        # Convert incoming dictionary to a DataFrame
        df_input = pd.DataFrame([payload.features])

        # Ensure all required model features are present; default missing ones to 0.0
        for col in feature_cols:
            if col not in df_input.columns:
                df_input[col] = 0.0

        # Align column order strictly to what the model was trained on
        X = df_input[feature_cols]

        # Run inference
        pred_class = int(model.predict(X)[0])
        probabilities = model.predict_proba(X)[0]
        confidence = float(max(probabilities))

        state_map = {0: "Healthy", 1: "Degraded", 2: "Failed"}

        return {
            "service_name": payload.service_name,
            "prediction": pred_class,
            "state": state_map.get(pred_class, "Unknown"),
            "confidence": round(confidence, 3),
            "probabilities": {
                "healthy": round(float(probabilities[0]), 3),
                "degraded": round(float(probabilities[1]), 3),
                "failed": round(float(probabilities[2]), 3)
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


@app.get("/health", summary="Health Check")
def health_check():
    return {
        "status": "online",
        "model_loaded": model is not None,
        "features_count": len(feature_cols)
    }