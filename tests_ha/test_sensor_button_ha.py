# SPDX-License-Identifier: MIT
"""Task 4 of docs/agent-test-plan.md: the screen sensor and the refresh button."""
from unittest.mock import patch

import pytest

from homeassistant.exceptions import HomeAssistantError

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN)

pytestmark = pytest.mark.asyncio

SECRET = "s3cret-value"


async def loaded_entry(hass, screens, device="192.0.2.10", unique_id="perink-7c4d.local."):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock = MockConfigEntry(domain=DOMAIN, title="Desk",
                           data={CONF_DEVICE: device, "url": "http://ha.local",
                                 "layout": "hero", CONF_SECRET: SECRET},
                           options={CONF_SCREENS: screens}, unique_id=unique_id)
    mock.add_to_hass(hass)

    async def hostname(hass, device, *, discovery=False):
        return "perink-7c4d"

    async def push(hass, device, url, secret):
        return None

    with patch("custom_components.perinkpheral.get_hostname", side_effect=hostname), \
         patch("custom_components.perinkpheral.push_settings", side_effect=push):
        assert await hass.config_entries.async_setup(mock.entry_id)
        await hass.async_block_till_done()
    return mock


async def test_sensor_follows_first_screen_and_updates(hass):
    hass.states.async_set("sensor.first", "11")
    hass.states.async_set("sensor.second", "22")
    # Two screens: the sensor must show the first one only, without the page line.
    await loaded_entry(hass, [
        {CONF_LAYOUT: "single", "value_entity": "sensor.first"},
        {CONF_LAYOUT: "single", "value_entity": "sensor.second"},
    ])
    state = hass.states.get("sensor.desk")
    assert state is not None
    assert "page|" not in state.attributes["screen"]
    assert "11" in state.attributes["screen"]
    assert "22" not in state.attributes["screen"]
    assert state.state == "ok"
    hass.states.async_set("sensor.first", "99")
    await hass.async_block_till_done()
    assert "99" in hass.states.get("sensor.desk").attributes["screen"]


async def test_button_sends_the_refresh(hass):
    pushed = []

    async def push(hass, device, url, secret):
        pushed.append((device, url, secret))

    async def hostname(hass, device, *, discovery=False):
        return "perink-7c4d"

    with patch("custom_components.perinkpheral.push_settings", side_effect=push), \
         patch("custom_components.perinkpheral.get_hostname", side_effect=hostname):
        await loaded_entry(hass, [{CONF_LAYOUT: "single", "value_entity": "sensor.a"}])
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.desk_refresh"}, blocking=True)
        await hass.async_block_till_done()
        assert ("192.0.2.10", "http://ha.local", SECRET) in pushed
        presses = len(pushed)
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.desk_refresh"}, blocking=True)
        await hass.async_block_till_done()
        assert len(pushed) == presses + 1  # every press reaches the device


@pytest.mark.parametrize("reason,expected", [
    ("cannot_connect", "cannot_connect"),
    ("identity_mismatch", "identity_mismatch"),
    ("identity_missing", "identity_mismatch"),
    ("app_missing", "app_missing"),
    ("refused", "refused"),
    ("something else", "cannot_connect"),
])
async def test_button_reports_each_error_kind(hass, reason, expected):
    from custom_components.perinkpheral.device import DeviceError

    async def hostname(hass, device, *, discovery=False):
        if reason == "identity_missing":
            raise DeviceError("identity_missing")
        if reason == "identity_mismatch":
            return "other-board"
        return "perink-7c4d"

    async def push(hass, device, url, secret):
        if reason in ("app_missing", "refused", "cannot_connect", "something else"):
            raise DeviceError(reason)

    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock = MockConfigEntry(domain=DOMAIN, title="Desk",
                           data={CONF_DEVICE: "192.0.2.10", "url": "http://ha.local",
                                 "layout": "hero", CONF_SECRET: SECRET},
                           options={CONF_SCREENS: [{CONF_LAYOUT: "single", "value_entity": "sensor.a"}]},
                           unique_id="perink-7c4d.local.")
    mock.add_to_hass(hass)
    with patch("custom_components.perinkpheral.get_hostname", side_effect=hostname), \
         patch("custom_components.perinkpheral.push_settings", side_effect=push):
        assert await hass.config_entries.async_setup(mock.entry_id)
        await hass.async_block_till_done()
        with pytest.raises(HomeAssistantError) as caught:
            await hass.services.async_call("button", "press",
                                           {"entity_id": "button.desk_refresh"}, blocking=True)
    assert expected in str(caught.value.translation_key or caught.value)


async def test_button_absent_without_a_device(hass):
    await loaded_entry(hass, [{CONF_LAYOUT: "single", "value_entity": "sensor.a"}], device="")
    assert hass.states.get("button.desk_refresh") is None
