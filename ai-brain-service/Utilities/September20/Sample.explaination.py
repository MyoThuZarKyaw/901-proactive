def run_monitoring_cycle(target_service):
    # 'global' tells Python to use the 'history_buffer' variable defined outside this function,
    # rather than creating a new local variable. This list persists across loop iterations.
    global history_buffer

    # 1. Fetch raw metrics from Prometheus right now.
    # Returns a dictionary representing one moment in time, e.g.:
    # {"timestamp": 1695200000, "target_latency": 150.2, "target_cpu": 45.0, ...}
    raw_data = fetch_raw_metrics(target_service)

    # 2. Append to history buffer
    # Add the newest dictionary to the end of our Python list.
    history_buffer.append(raw_data)

    # Sliding window maintenance:
    # If our list exceeds the allowed maximum size (WINDOW_SIZE), discard the oldest item at index 0.
    # This prevents the program from consuming unlimited RAM over time.
    if len(history_buffer) > WINDOW_SIZE:
        history_buffer.pop(0)  # Remove oldest element

    # 3. Need at least 30 points (60s) to calculate rolling averages and deltas
    # Since step = 2 seconds: 30 data points * 2 seconds = 60 seconds of history.
    # Rolling 1-minute statistics cannot be accurately computed without at least 60s of data.
    if len(history_buffer) < 30:
        print(f"[{target_service}] Buffering history... ({len(history_buffer)}/30)")
        return  # Exit early and wait for the next iteration

    # 4. Convert history to DataFrame to compute features
    # --- PANDAS STEP: List of Dicts to DataFrame ---
    # Pandas interprets a list of dictionaries where:
    # - Each dictionary becomes a row.
    # - The dictionary keys become the column headers.
    df = pd.DataFrame(history_buffer)

    # Define steps in terms of index rows:
    # Because each row is sampled every 2 seconds:
    # 15 rows = 15 * 2s = 30 seconds ago
    # 30 rows = 30 * 2s = 60 seconds ago
    STEP_30S = 15
    STEP_60S = 30

    # =========================================================================
    # FEATURE ENGINEERING WITH PANDAS
    # =========================================================================

    # --- PANDAS STEP: .shift(n) ---
    # .shift(n) moves the column down by 'n' rows.
    # df["target_latency"].shift(15) gets the latency from 15 rows (30 seconds) in the past!
    # By subtracting the shifted column from the current column, we get the change (delta) over time:
    # delta = current_value - past_value
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

    # --- PANDAS STEP: .rolling(window=n) ---
    # .rolling(window=30) looks at a moving window of the last 30 rows (the last 60 seconds).
    # .mean() calculates the average across that 60-second window.
    df["latency_rolling_mean_1m"] = df["target_latency"].rolling(window=STEP_60S).mean()

    # .std() calculates the standard deviation (volatility/spread) over the last 60 seconds.
    # .fillna(0) ensures that if std cannot be calculated (e.g., constant numbers), it defaults to 0 instead of NaN.
    df["latency_std_1m"] = df["target_latency"].rolling(window=STEP_60S).std().fillna(0)

    # Rolling 1-minute average throughput and active requests
    df["throughput_rolling_mean_1m"] = (
        df["target_throughput"].rolling(window=STEP_60S).mean()
    )
    df["active_req_rolling_mean_1m"] = (
        df["target_active_requests"].rolling(window=STEP_60S).mean()
    )

    # Acceleration: The rate of change of the rate of change (2nd derivative).
    # Subtracting the 30s delta of 30 seconds ago from the current 30s delta.
    df["latency_accel_30s"] = df["latency_delta_30s"] - df["latency_delta_30s"].shift(
        STEP_30S
    )

    # --- RATIO & INTERACTION FEATURES ---
    # Note: '+ 1e-5' (0.00001) is added to denominators to prevent 'Division by Zero' crashes.

    # Measures how much current latency deviates from the recent 1-minute average.
    # (A value of 2.0 means current latency is 2x the normal average).
    df["latency_surge_ratio"] = df["target_latency"] / (
        df["latency_rolling_mean_1m"] + 1e-5
    )

    # Measures workload density per available thread.
    # Higher values mean threads are overwhelmed by active requests.
    df["thread_pressure_ratio"] = df["target_active_requests"] / (
        df["target_live_threads"] + 1e-5
    )

    # Z-Score formula: (Current Value - Mean) / Standard Deviation
    # Measures how many standard deviations current latency is away from the mean.
    # A z-score > 3.0 indicates a statistically significant, extreme anomaly.
    df["latency_zscore"] = (df["target_latency"] - df["latency_rolling_mean_1m"]) / (
        df["latency_std_1m"] + 1e-5
    )

    # 5. Extract the absolute latest row as a dictionary
    # --- PANDAS STEP: .iloc[-1] ---
    # .iloc stands for 'Integer Location'. Index [-1] grabs the very last (most recent) row.
    # .fillna(0.0) replaces any NaN values (e.g. from the earliest shifts) with 0.0.
    # .to_dict() turns the Pandas Series representing that row back into a Python dictionary:
    # {"target_latency": 120.0, "latency_surge_ratio": 1.15, ...}
    latest_row_dict = df.iloc[-1].fillna(0.0).to_dict()

    # Clean up non-feature keys from the dictionary
    # The Machine Learning model only expects numerical mathematical features.
    # We remove metadata or labels (like timestamps and status text) so the model doesn't reject the input.
    for k in [
        "timestamp",
        "Local Datetime",
        "status",
        "experiment_id",
        "service_name",
        "source_file",
    ]:
        # .pop(k, None) removes key 'k'. If 'k' does not exist, it quietly returns None without raising a KeyError.
        latest_row_dict.pop(k, None)

    # 6. Construct the payload requested by the Brain Service
    # Packages the current state into the JSON structure expected by the ML service API.
    payload = {
        "service_name": target_service,
        "timestamp": int(time.time()),
        "features": latest_row_dict,
    }

    # 7. Call the Brain Service via POST
    try:
        # Send an HTTP POST request carrying our features JSON payload.
        response = requests.post(BRAIN_SERVICE_URL, json=payload, timeout=3)
        # Check for HTTP errors (4xx / 5xx)
        response.raise_for_status()
        # Parse the JSON response returned by the ML brain
        result = response.json()

        # Display the ML model's inference (e.g., "Healthy", "Degraded") and confidence score
        print(
            f"[{target_service}] Prediction: {result['state']} (Conf: {result['confidence'] * 100:.1f}%)"
        )

        # Here is where the Monitoring Service acts on prediction != "Healthy"
        # 0 = Healthy, 1 = Degraded, 2 = Failing / Dead
        if result["prediction"] > 0:
            handle_actuation(target_service, result["prediction"])

    except Exception as e:
        print(f"[{target_service}] Error communicating with Brain Service: {e}")


def handle_actuation(service_name, state_code):
    """
    Executes automated mitigation actions based on the ML diagnosis.
    """
    if state_code == 1:
        # State 1 (Degraded): Slow down incoming traffic before the system crashes
        print(f"  [~] ADVISORY: {service_name} is DEGRADED. Triggering rate-limiter...")
    elif state_code == 2:
        # State 2 (Failing): Stop routing traffic entirely to prevent cascade failures
        print(
            f"  [!] CRITICAL: {service_name} is FAILING! Forcing Circuit Breaker OPEN..."
        )
        # Code here to notify gateway or caller service


# Loop continuously every 2 seconds
if __name__ == "__main__":
    print("[*] Monitoring Service started...")
    while True:
        # Run one check cycle against the inventory microservice
        run_monitoring_cycle("inventory_service")
        # Pause execution for 2 seconds before running the next cycle
        time.sleep(2)
