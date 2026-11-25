"""Einrichtungs- und Optionsseiten mit Attrappen."""

from __future__ import annotations

import asyncio
from typing import Any

from conftest import AKKU, ECO, EVU, HANDY, HEIZT, KOMFORT, OPTIONEN, PV_GEN24, TEMP, haus
import ha_attrappe

from custom_components.legionellen.config_flow import (
    LegionellenConfigFlow,
    LegionellenOptionsFlow,
    _notify_auswahl,
)

SEITE_1: dict[str, Any] = {
    "name": "Speicher Keller",
    "temperatur": TEMP,
    "sollwerte": [KOMFORT, ECO],
    "heizt": HEIZT,
    "sperren": [EVU],
    "ziel": 60.0,
    "erfolg_ab": 59.5,
    "max_dauer": 3.5,
}
SEITE_2: dict[str, Any] = {
    "pv": [PV_GEN24],
    "pv_ab": 2.5,
    "akku": AKKU,
    "akku_ab": 90.0,
    "pv_dauer": 10.0,
    "pv_von": "10:00:00",
    "pv_bis": "14:30:00",
}
SEITE_3: dict[str, Any] = {
    "pv_ab_tag": 5.0,
    "spaetestens_tag": 7.0,
    "pflicht_uhrzeit": "12:30:00",
    "stillstand_tage": 3.0,
    "zapf_schwelle": 0.3,
    "benachrichtigen": [HANDY],
}


def neuer_flow(hass: ha_attrappe.FakeHass) -> LegionellenConfigFlow:
    flow = LegionellenConfigFlow()
    flow.hass = hass
    return flow


def felder(ergebnis: dict[str, Any]) -> list[str]:
    return [str(schluessel) for schluessel in ergebnis["data_schema"].schema]


def test_einrichtung_in_drei_schritten() -> None:
    async def ablauf() -> None:
        flow = neuer_flow(haus())
        ergebnis = await flow.async_step_user()
        assert ergebnis["step_id"] == "user"
        assert felder(ergebnis) == ["name", "temperatur", "sollwerte", "heizt", "sperren", "ziel", "erfolg_ab", "max_dauer"]
        ergebnis = await flow.async_step_user(dict(SEITE_1))
        assert ergebnis["step_id"] == "pv"
        ergebnis = await flow.async_step_pv(dict(SEITE_2))
        assert ergebnis["step_id"] == "zeitplan"
        assert "benachrichtigen" in felder(ergebnis)
        ergebnis = await flow.async_step_zeitplan(dict(SEITE_3))
        assert ergebnis["type"] == "create_entry"
        assert ergebnis["title"] == "Speicher Keller"
        assert ergebnis["data"] == {}
        optionen = ergebnis["options"]
        assert "name" not in optionen
        assert optionen["sollwerte"] == [KOMFORT, ECO]
        assert optionen["benachrichtigen"] == [HANDY]
        assert optionen["pflicht_uhrzeit"] == "12:30:00"

    asyncio.run(ablauf())


def test_pruefungen_seite_1() -> None:
    async def ablauf() -> None:
        hass = haus()
        flow = neuer_flow(hass)
        ergebnis = await flow.async_step_user({**SEITE_1, "erfolg_ab": 61.0})
        assert ergebnis["errors"] == {"erfolg_ab": "erfolg_ueber_ziel"}
        ergebnis = await flow.async_step_user({**SEITE_1, "ziel": 65.0})
        assert ergebnis["errors"] == {"ziel": "ziel_zu_hoch"}
        assert ergebnis["description_placeholders"] == {
            "entitaet": "WP WW Temp. Ziel Komfort",
            "maximum": "60",
        }
        ergebnis = await flow.async_step_user({**SEITE_1, "sollwerte": []})
        assert ergebnis["errors"] == {"sollwerte": "keine_sollwerte"}
        # gleicher Temperatursensor schon eingerichtet
        hass.config_entries.liste.append(ha_attrappe.ConfigEntry(hass, dict(OPTIONEN)))
        ergebnis = await flow.async_step_user(dict(SEITE_1))
        assert ergebnis["errors"] == {"temperatur": "schon_verwendet"}

    asyncio.run(ablauf())


def test_pruefungen_seite_2_und_3() -> None:
    async def ablauf() -> None:
        flow = neuer_flow(haus())
        await flow.async_step_user(dict(SEITE_1))
        ergebnis = await flow.async_step_pv({**SEITE_2, "pv_von": "15:00:00", "pv_bis": "10:00:00"})
        assert ergebnis["errors"] == {"pv_bis": "pv_fenster"}
        await flow.async_step_pv(dict(SEITE_2))
        ergebnis = await flow.async_step_zeitplan({**SEITE_3, "pv_ab_tag": 8.0})
        assert ergebnis["errors"] == {"pv_ab_tag": "pv_nach_pflicht"}

    asyncio.run(ablauf())


def test_ohne_pv_und_benachrichtigung() -> None:
    async def ablauf() -> None:
        flow = neuer_flow(haus())
        await flow.async_step_user({k: v for k, v in SEITE_1.items() if k not in ("heizt", "sperren")})
        await flow.async_step_pv({k: v for k, v in SEITE_2.items() if k not in ("pv", "akku")})
        ergebnis = await flow.async_step_zeitplan({k: v for k, v in SEITE_3.items() if k != "benachrichtigen"})
        optionen = ergebnis["options"]
        for fehlt in ("heizt", "sperren", "pv", "akku", "benachrichtigen"):
            assert fehlt not in optionen

    asyncio.run(ablauf())


def test_optionen_aendern_und_leeren() -> None:
    async def ablauf() -> None:
        hass = haus()
        entry = ha_attrappe.ConfigEntry(hass, dict(OPTIONEN))
        hass.config_entries.liste.append(entry)
        flow = LegionellenOptionsFlow()
        flow.hass = hass
        flow.config_entry = entry
        ergebnis = await flow.async_step_init()
        assert ergebnis["step_id"] == "init"
        assert "name" not in felder(ergebnis)
        seite_1 = {k: v for k, v in SEITE_1.items() if k not in ("name", "heizt")}
        ergebnis = await flow.async_step_init(seite_1)  # eigener Sensor ist kein Duplikat
        assert ergebnis["step_id"] == "pv"
        ergebnis = await flow.async_step_pv({k: v for k, v in SEITE_2.items() if k != "akku"})
        assert ergebnis["step_id"] == "zeitplan"
        ergebnis = await flow.async_step_zeitplan({**SEITE_3, "benachrichtigen": [], "spaetestens_tag": 6.0})
        assert ergebnis["type"] == "create_entry"
        daten = ergebnis["data"]
        assert "heizt" not in daten
        assert "akku" not in daten
        assert "benachrichtigen" not in daten
        assert daten["spaetestens_tag"] == 6.0
        assert daten["temperatur"] == TEMP

    asyncio.run(ablauf())


def test_benachrichtigungsdienste() -> None:
    werte = [option["value"] for option in _notify_auswahl(haus(), ["notify.altes_handy"])]
    assert "notify.mobile_app_handy" in werte
    assert "notify.persistent_notification" in werte
    assert "notify.send_message" not in werte
    assert "notify.altes_handy" in werte
