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
docker exec -it redis redis-cli PUBLISH circuit-breaker-channel '{"event_id":"3d7875baf6b94a9296011c20ed7d92ac","target_service":"order-service","status":"Failed","reason":null,"timestamp":"2026-10-31T10:23:46.355904Z"}'
```

*Podman Commands*
```shell
# To restart podman machines
podman machine stop
podman machine start
```

*Modules and their main responsibilities*
- config.py
  - It loads all the settings required for the application from the config files, .env.dev, .env.prod, etc...
- __init__.py
  - Main module file for the applications. It does all the bootstrap things for the applications such as
    - loading brain model
    - loading configs
    - running schedulers for monitoring or prediction
- routers.py
  - Host of the all RestAPIs methods supported by the applications
- schedulers.py
  - Implementation of schedules required for the application such as prediction schedule which is run from `__init__` module
- services.py
  - All the core business logic are implemented in here such as, querying metric data from prometheus, building payload to pass to brain
  - for prediction, sending alert message to redis
- container.py
  - It is a service locator instance which hold all the singleton service instances. So, whenever a service is needed, the client code should get it from
  - the container instead of creating it by its own.


*How to run in docker*
```shell
cd advisory-service
docker compose build
docker compose up
# or: podman build -t advisory-service . && podman run -p 8000:8000 --env-file .env.docker advisory-service

or

cd advisory-service
npm run python:docker:dev
npm run prt-services:up
```