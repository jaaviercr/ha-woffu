"""Tests for the Woffu config flow."""

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.woffu.api import APIAuthError, APIConnectionError
from custom_components.woffu.const import DOMAIN
from custom_components.woffu import PLATFORMS, async_unload_entry

from pytest_homeassistant_custom_component.common import MockConfigEntry

CREDENTIALS = {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "secret"}


def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Add a configured Woffu account."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=CREDENTIALS,
        unique_id="user@example.com",
        title="user@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_user_flow_creates_entry(hass: HomeAssistant) -> None:
    """Valid credentials must create an entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch("custom_components.woffu.api.API.connect", return_value=True),
        patch("custom_components.woffu.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.com"
    assert result["result"].unique_id == "user@example.com"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (APIAuthError("bad password"), "invalid_auth"),
        (APIConnectionError("offline"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_reports_errors(hass: HomeAssistant, error, expected) -> None:
    """Each failure must map to its own message."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch("custom_components.woffu.api.API.connect", side_effect=error):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_user_flow_rejects_duplicate_account(hass: HomeAssistant) -> None:
    """The same account must not be configured twice."""
    mock_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with patch("custom_components.woffu.api.API.connect", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], CREDENTIALS
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_second_account_is_allowed(hass: HomeAssistant) -> None:
    """A different account must create its own entry."""
    mock_entry(hass)
    other = {CONF_USERNAME: "other@example.com", CONF_PASSWORD: "secret"}

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    with (
        patch("custom_components.woffu.api.API.connect", return_value=True),
        patch("custom_components.woffu.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], other)
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "other@example.com"


async def test_reconfigure_updates_password(hass: HomeAssistant) -> None:
    """Reconfiguring must store the new credentials."""
    entry = mock_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )
    assert result["type"] is FlowResultType.FORM

    with (
        patch("custom_components.woffu.api.API.connect", return_value=True),
        patch("custom_components.woffu.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "new-secret"},
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_PASSWORD] == "new-secret"


async def test_reconfigure_rejects_a_different_account(hass: HomeAssistant) -> None:
    """Reconfiguring must not silently swap the account."""
    entry = mock_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
    )

    with patch("custom_components.woffu.api.API.connect", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "someone@example.com", CONF_PASSWORD: "secret"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "account_mismatch"


async def test_reauth_updates_password(hass: HomeAssistant) -> None:
    """Re-authentication must accept a new password."""
    entry = mock_entry(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert result["step_id"] == "reauth_confirm"

    with (
        patch("custom_components.woffu.api.API.connect", return_value=True),
        patch("custom_components.woffu.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "refreshed"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_PASSWORD] == "refreshed"


async def test_options_flow_sets_scan_interval(hass: HomeAssistant) -> None:
    """The Configure button must open and store the scan interval."""
    entry = mock_entry(hass)

    with patch("custom_components.woffu.async_setup_entry", return_value=True):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 30}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 30


async def test_unload_entry_unloads_all_platforms(hass: HomeAssistant) -> None:
    """Unloading an entry delegates to all configured platforms."""
    entry = mock_entry(hass)
    unload_platforms = AsyncMock(return_value=True)
    hass.config_entries.async_unload_platforms = unload_platforms

    assert await async_unload_entry(hass, entry) is True

    unload_platforms.assert_awaited_once_with(entry, PLATFORMS)
