"""Legionellen-Aufheizung für Warmwasser-Wärmepumpen.

Hebt den Warmwasser-Sollwert regelmäßig auf 60 °C an – bevorzugt mit
PV-Überschuss, spätestens nach einer Woche notfalls mit Netzstrom – und stellt
ihn danach wieder zurück.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .config_flow import NEU_LADEN_EINGEBAUT
from .const import DOMAIN, SPEICHER_VERSION
from .steuerung import LegionellenConfigEntry, LegionellenSteuerung

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: LegionellenConfigEntry) -> bool:
    """Speicher einrichten."""
    steuerung = LegionellenSteuerung(hass, entry)
    await steuerung.async_laden()
    entry.runtime_data = steuerung
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    steuerung.async_starten()
    if not NEU_LADEN_EINGEBAUT:
        # Ältere Home-Assistant-Versionen laden nach geänderten Optionen nicht selbst neu.
        entry.async_on_unload(entry.add_update_listener(_async_optionen_geaendert))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LegionellenConfigEntry) -> bool:
    """Speicher entladen; eine laufende Aufheizung wird zurückgestellt."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.async_stoppen()
    return True


async def async_remove_entry(hass: HomeAssistant, entry: LegionellenConfigEntry) -> None:
    """Gespeicherten Zustand löschen, wenn die Integration entfernt wird."""
    await Store(hass, SPEICHER_VERSION, f"{DOMAIN}.{entry.entry_id}").async_remove()


async def _async_optionen_geaendert(hass: HomeAssistant, entry: LegionellenConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
