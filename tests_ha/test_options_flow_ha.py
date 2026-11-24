# SPDX-License-Identifier: MIT
"""Task 2 of docs/agent-test-plan.md: every options screen, through the real
Home Assistant options flow manager. Release 0.4.0 shipped a menu step with no
method and Home Assistant answered UnknownStep; the stubs did not."""
import pytest

from homeassistant.data_entry_flow import FlowResultType

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN, MAX_SCREENS)

pytestmark = pytest.mark.asyncio

HERO = {CONF_LAYOUT: "hero", "hero_entity": "sensor.a", "detail_1_entity": "sensor.b"}
TILES = {CONF_LAYOUT: "tiles", "tile_1_entity": "sensor.c"}


def entry_with_options(hass, options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, title="Desk",
                            data={CONF_DEVICE: "192.0.2.10", "url": "http://ha.local",
                                  "layout": "hero", CONF_SECRET: "s3cret"},
                            options=options)
    entry.add_to_hass(hass)
    return entry


async def open_options(hass, entry):
    return await hass.config_entries.options.async_init(entry.entry_id)


async def submit(hass, result, user_input=None):
    return await hass.config_entries.options.async_configure(result["flow_id"], user_input)


async def test_legacy_flat_options_open_menu_and_keep_places(hass):
    """An entry made before the list form: the menu shows one screen, and a save
    keeps every place of the old flat screen."""
    flat = {CONF_LAYOUT: "tiles", "tile_1_entity": "sensor.old", "tile_1_label": "Old"}
    entry = entry_with_options(hass, flat)
    result = await open_options(hass, entry)
    assert result["type"] is FlowResultType.MENU
    assert list(result["menu_options"]) == ["screen_1", "add"]
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "screen"
    result = await submit(hass, result, {"next_step_id": "edit"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "edit"
    result = await submit(hass, result, {CONF_LAYOUT: "tiles"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "places"
    result = await submit(hass, result, {"tile_1_entity": "sensor.old", "tile_1_label": "Old"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    screens = entry.options[CONF_SCREENS]
    assert screens[0]["tile_1_entity"] == "sensor.old"
    assert screens[0]["tile_1_label"] == "Old"


async def test_every_step_reachable_and_submittable(hass):
    """Menu option and form step for: screen 1..4, add, edit, remove, move up,
    move down, the layout form, the places form of each of the four layouts.
    No UnknownStep, no exception."""
    screens = [dict(HERO), dict(TILES), {CONF_LAYOUT: "single", "value_entity": "sensor.d"},
               {CONF_LAYOUT: "list", "row_1_entity": "sensor.e"}]
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(s) for s in screens]})
    result = await open_options(hass, entry)
    # At four screens the menu offers screen_1..4 and no add.
    assert list(result["menu_options"]) == [
        "screen_1", "screen_2", "screen_3", "screen_4"]
    for number in range(1, MAX_SCREENS + 1):
        result = await submit(hass, result, {"next_step_id": "screen_%d" % number})
        assert result["step_id"] == "screen"
        # Each screen's own menu: edit, and remove/move where allowed.
        offered = list(result["menu_options"])
        assert "edit" in offered and "remove" in offered
        assert ("move_up" in offered) == (number > 1)
        assert ("move_down" in offered) == (number < MAX_SCREENS)
        result = await submit(hass, result, {"next_step_id": "edit"})
        result = await submit(hass, result, {CONF_LAYOUT: screens[number - 1][CONF_LAYOUT]})
        assert result["step_id"] == "places"
        result = await submit(hass, result, {})  # clear the places, keep the layout
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert entry.options[CONF_SCREENS][number - 1][CONF_LAYOUT] == screens[number - 1][CONF_LAYOUT]
        result = await open_options(hass, entry)


async def test_screen_menu_description_carries_the_number(hass):
    """v0.4.4: the frontend fills placeholders into a menu's description, not its
    title - the screen's menu says "Screen <n> of <count>" through the real flow
    manager, and no menu title is left with an unfilled brace."""
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(HERO), dict(TILES), dict(TILES)]})
    result = await open_options(hass, entry)
    for number in range(1, 4):
        result = await submit(hass, result, {"next_step_id": "screen_%d" % number})
        assert result["step_id"] == "screen"
        placeholders = result["description_placeholders"]
        assert placeholders["number"] == str(number)
        # "of <count>" counts this display's screens, not the maximum.
        assert placeholders["count"] == str(len(entry.options[CONF_SCREENS]))
        result = await submit(hass, result, {"next_step_id": "edit"})
        assert "{" not in result.get("title_placeholders", {})
        result = await open_options(hass, entry)


async def test_add_not_offered_at_four(hass):
    screens = [dict(HERO) for _ in range(MAX_SCREENS)]
    entry = entry_with_options(hass, {CONF_SCREENS: screens})
    result = await open_options(hass, entry)
    assert "add" not in list(result["menu_options"])


