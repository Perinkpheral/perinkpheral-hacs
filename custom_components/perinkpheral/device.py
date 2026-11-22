# SPDX-License-Identifier: MIT
"""Telling the display where its screen is.

HA Companion on the display takes two settings the display's page does not
show: the server and a token. This writes them for the user - this Home
Assistant's address and a secret made for this screen - so that nobody copies
a token by hand. The application asks again at once whenever its settings
are written, which is also how a change made here reaches the screen
without waiting.
"""
import asyncio

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DEVICE_APP

TIMEOUT_S = 10


class DeviceError(Exception):
    """The display did not take the settings; the text is the reason."""


async def get_hostname(hass: HomeAssistant, device: str, *, discovery: bool = False) -> str:
    """Read the board's identity, checking the firmware status format for discovery."""
    address = device if "://" in device else "http://" + device
    try:
        async with asyncio.timeout(TIMEOUT_S):
            async with async_get_clientsession(hass).get(
                    "%s/api/status" % address.rstrip("/")) as answer:
                if answer.status != 200:
                    raise DeviceError("refused")
                status = await answer.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as failure:
        raise DeviceError("cannot_connect") from failure
    hostname = status.get("hostname") if isinstance(status, dict) else None
    if not isinstance(hostname, str) or not hostname.strip():
        raise DeviceError("cannot_connect")
    # HTTP service names are editable and carry no product TXT record. Check
    # the firmware status format before offering an unfamiliar service in HA.
    if discovery and not (isinstance(status.get("firmware"), str)
                          and status["firmware"]
                          and status.get("mode") == "application"
                          and status.get("ota_protocol") == 1
                          and isinstance(status.get("supported_abis"), list)
                          and 3 in status["supported_abis"]):
        raise DeviceError("not_perinkpheral")
    return hostname.strip()


async def push_settings(hass: HomeAssistant, device: str, url: str, secret: str) -> None:
    address = device if "://" in device else "http://" + device
    try:
        async with asyncio.timeout(TIMEOUT_S):
            async with async_get_clientsession(hass).post(
                    "%s/api/apps/settings?app=%s" % (address.rstrip("/"), DEVICE_APP),
                    json={"server": url.rstrip("/"), "token": secret}) as answer:
                status = answer.status
                await answer.read()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as failure:
        raise DeviceError("cannot_connect") from failure
    if status == 404:
        raise DeviceError("app_missing")
    if status != 200:
        raise DeviceError("refused")
