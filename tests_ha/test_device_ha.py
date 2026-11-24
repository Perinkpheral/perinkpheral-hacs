# SPDX-License-Identifier: MIT
"""device.py against a local HTTP server standing in for the display: every
answer kind it meets - a good status, a wrong one, a refusal, a missing app,
a port that nothing listens on. The plan forbids touching a real device;
127.0.0.1 is not one."""
import pytest
from aiohttp import web

from custom_components.perinkpheral.device import DeviceError, get_hostname, push_settings

pytestmark = pytest.mark.asyncio

GOOD_STATUS = {"hostname": "perink-7c4d", "firmware": "0.9.1", "mode": "application",
               "supported_abis": ["riscv32imc"]}


@pytest.fixture
async def display(socket_enabled, unused_tcp_port):
    """A stand-in display on 127.0.0.1; the test sets `display.state`."""
    state = {"status": 200, "json": dict(GOOD_STATUS), "post_status": 200}

    async def status(request):
        return web.json_response(state["json"], status=state["status"])

    async def settings(request):
        body = await request.json()
        state["pushed"] = (request.query.get("app"), body)
        return web.json_response({"ok": True}, status=state["post_status"])

    app = web.Application()
    app.router.add_get("/api/status", status)
    app.router.add_post("/api/apps/settings", settings)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", unused_tcp_port)
    await site.start()
    state["address"] = "127.0.0.1:%d" % unused_tcp_port
    yield state
    await runner.cleanup()


async def test_get_hostname_reads_the_name(hass, display):
    assert await get_hostname(hass, display["address"]) == "perink-7c4d"


async def test_get_hostname_discovery_checks_the_firmware_format(hass, display):
    """A service that answers but is not a display must not be offered."""
    display["json"] = {"hostname": "printer"}
    assert await get_hostname(hass, display["address"]) == "printer"  # not discovery: no check
    with pytest.raises(DeviceError) as caught:
        await get_hostname(hass, display["address"], discovery=True)
    assert str(caught.value) == "not_perinkpheral"
    display["json"] = dict(GOOD_STATUS)
    assert await get_hostname(hass, display["address"], discovery=True) == "perink-7c4d"


async def test_get_hostname_refused_and_dead(hass, display):
    display["status"] = 403
    with pytest.raises(DeviceError) as caught:
        await get_hostname(hass, display["address"])
    assert str(caught.value) == "refused"
    with pytest.raises(DeviceError) as caught:
        await get_hostname(hass, "127.0.0.1:1")  # nothing listens there
    assert str(caught.value) == "cannot_connect"


async def test_get_hostname_broken_body(hass, display):
    display["json"] = {"hostname": "   "}
    with pytest.raises(DeviceError) as caught:
        await get_hostname(hass, display["address"])
    assert str(caught.value) == "cannot_connect"


async def test_push_settings_writes_and_checks_the_answer(hass, display):
    await push_settings(hass, display["address"], "http://ha.local/", "sec")
    assert display["pushed"] == ("ha", {"server": "http://ha.local", "token": "sec"})
    display["post_status"] = 404
    with pytest.raises(DeviceError) as caught:
        await push_settings(hass, display["address"], "http://ha.local", "sec")
    assert str(caught.value) == "app_missing"
    display["post_status"] = 500
    with pytest.raises(DeviceError) as caught:
        await push_settings(hass, display["address"], "http://ha.local", "sec")
    assert str(caught.value) == "refused"
    with pytest.raises(DeviceError) as caught:
        await push_settings(hass, "127.0.0.1:1", "http://ha.local", "sec")
    assert str(caught.value) == "cannot_connect"
