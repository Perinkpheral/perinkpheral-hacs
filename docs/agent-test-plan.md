# Test plan for an unattended agent: perinkpheral-hacs

This plan is for a coding agent that works alone for one or two days. Each task is small
and stands alone. Do the tasks in order. Finish one task, write its report, then start the
next.

## Why

The tests in `tests/` run the integration against stubs of Home Assistant. Stubs do not
check what Home Assistant checks. Release 0.4.0 shipped an options menu whose step had no
method: Home Assistant refused it with `UnknownStep`, the stubs did not. This plan adds
tests that run inside a real Home Assistant.

## Rules

- Do not change `custom_components/perinkpheral/`. You may add files under
  `tests_ha/` and a `requirements_test.txt` only.
- Do not commit, push, tag or open pull requests.
- Do not contact any real Home Assistant, device or router. Everything runs locally.
- Do not fix a bug you find. Report it.
- After each task, append its report to `REPORT.md` in the report folder you were given.
  If no folder was given, use `tests_ha/REPORT.md`.

## Report format, for every finding

```
### <task number>.<finding number> <one-line title>
File: <path>:<line>
What happens: <exception with its last traceback lines / wrong result>
Expected: <what README.md or the code promises>
How to reproduce: <one command>
```

## Install the toolchain first

There is no device. Everything runs on this computer, in the simulator. Install these
before any task, and check each with the command after it:

- Git: `git --version`.
- Java 21 or later (Temurin is fine): `java -version`.
- A C compiler. For fuzzing you need clang with libFuzzer: on Linux the distribution's
  `clang` and `llvm`; on macOS Homebrew's `llvm` (Apple's clang has no libFuzzer), used as
  `$(brew --prefix llvm)/bin/clang`. Check: `clang --version`.
- wasi-sdk 34 from https://github.com/WebAssembly/wasi-sdk/releases (the archive for this
  computer's system and processor). Unpack it and `export WASI_SDK_PATH=<its folder>`.
  Check: `$WASI_SDK_PATH/bin/clang --version`.
- Python 3.12 or later: `python3 --version`.
- Node.js 22 and npm: `node --version`.
- ffmpeg: `ffmpeg -version`.
- Optional, for checks that match the Linux CI: Docker with the `gcc:14` image.

ESP-IDF is not needed: nothing here builds or flashes device firmware.

Get the repositories side by side in one folder, from https://github.com/Perinkpheral:
`perinkpheral-os`, `perinkpheral-apps`, `perinkpheral-hacs`, `perinkpheral-dev-portal`,
`perinkpheral-clion-plugin`. The tools find each other as siblings.

Then build the tools and the simulator once and run an application in it:

```sh
cd perinkpheral-os
tools/perinkpheral                        # builds the Kotlin tools on first use, prints the commands
make -C firmware/test/host test           # host tests; needs WASI_SDK_PATH
tools/perinkpheral sim-test firmware/test/sim
tools/perinkpheral sim sdk/apps/hello     # the simulator with one application; stop it with Ctrl-C
```

All four must work before Task 1. If one fails, write the exact error into the report and
stop: do not change the repository to make it pass.

## Setup

1. Make a virtual environment with the Python version Home Assistant's current release
   needs. Install `pytest-homeassistant-custom-component` pinned to the version that
   matches the Home Assistant release named in `hacs.json` or the newest stable one.
2. Write `tests_ha/conftest.py` that enables custom integrations
   (`enable_custom_integrations` fixture).
3. `python -m pytest tests_ha -q` must run, with zero tests, before you start Task 1.

## Task 1. Config flow

1. The user step with a device address that answers (mock `device.py`'s
   `get_hostname` and `push_settings`) creates an entry with a secret.
2. The same device twice is refused (`already_configured`), by address and by hostname.
3. A device that does not answer shows the error and creates nothing.
4. Zeroconf discovery of a known device updates its address and aborts.

## Task 2. Options flow: screens

Use the real `hass.config_entries.options` flow manager.

1. An entry with old flat options (no `screens` key) opens the menu with one screen; its
   places are kept after any save.
2. Every menu option and every form step can be reached and submitted: screen 1..4,
   add, edit, remove, move up, move down, the layout form, the places form for each of
   the four layouts. No `UnknownStep`, no exception.
3. The limit of four screens: `add` is not offered at four.
4. Removing the screen being edited, reordering, then reading `/api/perinkpheral/screen`
   gives the right screen.

## Task 3. The screen view

Use `hass_client_no_auth`.

1. `GET /api/perinkpheral/screen` without a secret, with a wrong secret, with the right
   one: 401, 401, 200.
2. `?page=` with 1..4, 0, 5, -1, `x`, empty: the first line is `page|n|count` with n
   clamped to 1..count, or 400 for a value that is not a number. Check what the code does
   and report any difference from README.md.
3. Entities in every state: unavailable, unknown, a number, a string, a timestamp,
   a weather entity; units; a label of 100 characters; a picture of every value in
   `const.PICTURES`. The response never exceeds `SCREEN_MAX_BYTES` and never cuts a line.

## Task 4. Sensor and button

1. The screen sensor follows the first screen and updates when an entity changes.
2. The button sends the refresh to the device (mocked) and reports each error kind with
   its own message.

## When all tasks are done

Write a short summary at the top of `REPORT.md`: findings per task, and which tests you
would keep. Then stop.
