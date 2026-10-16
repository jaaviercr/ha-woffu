"""Fixtures for the Woffu tests."""

import json

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration available to every test."""
    yield


class FakeResponse:
    """Minimal stand-in for a requests response."""

    def __init__(self, status_code=200, payload=None, text=None):
        self.status = status_code
        self._payload = payload if payload is not None else {}
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def text(self):
        if isinstance(self._payload, Exception):
            return "invalid json"
        if self._text is not None:
            return self._text
        return json.dumps(self._payload)


class FakeSession:
    """Return fake aiohttp responses for API requests."""

    def __init__(self, request_handler):
        self.request_handler = request_handler

    def request(self, method, url, **kwargs):
        return self.request_handler(method, url, **kwargs)


class FakeWoffu:
    """Simulates the Woffu endpoints used by the integration."""

    def __init__(self, signs=None):
        self.signs = list(signs or [])
        self.posted_signs = []
        self.token_requests = 0

    def request(self, method, url, **kwargs):
        if url.endswith("/token"):
            self.token_requests += 1
            return FakeResponse(200, {"access_token": "token"})
        if "api/users" in url:
            return FakeResponse(200, {"UserId": 4242})
        if method == "post" and "svc/signs" in url:
            self.posted_signs.append(kwargs.get("json"))
            self.signs.append({"ShortTrueTime": "18:00"})
            return FakeResponse(200, {})
        if "api/signs" in url:
            return FakeResponse(200, list(self.signs))
        raise AssertionError(f"Unexpected request: {method} {url}")


@pytest.fixture
def fake_woffu():
    """Return a controllable fake Woffu backend."""
    return FakeWoffu
