"""Binärsensoren der Legionellen-Aufheizung."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity

from .entity import LegionellenEntitaet
from .steuerung import LegionellenConfigEntry, LegionellenSteuerung

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LegionellenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Binärsensoren anlegen."""
    steuerung = entry.runtime_data
    entitaeten: list[BinarySensorEntity] = [LaeuftSensor(steuerung)]
    if steuerung.pv_aktiv:
        entitaeten.append(PvUeberschussSensor(steuerung))
    async_add_entities(entitaeten)


class LaeuftSensor(LegionellenEntitaet, BinarySensorEntity):
    """An, solange eine Aufheizung läuft."""

    _attr_translation_key = "laeuft"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, steuerung: LegionellenSteuerung) -> None:
        """Sensor anlegen."""
        super().__init__(steuerung, "laeuft")

    @property
    def is_on(self) -> bool:
        """Läuft gerade eine Aufheizung?"""
        return self._steuerung.laeuft


class PvUeberschussSensor(LegionellenEntitaet, BinarySensorEntity):
    """An, wenn PV-Leistung und Akku lange genug Überschuss melden."""

    _attr_translation_key = "pv_ueberschuss"

    def __init__(self, steuerung: LegionellenSteuerung) -> None:
        """Sensor anlegen."""
        super().__init__(steuerung, "pv_ueberschuss")

    @property
    def is_on(self) -> bool:
        """Gibt es gerade PV-Überschuss?"""
        return self._steuerung.pv_ueberschuss
