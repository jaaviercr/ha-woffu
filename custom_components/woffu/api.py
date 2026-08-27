"""API class for connecting to Woffu API."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from time import time

import requests

from .const import DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://gtd.woffu.com"
REQUEST_TIMEOUT = 30
TOKEN_MAX_AGE = 3000
AUTH_STATUS_CODES = (400, 401, 403)
# Woffu may not return a sign immediately after creating it.
SIGN_SETTLE_GRACE = 90
BASE_HEADERS = {
    "User-Agent": "HomeAssistant-Woffu",
    "Accept": "application/json, text/plain, */*",
}


class API:
    """Class API for connecting to Woffu API."""

    def clock_in_out(self, clock_in: bool | None = None) -> bool:
        """Clock in or out, or toggle the current state when no value is given."""
        token = self.get_access_token()
        user_id = self.get_user_id(token)
        # Woffu derives the direction from the existing signs, so never sign on stale data.
        _, current_state = self._load_signs(token, user_id, refresh_cache=True)
        if clock_in is not None and clock_in == current_state:
            self._clear_pending_state()
            self._last_clocked_in_state = current_state
            _LOGGER.debug("Skipping sign: Woffu already reports state %s", current_state)
            return True

        now = datetime.now(timezone.utc).astimezone()
        offset_minutes = int(now.utcoffset().total_seconds() / 60)
        timestamp = now.replace(microsecond=0).isoformat()
        payload = {
            "StartDate": timestamp,
            "EndDate": timestamp,
            "TimezoneOffset": -offset_minutes,
            "UserId": user_id,
        }
        self._request(
            "post",
            f"{BASE_URL}/api/svc/signs/signs",
            headers=self.get_auth_headers(token),
            json=payload,
        )

        new_state = clock_in if clock_in is not None else not current_state
        self._pending_state = new_state
        self._pending_state_time = time()
        self._last_clocked_in_state = new_state
        self._last_signs_time = None
        return True

    def __init__(self, user: str, pwd: str) -> None:
        """Initialise."""
        self.user = user
        self.user_in_sensor_name = re.sub(r"[.@]", "_", self.user)
        self.pwd = pwd
        self.connected: bool = False
        self._last_clocked_in_state = None
        self._last_minutes = None
        self._last_signs = None
        self._last_signs_time = None  # timestamp of last cache
        self._last_token = None
        self._last_token_time = None
        self._last_user_id = None
        self._pending_state = None
        self._pending_state_time = None

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return self.user_in_sensor_name

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Perform an HTTP request and translate failures into API errors."""
        try:
            response = requests.request(
                method, url, timeout=REQUEST_TIMEOUT, **kwargs
            )
        except requests.RequestException as err:
            raise APIConnectionError(f"Error connecting to Woffu: {err}") from err

        if response.status_code in AUTH_STATUS_CODES:
            raise APIAuthError(f"HTTP {response.status_code}: {response.text}")
        if not response.ok:
            raise APIConnectionError(f"HTTP {response.status_code}: {response.text}")
        return response

    def _json(self, response: requests.Response):
        """Return the decoded body or fail with a connection error."""
        try:
            return response.json()
        except ValueError as err:
            raise APIConnectionError(f"Invalid JSON from Woffu: {err}") from err

    def connect(self) -> bool:
        """Connect to API and verify real credentials."""
        self.get_access_token()
        self.connected = True
        return True

    def disconnect(self) -> bool:
        """Disconnect from API."""
        self.connected = False
        return True

    def get_access_token(self):
        """Cache token for session."""
        if (
            self._last_token
            and self._last_token_time
            and time() - self._last_token_time < TOKEN_MAX_AGE
        ):
            return self._last_token

        response = self._request(
            "post",
            f"{BASE_URL}/token",
            headers=BASE_HEADERS,
            data={
                "grant_type": "password",
                "username": self.user,
                "password": self.pwd,
            },
        )
        payload = self._json(response)
        access_token = payload.get("access_token")
        if not access_token:
            raise APIAuthError(
                payload.get("error_description", "Login response contained no token")
            )
        self._last_token = access_token
        self._last_token_time = time()
        return access_token

    def get_auth_headers(self, token):
        """Return the headers used for authenticated requests."""
        return {**BASE_HEADERS, "Authorization": f"Bearer {token}"}

    def get_user_id(self, token):
        """Return the Woffu user id, caching it for the session."""
        if self._last_user_id is not None:
            return self._last_user_id
        response = self._request(
            "get", f"{BASE_URL}/api/users/", headers=self.get_auth_headers(token)
        )
        user_info = self._json(response)
        try:
            self._last_user_id = user_info["UserId"]
        except (KeyError, TypeError) as err:
            raise APIConnectionError("Woffu did not return a user id") from err
        return self._last_user_id

    def get_signs(self, token, user_id, date, refresh_cache):
        """Return today's signs, using the cache when it is still fresh."""
        if self._should_use_cache(refresh_cache):
            return self._last_signs
        response = self._request(
            "get",
            self._build_signs_url(user_id, date),
            headers=self.get_auth_headers(token),
        )
        result = self._json(response)
        self._update_signs_cache(result)
        return result

    @staticmethod
    def _build_signs_url(user_id, date):
        date_str = date.strftime("%Y-%m-%d")
        return f"https://gtd.woffu.com/api/signs?userId={user_id}&date={date_str}"

    def _should_use_cache(self, refresh_cache):
        now_ts = time()
        if not refresh_cache and self._last_signs is not None and self._last_signs_time is not None:
            if now_ts - self._last_signs_time < DEFAULT_SCAN_INTERVAL:
                return True
        return False

    def _update_signs_cache(self, result):
        self._last_signs = result
        self._last_signs_time = time()

    @staticmethod
    def _time_to_minutes(value: str) -> float:
        """Convert a Woffu HH:MM[:SS] time value to minutes."""
        hours, minutes, *seconds = value.split(":")
        return int(hours) * 60 + int(minutes) + (int(seconds[0]) / 60 if seconds else 0)

    def calculate_minutes_from_signs(self, signs):
        total_minutes = 0
        if not signs:
            return 0
        sorted_signs = sorted(signs, key=lambda x: x.get("TrueDate", x.get("Date", "")))
        for i in range(0, len(sorted_signs), 2):
            if i+1 < len(sorted_signs):
                sign_in = sorted_signs[i]
                sign_out = sorted_signs[i+1]
                time_in = sign_in.get("ShortTrueTime") or sign_in.get("ShortTime")
                time_out = sign_out.get("ShortTrueTime") or sign_out.get("ShortTime")
                if time_in and time_out:
                    minutes_in = self._time_to_minutes(time_in)
                    minutes_out = self._time_to_minutes(time_out)
                    # Si time_in > time_out, se ha pasado de día
                    if minutes_out < minutes_in:
                        # Añadimos 24h (1440 minutos) al out
                        minutes_out += 24 * 60
                    total_minutes += minutes_out - minutes_in
            else:
                sign_in = sorted_signs[i]
                time_in = sign_in.get("ShortTrueTime") or sign_in.get("ShortTime")
                if time_in:
                    minutes_in = self._time_to_minutes(time_in)
                    now = datetime.now()
                    minutes_now = now.hour * 60 + now.minute + now.second / 60
                    # Si time_in > time_out, se ha pasado de día
                    if minutes_now < minutes_in:
                        # Añadimos 24h (1440 minutos) al now
                        minutes_now += 24 * 60
                    total_minutes += minutes_now - minutes_in
        return total_minutes

    def get_time_worked_today(self, refresh_cache=False):
        """Return today's worked minutes and store the current clock-in state."""
        token = self.get_access_token()
        user_id = self.get_user_id(token)
        minutes, state = self._load_signs(token, user_id, refresh_cache)
        self._last_clocked_in_state = self._settle_state(state)
        return minutes

    def _load_signs(self, token, user_id, refresh_cache):
        """Return today's minutes and the state reported by Woffu."""
        signs = self.get_signs(token, user_id, datetime.now(), refresh_cache)
        sign_data = signs.get("data", []) if isinstance(signs, dict) else signs
        minutes = self.calculate_minutes_from_signs(sign_data)
        self._last_minutes = minutes
        return minutes, bool(sign_data and len(sign_data) % 2 == 1)

    def _clear_pending_state(self) -> None:
        self._pending_state = None
        self._pending_state_time = None

    def _settle_state(self, state: bool) -> bool:
        """Keep the just-signed state until Woffu reports it back."""
        if self._pending_state is None:
            return state
        if state == self._pending_state:
            self._clear_pending_state()
            return state
        if time() - self._pending_state_time < SIGN_SETTLE_GRACE:
            return self._pending_state
        self._clear_pending_state()
        return state

    def is_clocked_in(self, refresh_cache=False):
        """Return the clock-in state, refreshing it when the cache is stale."""
        if (
            refresh_cache
            or self._last_clocked_in_state is None
            or (
                self._last_signs_time is not None
                and time() - self._last_signs_time > DEFAULT_SCAN_INTERVAL
            )
        ):
            self.get_time_worked_today(refresh_cache)
        return self._last_clocked_in_state


class APIAuthError(Exception):
    """Exception class for auth error."""

class APIConnectionError(Exception):
    """Exception class for connection error."""
