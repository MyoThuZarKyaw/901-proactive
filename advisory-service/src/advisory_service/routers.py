from fastapi import APIRouter

app_router = APIRouter()

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(app_router)

context_router = APIRouter(prefix="/advisory")
context_router.include_router(api_v1_router)


@context_router.get("/")
def ping():
    return "Welcome to advisory service!"


@context_router.get("/ping")
def ping():
    return "PONG"


@app_router.post("/advise")
def advise():
    """Get current matric data, ask the brain and action accordingly"""
    return {
        "matric": "The data got from prometious and passed to the brain",
        "response": "The response return from the braind",
        "event": "The event happened based on the response",
    }
