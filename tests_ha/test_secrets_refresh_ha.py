# SPDX-License-Identifier: MIT
"""Task 6 of the round-2 plan: enabled and disabled entries carry DIFFERENT
secrets, a disabled entry's secret is refused and its sentinel values never
appear in any answer; the refresh button's error paths are exercised against an
owned local fake display, checking the reported reason, the request method, body
and order - with zero real network access."""
import pytest
from aiohttp import web
from homeassistant.exceptions import HomeAssistantError

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, CONF_URL, DOMAIN)

pytestmark = pytest.mark.asyncio

PATH = "/api/perinkpheral/screen"
ENABLED_SECRET = "enabled-secret-1"
DISABLED_SECRET = "disabled-secret-2"
GOOD_STATUS = {"hostname": "perink-7c4d", "firmware": "0.9.1", "mode": "application",
               "supported_abis": ["riscv32imc"]}


def screen(label, entity):
    return {CONF_LAYOUT: "single", "value_entity": entity, "value_label": label}


def make_entry(hass, secret, screens, *, device="192.0.2.10", unique_id="perink-7c4d.local.",
               disabled_by=None, title="Desk"):
    from homeassistant.config_entries import ConfigEntryDisabler
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    if disabled_by is not None:
        disabled_by = ConfigEntryDisabler(disabled_by)
    return MockConfigEntry(domain=DOMAIN, title=title,
                           data={CONF_DEVICE: device, CONF_URL: "http://ha.example.test",
                                 "layout": "hero", CONF_SECRET: secret},
                           options={CONF_SCREENS: screens},
                           unique_id=unique_id, disabled_by=disabled_by)


async def setup_quietly(hass, mock):
    """Set the entry up with the device calls intercepted, so nothing reaches a
    network - the fake display tests below use the real local server instead."""
    from unittest.mock import patch

    async def hostname(hass, device, *, discovery=False):
        return "perink-7c4d"

    async def no_push(hass, device, url, secret):
        return None

    mock.add_to_hass(hass)
    with patch("custom_components.perinkpheral.get_hostname", side_effect=hostname), \
         patch("custom_components.perinkpheral.push_settings", side_effect=no_push):
        assert await hass.config_entries.async_setup(mock.entry_id)
        await hass.async_block_till_done()


async def test_disabled_entry_secret_is_refused_and_its_values_never_appear(
        hass, hass_client_no_auth):
    """Two entries, two DIFFERENT secrets: only the enabled one answers, and no
    answer carries the disabled screen's sentinel."""
    hass.states.async_set("sensor.enabled_only", "11", {})
    hass.states.async_set("sensor.disabled_only", "22", {})
    enabled = make_entry(hass, ENABLED_SECRET, [screen("ENABLEDSENTINEL", "sensor.enabled_only")])
    disabled = make_entry(hass, DISABLED_SECRET, [screen("DISABLEDSENTINEL", "sensor.disabled_only")],
                          disabled_by="user")
    disabled.add_to_hass(hass)
    await setup_quietly(hass, enabled)
    client = await hass_client_no_auth()

    async def get(secret):
        headers = {} if secret is None else {"Authorization": "Bearer " + secret}
        response = await client.get(PATH, headers=headers)
        return response.status, await response.text()

    status, body = await get(None)
    assert status == 401 and "DISABLEDSENTINEL" not in body and "ENABLEDSENTINEL" not in body
    status, body = await get("wrong-secret")
    assert status == 401 and "DISABLEDSENTINEL" not in body
    # The disabled entry's own secret: refused, and it leaks nothing of that screen.
    status, body = await get(DISABLED_SECRET)
    assert status == 401
    assert "DISABLEDSENTINEL" not in body and "22" not in body
    # The enabled entry's secret: its own screen, and nothing of the disabled one.
    status, body = await get(ENABLED_SECRET)
    assert status == 200
    assert "ENABLEDSENTINEL" in body and "11" in body
    assert "DISABLEDSENTINEL" not in body and "sensor.disabled_only" not in body


