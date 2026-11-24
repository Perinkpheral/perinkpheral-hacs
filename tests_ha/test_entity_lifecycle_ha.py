# SPDX-License-Identifier: MIT
"""Task 4 of the round-2 plan: an entity used on the first screen goes through
valid -> changed -> unknown -> unavailable -> removed, and after every step BOTH
the HTTP view and the screen sensor are read and compared with the exact expected
representation - never "any well-formed answer is fine". Removal is repeated after
an options change to catch stale listeners."""
import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN)

pytestmark = pytest.mark.asyncio

SECRET = "lifecycle-secret"
PATH = "/api/perinkpheral/screen"
ENTITY = "sensor.lc"


async def loaded_entry(hass, screens):
    from unittest.mock import patch
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock = MockConfigEntry(domain=DOMAIN, title="Desk",
                           data={CONF_DEVICE: "192.0.2.10", "url": "http://ha.local",
                                 "layout": "hero", CONF_SECRET: SECRET},
                           options={CONF_SCREENS: screens})
    mock.add_to_hass(hass)

    async def no_device(hass, device, *, discovery=False):
        from custom_components.perinkpheral.device import DeviceError
        raise DeviceError("cannot_connect")

    async def no_push(hass, device, url, secret):
        from custom_components.perinkpheral.device import DeviceError
        raise DeviceError("cannot_connect")

    with patch("custom_components.perinkpheral.get_hostname", side_effect=no_device), \
         patch("custom_components.perinkpheral.push_settings", side_effect=no_push):
        assert await hass.config_entries.async_setup(mock.entry_id)
        await hass.async_block_till_done()
    return mock


async def both_readings(hass, client):
    """The HTTP view's line and the sensor's screen attribute, as one pair."""
    response = await client.get(PATH, headers={"Authorization": "Bearer " + SECRET})
    assert response.status == 200
    http_lines = (await response.text()).splitlines()
    sensor = hass.states.get("sensor.desk")
    assert sensor is not None
    return http_lines[-1], sensor.attributes["screen"].splitlines()[-1], sensor.state


async def test_value_changes_reach_view_and_sensor_exactly(hass, hass_client_no_auth):
    screen = {CONF_LAYOUT: "single", "value_entity": ENTITY, "value_label": "LC"}
    hass.states.async_set(ENTITY, "21.5", {"unit_of_measurement": "°C"})
    await loaded_entry(hass, [screen])
    client = await hass_client_no_auth()

    # Initial valid reading.
    expected = "item|LC||21.5°"
    http_line, sensor_line, sensor_state = await both_readings(hass, client)
    assert http_line == expected and sensor_line == expected
    assert sensor_state == "ok"

    # A changed value replaces the old one in both.
    hass.states.async_set(ENTITY, "19.0", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    expected = "item|LC||19°"
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == expected and sensor_line == expected

    # unknown shows the nothing mark, not the previous number.
    hass.states.async_set(ENTITY, "unknown", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    expected = "item|LC||--"
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == expected and sensor_line == expected

    # unavailable likewise.
    hass.states.async_set(ENTITY, "unavailable", {"unit_of_measurement": "°C"})
    await hass.async_block_till_done()
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == expected and sensor_line == expected

    # Removed: the same nothing, no exception, no stale value.
    hass.states.async_remove(ENTITY)
    await hass.async_block_till_done()
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == expected and sensor_line == expected

    # And it recovers when the entity comes back.
    hass.states.async_set(ENTITY, "5", {})
    await hass.async_block_till_done()
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == "item|LC||5" and sensor_line == "item|LC||5"


async def test_removal_after_an_options_change_uses_the_new_listener(hass, hass_client_no_auth):
    """The screen is re-pointed at a second entity through the real options flow;
    removing the FIRST entity must not disturb the screen, and removing the second
    must show the nothing mark - proving the listener follows the options."""
    first = {CONF_LAYOUT: "single", "value_entity": "sensor.lc_a", "value_label": "A"}
    hass.states.async_set("sensor.lc_a", "1", {})
    mock = await loaded_entry(hass, [dict(first)])
    client = await hass_client_no_auth()

    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == "item|A||1" and sensor_line == "item|A||1"

    # Re-point the screen at sensor.lc_b through the real options flow.
    hass.states.async_set("sensor.lc_b", "2", {})
    result = await hass.config_entries.options.async_init(mock.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "screen_1"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "edit"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_LAYOUT: "single"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"value_entity": "sensor.lc_b", "value_label": "B"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # The screen now shows B; removing A changes nothing.
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == "item|B||2" and sensor_line == "item|B||2"
    hass.states.async_remove("sensor.lc_a")
    await hass.async_block_till_done()
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == "item|B||2" and sensor_line == "item|B||2"

    # Updates to the new entity must reach both consumers after re-pointing.
    for value, expected in (("3", "3"), ("unknown", "--"), ("unavailable", "--")):
        hass.states.async_set("sensor.lc_b", value, {})
        await hass.async_block_till_done()
        http_line, sensor_line, _ = await both_readings(hass, client)
        assert http_line == f"item|B||{expected}" and sensor_line == http_line

    # Removing B shows the nothing mark in both readings.
    hass.states.async_remove("sensor.lc_b")
    await hass.async_block_till_done()
    http_line, sensor_line, _ = await both_readings(hass, client)
    assert http_line == "item|B||--" and sensor_line == "item|B||--"
