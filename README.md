<img src="https://raw.githubusercontent.com/Perinkpheral/perinkpheral-os/main/assets/mark/mark-on-paper-512.png" width="96" alt="The perINKpheral mark">

# perINKpheral for Home Assistant

Home Assistant integration for [perINKpheral](https://perinkpheral.dev).
Configures display layouts and entities for the HA Companion application.

[Device setup](https://perinkpheral.dev/setup) -
[Application catalog](https://github.com/perinkpheral/perinkpheral-apps/tree/main/catalog).

## Installation

Requires Home Assistant, HACS and HA Companion (`ha`) installed from the device's catalog.

1. Add this repository to HACS as an integration and download it.
2. Restart Home Assistant, then add perINKpheral under Settings - Devices & services.
3. Set the display address and the Home Assistant origin reachable from the display,
   such as `http://homeassistant.local:8123`. Do not include a dashboard path, query
   or fragment.
4. Open the integration options to manage up to four screens. Select a screen to
   edit its layout and entities, remove it, or move it up or down. Add screen creates
   another screen with its own layout. At least one screen is kept.

[![Add the repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Perinkpheral&repository=perinkpheral-hacs&category=integration)
[![Add the integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=perinkpheral)

The integration writes only `server` and `token` to HA Companion. The display
fetches its screen from Home Assistant. A sensor exposes the screen text in
Home Assistant; a refresh button requests an update on the display.

Displays are identified by the hostname reported by the firmware, which follows
the device name. Give each display a distinct name. After renaming a display,
remove its old integration entry and pair it again. The firmware
status API currently provides no stable device ID across renames.

Discovery accepts custom display names. For an unfamiliar HTTP service it checks
the firmware status format before offering setup. A paired display's hostname
announcement updates its address after a DHCP change. Before writing settings,
the integration checks that the address still reports the paired hostname.
Older entries without a saved hostname must be rediscovered or paired again
before settings can be sent.

[HA Companion's reference](https://github.com/perinkpheral/perinkpheral-apps/blob/main/apps/ha/README.md)
describes the screen format rendered by this integration.

HA Companion requests `/api/perinkpheral/screen?page=<n>` (1-based, default 1).
The reply starts with `page|<actual>|<count>`, with up to four screens; a page past
the end returns the last screen, one below 1 the first, and a page that is not a number
is refused with 400. Only that screen's entities are read. Existing
applications ignore the new line. The text sensor continues to expose screen 1
without the page line. Replies, including the header, fit in 512 UTF-8 bytes.

Screen settings are stored in `entry.options["screens"]` as a list of dictionaries,
each containing `layout` and its place settings. Older flat options are read as one
screen and converted to the list form when options are next saved, retaining
settings from other layouts. On the display, UP and DOWN wrap between screens;
OK refreshes the current screen. Holding UP or DOWN scrolls a list.
Application code belongs in [perinkpheral-apps](https://github.com/perinkpheral/perinkpheral-apps);
this repository owns the Home Assistant component. The device API is documented in
[the firmware repository](https://github.com/Perinkpheral/perinkpheral-os/blob/main/docs/api/openapi.yaml).

## Development

Rendering and pairing tests require Python 3.11 or later and run without Home Assistant.
The integration tests require Python 3.13 and run in a local Home Assistant
instance, with a fake display on loopback; they require the dependencies below.

```sh
python3 tests/test_render.py
python3 tests/test_config_flow.py
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/python -m pytest tests_ha -q
```

- `custom_components/perinkpheral/` - integration, configuration flow and screen rendering.
- `tests/` - rendering and pairing tests.
- `tests_ha/` - Home Assistant flow, HTTP view and device integration tests.
- `hacs.json` - HACS package configuration.

CI runs rendering, pairing and Home Assistant integration tests, hassfest and HACS validation on every push.
Each successful push to `main` releases `perinkpheral.zip` for HACS.

## License

[MIT](LICENSE).
