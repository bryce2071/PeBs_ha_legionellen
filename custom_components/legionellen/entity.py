"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.entity import Entity

from .steuerung import LegionellenSteuerung


class LegionellenEntitaet(Entity):
    """Entität, die ihren Zustand aus der Steuerung liest."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, steuerung: LegionellenSteuerung, schluessel: str) -> None:
        """Entität einem Speicher zuordnen."""
        self._steuerung = steuerung
        self._attr_unique_id = f"{steuerung.entry.entry_id}_{schluessel}"
        self._attr_device_info = steuerung.device_info

    async def async_added_to_hass(self) -> None:
        """Bei Änderungen der Steuerung neu schreiben."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._steuerung.async_zuhoerer_hinzufuegen(self.async_write_ha_state)
        )

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """Umbenennen der Entitäts-ID braucht hier nichts weiter (ab HA 2026.11)."""
        super().async_entity_id_changed(old_entity_id)  # type: ignore[misc]
