import logging
import logging.handlers
import os
import queue
import sys

from pythonjsonlogger import jsonlogger

log_queue = queue.Queue(-1)


class LoggerSetup:
    def __init__(self, logger_name: str = __name__):
        self.logger = logging.getLogger(logger_name)
        if not self.logger.hasHandlers():
            self.setup_logging()

    def setup_logging(self):
        log_dir = "logs"
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            print(f"Error creating log directory: {e}", file=sys.stderr)
        LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
        json_formatter = jsonlogger.JsonFormatter(
            LOG_FORMAT, rename_fields={"levelname": "level", "asctime": "timestamp"}
        )
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(json_formatter)
        console_handler.setLevel(logging.DEBUG)
        log_file_path = os.path.join(log_dir, "app.log")
        file_handler = logging.handlers.TimedRotatingFileHandler(
            filename=log_file_path,
            when="midnight",
            backupCount=7,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(json_formatter)
        file_handler.setLevel(logging.INFO)
        queue_handler = logging.handlers.QueueHandler(log_queue)
        self.logger.addHandler(queue_handler)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self.listener = logging.handlers.QueueListener(
            log_queue, console_handler, file_handler, respect_handler_level=True
        )
        self.listener.start()
