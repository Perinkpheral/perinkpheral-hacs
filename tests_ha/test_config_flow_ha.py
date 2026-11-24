# SPDX-License-Identifier: MIT
"""Task 1 of docs/agent-test-plan.md: the config flow inside a real Home Assistant."""
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.perinkpheral.const import CONF_DEVICE, CONF_SECRET, DOMAIN

pytestmark = pytest.mark.asyncio

USER_INPUT = {"name": "Desk", "layout": "hero", "device": "192.0.2.10",
              "url": "http://homeassistant.local:8123"}


@contextmanager
def device_transport(hostname="perink-7c4d", error=None):
    """The device transport, as the plan says to mock it. __init__ imported the
    names into its own module, so both modules are patched."""
    async def get_hostname(hass, device, *, discovery=False):
        if error:
            raise error
        return hostname

    async def push_settings(hass, device, url, secret):
        return None

    with patch("custom_components.perinkpheral.config_flow.get_hostname", side_effect=get_hostname), \
         patch("custom_components.perinkpheral.config_flow.push_settings", side_effect=push_settings), \
         patch("custom_components.perinkpheral.get_hostname", side_effect=get_hostname), \
         patch("custom_components.perinkpheral.push_settings", side_effect=push_settings):
        yield


async def start(hass):
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})


async def add_entry(hass, device="192.0.2.10", unique_id="perink-7c4d.local."):
    """An entry as if it had been set up before, without running its setup."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, title="Desk",
                            data={CONF_DEVICE: device, "url": "http://ha.local",
                                  "layout": "hero", CONF_SECRET: "s3cret"},
                            unique_id=unique_id, options={})
    entry.add_to_hass(hass)
    return entry


async def test_user_step_creates_entry_with_secret(hass):
    with device_transport():
        result = await start(hass)
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Desk"
    assert result["data"][CONF_DEVICE] == "192.0.2.10"
    assert len(result["data"][CONF_SECRET]) >= 24


async def test_same_device_twice_refused_by_address(hass):
    with device_transport():
        first = await start(hass)
        await hass.config_entries.flow.async_configure(first["flow_id"], USER_INPUT)
        second = await start(hass)
        result = await hass.config_entries.flow.async_configure(second["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_same_device_twice_refused_by_hostname(hass):
    """The second time the same board is written by its mDNS name, not its address."""
    with device_transport():
        first = await start(hass)
        await hass.config_entries.flow.async_configure(first["flow_id"], USER_INPUT)
        second = await start(hass)
        result = await hass.config_entries.flow.async_configure(
            second["flow_id"], {**USER_INPUT, "device": "perink-7c4d.local"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_device_that_does_not_answer_shows_error(hass):
    from custom_components.perinkpheral.device import DeviceError
    with device_transport(error=DeviceError("cannot_connect")):
        result = await start(hass)
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": "cannot_connect"}
        # The flow can be finished once the device answers.
        with device_transport():
            result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_zeroconf_of_known_device_updates_address_and_aborts(hass):
    entry = await add_entry(hass, device="192.0.2.10")
    discovery = type("Zeroconf", (), {"host": "192.0.2.99", "hostname": "perink-7c4d.local.",
                                      "type": "_http._tcp.local.", "name": "perink-7c4d._http._tcp.local.",
                                      "port": 80, "properties": {}})()
    with device_transport():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=discovery)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_DEVICE] == "192.0.2.99"


def zeroconf(host="192.0.2.10", hostname="perink-9f00.local."):
    return type("Zeroconf", (), {"host": host, "hostname": hostname,
                                 "type": "_http._tcp.local.", "port": 80,
                                 "properties": {}})()


async def test_zeroconf_of_an_unknown_device_offers_the_user_step(hass):
    with device_transport():
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF},
            data=zeroconf(hostname="perink-7c4d.local."))
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    progress = [item for item in hass.config_entries.flow.async_progress(DOMAIN)
                if item["flow_id"] == result["flow_id"]][0]
    assert progress["context"]["title_placeholders"] == {"name": "perink-7c4d.local"}


async def test_zeroconf_of_a_silent_device_aborts(hass):
    from custom_components.perinkpheral.device import DeviceError
    with device_transport(error=DeviceError("cannot_connect")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=zeroconf())
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_perinkpheral"


async def test_zeroconf_whose_hostname_lies_about_itself_aborts(hass):
    """The announced name and the name the device answers with must match."""
    with device_transport(hostname="another-board"):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF},
            data=zeroconf(hostname="perink-9f00.local."))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_perinkpheral"
