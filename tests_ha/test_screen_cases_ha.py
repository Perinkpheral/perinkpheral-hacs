# SPDX-License-Identifier: MIT
"""Task 3 of the round-2 plan: EVERY declared case is served through the registered
integration view (batches of at most four screens, one entry per batch), and every
served line is compared against the exact expected line derived from the rendering
contract in render.py - not against separators or a byte length."""
import pytest

from custom_components.perinkpheral.const import (CONF_DEVICE, CONF_LAYOUT, CONF_SCREENS,
                                                  CONF_SECRET, DOMAIN, MAX_SCREENS,
                                                  NAME_MAX, PICTURE_AUTO, PICTURES,
                                                  SCREEN_MAX_BYTES)

pytestmark = pytest.mark.asyncio

PATH = "/api/perinkpheral/screen"
LONG_LABEL = "L" * 100


class Case:
    """One declared case: the entity to set, the screen to put it on, and the exact
    line the view must answer (single layout: item|name|picture|value)."""

    def __init__(self, case_id, entity_id, state, attributes, options, expected):
        self.case_id = case_id
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes
        self.screen = {CONF_LAYOUT: "single", "value_entity": entity_id}
        self.screen.update(options)
        self.expected = expected


def cases():
    out = []
    add = out.append
    # States and their visible representation.
    add(Case("unavailable", "sensor.t_unavail", "unavailable", {},
             {"value_label": "Un"}, "item|Un||--"))
    add(Case("unknown", "sensor.t_unknown", "unknown", {},
             {"value_label": "Unk"}, "item|Unk||--"))
    add(Case("empty", "sensor.t_empty", "", {},
             {"value_label": "E"}, "item|E||--"))
    add(Case("temp", "sensor.t_temp", "22.5", {"unit_of_measurement": "°C"},
             {"value_label": "T"}, "item|T||22.5°"))
    add(Case("humidity", "sensor.t_hum", "48", {"unit_of_measurement": "%"},
             {"value_label": "H"}, "item|H||48%"))
    add(Case("pressure", "sensor.t_press", "1013.2", {"unit_of_measurement": "hPa"},
             {"value_label": "P"}, "item|P||1013hPa"))
    add(Case("string", "sensor.t_str", "not a number", {},
             {"value_label": "S"}, "item|S||not a number"))
    add(Case("inf", "sensor.t_inf", "1e400", {"unit_of_measurement": "%"},
             {"value_label": "I"}, "item|I||--"))
    add(Case("negative", "sensor.t_neg", "-7", {},
             {"value_label": "N"}, "item|N||-7"))
    add(Case("on", "sensor.t_on", "on", {},
             {"value_label": "O"}, "item|O||on"))
    add(Case("timestamp", "sensor.t_stamp", "1764000000", {},
             {"value_label": "TS"}, "item|TS||1764000000"))
    # Weather: the value is the temperature attribute, the picture the state name.
    add(Case("weather", "weather.home", "sunny", {"temperature": 21.4},
             {"value_label": "W"}, "item|W|sunny|21.4°"))
    add(Case("weather_no_temp", "weather.b", "cloudy", {},
             {"value_label": "WB"}, "item|WB|cloudy|--"))
    add(Case("weather_bad_temp", "weather.c", "rainy", {"temperature": "abc"},
             {"value_label": "WC"}, "item|WC|rainy|--"))
    # Names: pipe becomes a slash, control characters become spaces, 100 becomes 23.
    add(Case("label_pipe", "sensor.t_pipe", "5", {},
             {"value_label": "A|B"}, "item|A/B||5"))
    add(Case("label_control", "sensor.t_ctrl", "6", {},
             {"value_label": "A\x01B"}, "item|A B||6"))
    add(Case("label_long", "sensor.t_long", "7", {},
             {"value_label": LONG_LABEL}, "item|" + "L" * NAME_MAX + "||7"))
    add(Case("friendly_name", "sensor.t_friend", "9", {"friendly_name": "Датчик"},
             {}, "item|Датчик||9"))
    add(Case("derived_name", "sensor.some_temp", "10", {},
             {}, "item|Some temp||10"))
    add(Case("missing_entity", "sensor.gone", None, {},
             {"value_label": "M"}, "item|M||--"))
    # Units: "-" means none, a chosen unit replaces the entity's, eight at most.
    add(Case("unit_dash", "sensor.t_udash", "48", {"unit_of_measurement": "%"},
             {"value_label": "UD", "value_unit": "-"}, "item|UD||48"))
    add(Case("unit_chosen", "sensor.t_uch", "48", {"unit_of_measurement": "%"},
             {"value_label": "UC", "value_unit": "м/с"}, "item|UC||48м/с"))
    add(Case("unit_long", "sensor.t_ulong", "48", {"unit_of_measurement": "%"},
             {"value_label": "UL", "value_unit": "0123456789"}, "item|UL||4801234567"))
    # Every picture the integration offers, chosen explicitly.
    for picture in PICTURES:
        # "none" draws nothing; "auto" on a plain sensor with no class or known
        # domain also draws nothing; every other name is drawn as chosen.
        shown = "" if picture in ("none", PICTURE_AUTO) else picture
        add(Case("pic_" + picture, "sensor.p_" + picture, "5", {},
                 {"value_label": "P_" + picture, "value_picture": picture},
                 "item|P_%s|%s|5" % (picture, shown)))
    # auto: by device class, by domain, and nothing when neither matches.
    add(Case("pic_auto_class", "sensor.t_aclass", "20", {"device_class": "temperature"},
             {"value_label": "AC", "value_picture": "auto"}, "item|AC|thermometer|20"))
    add(Case("pic_auto_light", "light.kitchen", "on", {},
             {"value_label": "AL", "value_picture": "auto"}, "item|AL|bulb|on"))
    add(Case("pic_auto_plain", "sensor.t_aplain", "3", {},
             {"value_label": "AP", "value_picture": "auto"}, "item|AP||3"))
    return out


