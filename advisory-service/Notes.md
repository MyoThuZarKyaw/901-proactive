*Command to Start the Service*

```shell
-- DEV Environment

uv run fastapi dev
```

*Redis Utils Commands*
```shell
# Ping if Redis is up and running
docker exec -it redis redis-cli ping

# Subscribe "circuit-breaker-channel"
docker exec -it redis redis-cli SUBSCRIBE circuit-breaker-channel

# Publish message to "circuit-breaker-channel"
docker exec -it redis redis-cli PUBLISH circuit-breaker-channel "payment-service"
```

*Podman Commands*
```shell
# To restart podman machines
podman machine stop
podman machine start
```