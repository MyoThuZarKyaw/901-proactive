from fastapi import APIRouter

from .services import RedisPublisherService

_app_router = APIRouter()

_api_v1_router = APIRouter(prefix="/api/v1")
_api_v1_router.include_router(_app_router)

context_router = APIRouter(prefix="/advisory")
context_router.include_router(_api_v1_router)


@context_router.get("/")
def welcome():
    return "Welcome to advisory service!"


@context_router.get("/ping")
def ping():
    return "PONG"


@_app_router.post("/advise")
def advise():
    """Get current matric data, ask the brain and action accordingly"""

    publisher = RedisPublisherService()
    publisher.publish()

    return {
        "matric": "The data got from prometious and passed to the brain",
        "response": "The response return from the braind",
        "event": "The event happened based on the response",
    }
