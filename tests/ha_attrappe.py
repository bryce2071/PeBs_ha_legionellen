"""Attrappen der benötigten Home-Assistant-Schnittstellen für Tests ohne Home Assistant.

Nachgebildet ist nur, was die Integration nutzt – so lassen sich Ablauf,
Fehlerfälle und Einrichtungsseiten durchspielen. Ob die echte Home-Assistant-API
genau so aussieht, prüfen diese Tests nicht.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum, StrEnum
import inspect
import sys
import types
from typing import Any
from zoneinfo import ZoneInfo

ZEITZONE = ZoneInfo("Europe/Berlin")


class Uhr:
    """Von den Tests gesteuerte Uhr."""

    def __init__(self) -> None:
        self.jetzt = datetime(2026, 11, 23, 9, 0, tzinfo=ZEITZONE)

    def utcnow(self) -> datetime:
        return self.jetzt.astimezone(UTC)

    def now(self) -> datetime:
        return self.jetzt.astimezone(ZEITZONE)

    def stellen(self, wert: datetime) -> None:
        self.jetzt = wert

    def vor(self, **dauer: float) -> None:
        self.jetzt += timedelta(**dauer)


UHR = Uhr()


def _modul(name: str, **inhalt: Any) -> types.ModuleType:
    modul = sys.modules.get(name) or types.ModuleType(name)
    for schluessel, wert in inhalt.items():
        setattr(modul, schluessel, wert)
    sys.modules[name] = modul
    if "." in name:
        eltern, _, kurz = name.rpartition(".")
        setattr(_modul(eltern), kurz, modul)
    else:
        modul.__path__ = []  # type: ignore[attr-defined]
    return modul


# ---------------------------------------------------------------- voluptuous


class Invalid(Exception):
    pass


class Marker:
    def __init__(self, schema: str, default: Any = None, description: Any = None) -> None:
        self.schema = schema
        self.default = default
        self.description = description

    def __hash__(self) -> int:
        return hash(self.schema)

    def __eq__(self, anderes: object) -> bool:
        return str(anderes) == self.schema if not isinstance(anderes, Marker) else anderes.schema == self.schema

    def __str__(self) -> str:
        return self.schema


class Required(Marker):
    pass


class Optional(Marker):
    pass


class Schema:
    def __init__(self, schema: dict[Any, Any]) -> None:
        self.schema = schema

    def __call__(self, daten: Any) -> Any:
        return daten


# ---------------------------------------------------------------- core


def callback(funktion: Callable[..., Any]) -> Callable[..., Any]:
    return funktion


class CoreState(Enum):
    running = "RUNNING"
    stopping = "STOPPING"


class HomeAssistantError(Exception):
    def __init__(self, *args: Any, translation_domain: str | None = None,
                 translation_key: str | None = None,
                 translation_placeholders: dict[str, str] | None = None) -> None:
        super().__init__(*args)
        self.translation_domain = translation_domain
        self.translation_key = translation_key
        self.translation_placeholders = translation_placeholders


@dataclass
class State:
    entity_id: str
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)
    last_changed: datetime = field(default_factory=UHR.utcnow)

    @property
    def name(self) -> str:
        return self.attributes.get("friendly_name", self.entity_id)


class Zustaende:
    def __init__(self, hass: FakeHass) -> None:
        self._hass = hass
        self._werte: dict[str, State] = {}

    def get(self, entity_id: str) -> State | None:
        return self._werte.get(entity_id)

    def setzen(self, entity_id: str, wert: Any, attribute: dict[str, Any] | None = None,
               geaendert: datetime | None = None) -> None:
        alt = self._werte.get(entity_id)
        text = str(wert)
        if attribute is None:
            attribute = dict(alt.attributes) if alt else {}
        if geaendert is None:
            geaendert = UHR.utcnow() if alt is None or alt.state != text else alt.last_changed
        self._werte[entity_id] = State(entity_id, text, attribute, geaendert)
        for ids, rueckruf in list(self._hass.zustands_beobachter):
            if entity_id in ids:
                rueckruf({"entity_id": entity_id})


class Dienste:
    def __init__(self, hass: FakeHass) -> None:
        self._hass = hass
        self.aufrufe: list[tuple[str, str, dict[str, Any]]] = []
        self.fehler: dict[tuple[str, str, str | None], Exception] = {}
        self.notify = ["mobile_app_handy", "persistent_notification", "send_message"]

    async def async_call(self, domain: str, dienst: str, daten: dict[str, Any],
                         blocking: bool = False, **_: Any) -> None:
        await asyncio.sleep(0)
        self.aufrufe.append((domain, dienst, copy.deepcopy(daten)))
        eid = daten.get("entity_id")
        if (fehler := self.fehler.get((domain, dienst, eid))) is not None:
            raise fehler
        if domain in ("number", "input_number") and dienst == "set_value":
            self._hass.states.setzen(eid, float(daten["value"]))
        elif domain == "water_heater" and dienst == "set_temperature":
            zustand = self._hass.states.get(eid)
            assert zustand is not None
            self._hass.states.setzen(eid, zustand.state, {**zustand.attributes, "temperature": daten["temperature"]})
        elif domain == "notify" and dienst not in self.notify:
            raise HomeAssistantError(f"Dienst notify.{dienst} fehlt")

    def async_services(self) -> dict[str, dict[str, object]]:
        return {"notify": {name: object() for name in self.notify}, "light": {"turn_on": object()}}

    def gefiltert(self, domain: str, dienst: str | None = None) -> list[dict[str, Any]]:
        return [d for (dom, srv, d) in self.aufrufe if dom == domain and (dienst is None or srv == dienst)]


class Konfiguration:
    language = "de"
    components = {"logbook", "recorder"}


class Eintraege:
    def __init__(self) -> None:
        self.liste: list[ConfigEntry] = []

    def async_entries(self, domain: str) -> list[ConfigEntry]:
        return list(self.liste)

    async def async_forward_entry_setups(self, entry: ConfigEntry, plattformen: list[str]) -> None:
        hass = entry.hass
        for plattform in plattformen:
            modul = __import__(f"custom_components.legionellen.{plattform}", fromlist=["x"])
            neue: list[Any] = []
            await modul.async_setup_entry(hass, entry, lambda entitaeten, neue=neue: neue.extend(entitaeten))
            for entitaet in neue:
                entitaet.hass = hass
                entitaet.entity_id = f"{plattform}.legionellen_{entitaet.unique_id.split('_', 1)[1]}"
                await entitaet.async_added_to_hass()
                hass.entitaeten[entitaet.entity_id] = entitaet
                hass.registry[(plattform, entitaet.unique_id)] = entitaet.entity_id

    async def async_unload_platforms(self, entry: ConfigEntry, plattformen: list[str]) -> bool:
        hass = entry.hass
        for eid, entitaet in list(hass.entitaeten.items()):
            for rueckruf in getattr(entitaet, "_beim_entfernen", []):
                rueckruf()
            del hass.entitaeten[eid]
        return True


class FakeHass:
    def __init__(self) -> None:
        self.states = Zustaende(self)
        self.services = Dienste(self)
        self.config = Konfiguration()
        self.config_entries = Eintraege()
        self.state = CoreState.running
        self.zustands_beobachter: list[tuple[set[str], Callable[[Any], None]]] = []
        self.intervalle: list[Callable[[datetime], None]] = []
        self.aufgaben: list[asyncio.Task[Any]] = []
        self.entitaeten: dict[str, Any] = {}
        self.registry: dict[tuple[str, str], str] = {}

    def minute(self) -> None:
        """Einen Minutentakt auslösen."""
        for rueckruf in list(self.intervalle):
            rueckruf(UHR.utcnow())


def async_track_state_change_event(hass: FakeHass, ids: list[str], rueckruf: Callable[[Any], None]) -> Callable[[], None]:
    eintrag = (set(ids), rueckruf)
    hass.zustands_beobachter.append(eintrag)
    return lambda: hass.zustands_beobachter.remove(eintrag)


def async_track_time_interval(hass: FakeHass, rueckruf: Callable[[datetime], None], intervall: timedelta) -> Callable[[], None]:
    hass.intervalle.append(rueckruf)
    return lambda: hass.intervalle.remove(rueckruf)


def async_at_started(hass: FakeHass, rueckruf: Callable[[FakeHass], Any]) -> Callable[[], None]:
    ergebnis = rueckruf(hass)
    if inspect.iscoroutine(ergebnis):
        hass.aufgaben.append(asyncio.get_running_loop().create_task(ergebnis))
    return lambda: None


class Store:
    daten: dict[str, Any] = {}

    def __init__(self, hass: FakeHass, version: int, schluessel: str) -> None:
        self.schluessel = schluessel

    def __class_getitem__(cls, _: Any) -> type[Store]:
        return cls

    async def async_load(self) -> Any:
        return copy.deepcopy(Store.daten.get(self.schluessel))

    async def async_save(self, inhalt: Any) -> None:
        await asyncio.sleep(0)
        Store.daten[self.schluessel] = copy.deepcopy(inhalt)

    def async_delay_save(self, liefern: Callable[[], Any], verzoegerung: float = 0) -> None:
        Store.daten[self.schluessel] = copy.deepcopy(liefern())

    async def async_remove(self) -> None:
        Store.daten.pop(self.schluessel, None)


class ConfigEntry:
    def __init__(self, hass: FakeHass, options: dict[str, Any], *, entry_id: str = "eintrag1",
                 title: str = "Legionellen-Aufheizung") -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.title = title
        self.options = options
        self.data: dict[str, Any] = {}
        self.runtime_data: Any = None
        self.beim_entladen: list[Callable[[], Any]] = []

    def __class_getitem__(cls, _: Any) -> type[ConfigEntry]:
        return cls

    def _aufgabe(self, coro: Any) -> asyncio.Task[Any]:
        aufgabe = asyncio.Task(coro, loop=asyncio.get_running_loop(), eager_start=True)
        self.hass.aufgaben.append(aufgabe)
        return aufgabe

    def async_create_background_task(self, hass: FakeHass, coro: Any, name: str, eager_start: bool = True) -> asyncio.Task[Any]:
        return self._aufgabe(coro)

    def async_create_task(self, hass: FakeHass, coro: Any, name: str | None = None, eager_start: bool = True) -> asyncio.Task[Any]:
        return self._aufgabe(coro)

    def async_on_unload(self, funktion: Callable[[], Any]) -> None:
        self.beim_entladen.append(funktion)

    def add_update_listener(self, zuhoerer: Any) -> Callable[[], None]:
        return lambda: None


class FlowHandler:
    hass: FakeHass

    def async_show_form(self, *, step_id: str, data_schema: Any = None, errors: dict[str, str] | None = None,
                        description_placeholders: dict[str, str] | None = None, **_: Any) -> dict[str, Any]:
        return {"type": "form", "step_id": step_id, "data_schema": data_schema, "errors": errors or {},
                "description_placeholders": description_placeholders}

    def add_suggested_values_to_schema(self, schema: Schema, werte: Any) -> Schema:
        assert isinstance(schema, Schema)
        return schema

    def async_create_entry(self, *, data: Any, title: str | None = None, options: Any = None, **_: Any) -> dict[str, Any]:
        return {"type": "create_entry", "title": title, "data": data, "options": options}


class ConfigFlow(FlowHandler):
    def __init_subclass__(cls, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls.domain = domain


class OptionsFlow(FlowHandler):
    config_entry: ConfigEntry


class OptionsFlowWithReload(OptionsFlow):
    pass


# ---------------------------------------------------------------- Entitäten


class Entity:
    hass: Any = None
    entity_id: str | None = None
    entity_description: Any = None
    _attr_has_entity_name = False
    _attr_should_poll = True
    _attr_unique_id: str | None = None
    _attr_device_info: Any = None
    _attr_translation_key: str | None = None
    _attr_device_class: Any = None

    @property
    def unique_id(self) -> str | None:
        return self._attr_unique_id

    async def async_added_to_hass(self) -> None:
        pass

    def async_on_remove(self, funktion: Callable[[], None]) -> None:
        self.__dict__.setdefault("_beim_entfernen", []).append(funktion)

    def async_write_ha_state(self) -> None:
        if self.hass is None:
            raise RuntimeError("Entität ist nicht hinzugefügt")
        self.__dict__["schreibvorgaenge"] = self.__dict__.get("schreibvorgaenge", 0) + 1

    def async_entity_id_changed(self, old_entity_id: str) -> None:
        pass


@dataclass(frozen=True, kw_only=True)
class EntityDescription:
    key: str
    translation_key: str | None = None
    device_class: Any = None


@dataclass(frozen=True, kw_only=True)
class SensorEntityDescription(EntityDescription):
    options: list[str] | None = None
    native_unit_of_measurement: str | None = None
    state_class: Any = None
    suggested_display_precision: int | None = None


class SensorDeviceClass(StrEnum):
    ENUM = "enum"
    TIMESTAMP = "timestamp"
    DURATION = "duration"


class SensorStateClass(StrEnum):
    MEASUREMENT = "measurement"


class BinarySensorDeviceClass(StrEnum):
    RUNNING = "running"


class SensorEntity(Entity):
    pass


class BinarySensorEntity(Entity):
    pass


class ButtonEntity(Entity):
    pass


class SwitchEntity(Entity):
    pass


class Platform(StrEnum):
    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    SENSOR = "sensor"
    SWITCH = "switch"


class UnitOfTime(StrEnum):
    DAYS = "d"


class DeviceEntryType(StrEnum):
    SERVICE = "service"


@dataclass(kw_only=True)
class DeviceInfo:
    identifiers: set[tuple[str, str]]
    name: str
    entry_type: DeviceEntryType | None = None
    sw_version: str | None = None


class Registry:
    def __init__(self, hass: FakeHass) -> None:
        self._hass = hass

    def async_get_entity_id(self, domain: str, plattform: str, unique_id: str) -> str | None:
        return self._hass.registry.get((domain, unique_id))


# ---------------------------------------------------------------- Selektoren


class _Selektor:
    def __init__(self, konfig: Any = None) -> None:
        self.konfig = konfig or {}


class NumberSelectorMode(StrEnum):
    BOX = "box"


class SelectSelectorMode(StrEnum):
    DROPDOWN = "dropdown"


def _konfig(**werte: Any) -> dict[str, Any]:
    return dict(werte)


def installieren() -> None:
    """Attrappen als Module registrieren."""
    _modul("voluptuous", Invalid=Invalid, Required=Required, Optional=Optional, Schema=Schema, Marker=Marker)
    _modul("homeassistant")
    _modul(
        "homeassistant.const",
        Platform=Platform,
        UnitOfTime=UnitOfTime,
        ATTR_ENTITY_ID="entity_id",
        ATTR_UNIT_OF_MEASUREMENT="unit_of_measurement",
        STATE_ON="on",
        STATE_OFF="off",
        STATE_UNAVAILABLE="unavailable",
        STATE_UNKNOWN="unknown",
        CONF_NAME="name",
    )
    _modul("homeassistant.core", callback=callback, CoreState=CoreState, HomeAssistant=FakeHass, State=State)
    _modul("homeassistant.exceptions", HomeAssistantError=HomeAssistantError)
    _modul(
        "homeassistant.config_entries",
        ConfigEntry=ConfigEntry,
        ConfigFlow=ConfigFlow,
        ConfigFlowResult=dict,
        OptionsFlow=OptionsFlow,
        OptionsFlowWithReload=OptionsFlowWithReload,
    )
    _modul("homeassistant.helpers")
    _modul(
        "homeassistant.helpers.selector",
        TextSelector=_Selektor,
        EntitySelector=_Selektor,
        NumberSelector=_Selektor,
        TimeSelector=_Selektor,
        SelectSelector=_Selektor,
        EntitySelectorConfig=_konfig,
        NumberSelectorConfig=_konfig,
        SelectSelectorConfig=_konfig,
        SelectOptionDict=_konfig,
        NumberSelectorMode=NumberSelectorMode,
        SelectSelectorMode=SelectSelectorMode,
    )
    _modul("homeassistant.helpers.entity_registry", async_get=Registry)
    _modul("homeassistant.helpers.device_registry", DeviceInfo=DeviceInfo, DeviceEntryType=DeviceEntryType)
    _modul(
        "homeassistant.helpers.event",
        async_track_state_change_event=async_track_state_change_event,
        async_track_time_interval=async_track_time_interval,
    )
    _modul("homeassistant.helpers.start", async_at_started=async_at_started)
    _modul("homeassistant.helpers.storage", Store=Store)
    _modul("homeassistant.helpers.entity", Entity=Entity)
    _modul("homeassistant.helpers.entity_platform")
    _modul("homeassistant.util")
    _modul("homeassistant.util.dt", utcnow=UHR.utcnow, now=UHR.now)
    _modul("homeassistant.components")
    _modul(
        "homeassistant.components.sensor",
        SensorEntity=SensorEntity,
        SensorEntityDescription=SensorEntityDescription,
        SensorDeviceClass=SensorDeviceClass,
        SensorStateClass=SensorStateClass,
    )
    _modul(
        "homeassistant.components.binary_sensor",
        BinarySensorEntity=BinarySensorEntity,
        BinarySensorDeviceClass=BinarySensorDeviceClass,
    )
    _modul("homeassistant.components.button", ButtonEntity=ButtonEntity)
    _modul("homeassistant.components.switch", SwitchEntity=SwitchEntity)
