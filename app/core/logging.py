"""Logging is configured once by process entrypoints."""
import logging
import sys
from pathlib import Path

class SecretFilter(logging.Filter):
    def __init__(self, secrets=()):
        super().__init__()
        self.secrets = tuple(str(value) for value in secrets if value)

    def filter(self, record):
        message = record.getMessage()
        for value in self.secrets:
            message = message.replace(value, "[REDACTED]")
        record.msg, record.args = message, ()
        return True


def configure_logging(level=logging.INFO, path=None, secrets=(), overwrite=True):
    handlers = [logging.StreamHandler(sys.stdout)]
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, mode="w" if overwrite else "a"))
    for handler in handlers:
        handler.addFilter(SecretFilter(secrets))
    logging.basicConfig(level=level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", handlers=handlers, force=True)
