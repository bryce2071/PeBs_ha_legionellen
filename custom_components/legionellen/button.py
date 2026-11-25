"""Tasten zum Starten und Abbrechen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

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
    """Tasten anlegen."""
    steuerung = entry.runtime_data
    async_add_entities([JetztAufheizenTaste(steuerung), AbbrechenTaste(steuerung)])


class JetztAufheizenTaste(LegionellenEntitaet, ButtonEntity):
    """Startet die Aufheizung sofort, auch bei ausgeschalteter Automatik."""

    _attr_translation_key = "jetzt_aufheizen"

    def __init__(self, steuerung: LegionellenSteuerung) -> None:
        """Taste anlegen."""
        super().__init__(steuerung, "jetzt_aufheizen")

    async def async_press(self) -> None:
        """Aufheizung starten."""
        await self._steuerung.async_von_hand_starten()


class AbbrechenTaste(LegionellenEntitaet, ButtonEntity):
    """Bricht eine laufende Aufheizung ab und stellt die Sollwerte zurück."""

    _attr_translation_key = "abbrechen"

    def __init__(self, steuerung: LegionellenSteuerung) -> None:
        """Taste anlegen."""
        super().__init__(steuerung, "abbrechen")

    async def async_press(self) -> None:
        """Aufheizung abbrechen."""
        await self._steuerung.async_abbrechen()