def entry_with_secret(hass, screens, secret):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    mock = MockConfigEntry(domain=DOMAIN, title="Desk",
                           data={CONF_DEVICE: "192.0.2.10", "url": "http://ha.local",
                                 "layout": "hero", CONF_SECRET: secret},
                           options={CONF_SCREENS: screens})
    mock.add_to_hass(hass)
    return mock


async def loaded_entry_with_secret(hass, screens, secret):
    from unittest.mock import patch
    mock = entry_with_secret(hass, screens, secret)

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


async def serve_all(hass, hass_client_no_auth, all_cases, expected_of):
    """Serve every case through the view in batches of MAX_SCREENS and return the
    ledger of case ids actually served and matched."""
    client = None
    served = []
    for start in range(0, len(all_cases), MAX_SCREENS):
        batch = all_cases[start:start + MAX_SCREENS]
        secret = "sec-%03d" % start
        for case in batch:
            if case.state is not None:
                hass.states.async_set(case.entity_id, case.state, case.attributes)
        await loaded_entry_with_secret(hass, [c.screen for c in batch], secret)
        if client is None:
            # The http app exists only once the integration has registered its view.
            client = await hass_client_no_auth()
        for number, case in enumerate(batch, start=1):
            response = await client.get(
                PATH + "?page=%d" % number,
                headers={"Authorization": "Bearer " + secret})
            assert response.status == 200, case.case_id
            body = await response.text()
            assert len(body.encode("utf-8")) <= SCREEN_MAX_BYTES, case.case_id
            lines = body.splitlines()
            assert lines[0] == "page|%d|%d" % (number, len(batch)), case.case_id
            # single layout announces itself, then its one place.
            assert lines[1] == "layout|single", case.case_id
            # Whole lines only: the value line keeps its four fields.
            assert len(lines[2].split("|")) == 4, (case.case_id, repr(lines[2]))
            assert len(lines) == 3, case.case_id  # header, layout, one place
            assert lines[2] == expected_of(case), (case.case_id, lines[2])
            served.append(case.case_id)
    return served


async def test_every_declared_case_is_served_and_matches(hass, hass_client_no_auth):
    all_cases = cases()
    ledger = await serve_all(hass, hass_client_no_auth, all_cases, lambda c: c.expected)
    declared = [c.case_id for c in all_cases]
    assert ledger == declared, "cases declared but not served, or out of order"


async def test_a_wrong_expected_value_fails_the_ledger(hass, hass_client_no_auth):
    """Negative control: the same machinery with one injected wrong expectation
    must fail - a green ledger is not automatic."""
    all_cases = cases()
    wrong = dict((c.case_id, c.expected) for c in all_cases)
    wrong["temp"] = "item|T||999°"

    def expected_of(case):
        return wrong[case.case_id]

    with pytest.raises(AssertionError) as caught:
        await serve_all(hass, hass_client_no_auth, all_cases, expected_of)
    assert "temp" in str(caught.value) or "999" in str(caught.value)
