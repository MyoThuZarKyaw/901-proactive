
# September 11

### 1. Global Cluster Queries
```promql
cluster_cpu = avg(otel_process_cpu_usage) * 100
cluster_mem = sum(otel_jvm_memory_used_bytes) / sum(otel_jvm_memory_committed_bytes)
cluster_throughput = sum(rate(otel_http_server_requests_milliseconds_count[1m]))
cluster_error_rate = sum(rate(otel_http_server_requests_milliseconds_count{status=~'5..'}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count[1m]))
```

---

### 2. Caller Queries (`caller = "order_service"`)
```promql
caller_cpu = otel_process_cpu_usage{application="order_service"} * 100
caller_mem = otel_jvm_memory_used_bytes{application="order_service"} / otel_jvm_memory_committed_bytes{application="order_service"}
```

---

### 3. Target Service Queries (`target = "inventory_service"` or `"payment_service"`)
```promql
target_cpu = otel_process_cpu_usage{application="{target_name}"} * 100
target_mem = otel_jvm_memory_used_bytes{application="{target_name}"} / otel_jvm_memory_committed_bytes{application="{target_name}"}
target_latency = sum(rate(otel_http_server_requests_milliseconds_sum{application="{target_name}"}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{application="{target_name}"}[1m]))
target_error_rate = sum(rate(otel_http_server_requests_milliseconds_count{application="{target_name}", status=~"5.."}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{application="{target_name}"}[1m]))
```

---

### 4. Circuit Breaker Queries (`cb_name = "inventoryService"` or `"paymentService"`)
```promql
cb_slow_call_rate = otel_resilience4j_circuitbreaker_slow_call_rate{application="order_service", name="{cb_name}"}
cb_failure_rate = otel_resilience4j_circuitbreaker_failure_rate{application="order_service", name="{cb_name}"}
cb_state = otel_resilience4j_circuitbreaker_state{application="order_service", name="{cb_name}", state="open"}
```