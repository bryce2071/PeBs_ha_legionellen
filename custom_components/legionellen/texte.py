"""Texte für Benachrichtigungen und Logbuch (Deutsch und Englisch)."""

from __future__ import annotations

TEXTE: dict[str, dict[str, str]] = {
    "de": {
        "grund_pv": "PV-Überschuss",
        "grund_pflicht": "Wochen-Pflicht, notfalls mit Netzstrom",
        "grund_stillstand": "Stillstand – seit {tage} Tagen nichts gezapft",
        "grund_hand": "von Hand",
        "log_start": "Aufheizung auf {ziel} °C gestartet ({grund}).",
        "titel_erfolgreich": "🦠 Warmwasser auf {temperatur} °C aufgeheizt",
        "text_erfolgreich": "Legionellen-Aufheizung erledigt ({grund}, {dauer} min).",
        "titel_fehlschlag": "🦠 Legionellen-Aufheizung nicht geschafft",
        "text_nicht_gestartet": "Die Wärmepumpe hat nicht angefangen zu heizen ({grund}).",
        "text_nicht_erreicht": "Die Wärmepumpe hat bei {temperatur} °C aufgehört ({grund}).",
        "text_zeitlimit": "Nach {dauer} min erst {temperatur} °C erreicht ({grund}).",
        "text_fehler": "Technischer Fehler ({grund}): {fehler}. Neuer Versuch frühestens in 12 Stunden.",
        "zusatz_neuer_versuch": "Sollwert ist zurückgestellt, neuer Versuch frühestens in 12 Stunden.",
        "titel_abgebrochen": "🦠 Legionellen-Aufheizung abgebrochen",
        "text_abgebrochen": "Von Hand abgebrochen bei {temperatur} °C. Sollwert ist zurückgestellt.",
        "fehler_sollwert_lesen": "{entitaet} ist nicht lesbar",
        "fehler_sollwert_setzen": "{entitaet} ließ sich nicht setzen",
    },
    "en": {
        "grund_pv": "PV surplus",
        "grund_pflicht": "weekly duty, grid power if needed",
        "grund_stillstand": "stagnation – no hot water drawn for {tage} days",
        "grund_hand": "manual",
        "log_start": "Heating to {ziel} °C started ({grund}).",
        "titel_erfolgreich": "🦠 Hot water heated to {temperatur} °C",
        "text_erfolgreich": "Legionella heat-up done ({grund}, {dauer} min).",
        "titel_fehlschlag": "🦠 Legionella heat-up failed",
        "text_nicht_gestartet": "The heat pump did not start heating ({grund}).",
        "text_nicht_erreicht": "The heat pump stopped at {temperatur} °C ({grund}).",
        "text_zeitlimit": "Only {temperatur} °C after {dauer} min ({grund}).",
        "text_fehler": "Technical error ({grund}): {fehler}. Next attempt in 12 hours at the earliest.",
        "zusatz_neuer_versuch": "Setpoint restored, next attempt in 12 hours at the earliest.",
        "titel_abgebrochen": "🦠 Legionella heat-up cancelled",
        "text_abgebrochen": "Cancelled manually at {temperatur} °C. Setpoint restored.",
        "fehler_sollwert_lesen": "{entitaet} cannot be read",
        "fehler_sollwert_setzen": "{entitaet} could not be set",
    },
}


def _deutsch(sprache: str | None) -> bool:
    return (sprache or "de").lower().startswith("de")


def text(sprache: str | None, schluessel: str, **werte: object) -> str:
    """Text in der Sprache des Systems (Deutsch, sonst Englisch)."""
    tabelle = TEXTE["de"] if _deutsch(sprache) else TEXTE["en"]
    return tabelle[schluessel].format(**werte)


def zahl(sprache: str | None, wert: float | None, stellen: int = 1) -> str:
    """Zahl mit Dezimalkomma (Deutsch) bzw. -punkt formatieren."""
    if wert is None:
        return "?"
    ergebnis = f"{wert:.{stellen}f}"
    return ergebnis.replace(".", ",") if _deutsch(sprache) else ergebnis
