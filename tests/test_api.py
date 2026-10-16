"""Tests for the Woffu API client."""

import asyncio
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta, timezone
from time import time
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
import pytest
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_socket import disable_socket, enable_socket

from custom_components.woffu.api import (
    REQUEST_TIMEOUT,
    API,
    APIAuthError,
    APIConnectionError,
)

from .conftest import FakeResponse, FakeSession, FakeWoffu


def build_api(backend):
    """Return an API bound to a fake backend."""
    api = API("user@example.com", "secret", FakeSession(backend.request))
    return api, nullcontext()


def api_for_unit_tests(user="user", password="secret"):
    """Return an API with a session for tests that do not make requests."""
    return API(user, password, FakeSession(lambda *_args, **_kwargs: FakeResponse()))


@contextmanager
def allow_local_sockets():
    """Temporarily allow sockets for aiohttp's local test server."""
    enable_socket()
    try:
        yield
    finally:
        disable_socket()


async def test_connect_reuses_token_from_login():
    """The token from connect() must not trigger a second login."""
    backend = FakeWoffu()
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()
        await api.async_get_access_token()

    assert backend.token_requests == 1


async def test_workday_snapshot_returns_minutes_and_clocked_in_state():
    """Worked time and clock-in state come from the same signs response."""
    backend = FakeWoffu(
        signs=[{"ShortTrueTime": "09:00"}, {"ShortTrueTime": "13:30"}]
    )
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()
        snapshot = await api.async_get_workday_snapshot(refresh_cache=True)

    assert snapshot == (270, False)


async def test_shared_session_fetches_workday_from_local_server(
    hass, aiohttp_server, monkeypatch
):
    """The shared Home Assistant session handles the real API request flow."""
    calls = []

    async def login(request):
        calls.append("token")
        assert (await request.post())["username"] == "user@example.com"
        return web.json_response({"access_token": "token"})

    async def get_user(request):
        calls.append("user")
        assert request.headers["Authorization"] == "Bearer token"
        return web.json_response({"UserId": 4242})

    async def get_signs(request):
        calls.append("signs")
        assert request.headers["Authorization"] == "Bearer token"
        return web.json_response(
            [{"ShortTrueTime": "09:00"}, {"ShortTrueTime": "13:30"}]
        )

    app = web.Application()
    app.router.add_post("/token", login)
    app.router.add_get("/api/users/", get_user)
    app.router.add_get("/api/signs", get_signs)
    with allow_local_sockets():
        server = await aiohttp_server(app)
        base_url = str(server.make_url("/")).rstrip("/")
        monkeypatch.setattr("custom_components.woffu.api.BASE_URL", base_url)
        monkeypatch.setattr(
            API,
            "_build_signs_url",
            staticmethod(
                lambda user_id, date: (
                    f"{base_url}/api/signs?userId={user_id}&date={date:%Y-%m-%d}"
                )
            ),
        )
        api = API(
            "user@example.com",
            "secret",
            async_get_clientsession(hass),
        )

        await api.async_connect()
        snapshot = await api.async_get_workday_snapshot(refresh_cache=True)

        assert snapshot == (270, False)
        assert calls == ["token", "user", "signs"]


async def test_shared_session_timeout_becomes_connection_error(
    hass, aiohttp_server, monkeypatch
):
    """A real aiohttp timeout is translated to the integration error."""
    async def slow_login(_request):
        await asyncio.sleep(0.05)
        return web.json_response({"access_token": "token"})

    app = web.Application()
    app.router.add_post("/token", slow_login)
    with allow_local_sockets():
        server = await aiohttp_server(app)
        monkeypatch.setattr(
            "custom_components.woffu.api.BASE_URL",
            str(server.make_url("/")).rstrip("/"),
        )
        monkeypatch.setattr("custom_components.woffu.api.REQUEST_TIMEOUT", 0.01)
        api = API(
            "user@example.com",
            "secret",
            async_get_clientsession(hass),
        )

        with pytest.raises(APIConnectionError, match="Error connecting to Woffu"):
            await api.async_connect()