async def test_add_reaches_four_through_the_form(hass):
    """add is refused once the fourth screen exists, even mid-flow."""
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(HERO)]})
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "add"})
    result = await submit(hass, result, {CONF_LAYOUT: "single"})
    result = await submit(hass, result, {"value_entity": "sensor.x"})
    assert len(entry.options[CONF_SCREENS]) == 2
    # Fill to four, then try add again.
    for _ in range(2):
        result = await open_options(hass, entry)
        result = await submit(hass, result, {"next_step_id": "add"})
        result = await submit(hass, result, {CONF_LAYOUT: "single"})
        result = await submit(hass, result, {"value_entity": "sensor.y"})
    assert len(entry.options[CONF_SCREENS]) == MAX_SCREENS
    result = await open_options(hass, entry)
    assert "add" not in list(result["menu_options"])


async def loaded_entry_with(hass, screens):
    """An entry whose integration is really set up, so the screen view answers."""
    from unittest.mock import patch
    mock = entry_with_options(hass, {CONF_SCREENS: screens})

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


async def test_remove_edit_reorder_then_read_back(hass, hass_client_no_auth):
    """Task 5 of round 2: after EACH options operation the affected pages are GET
    over HTTP and compared with the exact page|n|count header and entity value -
    removal of the edited screen, move up and move down, both directions."""
    screens = [{CONF_LAYOUT: "single", "value_entity": "sensor.%s" % name,
                "value_label": name.upper()}
               for name in ("one", "two", "three")]
    for name, value in (("one", "1"), ("two", "2"), ("three", "3")):
        hass.states.async_set("sensor." + name, value, {})
    entry = await loaded_entry_with(hass, [dict(s) for s in screens])
    client = await hass_client_no_auth()

    async def page(number):
        response = await client.get(
            "/api/perinkpheral/screen?page=%d" % number,
            headers={"Authorization": "Bearer s3cret"})
        assert response.status == 200
        return (await response.text()).splitlines()

    # The starting order, read back.
    lines = await page(2)
    assert lines[0] == "page|2|3" and lines[-1] == "item|TWO||2"

    # Remove the screen being edited (screen 2): the pages shift, count drops.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_2"})
    result = await submit(hass, result, {"next_step_id": "remove"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    lines = await page(1)
    assert lines[0] == "page|1|2" and lines[-1] == "item|ONE||1"
    lines = await page(2)
    assert lines[0] == "page|2|2" and lines[-1] == "item|THREE||3"

    # Move screen 2 (three) up: it becomes page 1, one becomes page 2.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_2"})
    result = await submit(hass, result, {"next_step_id": "move_up"})
    lines = await page(1)
    assert lines[0] == "page|1|2" and lines[-1] == "item|THREE||3"
    lines = await page(2)
    assert lines[0] == "page|2|2" and lines[-1] == "item|ONE||1"

    # Move screen 1 (three) down: the other direction, back to one, three.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    assert "move_down" in list(result["menu_options"])
    result = await submit(hass, result, {"next_step_id": "move_down"})
    lines = await page(1)
    assert lines[0] == "page|1|2" and lines[-1] == "item|ONE||1"
    lines = await page(2)
    assert lines[0] == "page|2|2" and lines[-1] == "item|THREE||3"

    # The last screen cannot move down; the pages stay exactly as read.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_2"})
    assert "move_down" not in list(result["menu_options"])
    lines = await page(2)
    assert lines[0] == "page|2|2" and lines[-1] == "item|THREE||3"

    # README: pages clamp to the ends; a page that is not a number is refused.
    for asked, actual in [("0", 1), ("9", 2), ("-3", 1)]:
        response = await client.get(
            "/api/perinkpheral/screen?page=%s" % asked,
            headers={"Authorization": "Bearer s3cret"})
        assert response.status == 200, asked
        assert (await response.text()).splitlines()[0] == "page|%d|2" % actual, asked
    for bad in ["x", ""]:
        response = await client.get(
            "/api/perinkpheral/screen?page=%s" % bad,
            headers={"Authorization": "Bearer s3cret"})
        assert response.status == 400, bad


async def test_places_form_keeps_other_layouts_settings(hass):
    """What was put into the places of another layout is kept when this one saves."""
    screen = {CONF_LAYOUT: "hero", "hero_entity": "sensor.h", "tile_1_entity": "sensor.t"}
    entry = entry_with_options(hass, {CONF_SCREENS: [screen]})
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    result = await submit(hass, result, {"next_step_id": "edit"})
    result = await submit(hass, result, {CONF_LAYOUT: "tiles"})
    result = await submit(hass, result, {"tile_1_entity": "sensor.new"})
    saved = entry.options[CONF_SCREENS][0]
    assert saved["tile_1_entity"] == "sensor.new"
    assert saved["hero_entity"] == "sensor.h"  # the hero place survived the tiles save
