from fastapi import FastAPI
import joblib
import pandas as pd
from pydantic import BaseModel
import sklearn  # Add this just to check if scikit-learn is found

# 1. Initialize FastAPI
app = FastAPI(title="Gateway AI Brain Service")

# 2. Load the trained Random Forest model
# Ensure 'gateway_ai_model.joblib' is in the same folder
model = joblib.load('gateway_ai_model_v2.joblib')

# 3. Define the data structure the Gateway must send
class SystemMetrics(BaseModel):
    throughput: float
    latency: float
    process_cpu: float
    system_cpu: float
    mem_utilization: float
    error_rate: float
    feat_threshold: float

@app.post("/predict")
async def predict_status(metrics: SystemMetrics, service_name: str):
    # Convert incoming JSON to a DataFrame (the format the model expects)
    input_data = pd.DataFrame([metrics.dict()])

    # Calculate the latency_ratio (the AI needs this to be context-aware!)
    input_data['latency_ratio'] = input_data['latency'] / input_data['feat_threshold']

    # Ensure columns are in the exact same order as training
    feature_order = [
        'throughput', 'process_cpu', 'system_cpu',
        'mem_utilization', 'error_rate', 'feat_threshold', 'latency_ratio'
    ]
    input_data = input_data[feature_order]


    # Perform the prediction
    prediction = model.predict(input_data)[0]

    # Optional: Get probability (How sure is the AI)
    probabilities = model.predict_proba(input_data)[0]
    confidence = max(probabilities)

    return {
        "service": service_name,
        "status": prediction,
        "confidence": round(confidence, 4)
    }

@app.get("/health")
async def health_check():
    return {"status": "Brain is online"}