async def test_login_sends_structured_credentials_with_timeout():
    """Special characters must survive the login request."""
    captured = {}

    def request(method, url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(200, {"access_token": "token"})

    api = API("user@example.com", "pass&word=+1", FakeSession(request))
    await api.async_connect()

    assert captured["data"]["username"] == "user@example.com"
    assert captured["data"]["password"] == "pass&word=+1"
    assert captured["timeout"] == REQUEST_TIMEOUT


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_rejected_credentials_raise_auth_error(status):
    """Woffu rejecting the credentials must be an auth error."""
    api = API("user", "wrong", FakeSession(lambda *_args, **_kwargs: FakeResponse(status)))

    with pytest.raises(APIAuthError):
        await api.async_connect()


async def test_server_error_raises_connection_error():
    """A broken backend must not be reported as invalid credentials."""
    api = API("user", "secret", FakeSession(lambda *_args, **_kwargs: FakeResponse(500)))

    with pytest.raises(APIConnectionError):
        await api.async_connect()


async def test_network_failure_raises_connection_error():
    """Network problems must not be reported as invalid credentials."""
    def request(*_args, **_kwargs):
        raise aiohttp.ClientConnectionError("no route to host")

    api = API("user", "secret", FakeSession(request))

    with pytest.raises(APIConnectionError):
        await api.async_connect()


async def test_invalid_json_raises_connection_error():
    """A malformed body must not be silently treated as no data."""
    api = API(
        "user",
        "secret",
        FakeSession(lambda *_args, **_kwargs: FakeResponse(200, text="not json")),
    )

    with pytest.raises(APIConnectionError):
        await api.async_connect()


@pytest.mark.parametrize("payload", [[], "token"])
async def test_invalid_login_shape_raises_connection_error(payload):
    """A login response with the wrong JSON shape is a connection error."""
    api = API("user", "secret", FakeSession(lambda *_args, **_kwargs: FakeResponse(200, payload)))

    with pytest.raises(APIConnectionError):
        await api.async_connect()


async def test_invalid_user_shape_raises_connection_error():
    """A user response with the wrong JSON shape is a connection error."""
    responses = iter(
        [FakeResponse(200, {"access_token": "token"}), FakeResponse(200, [])]
    )
    api = API("user", "secret", FakeSession(lambda *_args, **_kwargs: next(responses)))

    with pytest.raises(APIConnectionError):
        await api.async_get_user_id(await api.async_get_access_token())


@pytest.mark.parametrize("user_id", [None, "4242", 0, -1, True, False])
async def test_invalid_user_id_raises_connection_error(user_id):
    """A user response with an invalid id is a connection error."""
    api = API(
        "user",
        "secret",
        FakeSession(lambda *_args, **_kwargs: FakeResponse(200, {"UserId": user_id})),
    )

    with pytest.raises(APIConnectionError):
        await api.async_get_user_id("token")


@pytest.mark.parametrize("payload", [None, "signs", {"data": {}}])
async def test_invalid_signs_shape_raises_connection_error(payload):
    """A signs response with the wrong JSON shape is a connection error."""
    responses = iter(
        [
            FakeResponse(200, {"access_token": "token"}),
            FakeResponse(200, {"UserId": 4242}),
            FakeResponse(200, payload),
        ]
    )
    api = API("user", "secret", FakeSession(lambda *_args, **_kwargs: next(responses)))

    with pytest.raises(APIConnectionError):
        await api.async_get_time_worked_today(refresh_cache=True)


@pytest.mark.parametrize(
    "signs",
    [["invalid"], [{"ShortTrueTime": "09:60"}], [{"ShortTime": "25:00:00"}], [{}]],
)
async def test_invalid_sign_record_raises_connection_error(signs):
    """A malformed sign record is a connection error."""
    responses = iter(
        [
            FakeResponse(200, {"access_token": "token"}),
            FakeResponse(200, {"UserId": 4242}),
            FakeResponse(200, signs),
        ]
    )
    api = API("user", "secret", FakeSession(lambda *_args, **_kwargs: next(responses)))

    with pytest.raises(APIConnectionError):
        await api.async_get_time_worked_today(refresh_cache=True)


async def test_api_failure_does_not_report_zero_minutes():
    """A failing API must raise instead of reporting an empty workday."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()

    api._session.request_handler = lambda *_args, **_kwargs: FakeResponse(500)
    with pytest.raises(APIConnectionError):
        await api.async_get_time_worked_today(refresh_cache=True)


@pytest.mark.parametrize(
    ("signs", "expected"),
    [
        ([], 0),
        ([{"ShortTrueTime": "09:00"}, {"ShortTrueTime": "13:30"}], 270),
        (
            [
                {"ShortTrueTime": "09:00"},
                {"ShortTrueTime": "13:00"},
                {"ShortTrueTime": "14:00"},
                {"ShortTrueTime": "17:00"},
            ],
            420,
        ),
        ([{"ShortTrueTime": "23:30"}, {"ShortTrueTime": "00:30"}], 60),
    ],
)
def test_calculate_minutes_from_signs(signs, expected):
    """Worked minutes must be derived correctly, including past midnight."""
    api = api_for_unit_tests()

    assert api.calculate_minutes_from_signs(signs) == expected


def test_calculate_minutes_from_open_sign_preserves_seconds():
    """An open work interval must include the current seconds."""
    api = api_for_unit_tests()

    with patch("custom_components.woffu.api.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 8, 27, 10, 30, 3)

        assert api.calculate_minutes_from_signs([{"ShortTrueTime": "09:00"}]) == pytest.approx(90.05)


def test_calculate_minutes_from_signs_preserves_sign_seconds():
    """Completed work intervals must include seconds returned by Woffu."""
    api = api_for_unit_tests()

    assert api.calculate_minutes_from_signs(
        [{"ShortTrueTime": "09:00:10"}, {"ShortTrueTime": "13:30:20"}]
    ) == pytest.approx(270 + 10 / 60)


async def test_clock_payload_carries_a_single_offset():
    """The timestamp must not repeat the UTC offset."""
    backend = FakeWoffu(signs=[])
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()
        await api.async_clock_in_out(True)

    timestamp = backend.posted_signs[0]["StartDate"]
    assert timestamp.count("+") <= 1
    assert not timestamp.endswith("+02:00+02:00")


async def test_clock_payload_uses_local_timezone_offset():
    """The clock payload contains the offset of the local timestamp."""
    backend = FakeWoffu(signs=[])
    api, patched = build_api(backend)
    local_now = datetime(2026, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))

    with patch("custom_components.woffu.api.datetime") as mocked_datetime:
        mocked_datetime.now.return_value.astimezone.return_value = local_now
        with patched:
            await api.async_connect()
            await api.async_clock_in_out(True)

    payload = backend.posted_signs[0]
    assert payload["StartDate"] == "2026-01-15T10:00:00+01:00"
    assert payload["TimezoneOffset"] == -60


def test_signs_url_uses_iso_date():
    """The signs request uses the API date format."""
    assert API._build_signs_url(4242, datetime(2026, 8, 28)) == (
        "https://gtd.woffu.com/api/signs?userId=4242&date=2026-08-28"
    )


async def test_clock_operations_are_serialized():
    """A second clock operation waits for the first one to finish."""
    api = api_for_unit_tests()
    api._last_token = "token"
    api._last_token_time = time()
    api._last_user_id = 4242
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    active = 0
    max_active = 0

    async def load_signs(*_args, **_kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if not first_started.is_set():
            first_started.set()
            await release_first.wait()
        active -= 1
        return [], False

    api._load_signs = load_signs
    api._request = AsyncMock(return_value=None)

    first = asyncio.create_task(api.async_clock_in_out(True))
    await asyncio.wait_for(first_started.wait(), timeout=5)
    second = asyncio.create_task(api.async_clock_in_out(False))
    await asyncio.sleep(0.05)
    assert max_active == 1
    release_first.set()
    assert await first is True
    assert await second is True


async def test_clock_out_is_skipped_when_woffu_already_reports_it():
    """An external clock-out must not be turned into a clock-in."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()
        await api.async_get_time_worked_today()
        assert await api.async_is_clocked_in() is True

        # The user clocks out from the Woffu app, Home Assistant does not know yet.
        backend.signs.append({"ShortTrueTime": "17:00"})
        await api.async_clock_in_out(False)

    assert backend.posted_signs == []
    assert await api.async_is_clocked_in() is False


async def test_state_does_not_bounce_while_woffu_lags_behind():
    """A just-created sign must survive a stale read from Woffu."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        await api.async_connect()
        await api.async_get_time_worked_today()

        # Clock out, but make Woffu keep returning the previous signs.
        def respond(method, url, **kwargs):
            if method == "post" and "svc/signs" in url:
                backend.posted_signs.append(kwargs.get("json"))
                return FakeResponse(200, {})
            if "api/signs" in url:
                return FakeResponse(200, [{"ShortTrueTime": "09:00"}])
            if "api/users" in url:
                return FakeResponse(200, {"UserId": 4242})
            return FakeResponse(200, {"access_token": "token"})

        api._session.request_handler = respond
        await api.async_clock_in_out(False)
        assert await api.async_is_clocked_in() is False

        await api.async_get_time_worked_today(refresh_cache=True)
        assert await api.async_is_clocked_in() is False
