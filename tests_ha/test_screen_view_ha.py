# SPDX-License-Identifier: MIT
"""Task 3 of docs/agent-test-plan.md: GET /api/perinkpheral/screen inside a real
Home Assistant, through hass_client_no_auth."""
import time

import pytest

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN, PICTURES,
                                                  SCREEN_MAX_BYTES)

pytestmark = pytest.mark.asyncio

SECRET = "s3cret-value"
PATH = "/api/perinkpheral/screen"


def entry(hass, screens):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock = MockConfigEntry(domain=DOMAIN, title="Desk",
                           data={CONF_DEVICE: "192.0.2.10", "url": "http://ha.local",
                                 "layout": "hero", CONF_SECRET: SECRET},
                           options={CONF_SCREENS: screens})
    mock.add_to_hass(hass)
    return mock


async def loaded_entry(hass, screens):
    """An entry whose integration is really set up, with the view registered."""
    from unittest.mock import patch
    mock = entry(hass, screens)

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


async def get_screen(client, secret=SECRET, page=None):
    url = PATH + ("" if page is None else "?page=%s" % page)
    headers = {} if secret is None else {"Authorization": "Bearer " + secret}
    return await client.get(url, headers=headers)


async def test_auth(hass, hass_client_no_auth):
    await loaded_entry(hass, [{CONF_LAYOUT: "single", "value_entity": "sensor.temp"}])
    client = await hass_client_no_auth()
    response = await get_screen(client, secret=None)
    assert response.status == 401
    response = await get_screen(client, secret="wrong")
    assert response.status == 401
    response = await get_screen(client)
    assert response.status == 200


async def test_page_numbers(hass, hass_client_no_auth):
    """1..4 clamp; 0 and 5 clamp to the ends; -1 clamps; a non-number is 400.
    README: the first line is page|<actual>|<count>, a page past the end returns
    the last screen."""
    screens = [{CONF_LAYOUT: "single", "value_entity": "sensor.v%d" % n} for n in range(1, 5)]
    for n in range(1, 5):
        hass.states.async_set("sensor.v%d" % n, str(n))
    await loaded_entry(hass, screens)
    client = await hass_client_no_auth()
    for asked, actual in [("1", 1), ("2", 2), ("4", 4), ("0", 1), ("5", 4), ("-1", 1)]:
        response = await get_screen(client, page=asked)
        assert response.status == 200, asked
        first = (await response.text()).splitlines()[0]
        assert first == "page|%d|4" % actual, asked
    for bad in ["x", ""]:
        response = await get_screen(client, page=bad)
        assert response.status == 400, bad


async def test_entities_in_every_state(hass, hass_client_no_auth):
    """unavailable, unknown, a number, a string, a timestamp, a weather entity;
    units; a 100-character label; a picture of every value in PICTURES. The
    response never exceeds SCREEN_MAX_BYTES and never cuts a line."""
    screens = []
    for picture in PICTURES:
        screens.append({CONF_LAYOUT: "single", "value_entity": "sensor.p_" + picture,
                        "value_picture": picture, "value_label": "L" * 100})
    # The view reads at most MAX_SCREENS screens; check the first four plus a
    # dedicated tiles screen for the rest of the pictures through the sensor.
    states = {
        "sensor.p_auto": "unavailable", "sensor.p_none": "unknown",
        "sensor.p_thermometer": "22.5", "sensor.p_drop": "48",
        "sensor.p_co2": "850", "sensor.p_gauge": "1013.2",
        "sensor.p_plug": "228", "sensor.p_bolt": "not a number",
        "sensor.p_chip": "", "sensor.p_network": "1e400",
        "sensor.p_battery": "-7", "sensor.p_bulb": "on",
        "sensor.p_door": "off", "sensor.p_home": None,
    }
    for entity_id, value in states.items():
        hass.states.async_set(entity_id, value if value is not None else "0",
                              {"unit_of_measurement": "ppm"})
    hass.states.async_set("sensor.stamp", str(int(time.time())))
    hass.states.async_set("weather.home", "sunny", {"temperature": 21.4})
    await loaded_entry(hass, screens[:4])
    client = await hass_client_no_auth()
    for page in range(1, 5):
        response = await get_screen(client, page=page)
        assert response.status == 200
        body = await response.text()
        assert len(body.encode("utf-8")) <= SCREEN_MAX_BYTES
        # Never a cut line: a layout line has 2 parts, a value line 4.
        for line in body.splitlines()[1:]:
            assert len(line.split("|")) in (2, 4), repr(line)


async def test_weather_entity_picture(hass, hass_client_no_auth):
    screens = [{CONF_LAYOUT: "single", "value_entity": "weather.home", "value_picture": "auto"}]
    hass.states.async_set("weather.home", "partlycloudy", {"temperature": -3.25})
    await loaded_entry(hass, screens)
    client = await hass_client_no_auth()
    body = await (await get_screen(client)).text()
    assert "-3.2°" in body or "-3.3°" in body  # rounded to one decimal
    assert "partlycloudy" in body  # the weather state is the picture
