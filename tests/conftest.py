"""Fixtures for the Woffu tests."""

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom integration available to every test."""
    yield


class FakeResponse:
    """Minimal stand-in for a requests response."""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.ok = status_code < 400
        self.text = text
        self._payload = payload if payload is not None else {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


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
