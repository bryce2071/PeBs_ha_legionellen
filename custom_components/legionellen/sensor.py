"""Sensoren der Legionellen-Aufheizung."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime

from .entity import LegionellenEntitaet
from .logic import Ergebnis, Status
from .steuerung import LegionellenConfigEntry, LegionellenSteuerung

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class LegionellenSensorBeschreibung(SensorEntityDescription):
    """Beschreibt, woher ein Sensor seinen Wert nimmt."""

    wert: Callable[[LegionellenSteuerung], str | float | datetime | None]
    attribute: Callable[[LegionellenSteuerung], dict[str, Any]] | None = None


SENSOREN: tuple[LegionellenSensorBeschreibung, ...] = (
    LegionellenSensorBeschreibung(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in Status],
        wert=lambda s: s.status.value,
        attribute=lambda s: s.status_attribute,
    ),
    LegionellenSensorBeschreibung(
        key="letzte_aufheizung",
        translation_key="letzte_aufheizung",
        device_class=SensorDeviceClass.TIMESTAMP,
        wert=lambda s: s.letzte_aufheizung,
    ),
    LegionellenSensorBeschreibung(
        key="tage_seit_aufheizung",
        translation_key="tage_seit_aufheizung",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        wert=lambda s: s.tage_seit_aufheizung,
    ),
    LegionellenSensorBeschreibung(
        key="letzte_zapfung",
        translation_key="letzte_zapfung",
        device_class=SensorDeviceClass.TIMESTAMP,
        wert=lambda s: s.letzte_zapfung,
    ),
    LegionellenSensorBeschreibung(
        key="tage_ohne_zapfung",
        translation_key="tage_ohne_zapfung",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.DAYS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        wert=lambda s: s.tage_ohne_zapfung,
    ),
    LegionellenSensorBeschreibung(
        key="naechste_pflicht",
        translation_key="naechste_pflicht",
        device_class=SensorDeviceClass.TIMESTAMP,
        wert=lambda s: s.naechste_pflicht,
    ),
    LegionellenSensorBeschreibung(
        key="letzter_versuch",
        translation_key="letzter_versuch",
        device_class=SensorDeviceClass.ENUM,
        options=[ergebnis.value for ergebnis in Ergebnis],
        wert=lambda s: s.ergebnis,
        attribute=lambda s: s.ergebnis_attribute,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LegionellenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Sensoren anlegen."""
    steuerung = entry.runtime_data
    async_add_entities(LegionellenSensor(steuerung, beschreibung) for beschreibung in SENSOREN)


class LegionellenSensor(LegionellenEntitaet, SensorEntity):
    """Sensor der Legionellen-Aufheizung."""

    entity_description: LegionellenSensorBeschreibung

    def __init__(
        self, steuerung: LegionellenSteuerung, beschreibung: LegionellenSensorBeschreibung
    ) -> None:
        """Sensor nach Beschreibung anlegen."""
        super().__init__(steuerung, beschreibung.key)
        self.entity_description = beschreibung

    @property
    def native_value(self) -> str | float | datetime | None:
        """Aktueller Wert."""
        return self.entity_description.wert(self._steuerung)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Zusatzinfos."""
        if self.entity_description.attribute is None:
            return None
        return self.entity_description.attribute(self._steuerung)
