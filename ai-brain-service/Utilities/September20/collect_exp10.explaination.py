# 'os' allows interacting with the operating system (e.g., file paths, directories).
import os

# 'datetime' allows us to parse, format, and manipulate dates and times.
from datetime import datetime

# 'pandas' is the core data analysis library for Python.
# 'as pd' is the universal standard abbreviation for Pandas.
import pandas as pd

# 'requests' is a library used to send HTTP requests to servers (like calling an API).
import requests

# ==============================================================================
# 1. CONFIGURATION FOR EXPERIMENT 6
# ==============================================================================
# The Prometheus HTTP endpoint used to query time-series data over a time range.
PROMETHEUS_URL = "http://localhost:9090/api/v1/query_range"

# The name of the microservice we want to collect metrics from.
TARGET_SERVICE = "payment_service"

# 'STEP' defines the query resolution for Prometheus (one data point every 2 seconds).
STEP = "2s"
STEP_SECONDS = 2  # Same step interval represented as an integer (in seconds).

# Human-readable start and end date/time strings for the experiment window.
START_TIME_STR = "2026-09-20 12:22:15"
END_TIME_STR = "2026-09-20 12:32:15"

# The destination path where our resulting CSV file will be written.
OUTPUT_FILE = "raw_data/exp10_container_kill_payment.csv"


# ==============================================================================
# 2. TIMESTAMP CONVERSION
# ==============================================================================
# 'strptime' parses the date strings above into Python 'datetime' objects.
# %Y = 4-digit year, %m = 2-digit month, %d = day, %H = hour (24-hr), %M = minute, %S = second.
start_dt = datetime.strptime(START_TIME_STR, "%Y-%m-%d %H:%M:%S")
end_dt = datetime.strptime(END_TIME_STR, "%Y-%m-%d %H:%M:%S")

# Prometheus requires UNIX timestamps (the number of seconds since Jan 1, 1970).
# .timestamp() gets this value as a float, and int() converts it to a whole number.
START_TS = int(start_dt.timestamp())
END_TS = int(end_dt.timestamp())


# ==============================================================================
# 3. QUERIES
# ==============================================================================
# A dictionary mapping friendly column names to their respective PromQL queries.
# Notice the double curly braces '{{' and '}}' — in Python f-strings, '{{' outputs a literal '{'.
QUERIES = {
    # Average CPU usage percentage for the service
    "target_cpu": f'avg(otel_process_cpu_usage{{application="{TARGET_SERVICE}"}}) * 100',
    # JVM memory used divided by committed (giving a ratio/percentage between 0.0 and 1.0)
    "target_mem": f'sum(otel_jvm_memory_used_bytes{{application="{TARGET_SERVICE}"}}) / sum(otel_jvm_memory_committed_bytes{{application="{TARGET_SERVICE}"}})',
    # Request throughput per second over a 1-minute sliding window
    "target_throughput": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    # Average latency (response time) per request in milliseconds
    "target_latency": f'sum(rate(otel_http_server_requests_milliseconds_sum{{application="{TARGET_SERVICE}"}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    # Ratio of HTTP 5xx errors to total requests (error rate)
    "target_error_rate": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}", status=~"5.."}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{TARGET_SERVICE}"}}[1m]))',
    # Number of live Java threads running
    "target_live_threads": f'max(otel_jvm_threads_live{{application="{TARGET_SERVICE}"}})',
    # Number of active in-flight HTTP requests currently being handled
    "target_active_requests": f'sum(otel_http_server_requests_active_milliseconds_count{{application="{TARGET_SERVICE}"}})',
}


# ==============================================================================
# 4. EXTRACTION ENGINE
# ==============================================================================
def fetch_series(query_name, query_str):
    """
    Executes a single Prometheus query and converts the response into a Pandas Series.
    """
    # The URL parameters sent with our GET request to Prometheus
    params = {"query": query_str, "start": START_TS, "end": END_TS, "step": STEP}
    try:
        # Send HTTP GET request with a 15-second timeout
        res = requests.get(PROMETHEUS_URL, params=params, timeout=15)
        # Raises an HTTPError if Prometheus returned an error status code (e.g., 400, 500)
        res.raise_for_status()

        # Parse JSON and drill down: response -> 'data' -> 'result'
        # If any key is missing, fallback safely using default values {} or []
        data = res.json().get("data", {}).get("result", [])

        # If the result list is empty (no data found for this query),
        # return an empty Pandas Series (a single empty column)
        if not data:
            return pd.Series(dtype=float)

        # Prometheus returns time series in data[0]["values"] as a list of:
        # [[1695200000, "12.34"], [1695200002, "12.80"], ...]
        values = data[0]["values"]

        # --- PANDAS STEP: Create a 2-column DataFrame ---
        # Column 1 = 'timestamp', Column 2 = the metric name (e.g. 'target_cpu')
        df_temp = pd.DataFrame(values, columns=["timestamp", query_name])

        # Prometheus timestamps can be floats; convert them to pure integers
        df_temp["timestamp"] = df_temp["timestamp"].astype(int)

        # Prometheus returns metric values as strings (e.g. "12.34").
        # 'pd.to_numeric' converts them to numbers.
        # 'errors="coerce"' turns any invalid or corrupted string into NaN (Not a Number / null).
        df_temp[query_name] = pd.to_numeric(df_temp[query_name], errors="coerce")

        # --- PANDAS STEP: Indexing ---
        # .set_index("timestamp") tells Pandas to make 'timestamp' the row labels instead of 0, 1, 2...
        # [query_name] extracts just that one column.
        # Returning this yields a Pandas Series indexed by the UNIX timestamp.
        return df_temp.set_index("timestamp")[query_name]

    except Exception as e:
        print(f"  [ERROR] {query_name}: {e}")
        # Return an empty series so a single failure doesn't crash the entire script
        return pd.Series(dtype=float)


