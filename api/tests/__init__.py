"""Keeps expected "database unavailable" warnings out of test output; real failures still show."""

import logging

logging.getLogger("uvicorn.error").setLevel(logging.ERROR)
