"""Abläufe der Steuerung mit Attrappen statt Home Assistant."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from conftest import (
    AKKU,
    ECO,
    EVU,
    HEIZT,
    KOMFORT,
    PV_GEN24,
    SPEICHER_SCHLUESSEL,
    TEMP,
    einrichten,
    haus,
    laufen_lassen,
    minuten,
    ortszeit,
    utc,
)
import ha_attrappe
import pytest

from custom_components import legionellen
from custom_components.legionellen.logic import Ergebnis, Status

UHR = ha_attrappe.UHR
HomeAssistantError = ha_attrappe.HomeAssistantError


def gespeichert(**extra: Any) -> dict[str, Any]:
    """Stand wie im Ausgangssystem: letzte 60-°C-Aufheizung am 3.11."""
    return {
        "automatik": True,
        "letzte_aufheizung": utc(ortszeit(3, 12)),
        "letzte_zapfung": utc(ortszeit(23, 7)),
        **extra,
    }


def sollwerte(hass: ha_attrappe.FakeHass) -> tuple[str, str]:
    return hass.states.get(KOMFORT).state, hass.states.get(ECO).state  # type: ignore[union-attr]


def gesetzt(hass: ha_attrappe.FakeHass) -> list[tuple[str, float]]:
    return [(d["entity_id"], d["value"]) for d in hass.services.gefiltert("number", "set_value")]


def speicher() -> dict[str, Any]:
    return ha_attrappe.Store.daten[SPEICHER_SCHLUESSEL]


def test_pv_aufheizung_erfolgreich() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        assert s.status is Status.FAELLIG
        assert len(hass.entitaeten) == 12

        UHR.stellen(ortszeit(23, 10))
        hass.states.setzen(PV_GEN24, "3.2")
        hass.states.setzen(AKKU, "95")
        await laufen_lassen()
        minuten(hass, 9)
        await laufen_lassen()
        assert not s.laeuft  # PV-Überschuss erst nach 10 Minuten
        minuten(hass, 1)
        await laufen_lassen()
        assert s.laeuft
        assert s.status is Status.HEIZT
        assert s.status_attribute["grund"] == "PV-Überschuss"
        assert gesetzt(hass) == [(KOMFORT, 60.0), (ECO, 60.0)]
        assert speicher()["gemerkte_sollwerte"] == {KOMFORT: 45.0, ECO: 41.0}
        assert speicher()["lauf"]["ausloeser"] == "pv"

        UHR.vor(minutes=2)
        hass.states.setzen(HEIZT, "on")
        await laufen_lassen()
        UHR.vor(minutes=60)
        hass.states.setzen(TEMP, "55.0")
        await laufen_lassen()
        assert s.laeuft
        assert s.status_attribute["hoechste_temperatur"] == 55.0
        UHR.vor(minutes=40)
        hass.states.setzen(TEMP, "59.5")
        await laufen_lassen()

        assert not s.laeuft
        assert sollwerte(hass) == ("45.0", "41.0")
        assert s.ergebnis == Ergebnis.ERFOLGREICH
        assert s.letzte_aufheizung == UHR.utcnow()
        assert s.status is Status.OK
        assert s.ergebnis_attribute["dauer_minuten"] == 102
        meldungen = hass.services.gefiltert("notify")
        assert len(meldungen) == 1
        assert meldungen[0]["title"] == "🦠 Warmwasser auf 59,5 °C aufgeheizt"
        assert meldungen[0]["message"] == "Legionellen-Aufheizung erledigt (PV-Überschuss, 102 min)."
        assert meldungen[0]["data"]["channel"] == "Legionellen-Info"
        logbuch = hass.services.gefiltert("logbook", "log")
        assert len(logbuch) == 2
        assert logbuch[0]["entity_id"] == "sensor.legionellen_status"
        assert "gemerkte_sollwerte" not in speicher()
        assert "lauf" not in speicher()

    asyncio.run(ablauf())


def test_waermepumpe_startet_nicht() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert(letzte_aufheizung=utc(ortszeit(22, 12))))
        s = entry.runtime_data
        await s.async_von_hand_starten()
        await laufen_lassen()
        assert s.laeuft
        assert sollwerte(hass) == ("60.0", "60.0")
        UHR.vor(minutes=19)
        await laufen_lassen()
        assert s.laeuft
        UHR.vor(minutes=2)
        await laufen_lassen()
        assert not s.laeuft
        assert s.ergebnis == Ergebnis.NICHT_GESTARTET
        assert sollwerte(hass) == ("45.0", "41.0")
        meldung = hass.services.gefiltert("notify")[-1]
        assert meldung["title"] == "🦠 Legionellen-Aufheizung nicht geschafft"
        assert "nicht angefangen" in meldung["message"]
        assert "von Hand" in meldung["message"]
        assert meldung["data"]["channel"] == "Legionellen"

    asyncio.run(ablauf())


def test_abbruch_von_hand() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        await s.async_von_hand_starten()
        await laufen_lassen()
        with pytest.raises(HomeAssistantError) as fehler:
            await s.async_von_hand_starten()
        assert fehler.value.translation_key == "laeuft_bereits"
        hass.states.setzen(HEIZT, "on")
        hass.states.setzen(TEMP, "48.2")
        await laufen_lassen()
        await s.async_abbrechen()
        assert not s.laeuft
        assert sollwerte(hass) == ("45.0", "41.0")
        assert s.ergebnis == Ergebnis.ABGEBROCHEN
        meldung = hass.services.gefiltert("notify")[-1]
        assert meldung["title"] == "🦠 Legionellen-Aufheizung abgebrochen"
        assert "48,2 °C" in meldung["message"]
        with pytest.raises(HomeAssistantError) as fehler:
            await s.async_abbrechen()
        assert fehler.value.translation_key == "laeuft_nicht"

    asyncio.run(ablauf())


def test_sollwert_fehler_wird_spaeter_zurueckgestellt() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        hass.services.fehler[("number", "set_value", ECO)] = HomeAssistantError("Modbus weg")
        await s.async_von_hand_starten()
        await laufen_lassen()
        assert not s.laeuft
        assert s.ergebnis == Ergebnis.FEHLER
        assert hass.states.get(KOMFORT).state == "45.0"  # type: ignore[union-attr]
        assert speicher()["gemerkte_sollwerte"] == {ECO: 41.0}
        assert "Technischer Fehler" in hass.services.gefiltert("notify")[-1]["message"]
        # Solange etwas offen ist, startet keine Automatik
        UHR.stellen(ortszeit(24, 12, 30))
        del hass.services.fehler[("number", "set_value", ECO)]
        hass.minute()
        await laufen_lassen()
        assert "gemerkte_sollwerte" not in speicher()
        assert hass.states.get(ECO).state == "41.0"  # type: ignore[union-attr]
        assert not s.laeuft
        hass.minute()
        await laufen_lassen()
        assert s.laeuft  # danach wieder normal

    asyncio.run(ablauf())


def test_wiederherstellung_nach_absturz() -> None:
    async def ablauf() -> None:
        hass = haus()
        hass.states.setzen(KOMFORT, "60.0")
        hass.states.setzen(ECO, "60.0")
        lauf = {"start": utc(ortszeit(23, 8)), "ausloeser": "pflicht", "grund": "Wochen-Pflicht"}
        entry = await einrichten(
            hass,
            gespeichert=gespeichert(
                lauf=lauf,
                gemerkte_sollwerte={KOMFORT: 45.0, ECO: 41.0},
                letzter_versuch=utc(ortszeit(23, 8)),
            ),
        )
        s = entry.runtime_data
        await laufen_lassen()
        assert sollwerte(hass) == ("45.0", "41.0")
        assert s.ergebnis == Ergebnis.ABGEBROCHEN
        assert "gemerkte_sollwerte" not in speicher()
        assert hass.services.gefiltert("notify") == []

    asyncio.run(ablauf())


def test_neue_aufheizung_behaelt_alte_gemerkte_werte() -> None:
    async def ablauf() -> None:
        hass = haus()
        hass.states.setzen(KOMFORT, "60.0")
        hass.states.setzen(ECO, "unavailable")  # Wärmepumpe noch nicht ganz da
        entry = await einrichten(
            hass, gespeichert=gespeichert(gemerkte_sollwerte={KOMFORT: 45.0, ECO: 41.0})
        )
        s = entry.runtime_data
        assert speicher()["gemerkte_sollwerte"] == {KOMFORT: 45.0, ECO: 41.0}
        hass.states.setzen(ECO, "60.0")
        # Von Hand starten, bevor der Minutentakt zurückstellen konnte
        await s.async_von_hand_starten()
        await laufen_lassen()
        hass.states.setzen(TEMP, "59.8")
        await laufen_lassen()
        assert not s.laeuft
        assert sollwerte(hass) == ("45.0", "41.0")  # nicht 60 „zurückgestellt“

    asyncio.run(ablauf())


def test_zapfung_erkannt() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert(letzte_zapfung=utc(ortszeit(20, 7))))
        s = entry.runtime_data
        assert s.tage_ohne_zapfung == 3.1
        for schritt in range(1, 4):  # Duschen: 0,1 K alle 3 Minuten
            UHR.vor(minutes=3)
            hass.states.setzen(TEMP, f"{45.6 - 0.1 * schritt:.1f}")
        assert s.letzte_zapfung == UHR.utcnow()
        assert s.tage_ohne_zapfung == 0.0

    asyncio.run(ablauf())


def test_keine_zapfung_kurz_nach_dem_heizen() -> None:
    async def ablauf() -> None:
        hass = haus()
        hass.states.setzen(HEIZT, "off", {}, geaendert=UHR.utcnow() - timedelta(minutes=10))
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        vorher = s.letzte_zapfung
        for schritt in range(1, 4):
            UHR.vor(minutes=3)
            hass.states.setzen(TEMP, f"{45.6 - 0.1 * schritt:.1f}")
        assert s.letzte_zapfung == vorher

    asyncio.run(ablauf())


def test_aufheizung_von_aussen_erkannt() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        hass.states.setzen(TEMP, "55.0")
        UHR.vor(minutes=30)
        hass.states.setzen(TEMP, "59.6")
        assert s.letzte_aufheizung == UHR.utcnow()
        assert s.status is Status.OK

    asyncio.run(ablauf())


def test_entladen_waehrend_aufheizung() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        await s.async_von_hand_starten()
        await laufen_lassen()
        assert sollwerte(hass) == ("60.0", "60.0")
        assert await legionellen.async_unload_entry(hass, entry) is True
        assert sollwerte(hass) == ("45.0", "41.0")
        assert hass.services.gefiltert("notify") == []
        assert speicher()["ergebnis"] == Ergebnis.ABGEBROCHEN
        assert hass.zustands_beobachter == []
        assert hass.intervalle == []

    asyncio.run(ablauf())


def test_erster_start_pflicht_um_1230() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass)
        s = entry.runtime_data
        assert s.letzte_aufheizung is None
        assert s.status is Status.FAELLIG
        assert s.naechste_pflicht == ortszeit(23, 12, 30)
        UHR.stellen(ortszeit(23, 12, 28))
        minuten(hass, 1)
        await laufen_lassen()
        assert not s.laeuft
        minuten(hass, 1)
        await laufen_lassen()
        assert s.laeuft
        assert s.status_attribute["grund"] == "Wochen-Pflicht, notfalls mit Netzstrom"

    asyncio.run(ablauf())


def test_sperre_verschiebt_pflicht() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        UHR.stellen(ortszeit(23, 12, 29))
        hass.states.setzen(EVU, "on")
        minuten(hass, 31)
        await laufen_lassen()
        assert not s.laeuft
        hass.states.setzen(EVU, "off")
        minuten(hass, 1)
        await laufen_lassen()
        assert s.laeuft

    asyncio.run(ablauf())


def test_automatik_schalter() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        schalter = hass.entitaeten["switch.legionellen_automatik"]
        await schalter.async_turn_off()
        assert schalter.is_on is False
        assert s.status is Status.AUS
        assert s.naechste_pflicht is None
        UHR.stellen(ortszeit(23, 12, 29))
        minuten(hass, 2)
        await laufen_lassen()
        assert not s.laeuft
        await schalter.async_turn_on()
        await laufen_lassen()
        assert s.laeuft
        assert speicher()["automatik"] is True

    asyncio.run(ablauf())


def test_stoerung_verhindert_start() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = await einrichten(hass, gespeichert=gespeichert())
        s = entry.runtime_data
        hass.states.setzen(KOMFORT, "unavailable")
        assert s.status is Status.STOERUNG
        assert s.status_attribute["nicht_verfuegbar"] == KOMFORT
        with pytest.raises(HomeAssistantError) as fehler:
            await hass.entitaeten["button.legionellen_jetzt_aufheizen"].async_press()
        assert fehler.value.translation_key == "nicht_verfuegbar"
        assert fehler.value.translation_placeholders == {"entitaet": KOMFORT}

    asyncio.run(ablauf())


def test_entitaeten() -> None:
    async def ablauf() -> None:
        hass = haus()
        await einrichten(hass, gespeichert=gespeichert())
        e = hass.entitaeten
        assert e["sensor.legionellen_status"].native_value == "faellig"
        assert e["sensor.legionellen_tage_seit_aufheizung"].native_value == 19.9
        assert e["sensor.legionellen_naechste_pflicht"].native_value == ortszeit(23, 12, 30)
        assert e["sensor.legionellen_letzter_versuch"].native_value is None
        assert e["sensor.legionellen_letzte_aufheizung"].native_value == ortszeit(3, 12)
        assert e["binary_sensor.legionellen_pv_ueberschuss"].is_on is False
        assert e["binary_sensor.legionellen_laeuft"].is_on is False
        assert e["switch.legionellen_automatik"].is_on is True
        status = e["sensor.legionellen_status"]
        assert status.entity_description.options == ["heizt", "stoerung", "aus", "faellig", "pv_bereit", "ok"]
        assert status.extra_state_attributes["pv_moeglich_ab"] == utc(ortszeit(8, 0))
        assert all(entitaet.schreibvorgaenge > 0 for entitaet in e.values())
        assert all(entitaet._attr_should_poll is False for entitaet in e.values())

    asyncio.run(ablauf())


def test_ohne_pv_und_ohne_heizsensor() -> None:
    async def ablauf() -> None:
        hass = haus()
        from conftest import OPTIONEN  # noqa: PLC0415

        optionen = {k: v for k, v in OPTIONEN.items() if k not in ("pv", "akku", "heizt", "benachrichtigen")}
        entry = await einrichten(hass, optionen=optionen, gespeichert=gespeichert())
        s = entry.runtime_data
        assert "binary_sensor.legionellen_pv_ueberschuss" not in hass.entitaeten
        assert s.status is Status.FAELLIG
        UHR.stellen(ortszeit(23, 12, 29))
        minuten(hass, 1)
        await laufen_lassen()
        assert s.laeuft
        UHR.vor(hours=2)  # ohne Heizsensor wird nur auf Temperatur und Höchstdauer geachtet
        await laufen_lassen()
        assert s.laeuft
        UHR.vor(hours=1, minutes=31)
        await laufen_lassen()
        assert not s.laeuft
        assert s.ergebnis == Ergebnis.ZEITLIMIT
        assert sollwerte(hass) == ("45.0", "41.0")

    asyncio.run(ablauf())