def assign_status(row):
    """
    Classifies system state based on the thresholds of a single row.
    'row' is a Pandas Series representing one horizontal row in the DataFrame.
    """
    # Failed: Container crashed (0 threads) OR Latency > 1000ms OR Error rate > 15%
    if (
        row["target_live_threads"] == 0
        or row["target_error_rate"] > 0.15
        or row["target_latency"] > 1000.0
    ):
        return "Failed"
    # Degraded: Early warning (Errors > 3%, Latency > 300ms, Memory > 80%, CPU > 70%)
    elif (
        row["target_error_rate"] > 0.03
        or row["target_latency"] > 300.0
        or row["target_mem"] > 0.80
        or row["target_cpu"] > 70.0
    ):
        return "Degraded"
    # Healthy: Normal operating range
    else:
        return "Healthy"


def main():
    print(f"[*] Extracting Experiment 10: {START_TIME_STR} -> {END_TIME_STR}")

    # --- PANDAS STEP: Combining Series into a DataFrame ---
    # A dictionary comprehension {name: fetch_series(...) for ...} runs all queries.
    # When passed to pd.DataFrame({...}), Pandas automatically aligns all columns
    # by their shared index (the timestamps)! If one metric is missing a timestamp,
    # Pandas will neatly align it and insert NaN (empty).
    df = pd.DataFrame({name: fetch_series(name, q) for name, q in QUERIES.items()})

    # --- PANDAS STEP: Reindexing ---
    # Create an uninterrupted sequence of timestamps from START_TS to END_TS in 2-second intervals.
    # range(start, stop, step) generates the numbers.
    full_timeline = range(START_TS, END_TS + 1, STEP_SECONDS)

    # .reindex(...) forces the DataFrame to have EXACTLY the rows specified in 'full_timeline'.
    # If the target container died for 30 seconds, Prometheus returned no data for those 30 seconds.
    # reindex forces those missing 30 seconds into the DataFrame as empty (NaN) rows!
    df = df.reindex(full_timeline)

    # Explicitly naming the index column "timestamp" so it will have a header.
    df.index.name = "timestamp"

    # --- PANDAS STEP: Handling Missing Values ---
    # Replace all NaN (empty / downtime gaps) with 0.0 across all numeric columns.
    df = df.fillna(0.0)

    # --- PANDAS STEP: Resetting Index ---
    # Move 'timestamp' from being the row index back to being a normal, regular column.
    # 'inplace=True' applies the modification directly to 'df' without needing 'df = df.reset_index()'.
    df.reset_index(inplace=True)

    # --- PANDAS STEP: Applying a Function to a Column ---
    # .apply() runs a function on every single value of the "timestamp" column.
    # Here, a lambda (inline function) converts each UNIX timestamp back into a readable date string.
    # The result is saved as a new column named "Local Datetime".
    df["Local Datetime"] = df["timestamp"].apply(
        lambda ts: datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    )

    # --- PANDAS STEP: Row-wise Evaluation ---
    # .apply(..., axis=1) iterates row-by-row (horizontal) instead of column-by-column.
    # Each row is passed into our assign_status() function to decide "Healthy", "Degraded", or "Failed".
    # The returned status is stored in a brand new column named "status".
    df["status"] = df.apply(assign_status, axis=1)

    # Ensure the parent directory exists before saving (e.g., 'raw_data/')
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # --- PANDAS STEP: Exporting ---
    # Save the whole table to a CSV file.
    # 'index=False' prevents Pandas from writing the default numeric row numbers (0, 1, 2...) into the CSV.
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"\n[✓] Successfully saved {len(df)} rows to '{OUTPUT_FILE}'")

    # --- PANDAS STEP: Summary Stats ---
    # .value_counts() counts how many times each unique value appears in the "status" column.
    # e.g., Healthy: 250, Degraded: 40, Failed: 10
    print("\n--- Status Distribution ---")
    print(df["status"].value_counts())


if __name__ == "__main__":
    main()
