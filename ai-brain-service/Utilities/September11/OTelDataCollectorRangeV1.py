import requests
import pandas as pd
import time
from datetime import datetime, timezone

# 1. Define your local date and time string
start_time_str = "2026-09-07 15:38:17"
end_time_str = "2026-09-07 15:43:30"
FEAT_THRESHOLD = 1500

# 2. Convert the string into a datetime object
# (This assumes the time matches your local computer's timezone)
start_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M:%S")
end_dt = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S")

# 3. Convert the local datetime object directly to a Unix timestamp integer
start_unix_timestamp = int(start_dt.timestamp())
end_unix_timestamp = int(end_dt.timestamp())

print(f"Unix Timestamp: {start_unix_timestamp}")

# --- CONFIGURATION ---
PROMETHEUS_URL = "http://localhost:9090/api/v1/query_range"
START_TS = start_unix_timestamp#1787098200  # <--- UPDATE THIS
END_TS = end_unix_timestamp#1787109200    # <--- UPDATE THIS
STEP = "1s"

queries = {
    "throughput": "sum(rate(otel_http_server_requests_milliseconds_count[1m]))",
    "latency": "sum(rate(otel_http_server_requests_milliseconds_sum[1m])) / sum(rate(otel_http_server_requests_milliseconds_count[1m]))",
    "process_cpu": "avg(otel_process_cpu_usage) * 100",
    "system_cpu": "avg(otel_system_cpu_usage) * 100",
    "mem_utilization": "sum(otel_jvm_memory_used_bytes) / sum(otel_jvm_memory_committed_bytes)",
    "error_rate": "sum(increase(otel_http_server_requests_milliseconds_count{status=~'5..'}[1m])) / sum(increase(otel_http_server_requests_milliseconds_count[1m]))",
    "cb_open": "sum(otel_resilience4j_circuitbreaker_state{state='open'})",
    "cb_half_open": "sum(otel_resilience4j_circuitbreaker_state{state='half_open'})",
    "cb_closed": "sum(otel_resilience4j_circuitbreaker_state{state='closed'})"
}

def fetch_data(query):
    params = {'query': query, 'start': START_TS, 'end': END_TS, 'step': STEP}
    response = requests.get(PROMETHEUS_URL, params=params)

    results = response.json()['data']['result']
    if not results: return pd.Series(dtype=float)
    values = results[0]['values']
    df_t = pd.DataFrame(values, columns=['timestamp', 'value'])
    df_t['value'] = df_t['value'].astype(float)
    df_t['timestamp'] = df_t['timestamp'].astype(int)
    return df_t.set_index('timestamp')['value']

# --- EXECUTION ---
print("Downloading metrics...")
df = pd.DataFrame({name: fetch_data(q) for name, q in queries.items()}).fillna(0)

# Instead of .fillna(0), we fill gaps with the PREVIOUS valid value (ffill)
# Then we fill any remaining zeros at the very start with 0 (bfill)
df = df.ffill().fillna(0)

# Move timestamp from Index to a Column
df.reset_index(inplace=True)
df.rename(columns={'index': 'timestamp'}, inplace=True)

# --- ADD HUMAN READABLE DATETIMES  ---
# UTC Time
df['UTC Datetime'] = df['timestamp'].apply(
    lambda x: datetime.fromtimestamp(x, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
)

# Local Time (Mac's time)
df['Local Datetime'] = df['timestamp'].apply(
    lambda x: datetime.fromtimestamp(x).strftime('%Y-%m-%d %H:%M:%S')
)

#adding threshold
df['feat_threshold'] = FEAT_THRESHOLD
df['latency_ratio'] = df['latency'] / df['feat_threshold']

# --- LABELING LOGIC FOR RANDOM FOREST ---
def assign_label(row):
    if row['cb_open'] > 0 or row['error_rate'] > 0.5:
        return 'Failed'
    #elif row['cb_half_open'] > 0 or row['error_rate'] > 0.1 or row['latency'] > row['feat_threshold']:
        #return 'Degraded'
        # DEGRADED (The 60% Warning)
        # DEGRADED (The 60% Warning)
    elif (row['cb_half_open'] > 0 or
        row['error_rate'] > 0.1 or
        row['latency'] > (row['feat_threshold'] * 0.6)):
        return 'Degraded'

    else:
        return 'Healthy'

df['status'] = df.apply(assign_label, axis=1)

# Save
exp_name = "validation_test"
version = "01"

filename = f"{exp_name}_{start_dt.strftime("%Y_%m_%d_%I_%M_%S_%p")}_{version}.csv"
df.to_csv(filename)
print(f"Saved {len(df)} rows to {filename}")