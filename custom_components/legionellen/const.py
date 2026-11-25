"""Konstanten der Legionellen-Aufheizung."""

from __future__ import annotations

from typing import Any, Final

DOMAIN: Final = "legionellen"
VERSION: Final = "1.0.0"
DEFAULT_NAME: Final = "Legionellen-Aufheizung"

# Seite 1: Wärmepumpe und Speicher
CONF_TEMPERATUR: Final = "temperatur"
CONF_SOLLWERTE: Final = "sollwerte"
CONF_HEIZT: Final = "heizt"
CONF_SPERREN: Final = "sperren"
CONF_ZIEL: Final = "ziel"
CONF_ERFOLG_AB: Final = "erfolg_ab"
CONF_MAX_DAUER: Final = "max_dauer"

# Seite 2: Photovoltaik und Hausakku
CONF_PV: Final = "pv"
CONF_PV_AB: Final = "pv_ab"
CONF_AKKU: Final = "akku"
CONF_AKKU_AB: Final = "akku_ab"
CONF_PV_DAUER: Final = "pv_dauer"
CONF_PV_VON: Final = "pv_von"
CONF_PV_BIS: Final = "pv_bis"

# Seite 3: Zeitplan und Benachrichtigung
CONF_PV_AB_TAG: Final = "pv_ab_tag"
CONF_SPAETESTENS_TAG: Final = "spaetestens_tag"
CONF_PFLICHT_UHRZEIT: Final = "pflicht_uhrzeit"
CONF_STILLSTAND_TAGE: Final = "stillstand_tage"
CONF_ZAPF_SCHWELLE: Final = "zapf_schwelle"
CONF_BENACHRICHTIGEN: Final = "benachrichtigen"

SCHLUESSEL_WAERMEPUMPE: Final = (
    CONF_TEMPERATUR,
    CONF_SOLLWERTE,
    CONF_HEIZT,
    CONF_SPERREN,
    CONF_ZIEL,
    CONF_ERFOLG_AB,
    CONF_MAX_DAUER,
)
SCHLUESSEL_PV: Final = (
    CONF_PV,
    CONF_PV_AB,
    CONF_AKKU,
    CONF_AKKU_AB,
    CONF_PV_DAUER,
    CONF_PV_VON,
    CONF_PV_BIS,
)
SCHLUESSEL_ZEITPLAN: Final = (
    CONF_PV_AB_TAG,
    CONF_SPAETESTENS_TAG,
    CONF_PFLICHT_UHRZEIT,
    CONF_STILLSTAND_TAGE,
    CONF_ZAPF_SCHWELLE,
    CONF_BENACHRICHTIGEN,
)

STANDARDWERTE: Final[dict[str, Any]] = {
    CONF_ZIEL: 60.0,
    CONF_ERFOLG_AB: 59.5,
    CONF_MAX_DAUER: 3.5,
    CONF_PV_AB: 2.5,
    CONF_AKKU_AB: 90.0,
    CONF_PV_DAUER: 10.0,
    CONF_PV_VON: "10:00:00",
    CONF_PV_BIS: "14:30:00",
    CONF_PV_AB_TAG: 5.0,
    CONF_SPAETESTENS_TAG: 7.0,
    CONF_PFLICHT_UHRZEIT: "12:30:00",
    CONF_STILLSTAND_TAGE: 3.0,
    CONF_ZAPF_SCHWELLE: 0.3,
}

SPEICHER_VERSION: Final = 1
#: Abstand der Prüfungen während einer laufenden Aufheizung (Sekunden).
PRUEF_INTERVALL_S: Final = 30.0
#: So weit schaut die Integration beim ersten Start in den Verlauf zurück.
VERLAUF_TAGE: Final = 14
