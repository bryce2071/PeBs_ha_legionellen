"""Gemeinsame Hilfen: Attrappen laden und ein System wie im Ausgangshaus aufbauen."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ha_attrappe  # noqa: E402

ha_attrappe.installieren()

from custom_components.legionellen import steuerung as steuerung_modul  # noqa: E402
from custom_components.legionellen.const import STANDARDWERTE  # noqa: E402

TEMP = "sensor.wp_actual_temperature_water"
KOMFORT = "number.wp_comfort_water_temperature_target"
ECO = "number.wp_eco_water_temperature_target"
HEIZT = "binary_sensor.wp_is_heating_boiler"
EVU = "binary_sensor.wp_power_off"
NACHHEIZEN = "input_boolean.warmwasser_nachheizen"
PV_GEN24 = "sensor.pv_solarnet_pv_leistung_2"
PV_PRIMO = "sensor.pv_primo_leistung_ac"
AKKU = "sensor.pv_speicher_ladezustand"
HANDY = "notify.mobile_app_handy"

OPTIONEN: dict[str, Any] = {
    **STANDARDWERTE,
    "temperatur": TEMP,
    "sollwerte": [KOMFORT, ECO],
    "heizt": HEIZT,
    "sperren": [EVU, NACHHEIZEN],
    "pv": [PV_GEN24, PV_PRIMO],
    "akku": AKKU,
    "benachrichtigen": [HANDY],
}

SPEICHER_SCHLUESSEL = "legionellen.eintrag1"


def utc(wert: datetime) -> str:
    return wert.astimezone(ha_attrappe.UTC).isoformat()


def ortszeit(tag: int, stunde: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, tag, stunde, minute, tzinfo=ha_attrappe.ZEITZONE)


@pytest.fixture(autouse=True)
def _zuruecksetzen(monkeypatch: pytest.MonkeyPatch) -> None:
    ha_attrappe.Store.daten.clear()
    ha_attrappe.UHR.stellen(ortszeit(23, 9))
    monkeypatch.setattr(steuerung_modul, "PRUEF_INTERVALL_S", 0)


def haus() -> ha_attrappe.FakeHass:
    """Zustände wie im Ausgangssystem am Morgen des 23.11.2026."""
    hass = ha_attrappe.FakeHass()
    setzen = hass.states.setzen
    zahl_attr = {"min": 10, "max": 60, "step": 0.1, "unit_of_measurement": "°C"}
    setzen(TEMP, "45.6", {"device_class": "temperature", "unit_of_measurement": "°C", "friendly_name": "WP WW Temp. jetzt"})
    setzen(KOMFORT, "45.0", {**zahl_attr, "friendly_name": "WP WW Temp. Ziel Komfort"})
    setzen(ECO, "41.0", {**zahl_attr, "friendly_name": "WP WW Temp. Ziel Eco"})
    setzen(HEIZT, "off", {}, geaendert=ha_attrappe.UHR.utcnow() - timedelta(hours=2))
    setzen(EVU, "off", {})
    setzen(NACHHEIZEN, "off", {})
    setzen(PV_GEN24, "0.0", {"unit_of_measurement": "kW", "device_class": "power"})
    setzen(PV_PRIMO, "unavailable", {"unit_of_measurement": "kW", "device_class": "power"})
    setzen(AKKU, "6.6", {"unit_of_measurement": "%", "device_class": "battery"})
    return hass


async def laufen_lassen(runden: int = 20) -> None:
    for _ in range(runden):
        await asyncio.sleep(0)


async def einrichten(
    hass: ha_attrappe.FakeHass,
    optionen: dict[str, Any] | None = None,
    gespeichert: dict[str, Any] | None = None,
) -> ha_attrappe.ConfigEntry:
    """Integration wie Home Assistant einrichten und starten."""
    from custom_components import legionellen  # noqa: PLC0415

    if gespeichert is not None:
        ha_attrappe.Store.daten[SPEICHER_SCHLUESSEL] = gespeichert
    entry = ha_attrappe.ConfigEntry(hass, dict(optionen or OPTIONEN))
    hass.config_entries.liste.append(entry)
    assert await legionellen.async_setup_entry(hass, entry) is True
    await laufen_lassen()
    return entry


def minuten(hass: ha_attrappe.FakeHass, anzahl: int) -> None:
    """Uhr minutenweise vorstellen und jeweils den Minutentakt auslösen."""
    for _ in range(anzahl):
        ha_attrappe.UHR.vor(minutes=1)
        hass.minute()
