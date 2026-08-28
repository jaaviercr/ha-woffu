"""Tests for the Woffu API client."""

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from time import sleep, time
from unittest.mock import patch

import pytest
import requests

from custom_components.woffu.api import (
    REQUEST_TIMEOUT,
    API,
    APIAuthError,
    APIConnectionError,
)

from .conftest import FakeResponse, FakeWoffu


def build_api(backend):
    """Return an API bound to a fake backend."""
    api = API("user@example.com", "secret")
    return api, patch(
        "custom_components.woffu.api.requests.request", side_effect=backend.request
    )


def test_connect_reuses_token_from_login():
    """The token from connect() must not trigger a second login."""
    backend = FakeWoffu()
    api, patched = build_api(backend)

    with patched:
        api.connect()
        api.get_access_token()

    assert backend.token_requests == 1


def test_login_sends_structured_credentials_with_timeout():
    """Special characters must survive the login request."""
    api = API("user@example.com", "pass&word=+1")
    captured = {}

    def request(method, url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(200, {"access_token": "token"})

    with patch("custom_components.woffu.api.requests.request", side_effect=request):
        api.connect()

    assert captured["data"]["username"] == "user@example.com"
    assert captured["data"]["password"] == "pass&word=+1"
    assert captured["timeout"] == REQUEST_TIMEOUT


@pytest.mark.parametrize("status", [400, 401, 403])
def test_rejected_credentials_raise_auth_error(status):
    """Woffu rejecting the credentials must be an auth error."""
    api = API("user", "wrong")

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(status),
    ):
        with pytest.raises(APIAuthError):
            api.connect()


def test_server_error_raises_connection_error():
    """A broken backend must not be reported as invalid credentials."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(500),
    ):
        with pytest.raises(APIConnectionError):
            api.connect()


def test_network_failure_raises_connection_error():
    """Network problems must not be reported as invalid credentials."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        side_effect=requests.ConnectionError("no route to host"),
    ):
        with pytest.raises(APIConnectionError):
            api.connect()


def test_invalid_json_raises_connection_error():
    """A malformed body must not be silently treated as no data."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(200, ValueError("not json")),
    ):
        with pytest.raises(APIConnectionError):
            api.connect()


@pytest.mark.parametrize("payload", [[], "token"])
def test_invalid_login_shape_raises_connection_error(payload):
    """A login response with the wrong JSON shape is a connection error."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(200, payload),
    ):
        with pytest.raises(APIConnectionError):
            api.connect()


def test_invalid_user_shape_raises_connection_error():
    """A user response with the wrong JSON shape is a connection error."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        side_effect=[
            FakeResponse(200, {"access_token": "token"}),
            FakeResponse(200, []),
        ],
    ):
        with pytest.raises(APIConnectionError):
            api.get_user_id(api.get_access_token())


@pytest.mark.parametrize("user_id", [None, "4242", 0, -1, True, False])
def test_invalid_user_id_raises_connection_error(user_id):
    """A user response with an invalid id is a connection error."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(200, {"UserId": user_id}),
    ):
        with pytest.raises(APIConnectionError):
            api.get_user_id("token")


@pytest.mark.parametrize("payload", [None, "signs", {"data": {}}])
def test_invalid_signs_shape_raises_connection_error(payload):
    """A signs response with the wrong JSON shape is a connection error."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        side_effect=[
            FakeResponse(200, {"access_token": "token"}),
            FakeResponse(200, {"UserId": 4242}),
            FakeResponse(200, payload),
        ],
    ):
        with pytest.raises(APIConnectionError):
            api.get_time_worked_today(refresh_cache=True)


@pytest.mark.parametrize(
    "signs",
    [["invalid"], [{"ShortTrueTime": "09:60"}], [{"ShortTime": "25:00:00"}], [{}]],
)
def test_invalid_sign_record_raises_connection_error(signs):
    """A malformed sign record is a connection error."""
    api = API("user", "secret")

    with patch(
        "custom_components.woffu.api.requests.request",
        side_effect=[
            FakeResponse(200, {"access_token": "token"}),
            FakeResponse(200, {"UserId": 4242}),
            FakeResponse(200, signs),
        ],
    ):
        with pytest.raises(APIConnectionError):
            api.get_time_worked_today(refresh_cache=True)


def test_api_failure_does_not_report_zero_minutes():
    """A failing API must raise instead of reporting an empty workday."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        api.connect()

    with patch(
        "custom_components.woffu.api.requests.request",
        return_value=FakeResponse(500),
    ):
        with pytest.raises(APIConnectionError):
            api.get_time_worked_today(refresh_cache=True)


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
    api = API("user", "secret")

    assert api.calculate_minutes_from_signs(signs) == expected


