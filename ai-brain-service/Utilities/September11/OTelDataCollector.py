from datetime import datetime

import requests
import pandas as pd
import time

# 1. Setup
PROMETHEUS_URL = "http://localhost:9090/api/v1/query"
# How many rows of data to collect (e.g., collect every 1 seconds for 1 hour)
INTERVAL_SEC = 1
TOTAL_POINTS = 200

def get_metric(query):
    try:
        response = requests.get(PROMETHEUS_URL, params={ 'query': query})
        results = response.json()['data']['result']
        #print("PARAM", query)
        #print("RESULTS", results)
        return float(results[0]['value'][1]) if results else 0.0
    except Exception as e:
        print("Error fetching metric: ", e)
        return 0.0

print("Starting Data Collection... Go run JMeter tests now!")

data_rows = []

for i in range(TOTAL_POINTS):
    # Fetch all features
    row = {
        "timestampe": time.time(),
        "cpu_usage": get_metric("otel_system_cpu_usage"),
        "memeory_usage": get_metric("otel_jvm_memory_used_bytes"),
        "request_rate": get_metric("rate(otel_http_server_requests_milliseconds_count[1m])"),
        "latency": get_metric("otel_http_server_requests_milliseconds_sum/otel_http_server_requests_milliseconds_count"),
        "throughput": get_metric("rate(otel_http_server_requests_milliseconds_count[1m])"),
        "error_rate": get_metric("rate(otel_http_server_requests_milliseconds_count{status=~'5..'}[1m])"),
        "thread_count": get_metric("otel_jvm_threads_live"),
        "cb_state": get_metric("otel_resilience4j_circuitbreaker_state{state='open'}") # 1 if Open, 0 if Closed
    }

    # Simple Auto-Labeling logic ( refine this later )
    if row['cb_state'] == 1.0 or row['error_rate'] > 5:
        row['status'] = 'Failed'
    elif row['latency'] > 500 or row['cpu_usage'] > 0.8: # Adjust 500 based on your 'ms' observations
        row['status'] = 'Degraded'
    else:
        row['status'] = 'Healthy'

    data_rows.append(row)
    print(f"Collected {i} rows...")
    #if i%10 == 0:
        #print(f"Collected {i} rows...")

    time.sleep(INTERVAL_SEC)

# Save to CSV
df = pd.DataFrame(data_rows)
now = datetime.now()
timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
filename = f"otem_data_{timestamp}.csv"
df.to_csv(filename, index=False)
print(f"Done! File saved as {filename}")