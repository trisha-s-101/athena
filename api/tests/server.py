"""Runs the API in a background uvicorn thread and calls it with urllib (standard library only, no httpx)."""

import json
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request

import uvicorn

from api.main import app


def findFreePort() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ServerTestCase(unittest.TestCase):
    @classmethod
    def startServer(cls):
        port = findFreePort()
        cls.baseUrl = f"http://127.0.0.1:{port}/api"
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        cls.server = uvicorn.Server(config)
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        deadline = time.time() + 10
        while not cls.server.started:
            if time.time() > deadline:
                raise RuntimeError("uvicorn did not start")
            time.sleep(0.05)

    @classmethod
    def stopServer(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.baseUrl + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())
