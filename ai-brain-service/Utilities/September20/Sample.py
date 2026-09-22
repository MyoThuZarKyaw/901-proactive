import time

import pandas as pd
import requests
from Utilities.September20.PrometheusQuery import fetch_raw_metrics

BRAIN_SERVICE_URL = "http://localhost:8000/predict"

# Keep a rolling history buffer for the target service in memory
history_buffer = []
WINDOW_SIZE = 40  # Keep last 40 samples (80 seconds at 2s interval)


def run_monitoring_cycle(target_service):
    global history_buffer

    # 1. Fetch raw metrics from Prometheus right now
    raw_data = fetch_raw_metrics(target_service)

    # 2. Append to history buffer
    history_buffer.append(raw_data)
    if len(history_buffer) > WINDOW_SIZE:
        history_buffer.pop(0)  # Remove oldest element

    # 3. Need at least 30 points (60s) to calculate rolling averages and deltas
    if len(history_buffer) < 30:
        print(f"[{target_service}] Buffering history... ({len(history_buffer)}/30)")
        return

    # 4. Convert history to DataFrame to compute features
    df = pd.DataFrame(history_buffer)

    STEP_30S = 15
    STEP_60S = 30

    # Replicate feature engineering
    df["latency_delta_30s"] = df["target_latency"] - df["target_latency"].shift(
        STEP_30S
    )
    df["latency_delta_60s"] = df["target_latency"] - df["target_latency"].shift(
        STEP_60S
    )
    df["mem_delta_60s"] = df["target_mem"] - df["target_mem"].shift(STEP_60S)
    df["cpu_delta_30s"] = df["target_cpu"] - df["target_cpu"].shift(STEP_30S)
    df["throughput_delta_30s"] = df["target_throughput"] - df[
        "target_throughput"
    ].shift(STEP_30S)

    df["latency_rolling_mean_1m"] = df["target_latency"].rolling(window=STEP_60S).mean()
    df["latency_std_1m"] = df["target_latency"].rolling(window=STEP_60S).std().fillna(0)
    df["throughput_rolling_mean_1m"] = (
        df["target_throughput"].rolling(window=STEP_60S).mean()
    )
    df["active_req_rolling_mean_1m"] = (
        df["target_active_requests"].rolling(window=STEP_60S).mean()
    )
    df["latency_accel_30s"] = df["latency_delta_30s"] - df["latency_delta_30s"].shift(
        STEP_30S
    )

    df["latency_surge_ratio"] = df["target_latency"] / (
        df["latency_rolling_mean_1m"] + 1e-5
    )
    df["thread_pressure_ratio"] = df["target_active_requests"] / (
        df["target_live_threads"] + 1e-5
    )
    df["latency_zscore"] = (df["target_latency"] - df["latency_rolling_mean_1m"]) / (
        df["latency_std_1m"] + 1e-5
    )

    # 5. Extract the absolute latest row as a dictionary
    latest_row_dict = df.iloc[-1].fillna(0.0).to_dict()

    # Clean up non-feature keys from the dictionary
    for k in [
        "timestamp",
        "Local Datetime",
        "status",
        "experiment_id",
        "service_name",
        "source_file",
    ]:
        latest_row_dict.pop(k, None)

    # 6. Construct the payload requested by the Brain Service
    payload = {
        "service_name": target_service,
        "timestamp": int(time.time()),
        "features": latest_row_dict,
    }

    # 7. Call the Brain Service via POST
    try:
        response = requests.post(BRAIN_SERVICE_URL, json=payload, timeout=3)
        response.raise_for_status()
        result = response.json()

        print(
            f"[{target_service}] Prediction: {result['state']} (Conf: {result['confidence'] * 100:.1f}%)"
        )

        # Here is where the Monitoring Service acts on prediction != "Healthy"
        if result["prediction"] > 0:
            handle_actuation(target_service, result["prediction"])

    except Exception as e:
        print(f"[{target_service}] Error communicating with Brain Service: {e}")


def handle_actuation(service_name, state_code):
    if state_code == 1:
        print(f"  [~] ADVISORY: {service_name} is DEGRADED. Triggering rate-limiter...")
    elif state_code == 2:
        print(
            f"  [!] CRITICAL: {service_name} is FAILING! Forcing Circuit Breaker OPEN..."
        )
        # Code here to notify gateway or caller service


# Loop continuously every 2 seconds
if __name__ == "__main__":
    print("[*] Monitoring Service started...")
    while True:
        run_monitoring_cycle("inventory_service")
        time.sleep(2)
