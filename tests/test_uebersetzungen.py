"""Passen Texte, Symbole und Code zusammen?"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from conftest import haus

from custom_components.legionellen import binary_sensor, button, config_flow, switch, texte
from custom_components.legionellen.logic import Ergebnis, Status
from custom_components.legionellen.sensor import SENSOREN

ORDNER = Path(__file__).resolve().parents[1] / "custom_components" / "legionellen"
DE = json.loads((ORDNER / "translations" / "de.json").read_text(encoding="utf-8"))
EN = json.loads((ORDNER / "translations" / "en.json").read_text(encoding="utf-8"))
ICONS = json.loads((ORDNER / "icons.json").read_text(encoding="utf-8"))
QUELLTEXT = "\n".join(p.read_text(encoding="utf-8") for p in ORDNER.glob("*.py"))


def schluessel(baum: Any, pfad: str = "") -> set[str]:
    if not isinstance(baum, dict):
        return {pfad}
    ergebnis: set[str] = set()
    for name, wert in baum.items():
        ergebnis |= schluessel(wert, f"{pfad}/{name}")
    return ergebnis


def test_deutsch_und_englisch_gleich_aufgebaut() -> None:
    assert schluessel(DE) == schluessel(EN)
    assert TEXTE_GLEICH()


def TEXTE_GLEICH() -> bool:
    return texte.TEXTE["de"].keys() == texte.TEXTE["en"].keys()


def test_felder_der_seiten_uebersetzt() -> None:
    hass = haus()
    seiten = {
        ("config", "user"): config_flow._schema_waermepumpe(mit_name=True),
        ("config", "pv"): config_flow._schema_pv(),
        ("config", "zeitplan"): config_flow._schema_zeitplan(hass, []),
        ("options", "init"): config_flow._schema_waermepumpe(mit_name=False),
        ("options", "pv"): config_flow._schema_pv(),
        ("options", "zeitplan"): config_flow._schema_zeitplan(hass, []),
    }
    for sprache in (DE, EN):
        for (art, schritt), schema in seiten.items():
            felder = {str(feld) for feld in schema.schema}
            eintrag = sprache[art]["step"][schritt]
            assert set(eintrag["data"]) == felder, (art, schritt)
            assert set(eintrag["data_description"]) <= felder, (art, schritt)


def test_fehler_und_ausnahmen_uebersetzt() -> None:
    fehler = set(re.findall(r'"(keine_sollwerte|erfolg_ueber_ziel|ziel_zu_hoch|schon_verwendet|pv_fenster|pv_nach_pflicht)"', QUELLTEXT))
    assert len(fehler) == 6
    ausnahmen = set(re.findall(r'translation_domain=DOMAIN,\s*translation_key="([a-z_]+)"', QUELLTEXT))
    assert ausnahmen == {"laeuft_bereits", "laeuft_nicht", "nicht_verfuegbar", "wiederherstellung"}
    for sprache in (DE, EN):
        for art in ("config", "options"):
            assert set(sprache[art]["error"]) == fehler
        assert set(sprache["exceptions"]) == ausnahmen
        for text in sprache["config"]["error"].values():
            assert set(re.findall(r"{(\w+)}", text)) <= set(config_flow._LEERE_PLATZHALTER)


def test_entitaeten_uebersetzt_und_mit_symbol() -> None:
    erwartet = {
        "sensor": {b.translation_key for b in SENSOREN},
        "binary_sensor": {binary_sensor.LaeuftSensor._attr_translation_key, binary_sensor.PvUeberschussSensor._attr_translation_key},
        "button": {button.JetztAufheizenTaste._attr_translation_key, button.AbbrechenTaste._attr_translation_key},
        "switch": {switch.AutomatikSchalter._attr_translation_key},
    }
    for plattform, keys in erwartet.items():
        for sprache in (DE, EN):
            assert set(sprache["entity"][plattform]) == keys, plattform
        assert set(ICONS["entity"][plattform]) == keys, plattform
    for sprache in (DE, EN):
        assert set(sprache["entity"]["sensor"]["status"]["state"]) == {s.value for s in Status}
        assert set(sprache["entity"]["sensor"]["letzter_versuch"]["state"]) == {e.value for e in Ergebnis}
    assert set(ICONS["entity"]["sensor"]["status"]["state"]) == {s.value for s in Status}
    assert set(ICONS["entity"]["sensor"]["letzter_versuch"]["state"]) == {e.value for e in Ergebnis}


def test_meldungstexte_vollstaendig() -> None:
    for ergebnis in (Ergebnis.NICHT_GESTARTET, Ergebnis.NICHT_ERREICHT, Ergebnis.ZEITLIMIT):
        for sprache in ("de", "en"):
            assert f"text_{ergebnis.value}" in texte.TEXTE[sprache]
    for ausloeser in ("pv", "pflicht", "stillstand", "hand"):
        assert f"grund_{ausloeser}" in texte.TEXTE["de"]
    assert texte.zahl("de", 59.5) == "59,5"
    assert texte.zahl("en", 59.5) == "59.5"


def test_manifest() -> None:
    manifest = json.loads((ORDNER / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "legionellen"
    assert manifest["config_flow"] is True
    assert manifest["version"]
    assert manifest["version"] in QUELLTEXT  # gleiche Version im Gerät
