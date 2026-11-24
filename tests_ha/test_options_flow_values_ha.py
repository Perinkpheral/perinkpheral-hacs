# SPDX-License-Identifier: MIT
"""Task 2 of the round-2 plan: after EVERY submitted options-flow form, assert the
exact entry/options values, that unrelated layout settings survive, and cover
add/edit/remove per screen - driving the real hass.config_entries.options manager."""
import pytest

from homeassistant.data_entry_flow import FlowResultType

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN, MAX_SCREENS,
                                                  PICTURE_AUTO, SLOTS)

pytestmark = pytest.mark.asyncio


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


async def edit_to_places(hass, entry, screen_number, layout):
    """init -> screen_N -> edit -> layout form submitted; returns the places result."""
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_%d" % screen_number})
    result = await submit(hass, result, {"next_step_id": "edit"})
    assert result["step_id"] == "edit"
    result = await submit(hass, result, {CONF_LAYOUT: layout})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "places"
    return result


async def test_each_layout_form_saves_exactly_what_was_submitted(hass):
    """For every layout: submit a full places form, then assert the saved screen
    holds exactly those entity/label/unit/picture values and nothing else of this
    layout's slots."""
    cases = {
        # hero has no label/unit; detail slots have no label; columns have all.
        "hero": {"hero_entity": "sensor.h", "detail_1_entity": "sensor.d1",
                 "detail_1_unit": "lx", "detail_2_entity": "sensor.d2",
                 "column_1_entity": "sensor.c1", "column_1_unit": "%"},
        "tiles": {"tile_1_entity": "sensor.t1", "tile_1_label": "T1",
                  "tile_1_picture": "thermometer", "tile_2_entity": "sensor.t2"},
        "single": {"value_entity": "sensor.v", "value_label": "Only",
                   "value_unit": "W", "value_picture": "bolt"},
        "list": {"row_1_entity": "sensor.r1", "row_1_label": "R1",
                 "row_2_entity": "sensor.r2", "row_2_unit": "h"},
    }
    for layout, submitted in cases.items():
        entry = entry_with_options(hass, {CONF_SCREENS: [{CONF_LAYOUT: "single",
                                                          "value_entity": "sensor.old"}]})
        result = await edit_to_places(hass, entry, 1, layout)
        result = await submit(hass, result, submitted)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        screen = entry.options[CONF_SCREENS][0]
        assert screen[CONF_LAYOUT] == layout
        for key, value in submitted.items():
            assert screen[key] == value, (layout, key)
        # A slot that was not submitted holds nothing of this layout, except the
        # picture select's schema default on layouts that show it.
        for slot in SLOTS[layout]:
            for suffix in ("entity", "label", "unit", "picture"):
                key = "%s_%s" % (slot, suffix)
                if key in submitted:
                    continue
                if suffix == "picture" and layout != "list":
                    assert screen.get(key) == PICTURE_AUTO, (layout, key)
                else:
                    assert key not in screen, (layout, key)
        # The entry's pairing data is untouched by an options save.
        assert entry.data[CONF_SECRET] == "s3cret"


async def test_switching_layout_keeps_the_other_layouts_places(hass):
    """hero places survive a round trip through tiles and back; tiles' own slots
    are gone while hero's are kept."""
    hero = {CONF_LAYOUT: "hero", "hero_entity": "sensor.h", "detail_1_entity": "sensor.d"}
    entry = entry_with_options(hass, {CONF_SCREENS: [hero]})
    result = await edit_to_places(hass, entry, 1, "tiles")
    result = await submit(hass, result, {"tile_1_entity": "sensor.t", "tile_1_label": "T"})
    screen = entry.options[CONF_SCREENS][0]
    assert screen[CONF_LAYOUT] == "tiles"
    assert screen["tile_1_entity"] == "sensor.t"
    # The other layout's places are kept in the screen while it is not shown -
    # the strings promise: "kept for when it is chosen again".
    assert screen["hero_entity"] == "sensor.h"
    assert screen["detail_1_entity"] == "sensor.d"
    result = await edit_to_places(hass, entry, 1, "hero")
    result = await submit(hass, result, {"hero_entity": "sensor.h2",
                                         "detail_1_entity": "sensor.d"})
    screen = entry.options[CONF_SCREENS][0]
    assert screen[CONF_LAYOUT] == "hero"
    assert screen["hero_entity"] == "sensor.h2"  # the new submission replaced it
    assert screen["detail_1_entity"] == "sensor.d"
    assert screen["tile_1_entity"] == "sensor.t"  # tiles' places survived the trip


