"""Entscheidungslogik der Legionellen-Aufheizung.

Das Modul kommt ohne Home Assistant aus. So lassen sich die Regeln ohne
laufendes System prüfen; ``steuerung.py`` liefert nur die Messwerte und führt
die Entscheidungen aus.

Regeln (Standardwerte in Klammern):

* Mit PV-Überschuss wird ab Tag 5 nach der letzten Aufheizung im PV-Zeitfenster
  (10:00–14:30 Uhr) aufgeheizt.
* Ist ab Tag 7 noch nichts passiert, wird zur Pflicht-Uhrzeit (12:30 Uhr)
  aufgeheizt, notfalls mit Netzstrom.
* Wurde 3 Tage lang nichts gezapft (Stillstand), gilt der Speicher schon dann
  als fällig – sofern die letzte Aufheizung ebenfalls älter als 3 Tage ist.
* Nach jedem Versuch startet die Automatik frühestens 12 Stunden später neu.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from enum import StrEnum

#: Spielraum bei Tagesgrenzen: „ab Tag 7“ heißt „mehr als 6,5 Tage her“. So
#: verschiebt die Uhrzeit der letzten Aufheizung den Termin nicht um einen Tag.
TOLERANZ_TAGE = 0.5
#: So lange nach der Pflicht-Uhrzeit darf die Pflicht-Aufheizung noch starten,
#: z. B. wenn um 12:30 Uhr gerade eine EVU-Sperre aktiv war.
PFLICHT_FENSTER = timedelta(hours=6)
#: Nach einem Versuch startet die Automatik frühestens so viel später erneut.
PAUSE_NACH_VERSUCH = timedelta(hours=12)
#: Zeitfenster, in dem ein Temperaturabfall als Zapfung gewertet wird.
ZAPF_FENSTER = timedelta(minutes=15)
#: So lange muss die Wärmepumpe vor dem Zeitfenster schon aus sein, damit das
#: Absinken nach dem Heizen nicht als Zapfung zählt.
ZAPF_NACHLAUF = timedelta(minutes=10)
#: So lange darf es dauern, bis die Wärmepumpe nach dem Anheben zu heizen beginnt.
START_FRIST = timedelta(minutes=20)
#: Hört die Wärmepumpe vor dem Ziel so lange auf, gilt der Versuch als gescheitert.
AUS_FRIST = timedelta(minutes=15)


class Ausloeser(StrEnum):
    """Warum eine Aufheizung startet."""

    PV = "pv"
    PFLICHT = "pflicht"
    STILLSTAND = "stillstand"
    HAND = "hand"


class Status(StrEnum):
    """Zustand für die Anzeige."""

    HEIZT = "heizt"
    STOERUNG = "stoerung"
    AUS = "aus"
    FAELLIG = "faellig"
    PV_BEREIT = "pv_bereit"
    OK = "ok"


class Ergebnis(StrEnum):
    """Ausgang eines Aufheizversuchs."""

    ERFOLGREICH = "erfolgreich"
    NICHT_GESTARTET = "nicht_gestartet"
    NICHT_ERREICHT = "nicht_erreicht"
    ZEITLIMIT = "zeitlimit"
    ABGEBROCHEN = "abgebrochen"
    FEHLER = "fehler"


@dataclass(frozen=True, slots=True)
class Zeitplan:
    """Einstellungen, wann aufgeheizt wird."""

    pv_ab_tag: float = 5.0
    spaetestens_tag: float = 7.0
    pflicht_uhrzeit: time = time(12, 30)
    pv_von: time = time(10, 0)
    pv_bis: time = time(14, 30)
    stillstand_tage: float = 3.0  # 0 = Stillstandserkennung aus


@dataclass(frozen=True, slots=True)
class Lage:
    """Momentaufnahme, aus der entschieden wird.

    ``jetzt`` muss die lokale, zeitzonenbewusste Uhrzeit sein, weil
    Zeitfenster und Pflicht-Uhrzeit Ortszeit sind. Die übrigen Zeitpunkte
    dürfen in beliebiger Zeitzone vorliegen.
    """

    jetzt: datetime
    letzte_aufheizung: datetime | None
    letzte_zapfung: datetime | None
    letzter_versuch: datetime | None = None
    pv_ueberschuss: bool = False
    gesperrt: bool = False


def tage_seit(zeitpunkt: datetime | None, jetzt: datetime) -> float | None:
    """Tage zwischen ``zeitpunkt`` und ``jetzt`` (``None``, wenn unbekannt)."""
    if zeitpunkt is None:
        return None
    return (jetzt - zeitpunkt).total_seconds() / 86400


def pv_faellig(lage: Lage, plan: Zeitplan) -> bool:
    """Darf mit PV-Überschuss aufgeheizt werden?"""
    tage = tage_seit(lage.letzte_aufheizung, lage.jetzt)
    return tage is None or tage > plan.pv_ab_tag - TOLERANZ_TAGE


def pflicht_faellig(
    lage: Lage, plan: Zeitplan, zeitpunkt: datetime | None = None
) -> bool:
    """Ist die Pflicht-Aufheizung (spätestens nach x Tagen) fällig?"""
    bezug = lage.jetzt if zeitpunkt is None else zeitpunkt
    tage = tage_seit(lage.letzte_aufheizung, bezug)
    return tage is None or tage > plan.spaetestens_tag - TOLERANZ_TAGE


def stillstand(lage: Lage, plan: Zeitplan, zeitpunkt: datetime | None = None) -> bool:
    """Steht das Wasser so lange, dass vorgezogen aufgeheizt werden soll?"""
    if plan.stillstand_tage <= 0:
        return False
    bezug = lage.jetzt if zeitpunkt is None else zeitpunkt
    ohne_zapfung = tage_seit(lage.letzte_zapfung, bezug)
    if ohne_zapfung is None or ohne_zapfung <= plan.stillstand_tage:
        return False
    seit_aufheizung = tage_seit(lage.letzte_aufheizung, bezug)
    return seit_aufheizung is None or seit_aufheizung > plan.stillstand_tage


def im_zeitfenster(jetzt: datetime, von: time, bis: time) -> bool:
    """Liegt die Uhrzeit von ``jetzt`` im Fenster (auch über Mitternacht)?"""
    uhrzeit = jetzt.time()
    if von <= bis:
        return von <= uhrzeit <= bis
    return uhrzeit >= von or uhrzeit <= bis


def pflicht_fensterbeginn(jetzt: datetime, uhrzeit: time) -> datetime:
    """Letzter Zeitpunkt mit der Pflicht-Uhrzeit, der nicht in der Zukunft liegt."""
    beginn = jetzt.replace(
        hour=uhrzeit.hour, minute=uhrzeit.minute, second=uhrzeit.second, microsecond=0
    )
    if beginn > jetzt:
        beginn -= timedelta(days=1)
    return beginn


def entscheide(lage: Lage, plan: Zeitplan, *, pv_aktiv: bool) -> Ausloeser | None:
    """Soll die Automatik jetzt aufheizen – und wenn ja, warum?"""
    if lage.gesperrt:
        return None
    if (
        lage.letzter_versuch is not None
        and lage.jetzt - lage.letzter_versuch < PAUSE_NACH_VERSUCH
    ):
        return None

    if (
        pv_aktiv
        and lage.pv_ueberschuss
        and im_zeitfenster(lage.jetzt, plan.pv_von, plan.pv_bis)
        and (pv_faellig(lage, plan) or stillstand(lage, plan))
    ):
        return Ausloeser.PV

    # Pflicht und Stillstand werden zur Pflicht-Uhrzeit entschieden. Das
    # Fenster danach dient nur als Reserve (Sperre, Neustart), damit nicht
    # z. B. abends um 18 Uhr eine Aufheizung „nachrutscht“.
    beginn = pflicht_fensterbeginn(lage.jetzt, plan.pflicht_uhrzeit)
    if lage.jetzt - beginn < PFLICHT_FENSTER:
        if pflicht_faellig(lage, plan, beginn):
            return Ausloeser.PFLICHT
        if stillstand(lage, plan, beginn):
            return Ausloeser.STILLSTAND
    return None


def status_ermitteln(lage: Lage, plan: Zeitplan, *, pv_aktiv: bool) -> Status:
    """Anzeige-Status, wenn weder geheizt wird noch eine Störung vorliegt."""
    if pflicht_faellig(lage, plan) or stillstand(lage, plan):
        return Status.FAELLIG
    if pv_aktiv and pv_faellig(lage, plan):
        return Status.PV_BEREIT
    return Status.OK


def naechste_pflicht(lage: Lage, plan: Zeitplan) -> datetime:
    """Wann die Pflicht-Aufheizung spätestens startet (ohne Sperren)."""
    beginn = pflicht_fensterbeginn(lage.jetzt, plan.pflicht_uhrzeit)
    if lage.jetzt - beginn >= PFLICHT_FENSTER:
        beginn += timedelta(days=1)
    frueheste = (
        None
        if lage.letzte_aufheizung is None
        else lage.letzte_aufheizung
        + timedelta(days=plan.spaetestens_tag - TOLERANZ_TAGE)
    )
    pause_ende = (
        None
        if lage.letzter_versuch is None
        else lage.letzter_versuch + PAUSE_NACH_VERSUCH
    )
    for _ in range(400):
        if frueheste is None or beginn > frueheste:
            start = beginn if pause_ende is None or pause_ende <= beginn else pause_ende
            if start - beginn < PFLICHT_FENSTER:
                return start
        beginn += timedelta(days=1)
    return beginn


def pv_moeglich_ab(lage: Lage, plan: Zeitplan) -> datetime | None:
    """Ab wann mit PV-Überschuss aufgeheizt werden darf (``None`` = sofort)."""
    if lage.letzte_aufheizung is None:
        return None
    return lage.letzte_aufheizung + timedelta(days=plan.pv_ab_tag - TOLERANZ_TAGE)


def pause_bis(lage: Lage) -> datetime | None:
    """Ende der Pause nach dem letzten Versuch, falls sie noch läuft."""
    if lage.letzter_versuch is None:
        return None
    ende = lage.letzter_versuch + PAUSE_NACH_VERSUCH
    return ende if ende > lage.jetzt else None


@dataclass(slots=True)
class Aufheizverlauf:
    """Überwacht eine laufende Aufheizung und meldet ihr Ergebnis."""

    start: datetime
    erfolg_ab: float
    max_dauer: timedelta
    hat_heizsensor: bool = True
    start_frist: timedelta = START_FRIST
    aus_frist: timedelta = AUS_FRIST
    gestartet: bool = False
    hoechste_temperatur: float | None = None
    pausiert_gesamt: timedelta = timedelta(0)
    letzte_pruefung: datetime | None = None
    aus_seit: datetime | None = None

    def pruefe(
        self,
        jetzt: datetime,
        temperatur: float | None,
        heizt: bool | None,
        gesperrt: bool,
    ) -> Ergebnis | None:
        """Neue Messung auswerten. ``None`` heißt: weiter warten."""
        if temperatur is not None:
            if self.hoechste_temperatur is None or temperatur > self.hoechste_temperatur:
                self.hoechste_temperatur = temperatur
            if temperatur >= self.erfolg_ab:
                return Ergebnis.ERFOLGREICH
        if jetzt - self.start >= self.max_dauer:
            return Ergebnis.ZEITLIMIT

        # Während einer Sperre (oder wenn der Heiz-Sensor nichts meldet) laufen
        # die Fristen für Start und Unterbrechung nicht weiter.
        pausiert = gesperrt or (self.hat_heizsensor and heizt is None)
        if pausiert and self.letzte_pruefung is not None:
            self.pausiert_gesamt += jetzt - self.letzte_pruefung
        self.letzte_pruefung = jetzt

        if not self.hat_heizsensor:
            return None
        if heizt:
            self.gestartet = True
            self.aus_seit = None
            return None
        if pausiert:
            self.aus_seit = None
            return None
        if not self.gestartet:
            if jetzt - self.start - self.pausiert_gesamt >= self.start_frist:
                return Ergebnis.NICHT_GESTARTET
            return None
        if self.aus_seit is None:
            self.aus_seit = jetzt
        if jetzt - self.aus_seit >= self.aus_frist:
            return Ergebnis.NICHT_ERREICHT
        return None


class Zapferkennung:
    """Erkennt Warmwasser-Zapfungen am Temperaturabfall im Speicher.

    Zapft jemand warmes Wasser, strömt kaltes nach und die gemessene
    Speichertemperatur fällt deutlich schneller als im Ruhezustand.
    """

    def __init__(self, fenster: timedelta = ZAPF_FENSTER) -> None:
        """Leere Messreihe anlegen."""
        self._fenster = fenster
        self._werte: deque[tuple[datetime, float]] = deque()

    def neuer_wert(self, zeit: datetime, temperatur: float) -> float:
        """Messwert aufnehmen und den Abfall im Zeitfenster liefern (Kelvin)."""
        self._werte.append((zeit, temperatur))
        grenze = zeit - self._fenster
        # Ältere Werte verwerfen. Der letzte Wert vor der Grenze bleibt, denn
        # er war zu Beginn des Fensters noch gültig.
        while len(self._werte) > 1 and self._werte[1][0] <= grenze:
            self._werte.popleft()
        hoechste = max(wert for _, wert in self._werte)
        # Runden, damit 45,0 − 44,7 nicht als 0,2999… unter der Schwelle landet
        return max(0.0, round(hoechste - temperatur, 3))

    def zuruecksetzen(self) -> None:
        """Messreihe verwerfen, z. B. wenn der Sensor kurz weg war."""
        self._werte.clear()


class Entprellung:
    """Gibt einen Wechsel erst weiter, wenn er lange genug besteht."""

    def __init__(self, verzoegerung: timedelta) -> None:
        """Startwert ist „aus“."""
        self._verzoegerung = verzoegerung
        self._wert = False
        self._abweichend_seit: datetime | None = None

    @property
    def wert(self) -> bool:
        """Entprellter Wert."""
        return self._wert

    def aktualisieren(self, roh: bool, jetzt: datetime) -> bool:
        """Rohwert übernehmen und den entprellten Wert liefern."""
        if roh == self._wert:
            self._abweichend_seit = None
            return self._wert
        if self._abweichend_seit is None:
            self._abweichend_seit = jetzt
        if jetzt - self._abweichend_seit >= self._verzoegerung:
            self._wert = roh
            self._abweichend_seit = None
        return self._wert


def leistung_in_kw(wert: float, einheit: str | None) -> float:
    """Leistung in kW umrechnen (W, kW und MW werden erkannt)."""
    faktor = {"W": 0.001, "kW": 1.0, "MW": 1000.0}.get((einheit or "kW").strip(), 1.0)
    return wert * faktor


def pv_ueberschuss_roh(
    pv_kw: float | None,
    akku_prozent: float | None,
    *,
    pv_ab: float,
    akku_ab: float,
    pv_konfiguriert: bool,
    akku_konfiguriert: bool,
) -> bool:
    """PV-Überschuss ohne Entprellung: alle eingerichteten Bedingungen erfüllt."""
    if not pv_konfiguriert and not akku_konfiguriert:
        return False
    if pv_konfiguriert and (pv_kw is None or pv_kw < pv_ab):
        return False
    return not (akku_konfiguriert and (akku_prozent is None or akku_prozent < akku_ab))


def zeit_aus_text(text: object, standard: time) -> time:
    """Uhrzeit aus „HH:MM[:SS]“ lesen, sonst den Standardwert liefern."""
    if isinstance(text, time):
        return text
    if isinstance(text, str):
        try:
            return time.fromisoformat(text.strip())
        except ValueError:
            pass
    return standard


def zeitpunkt_aus_text(text: object) -> datetime | None:
    """Gespeicherten Zeitpunkt (ISO-Text) lesen; ohne Zeitzone gilt UTC."""
    if isinstance(text, datetime):
        wert = text
    elif isinstance(text, str):
        try:
            wert = datetime.fromisoformat(text)
        except ValueError:
            return None
    else:
        return None
    return wert if wert.tzinfo is not None else wert.replace(tzinfo=UTC)