def test_calculate_minutes_from_open_sign_preserves_seconds():
    """An open work interval must include the current seconds."""
    api = API("user", "secret")

    with patch("custom_components.woffu.api.datetime") as mocked_datetime:
        mocked_datetime.now.return_value = datetime(2026, 8, 27, 10, 30, 3)

        assert api.calculate_minutes_from_signs([{"ShortTrueTime": "09:00"}]) == pytest.approx(90.05)


def test_calculate_minutes_from_signs_preserves_sign_seconds():
    """Completed work intervals must include seconds returned by Woffu."""
    api = API("user", "secret")

    assert api.calculate_minutes_from_signs(
        [{"ShortTrueTime": "09:00:10"}, {"ShortTrueTime": "13:30:20"}]
    ) == pytest.approx(270 + 10 / 60)


def test_clock_payload_carries_a_single_offset():
    """The timestamp must not repeat the UTC offset."""
    backend = FakeWoffu(signs=[])
    api, patched = build_api(backend)

    with patched:
        api.connect()
        api.clock_in_out(True)

    timestamp = backend.posted_signs[0]["StartDate"]
    assert timestamp.count("+") <= 1
    assert not timestamp.endswith("+02:00+02:00")


def test_clock_payload_uses_local_timezone_offset():
    """The clock payload contains the offset of the local timestamp."""
    backend = FakeWoffu(signs=[])
    api, patched = build_api(backend)
    local_now = datetime(2026, 1, 15, 10, 0, tzinfo=timezone(timedelta(hours=1)))

    with patch("custom_components.woffu.api.datetime") as mocked_datetime:
        mocked_datetime.now.return_value.astimezone.return_value = local_now
        with patched:
            api.connect()
            api.clock_in_out(True)

    payload = backend.posted_signs[0]
    assert payload["StartDate"] == "2026-01-15T10:00:00+01:00"
    assert payload["TimezoneOffset"] == -60


def test_signs_url_uses_iso_date():
    """The signs request uses the API date format."""
    assert API._build_signs_url(4242, datetime(2026, 8, 28)) == (
        "https://gtd.woffu.com/api/signs?userId=4242&date=2026-08-28"
    )


def test_clock_operations_are_serialized():
    """A second clock operation waits for the first one to finish."""
    api = API("user", "secret")
    api._last_token = "token"
    api._last_token_time = time()
    api._last_user_id = 4242
    first_started = Event()
    release_first = Event()
    active_lock = Lock()
    active = 0
    max_active = 0

    def load_signs(*_args, **_kwargs):
        nonlocal active, max_active
        with active_lock:
            active += 1
            max_active = max(max_active, active)
        if not first_started.is_set():
            first_started.set()
            release_first.wait(timeout=5)
        with active_lock:
            active -= 1
        return [], False

    api._load_signs = load_signs
    api._request = lambda *_args, **_kwargs: FakeResponse(200, {})

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(api.clock_in_out, True)
        assert first_started.wait(timeout=5)
        second = executor.submit(api.clock_in_out, False)
        sleep(0.05)
        assert max_active == 1
        release_first.set()
        assert first.result() is True
        assert second.result() is True


def test_clock_out_is_skipped_when_woffu_already_reports_it():
    """An external clock-out must not be turned into a clock-in."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        api.connect()
        api.get_time_worked_today()
        assert api.is_clocked_in() is True

        # The user clocks out from the Woffu app, Home Assistant does not know yet.
        backend.signs.append({"ShortTrueTime": "17:00"})
        api.clock_in_out(False)

    assert backend.posted_signs == []
    assert api.is_clocked_in() is False


def test_state_does_not_bounce_while_woffu_lags_behind():
    """A just-created sign must survive a stale read from Woffu."""
    backend = FakeWoffu(signs=[{"ShortTrueTime": "09:00"}])
    api, patched = build_api(backend)

    with patched:
        api.connect()
        api.get_time_worked_today()

        # Clock out, but make Woffu keep returning the previous signs.
        with patch.object(FakeWoffu, "request", autospec=True) as stale:
            def respond(_self, method, url, **kwargs):
                if method == "post" and "svc/signs" in url:
                    backend.posted_signs.append(kwargs.get("json"))
                    return FakeResponse(200, {})
                if "api/signs" in url:
                    return FakeResponse(200, [{"ShortTrueTime": "09:00"}])
                if "api/users" in url:
                    return FakeResponse(200, {"UserId": 4242})
                return FakeResponse(200, {"access_token": "token"})

            stale.side_effect = respond
            api.clock_in_out(False)
            assert api.is_clocked_in() is False

            api.get_time_worked_today(refresh_cache=True)
            assert api.is_clocked_in() is False
