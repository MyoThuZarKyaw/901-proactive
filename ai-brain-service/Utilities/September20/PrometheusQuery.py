from datetime import time

import requests

PROMETHEUS_URL = "http://localhost:9090/api/v1/query"


def fetch_raw_metrics(target_service):
    queries = {
        "target_cpu": f'avg(otel_process_cpu_usage{{application="{target_service}"}}) * 100',
        "target_mem": f'sum(otel_jvm_memory_used_bytes{{application="{target_service}"}}) / sum(otel_jvm_memory_committed_bytes{{application="{target_service}"}})',
        "target_throughput": f'sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_service}"}}[1m]))',
        "target_latency": f'(sum(rate(otel_http_server_requests_milliseconds_sum{{application="{target_service}"}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_service}"}}[1m]))) or on() vector(0)',
        "target_error_rate": f'(sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_service}", status=~"5.."}}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{{application="{target_service}"}}[1m]))) or on() vector(0)',
        "target_live_threads": f'max(otel_jvm_threads_live{{application="{target_service}"}})',
        "target_active_requests": f'sum(otel_http_server_requests_active_milliseconds_count{{application="{target_service}"}})'
    }

    snapshot = {"timestamp": int(time.time())}
    for key, q in queries.items():
        try:
            res = requests.get(PROMETHEUS_URL, params={"query": q}, timeout=2)
            res.raise_for_status()
            data = res.json().get("data", {}).get("result", [])
            snapshot[key] = float(data[0]["value"][1]) if data else 0.0
        except Exception:
            snapshot[key] = 0.0
    return snapshot