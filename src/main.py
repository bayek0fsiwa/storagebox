import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from .utils.loger import LoggerSetup


@asynccontextmanager
async def lifespan(app: FastAPI):
    global logger_setup_instance, logger
    logger_setup_instance = LoggerSetup(logger_name="app")
    logger = logging.getLogger("app")

    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = False

    logger.info("App starting")
    yield
    logger.info("App shutting down. Waiting for logs to be processed...")
    if logger_setup_instance and logger_setup_instance.listener:
        logger_setup_instance.listener.stop()
    logger.info("App stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/", status_code=status.HTTP_200_OK)
def health_check():
    if logger:
        logger.info("Health check endpoint accessed.", extra={"path": "/"})
    return JSONResponse({"status": "Online"})


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_config=None,
        reload=True,
    )