async def test_add_then_edit_then_remove_each_save_exact_state(hass):
    """add appends exactly the submitted screen; edit replaces exactly its slots;
    remove drops exactly that screen - asserted after each CREATE_ENTRY."""
    first = {CONF_LAYOUT: "single", "value_entity": "sensor.one", "value_label": "One"}
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(first)]})

    # add: the new screen appears last with exactly what was submitted.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "add"})
    result = await submit(hass, result, {CONF_LAYOUT: "list"})
    assert result["step_id"] == "places"
    result = await submit(hass, result, {"row_1_entity": "sensor.a", "row_1_label": "A"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    screens = entry.options[CONF_SCREENS]
    assert len(screens) == 2
    assert screens[0] == first  # untouched
    assert screens[1][CONF_LAYOUT] == "list"
    assert screens[1]["row_1_entity"] == "sensor.a"
    assert screens[1]["row_1_label"] == "A"

    # edit screen 2's places: exactly the submitted slots, the old row_1_label gone.
    result = await edit_to_places(hass, entry, 2, "list")
    result = await submit(hass, result, {"row_2_entity": "sensor.b"})
    screens = entry.options[CONF_SCREENS]
    assert screens[1] == {CONF_LAYOUT: "list", "row_2_entity": "sensor.b"}

    # remove screen 1: exactly it is gone, screen 2 keeps its exact state.
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    result = await submit(hass, result, {"next_step_id": "remove"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCREENS] == [{CONF_LAYOUT: "list", "row_2_entity": "sensor.b"}]


async def test_last_screen_cannot_be_removed(hass):
    """With one screen the menu offers no remove and the saved state is unchanged."""
    only = {CONF_LAYOUT: "single", "value_entity": "sensor.only"}
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(only)]})
    result = await open_options(hass, entry)
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    assert "remove" not in list(result["menu_options"])
    assert entry.options[CONF_SCREENS] == [only]


async def test_add_is_refused_at_four_mid_flow(hass):
    """Four screens: init offers no add, and the real flow manager rejects an
    add the frontend could not offer; the screens stay exactly as they were."""
    from homeassistant.data_entry_flow import InvalidData
    screens = [{CONF_LAYOUT: "single", "value_entity": "sensor.s%d" % n}
               for n in range(1, MAX_SCREENS + 1)]
    entry = entry_with_options(hass, {CONF_SCREENS: [dict(s) for s in screens]})
    result = await open_options(hass, entry)
    assert "add" not in list(result["menu_options"])
    with pytest.raises(InvalidData):
        await submit(hass, result, {"next_step_id": "add"})
    assert entry.options[CONF_SCREENS] == screens


async def test_flat_options_migrate_then_edit_saves_the_migrated_shape(hass):
    """Old flat options become one screen; editing it saves the migrated shape with
    exactly the new submission."""
    flat = {CONF_LAYOUT: "tiles", "tile_1_entity": "sensor.old", "tile_1_label": "Old"}
    entry = entry_with_options(hass, flat)
    result = await open_options(hass, entry)
    assert list(result["menu_options"]) == ["screen_1", "add"]
    result = await submit(hass, result, {"next_step_id": "screen_1"})
    result = await submit(hass, result, {"next_step_id": "edit"})
    result = await submit(hass, result, {CONF_LAYOUT: "tiles"})
    result = await submit(hass, result, {"tile_1_entity": "sensor.new",
                                         "tile_2_entity": "sensor.two",
                                         "tile_2_label": "Two"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    screens = entry.options[CONF_SCREENS]
    assert len(screens) == 1
    assert screens[0][CONF_LAYOUT] == "tiles"
    assert screens[0]["tile_1_entity"] == "sensor.new"
    assert screens[0]["tile_2_entity"] == "sensor.two"
    assert screens[0]["tile_2_label"] == "Two"
    assert "tile_1_label" not in screens[0]
