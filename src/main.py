import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from src.configs.db import create_db_and_tables

from .security.auth import APIKeyDep
from .utils.loger import LoggerSetup


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.logger_setup_instance = LoggerSetup(logger_name=__name__)
    app.state.logger = logging.getLogger(__name__)
    logging.getLogger("uvicorn.access").propagate = False

    app.state.logger.info("App starting")
    app.state.logger.info("Initializing database and tables.")
    try:
        await create_db_and_tables()
        app.state.logger.info("Database tables created successfully.")
    except Exception:
        app.state.logger.error(
            "Error creating database tables. The application will not start.",
            exc_info=True,
        )
        raise
    yield
    app.state.logger.info("App shutting down. Waiting for logs to be processed...")
    logger_setup = getattr(app.state, "logger_setup_instance", None)
    if logger_setup is not None:
        listener = getattr(logger_setup, "listener", None)
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                app.state.logger.exception("Failed to stop logger listener cleanly.")
    app.state.logger.info("App stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/", status_code=status.HTTP_200_OK)
def health_check(api_key: APIKeyDep):
    logger = getattr(app.state, "logger", logging.getLogger("app"))
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
