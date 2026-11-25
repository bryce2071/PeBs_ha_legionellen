"""Schalter für die Automatik."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

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
    """Schalter anlegen."""
    async_add_entities([AutomatikSchalter(entry.runtime_data)])


class AutomatikSchalter(LegionellenEntitaet, SwitchEntity):
    """Erlaubt oder verbietet das automatische Aufheizen."""

    _attr_translation_key = "automatik"

    def __init__(self, steuerung: LegionellenSteuerung) -> None:
        """Schalter anlegen."""
        super().__init__(steuerung, "automatik")

    @property
    def is_on(self) -> bool:
        """Ist die Automatik an?"""
        return self._steuerung.automatik

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Automatik einschalten."""
        await self._steuerung.async_automatik_setzen(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Automatik ausschalten."""
        await self._steuerung.async_automatik_setzen(False)