async def test_only_a_disabled_entry_means_no_secret_answers(hass, hass_client_no_auth):
    """An entry is paired, then disabled at runtime: from that moment even its own
    correct secret is refused - no enabled entry answers it any more."""
    only = make_entry(hass, DISABLED_SECRET, [screen("SOLO", "sensor.solo")])
    await setup_quietly(hass, only)
    client = await hass_client_no_auth()
    response = await client.get(PATH, headers={"Authorization": "Bearer " + DISABLED_SECRET})
    assert response.status == 200  # while enabled, its own secret answers
    from homeassistant.config_entries import ConfigEntryDisabler
    only.disabled_by = ConfigEntryDisabler.USER  # what disabling does to the entry
    await hass.async_block_till_done()
    response = await client.get(PATH, headers={"Authorization": "Bearer " + DISABLED_SECRET})
    assert response.status == 401
    assert "SOLO" not in await response.text()


@pytest.fixture
async def display(socket_enabled, unused_tcp_port):
    """The owned fake display: records every request's method, path and body."""
    state = {"status_json": dict(GOOD_STATUS), "post_status": 200, "requests": []}

    async def status(request):
        state["requests"].append(("GET", request.path, None))
        return web.json_response(state["status_json"])

    async def settings(request):
        body = await request.json()
        state["requests"].append(("POST", request.path, body))
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


async def test_refresh_against_the_fake_display_orders_and_bodies(hass, display):
    """A paired entry: the press reaches the fake display as GET /api/status then
    POST /api/apps/settings with exactly this entry's server and token."""
    mock = make_entry(hass, ENABLED_SECRET, [screen("R", "sensor.r")],
                      device=display["address"])
    mock.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock.entry_id)
    await hass.async_block_till_done()
    display["requests"].clear()  # only what the press itself does
    await hass.services.async_call("button", "press",
                                   {"entity_id": "button.desk_refresh"}, blocking=True)
    await hass.async_block_till_done()
    assert [(method, path) for method, path, _ in display["requests"]] == [
        ("GET", "/api/status"), ("POST", "/api/apps/settings")]
    body = display["requests"][1][2]
    assert body == {"server": "http://ha.example.test", "token": ENABLED_SECRET}


@pytest.mark.parametrize("kind,expected_key", [
    ("not_paired", "identity_mismatch"),
    ("renamed", "identity_mismatch"),
    ("app_missing", "app_missing"),
    ("refused", "refused"),
    ("dead", "cannot_connect"),
])
async def test_refresh_reports_each_failure_distinctly(hass, display, unused_tcp_port_factory,
                                                       kind, expected_key):
    """Each failure path names its own recovery reason, and the fake display sees
    exactly the requests that path is allowed to make."""
    device = display["address"]
    unique_id = "perink-7c4d.local."
    if kind == "not_paired":
        unique_id = None
    elif kind == "renamed":
        display["status_json"] = dict(GOOD_STATUS, hostname="other-board")
    elif kind == "app_missing":
        display["post_status"] = 404
    elif kind == "refused":
        display["post_status"] = 500
    elif kind == "dead":
        device = "127.0.0.1:%d" % unused_tcp_port_factory()
    mock = make_entry(hass, ENABLED_SECRET, [screen("R", "sensor.r")],
                      device=device, unique_id=unique_id)
    mock.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock.entry_id)
    await hass.async_block_till_done()
    display["requests"].clear()
    with pytest.raises(HomeAssistantError) as caught:
        await hass.services.async_call("button", "press",
                                       {"entity_id": "button.desk_refresh"}, blocking=True)
    assert caught.value.translation_key == expected_key
    requests = display["requests"]
    if kind in ("not_paired", "dead"):
        assert requests == []
    elif kind == "renamed":
        assert requests == [("GET", "/api/status", None)]
    else:
        assert requests == [
            ("GET", "/api/status", None),
            ("POST", "/api/apps/settings", {"server": "http://ha.example.test", "token": ENABLED_SECRET}),
        ]
