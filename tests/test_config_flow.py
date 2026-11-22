# SPDX-License-Identifier: MIT
"""Exercise the real configuration flow with an in-memory HA and device transport."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "perinkpheral"


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


class AbortFlow(Exception):
    pass


class ConfigFlow:
    entries = []

    def __init_subclass__(cls, **kwargs):
        pass

    def _async_current_entries(self):
        return self.entries

    async def async_set_unique_id(self, unique_id, **kwargs):
        self.context["unique_id"] = unique_id

    def _abort_if_unique_id_configured(self, updates=None):
        for entry in self.entries:
            if entry.unique_id == self.context.get("unique_id"):
                if updates:
                    self.hass.config_entries.async_update_entry(entry, data={**entry.data, **updates})
                raise AbortFlow("already_configured")

    def async_abort(self, reason):
        return {"type": "abort", "reason": reason}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, title, data):
        entry = types.SimpleNamespace(title=title, data=data,
                                      unique_id=self.context.get("unique_id"))
        self.entries.append(entry)
        return {"type": "create_entry", "entry": entry}


module("voluptuous", Schema=lambda fields: fields,
       Required=lambda key, **kwargs: key, Optional=lambda key, **kwargs: key)
module("homeassistant")
module("homeassistant.config_entries", ConfigEntry=object, ConfigFlow=ConfigFlow, OptionsFlow=object)
module("homeassistant.core", callback=lambda function: function, HomeAssistant=object)
module("homeassistant.helpers", selector=types.SimpleNamespace(
    TextSelector=lambda *args: None, TextSelectorConfig=lambda **kwargs: kwargs,
    TextSelectorType=types.SimpleNamespace(URL="url"),
    SelectSelector=lambda *args: None, SelectSelectorConfig=lambda **kwargs: kwargs,
    SelectSelectorMode=types.SimpleNamespace(LIST="list"),
))
module("homeassistant.helpers.network", NoURLAvailableError=RuntimeError, get_url=lambda hass, **kwargs: "")
module("perinkpheral", __path__=[str(PACKAGE)])
pushes = []
lookups = []
hostnames = {}


async def push_settings(hass, device, url, secret):
    pushes.append((device, url, secret))


async def get_hostname(hass, device):
    lookups.append(device)
    key = const.device_key(device)
    return hostnames.get(key, key.replace(":", "-"))


module("perinkpheral.device", DeviceError=RuntimeError, get_hostname=get_hostname,
       push_settings=push_settings)


def load(name):
    spec = importlib.util.spec_from_file_location("perinkpheral." + name, PACKAGE / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


const = load("const")
flow = load("config_flow")


class PairingTests(unittest.TestCase):
    def setUp(self):
        ConfigFlow.entries.clear()
        pushes.clear()
        lookups.clear()
        hostnames.clear()
        flow.push_settings = push_settings
        flow.get_hostname = get_hostname
        self.progress = []
        manager = types.SimpleNamespace(async_has_matching_flow=lambda candidate: any(
            candidate is not other and candidate.is_matching(other) for other in self.progress))
        def update(entry, **changes):
            entry.__dict__.update(changes)
        self.hass = types.SimpleNamespace(config_entries=types.SimpleNamespace(
            flow=manager, async_update_entry=update))

    def new_flow(self):
        instance = flow.PerinkpheralConfigFlow()
        instance.hass = self.hass
        instance.context = {}
        for name in ("async_step_user", "async_step_zeroconf"):
            original = getattr(instance, name)
            async def step(*args, original=original, **kwargs):
                try:
                    return await original(*args, **kwargs)
                except AbortFlow as failure:
                    return instance.async_abort(reason=str(failure))
            setattr(instance, name, step)
        self.progress.append(instance)
        return instance

    def pair(self, address):
        instance = self.new_flow()
        return asyncio.run(instance.async_step_user({
            "name": "Desk", "layout": "hero", "device": address, "url": "http://ha.example",
        }))

    def test_duplicate_forms_do_not_replace_the_secret(self):
        first = self.pair("display.local")
        self.assertEqual(first["type"], "create_entry")
        secret = pushes[0][2]
        for address in ("display.local", "DISPLAY", "http://Display.local:80/", " display.local. "):
            with self.subTest(address=address):
                self.assertEqual(self.pair(address), {"type": "abort", "reason": "already_configured"})
        self.assertEqual(len(ConfigFlow.entries), 1)
        self.assertEqual(len(pushes), 1)
        self.assertEqual(ConfigFlow.entries[0].data["secret"], secret)

    def test_different_devices_and_ports_are_not_duplicates(self):
        for address in ("display.local", "other.local", "display.local:8080"):
            self.assertEqual(self.pair(address)["type"], "create_entry")
        self.assertEqual(len(pushes), 3)

    def test_discovery_uses_the_same_identity(self):
        self.pair("http://Display.local:80/")
        instance = self.new_flow()
        result = asyncio.run(instance.async_step_zeroconf(types.SimpleNamespace(
            host="192.0.2.42", hostname="display.local.",
        )))
        self.assertEqual(result, {"type": "abort", "reason": "already_configured"})
        self.assertEqual(len(pushes), 1)
        self.assertEqual(ConfigFlow.entries[0].data["device"], "192.0.2.42")

    def test_rediscovery_updates_the_address_and_preserves_pairing(self):
        for unique_id in ("display.local.", "DISPLAY.local"):
            with self.subTest(unique_id=unique_id):
                entry = types.SimpleNamespace(unique_id=unique_id, data={
                    "device": "192.0.2.1", "secret": "keep", "url": "http://ha", "layout": "hero",
                })
                ConfigFlow.entries[:] = [entry]
                result = asyncio.run(self.new_flow().async_step_zeroconf(types.SimpleNamespace(
                    host="192.0.2.42", hostname="display.local.",
                )))
                self.assertEqual(result, {"type": "abort", "reason": "already_configured"})
                self.assertEqual(entry.data, {
                    "device": "192.0.2.42", "secret": "keep", "url": "http://ha", "layout": "hero",
                })
        self.assertEqual(pushes, [])

    def test_discovery_updates_legacy_manual_entry(self):
        for address in ("display.local", "192.0.2.42"):
            with self.subTest(address=address):
                entry = types.SimpleNamespace(unique_id=None, data={"device": address, "secret": "keep"})
                ConfigFlow.entries[:] = [entry]
                result = asyncio.run(self.new_flow().async_step_zeroconf(types.SimpleNamespace(
                    host="192.0.2.42", hostname="display.local.",
                )))
                self.assertEqual(result["type"], "abort")
                self.assertEqual(entry.data, {"device": "192.0.2.42", "secret": "keep"})
                self.assertEqual(entry.unique_id, "display.local.")

    def test_reused_ip_does_not_rebind_an_identified_display(self):
        entry = types.SimpleNamespace(unique_id="first.local.", data={
            "device": "192.0.2.42", "secret": "keep", "url": "http://ha", "layout": "hero",
        })
        ConfigFlow.entries.append(entry)
        original = entry.data.copy()
        result = asyncio.run(self.new_flow().async_step_zeroconf(types.SimpleNamespace(
            host="192.0.2.42", hostname="second.local.",
        )))
        self.assertEqual(result["type"], "form")
        self.assertEqual(entry.unique_id, "first.local.")
        self.assertEqual(entry.data, original)
        result = asyncio.run(self.new_flow().async_step_zeroconf(types.SimpleNamespace(
            host="192.0.2.43", hostname="first.local.",
        )))
        self.assertEqual(result, {"type": "abort", "reason": "already_configured"})
        self.assertEqual(entry.unique_id, "first.local.")
        self.assertEqual(entry.data, {**original, "device": "192.0.2.43"})
        self.assertEqual(pushes, [])
        self.assertEqual(lookups, [])

    def test_new_discovery_shows_the_address_without_pairing(self):
        result = asyncio.run(self.new_flow().async_step_zeroconf(types.SimpleNamespace(
            host="192.0.2.42", hostname="display.local.",
        )))
        self.assertEqual(result["type"], "form")
        self.assertEqual(pushes, [])
        self.assertEqual(lookups, [])

    def test_ip_and_hostname_aliases_do_not_replace_pairing(self):
        hostnames["192.0.2.42"] = "display"
        for first, second in (("192.0.2.42", "display.local"),
                              ("display.local", "192.0.2.42")):
            with self.subTest(first=first):
                ConfigFlow.entries.clear()
                self.progress.clear()
                pushes.clear()
                self.assertEqual(self.pair(first)["type"], "create_entry")
                self.assertEqual(self.pair(second), {"type": "abort", "reason": "already_configured"})
                self.assertEqual(len(pushes), 1)
                self.assertEqual(ConfigFlow.entries[0].unique_id, "display.local.")

    def test_alias_of_legacy_ip_entry_is_rejected(self):
        hostnames["192.0.2.42"] = "display"
        entry = types.SimpleNamespace(unique_id=None, data={"device": "192.0.2.42", "secret": "keep"})
        ConfigFlow.entries.append(entry)
        self.assertEqual(self.pair("display.local"), {"type": "abort", "reason": "already_configured"})
        self.assertEqual(lookups, ["display.local", "192.0.2.42"])
        self.assertEqual(pushes, [])
        self.assertEqual(entry.data["secret"], "keep")

    def test_blank_address_does_not_create_an_unpaired_entry(self):
        for device in ("", "  ", "\t"):
            with self.subTest(device=device):
                result = self.pair(device)
                self.assertEqual(result["type"], "form")
                self.assertEqual(result["errors"], {"device": "device_required"})
        self.assertEqual(ConfigFlow.entries, [])
        self.assertEqual(pushes, [])
        self.assertEqual(lookups, [])

    def test_failed_identity_lookup_does_not_send_credentials(self):
        async def unavailable(*args):
            raise flow.DeviceError("cannot_connect")
        flow.get_hostname = unavailable
        result = self.pair("display")
        self.assertEqual(result["errors"], {"base": "cannot_connect"})
        self.assertEqual(ConfigFlow.entries, [])
        self.assertEqual(pushes, [])

    def test_failed_legacy_lookup_does_not_block_a_new_display(self):
        for reason in ("cannot_connect", "refused"):
            with self.subTest(reason=reason):
                ConfigFlow.entries.clear()
                self.progress.clear()
                pushes.clear()
                entry = types.SimpleNamespace(
                    unique_id=None, data={"device": "192.0.2.42", "secret": "keep"})
                ConfigFlow.entries.append(entry)
                async def lookup(hass, device):
                    if device == "192.0.2.42":
                        raise flow.DeviceError(reason)
                    return "display"
                flow.get_hostname = lookup
                result = self.pair("display.local")
                self.assertEqual(result["type"], "create_entry")
                self.assertEqual(len(ConfigFlow.entries), 2)
                self.assertEqual(len(pushes), 1)
                self.assertEqual(pushes[0][0], "display.local")
                self.assertIsNone(entry.unique_id)
                self.assertEqual(entry.data, {"device": "192.0.2.42", "secret": "keep"})

    def test_legacy_lookups_run_together_and_still_detect_aliases(self):
        async def check(matching):
            addresses = ["192.0.2.41", "192.0.2.42", "192.0.2.43"]
            ConfigFlow.entries[:] = [types.SimpleNamespace(
                unique_id=None, data={"device": address, "secret": "keep"}) for address in addresses]
            started = set()
            all_started = asyncio.Event()

            async def lookup(hass, device):
                if device == "display.local":
                    return "display"
                started.add(device)
                if started == set(addresses):
                    all_started.set()
                # A serial implementation cannot start all probes before this deadline.
                await asyncio.wait_for(all_started.wait(), timeout=1)
                if device != addresses[-1]:
                    raise flow.DeviceError("cannot_connect")
                return "display" if matching else "other"

            flow.get_hostname = lookup
            result = await self.new_flow().async_step_user({
                "name": "Desk", "layout": "hero", "device": "display.local", "url": "http://ha",
            })
            self.assertEqual(started, set(addresses))
            if matching:
                self.assertEqual(result, {"type": "abort", "reason": "already_configured"})
                self.assertEqual(pushes, [])
                self.assertEqual(len(ConfigFlow.entries), 3)
            else:
                self.assertEqual(result["type"], "create_entry")
                self.assertEqual(len(pushes), 1)
                self.assertEqual(len(ConfigFlow.entries), 4)
            self.assertTrue(all(entry.data["secret"] == "keep" and entry.unique_id is None
                                for entry in ConfigFlow.entries[:3]))

        for matching in (False, True):
            with self.subTest(matching=matching):
                pushes.clear()
                self.progress.clear()
                asyncio.run(check(matching))

    def test_canceling_legacy_lookups_cancels_all_probes(self):
        async def check():
            addresses = {"192.0.2.41", "192.0.2.42"}
            ConfigFlow.entries[:] = [types.SimpleNamespace(
                unique_id=None, data={"device": address, "secret": "keep"}) for address in addresses]
            started, canceled = set(), set()
            all_started = asyncio.Event()

            async def lookup(hass, device):
                if device == "display.local":
                    return "display"
                started.add(device)
                if started == addresses:
                    all_started.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    canceled.add(device)

            flow.get_hostname = lookup
            instance = self.new_flow()
            task = asyncio.create_task(instance.async_step_user({
                "name": "Desk", "layout": "hero", "device": "display.local", "url": "http://ha",
            }))
            try:
                await asyncio.wait_for(all_started.wait(), timeout=1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(canceled, addresses)
            self.assertEqual(instance._pairing_device, "")
            self.assertEqual(pushes, [])
            self.assertEqual(len(ConfigFlow.entries), 2)

        asyncio.run(check())

    def test_concurrent_pairing_writes_one_secret(self):
        async def check():
            entered, release = asyncio.Event(), asyncio.Event()

            async def delayed_push(hass, device, url, secret):
                await push_settings(hass, device, url, secret)
                entered.set()
                await release.wait()

            flow.push_settings = delayed_push
            hostnames["192.0.2.42"] = "display"
            request = {"name": "Desk", "layout": "hero", "device": "display.local", "url": "http://ha"}
            first = self.new_flow()
            task = asyncio.create_task(first.async_step_user(request))
            await entered.wait()
            second = await self.new_flow().async_step_user({**request, "device": "192.0.2.42"})
            self.assertEqual(second, {"type": "abort", "reason": "already_configured"})
            self.assertEqual(len(pushes), 1)
            release.set()
            self.assertEqual((await task)["type"], "create_entry")
            self.assertEqual(len(ConfigFlow.entries), 1)
            self.assertEqual(ConfigFlow.entries[0].data["secret"], pushes[0][2])

        asyncio.run(check())

    def test_success_reserves_address_until_entry_is_registered(self):
        async def check():
            request = {"name": "Desk", "layout": "hero", "device": "display", "url": "http://ha"}
            first = self.new_flow()
            # HA's flow manager registers the entry after the step returns.
            first.async_create_entry = lambda **kwargs: {"type": "create_entry", **kwargs}
            result = await first.async_step_user(request)
            self.assertEqual(result["type"], "create_entry")
            self.assertEqual(ConfigFlow.entries, [])
            hostnames["192.0.2.42"] = "display"
            second = await self.new_flow().async_step_user({**request, "device": "192.0.2.42"})
            self.assertEqual(second["type"], "abort")
            self.assertEqual(len(pushes), 1)

        asyncio.run(check())

    def test_failed_pairing_releases_address_for_retry(self):
        async def check():
            request = {"name": "Desk", "layout": "hero", "device": "display", "url": "http://ha"}
            async def refused(*args):
                raise flow.DeviceError("cannot_connect")
            flow.push_settings = refused
            first = self.new_flow()
            result = await first.async_step_user(request)
            self.assertEqual(result["type"], "form")
            self.assertEqual(result["errors"], {"base": "cannot_connect"})
            self.assertEqual(first._pairing_device, "")
            flow.push_settings = push_settings
            self.assertEqual((await self.new_flow().async_step_user(request))["type"], "create_entry")
            self.assertEqual(len(pushes), 1)

        asyncio.run(check())

    def test_canceled_pairing_releases_address_for_retry(self):
        async def check():
            entered = asyncio.Event()
            async def delayed_push(*args):
                entered.set()
                await asyncio.Event().wait()
            flow.push_settings = delayed_push
            request = {"name": "Desk", "layout": "hero", "device": "display", "url": "http://ha"}
            first = self.new_flow()
            task = asyncio.create_task(first.async_step_user(request))
            await entered.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(first._pairing_device, "")
            flow.push_settings = push_settings
            self.assertEqual((await self.new_flow().async_step_user(request))["type"], "create_entry")
            self.assertEqual(len(pushes), 1)

        asyncio.run(check())

    def test_invalid_address_is_left_for_transport_validation(self):
        self.assertEqual(const.device_key("http://["), "http://[")
        self.assertEqual(const.device_key("display:bad"), "display:bad")


class Response:
    def __init__(self, *, text="", status=200, **kwargs):
        self.text, self.status = text, status


module("aiohttp", ClientError=type("ClientError", (Exception,), {}),
       web=types.SimpleNamespace(Request=object, Response=Response))
module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: hass.session)
module("homeassistant.components")
module("homeassistant.components.http", HomeAssistantView=object)
device = load("device")
load("render")
view = load("view")


class IdentityTransportTests(unittest.TestCase):
    def lookup(self, address, *, status=200, payload=None, failure=None):
        class Answer:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def json(self):
                if failure:
                    raise failure
                return payload

        answer = Answer()
        answer.status = status
        calls = []
        def get(url):
            calls.append(url)
            return answer
        hass = types.SimpleNamespace(session=types.SimpleNamespace(get=get))
        result = asyncio.run(device.get_hostname(hass, address))
        return result, calls

    def test_reads_canonical_hostname_using_the_given_address(self):
        for address, url in (("192.0.2.42", "http://192.0.2.42/api/status"),
                             ("https://display.local:8443/", "https://display.local:8443/api/status")):
            with self.subTest(address=address):
                result, calls = self.lookup(address, payload={"hostname": "display"})
                self.assertEqual(result, "display")
                self.assertEqual(calls, [url])

    def test_missing_or_invalid_identity_is_rejected(self):
        for payload in (None, [], {}, {"hostname": ""}, {"hostname": "  "}, {"hostname": 42}):
            with self.subTest(payload=payload):
                with self.assertRaisesRegex(device.DeviceError, "cannot_connect"):
                    self.lookup("display", payload=payload)

    def test_refused_status_is_reported(self):
        for status in (404, 500):
            with self.subTest(status=status):
                with self.assertRaisesRegex(device.DeviceError, "refused"):
                    self.lookup("display", status=status)

    def test_unreadable_or_interrupted_status_is_reported(self):
        for failure in (ValueError("invalid JSON"), OSError("offline"), asyncio.TimeoutError(),
                        sys.modules["aiohttp"].ClientError()):
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaisesRegex(device.DeviceError, "cannot_connect"):
                    self.lookup("display", failure=failure)


class ScreenViewTests(unittest.TestCase):
    def setUp(self):
        self.entry = types.SimpleNamespace(disabled_by=None, data={"secret": "paired", "layout": "hero"},
                                           options={"hero_entity": "sensor.room"})
        self.reads = []
        self.state = types.SimpleNamespace(entity_id="sensor.room", state="22.5", attributes={})
        def get(entity_id):
            self.reads.append(entity_id)
            return self.state
        hass = types.SimpleNamespace(
            config_entries=types.SimpleNamespace(async_entries=lambda domain: [self.entry]),
            states=types.SimpleNamespace(get=get))
        self.view = view.ScreenView(hass)

    def request(self, authorization="Bearer paired"):
        return asyncio.run(self.view.get(types.SimpleNamespace(headers={"Authorization": authorization})))

    def test_disabled_entry_cannot_read_live_entity_data(self):
        for disabled_by in ("user", "integration"):
            with self.subTest(disabled_by=disabled_by):
                self.entry.disabled_by = disabled_by
                self.assertEqual(self.request().status, 401)
        self.assertEqual(self.reads, [])

    def test_enabled_and_reenabled_entry_returns_the_current_screen(self):
        self.assertEqual(self.request().text, "hero|22.5|")
        self.entry.disabled_by = "user"
        self.assertEqual(self.request().status, 401)
        self.entry.disabled_by = None
        self.state.state = "23"
        answer = self.request()
        self.assertEqual(answer.status, 200)
        self.assertEqual(answer.text, "hero|23|")
        self.assertEqual(self.reads, ["sensor.room", "sensor.room"])

    def test_unknown_or_missing_token_is_rejected(self):
        for authorization in ("", "Bearer wrong", "Basic paired"):
            with self.subTest(authorization=authorization):
                self.assertEqual(self.request(authorization).status, 401)
        self.assertEqual(self.reads, [])


if __name__ == "__main__":
    unittest.main()
