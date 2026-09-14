


### Throughput
sum(rate(otel_http_server_requests_milliseconds_count{application="inventory_service"}[1m]))


### Latency

sum(rate(otel_http_server_requests_milliseconds_sum{application="inventory_service"}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{application="inventory_service"}[1m]))

### process_cpu

avg(otel_process_cpu_usage{application="inventory_service"}) * 100

### system_cpu

avg(otel_system_cpu_usage{application="inventory_service"}) * 100

*** Should use all of cpu usage? ***

### mem_utilization

sum(otel_jvm_memory_used_bytes{application="inventory_service"}) / sum(otel_jvm_memory_committed_bytes{application="inventory_service"})

### error_rate

sum(increase(otel_http_server_requests_milliseconds_count{application="inventory_service",status=~'5..'}[1m])) / sum(increase(otel_http_server_requests_milliseconds_count{application="inventory_service"}[1m]))


sum(rate(otel_http_server_requests_milliseconds_sum{application="inventory_service"}[1m])) / sum(rate(otel_http_server_requests_milliseconds_count{application="inventory_service"}[1m])) 1788226860 1788227460
