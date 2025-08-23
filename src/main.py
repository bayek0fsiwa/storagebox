from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("App starting")
    yield
    print("App stopping")
    print("App stopped")


app = FastAPI()


@app.get("/", status_code=status.HTTP_200_OK)
def health_check():
    return JSONResponse({"status": "Online"})
