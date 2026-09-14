from fastapi import APIRouter, FastAPI
from .routers import context_router

app = FastAPI()

app.include_router(context_router)


def main() -> None:
    print("Hello from advisory-service!")
