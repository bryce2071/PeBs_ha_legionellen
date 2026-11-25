"""Tests der Entscheidungslogik (ohne Home Assistant).

Die Zahlen stammen aus dem Ausgangssystem: Speicher normal 45 °C, Ziel 60 °C,
Ruhe-Abkühlung etwa 0,4 K/h, Zapfungen 1,2–3,2 K/h.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
import importlib.util
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

PFAD = Path(__file__).resolve().parents[1] / "custom_components" / "legionellen" / "logic.py"
_spec = importlib.util.spec_from_file_location("legionellen_logic", PFAD)
assert _spec is not None and _spec.loader is not None
logic = importlib.util.module_from_spec(_spec)
sys.modules["legionellen_logic"] = logic
_spec.loader.exec_module(logic)

Ausloeser = logic.Ausloeser
Ergebnis = logic.Ergebnis
Status = logic.Status

BERLIN = ZoneInfo("Europe/Berlin")
PLAN = logic.Zeitplan()
_FEHLT = object()


def t(tag: int, stunde: int, minute: int = 0, monat: int = 11) -> datetime:
    """Ortszeit Berlin im Jahr 2026."""
    return datetime(2026, monat, tag, stunde, minute, tzinfo=BERLIN)


def lage(
    jetzt: datetime,
    letzte: datetime | None,
    *,
    zapfung: object = _FEHLT,
    versuch: datetime | None = None,
    pv: bool = False,
    gesperrt: bool = False,
) -> logic.Lage:
    """Lage bauen; ohne Angabe wurde gerade erst gezapft (kein Stillstand)."""
    return logic.Lage(
        jetzt=jetzt,
        letzte_aufheizung=letzte,
        letzte_zapfung=jetzt if zapfung is _FEHLT else zapfung,  # type: ignore[arg-type]
        letzter_versuch=versuch,
        pv_ueberschuss=pv,
        gesperrt=gesperrt,
    )


def entscheide(l: logic.Lage, plan: logic.Zeitplan = PLAN, pv_aktiv: bool = True):
    return logic.entscheide(l, plan, pv_aktiv=pv_aktiv)


# --- Wann wird aufgeheizt? ---------------------------------------------------


def test_pv_nach_langer_pause() -> None:
    # Ausgangslage im Ausgangssystem: letzte 60-°C-Aufheizung am 3.11.
    assert entscheide(lage(t(23, 10), t(3, 12), pv=True)) is Ausloeser.PV


def test_pv_nur_im_zeitfenster() -> None:
    letzte = t(18, 12)  # 5 Tage her: PV erlaubt, Pflicht noch nicht fällig
    assert entscheide(lage(t(23, 9, 59), letzte, pv=True)) is None
    assert entscheide(lage(t(23, 10), letzte, pv=True)) is Ausloeser.PV
    assert entscheide(lage(t(23, 14, 30), letzte, pv=True)) is Ausloeser.PV
    assert entscheide(lage(t(23, 14, 31), letzte, pv=True)) is None
    # Ist die Pflicht fällig, startet sie im Pflicht-Fenster auch ohne PV
    assert entscheide(lage(t(23, 14, 31), t(3, 12), pv=True)) is Ausloeser.PFLICHT


def test_pv_ohne_pv_sensoren_wird_ignoriert() -> None:
    assert entscheide(lage(t(23, 10), t(3, 12), pv=True), pv_aktiv=False) is None


def test_pv_erst_ab_tag_5() -> None:
    letzte = t(18, 14)
    assert entscheide(lage(t(22, 10), letzte, pv=True)) is None  # 3,8 Tage
    assert entscheide(lage(t(23, 10), letzte, pv=True)) is Ausloeser.PV  # 4,8 Tage


def test_pflicht_zur_uhrzeit_ohne_pv() -> None:
    assert entscheide(lage(t(23, 12, 29), t(3, 12))) is None
    assert entscheide(lage(t(23, 12, 30), t(3, 12))) is Ausloeser.PFLICHT


def test_pflicht_an_tag_7() -> None:
    letzte = t(16, 13)
    assert entscheide(lage(t(22, 12, 30), letzte)) is None  # 5,98 Tage
    assert entscheide(lage(t(23, 12, 30), letzte)) is Ausloeser.PFLICHT  # 6,98 Tage


def test_pflicht_rutscht_nicht_in_den_abend() -> None:
    # Um 12:30 Uhr am Tag 6 ist es erst 6,27 Tage her. Dass die Schwelle um
    # 18:01 Uhr überschritten wird, darf keinen Abendstart auslösen.
    letzte = t(16, 6)
    assert entscheide(lage(t(22, 12, 30), letzte)) is None
    assert entscheide(lage(t(22, 18, 1), letzte)) is None
    assert entscheide(lage(t(23, 12, 30), letzte)) is Ausloeser.PFLICHT


def test_pflicht_wartet_bis_sperre_endet() -> None:
    letzte = t(3, 12)
    assert entscheide(lage(t(23, 12, 30), letzte, gesperrt=True)) is None
    assert entscheide(lage(t(23, 14), letzte)) is Ausloeser.PFLICHT
    assert entscheide(lage(t(23, 18, 31), letzte)) is None  # Fenster vorbei


def test_pause_nach_versuch() -> None:
    letzte = t(3, 12)
    versuch = t(23, 12, 30)
    assert entscheide(lage(t(23, 13), letzte, versuch=versuch)) is None
    assert entscheide(lage(t(23, 14), letzte, versuch=versuch, pv=True)) is None
    assert entscheide(lage(t(24, 10), letzte, versuch=versuch, pv=True)) is Ausloeser.PV
    assert entscheide(lage(t(24, 12, 30), letzte, versuch=versuch)) is Ausloeser.PFLICHT


def test_noch_nie_aufgeheizt() -> None:
    assert entscheide(lage(t(23, 9), None)) is None
    assert entscheide(lage(t(23, 10), None, pv=True)) is Ausloeser.PV
    assert entscheide(lage(t(23, 12, 30), None)) is Ausloeser.PFLICHT


def test_stillstand_zieht_vor() -> None:
    letzte = t(18, 12)
    zapfung = t(19, 8)
    assert entscheide(lage(t(23, 12, 30), letzte, zapfung=zapfung)) is Ausloeser.STILLSTAND
    # Mit PV schon vor Tag 5, wenn Stillstand vorliegt
    l = lage(t(23, 11), t(19, 12), zapfung=t(19, 13), pv=True)
    assert entscheide(l) is Ausloeser.PV
    # Ohne Stillstand wäre es dafür noch zu früh
    assert entscheide(lage(t(23, 11), t(19, 12), pv=True)) is None


def test_stillstand_nicht_kurz_nach_aufheizung() -> None:
    assert entscheide(lage(t(23, 12, 30), t(22, 12), zapfung=t(18, 8))) is None


def test_stillstand_abschaltbar() -> None:
    plan = logic.Zeitplan(stillstand_tage=0)
    assert entscheide(lage(t(23, 12, 30), t(18, 12), zapfung=t(19, 8)), plan) is None


def test_stillstand_ohne_bekannte_zapfung() -> None:
    assert entscheide(lage(t(23, 12, 30), t(18, 12), zapfung=None)) is None


def test_pflicht_ueber_mitternacht() -> None:
    plan = logic.Zeitplan(pflicht_uhrzeit=time(22, 0))
    assert entscheide(lage(t(23, 1), t(1, 12)), plan) is Ausloeser.PFLICHT
    assert entscheide(lage(t(23, 4, 1), t(1, 12)), plan) is None


def test_zeitfenster_ueber_mitternacht() -> None:
    assert logic.im_zeitfenster(t(23, 23), time(22), time(2))
    assert logic.im_zeitfenster(t(23, 1), time(22), time(2))
    assert not logic.im_zeitfenster(t(23, 12), time(22), time(2))


# --- Anzeige -------------------------------------------------------------------


def test_status() -> None:
    assert logic.status_ermitteln(lage(t(23, 8), t(22, 12)), PLAN, pv_aktiv=True) is Status.OK
    assert logic.status_ermitteln(lage(t(23, 8), t(18, 12)), PLAN, pv_aktiv=True) is Status.PV_BEREIT
    assert logic.status_ermitteln(lage(t(23, 8), t(18, 12)), PLAN, pv_aktiv=False) is Status.OK
    assert logic.status_ermitteln(lage(t(23, 8), t(3, 12)), PLAN, pv_aktiv=True) is Status.FAELLIG
    assert (
        logic.status_ermitteln(lage(t(23, 8), t(19, 12), zapfung=t(19, 13)), PLAN, pv_aktiv=True)
        is Status.FAELLIG
    )


def test_naechste_pflicht() -> None:
    assert logic.naechste_pflicht(lage(t(23, 14), t(23, 13)), PLAN) == t(30, 12, 30)
    # Nie aufgeheizt: laufendes Fenster bzw. nächster Tag
    assert logic.naechste_pflicht(lage(t(23, 13), None), PLAN) == t(23, 12, 30)
    assert logic.naechste_pflicht(lage(t(23, 19), None), PLAN) == t(24, 12, 30)
    # Gescheiterter Versuch: Pause verschiebt auf den nächsten Tag
    l = lage(t(23, 13), None, versuch=t(23, 12, 30))
    assert logic.naechste_pflicht(l, PLAN) == t(24, 12, 30)


def test_naechste_pflicht_ueber_zeitumstellung() -> None:
    # Ende der Sommerzeit am 25.10.2026: die Pflicht bleibt bei 12:30 Uhr Ortszeit.
    ergebnis = logic.naechste_pflicht(lage(t(20, 14, monat=10), t(20, 12, 30, monat=10)), PLAN)
    assert ergebnis == t(27, 12, 30, monat=10)
    assert ergebnis.astimezone(BERLIN).hour == 12


def test_pv_moeglich_ab_und_pause() -> None:
    l = lage(t(23, 8), t(20, 12), versuch=t(23, 6))
    assert logic.pv_moeglich_ab(l, PLAN) == t(25, 0)  # 4,5 Tage nach der letzten
    assert logic.pause_bis(l) == t(23, 18)
    assert logic.pause_bis(lage(t(23, 19), None, versuch=t(23, 6))) is None


# --- Zapfungen ----------------------------------------------------------------


def test_zapferkennung_ruhe_bleibt_unter_schwelle() -> None:
    z = logic.Zapferkennung()
    start = t(23, 0)
    temperatur = 45.6
    hoechster_abfall = 0.0
    # Ruhe-Abkühlung 0,4 K/h; der Sensor meldet in 0,1-K-Schritten
    for minute in range(0, 600, 15):
        hoechster_abfall = max(hoechster_abfall, z.neuer_wert(start + timedelta(minutes=minute), temperatur))
        temperatur = round(temperatur - 0.1, 1)
    assert hoechster_abfall < 0.3


def test_zapferkennung_dusche() -> None:
    z = logic.Zapferkennung()
    start = t(23, 7)
    z.neuer_wert(start - timedelta(hours=2), 45.6)  # lange unverändert
    # Duschen: etwa 2 K/h, also 0,1 K alle 3 Minuten
    abfaelle = [
        z.neuer_wert(start + timedelta(minutes=3 * i), round(45.6 - 0.1 * i, 1))
        for i in range(1, 6)
    ]
    assert abfaelle[1] < 0.3 <= abfaelle[2]


def test_zapferkennung_alte_werte_fallen_raus() -> None:
    z = logic.Zapferkennung()
    z.neuer_wert(t(23, 7), 45.0)
    z.neuer_wert(t(23, 7, 20), 44.8)
    assert round(z.neuer_wert(t(23, 7, 22), 44.5), 2) == 0.5
    assert round(z.neuer_wert(t(23, 7, 40), 44.4), 2) == 0.1
    z.zuruecksetzen()
    assert z.neuer_wert(t(23, 8), 40.0) == 0.0


# --- PV-Überschuss --------------------------------------------------------------


def test_entprellung() -> None:
    e = logic.Entprellung(timedelta(minutes=10))
    assert e.aktualisieren(True, t(23, 10)) is False
    assert e.aktualisieren(True, t(23, 10, 9)) is False
    assert e.aktualisieren(True, t(23, 10, 10)) is True
    # kurzer Einbruch zählt nicht
    assert e.aktualisieren(False, t(23, 11)) is True
    assert e.aktualisieren(True, t(23, 11, 5)) is True
    assert e.aktualisieren(False, t(23, 11, 6)) is True
    assert e.aktualisieren(False, t(23, 11, 16)) is False


def test_entprellung_ohne_verzoegerung() -> None:
    e = logic.Entprellung(timedelta(0))
    assert e.aktualisieren(True, t(23, 10)) is True


def test_leistung_in_kw() -> None:
    assert logic.leistung_in_kw(2500, "W") == 2.5
    assert logic.leistung_in_kw(2.5, "kW") == 2.5
    assert logic.leistung_in_kw(0.0025, "MW") == 2.5
    assert logic.leistung_in_kw(2.5, None) == 2.5


def test_pv_ueberschuss_roh() -> None:
    kw = {"pv_ab": 2.5, "akku_ab": 90.0}
    assert logic.pv_ueberschuss_roh(3.0, 95, pv_konfiguriert=True, akku_konfiguriert=True, **kw)
    assert not logic.pv_ueberschuss_roh(3.0, 89, pv_konfiguriert=True, akku_konfiguriert=True, **kw)
    assert not logic.pv_ueberschuss_roh(2.4, 95, pv_konfiguriert=True, akku_konfiguriert=True, **kw)
    assert not logic.pv_ueberschuss_roh(None, 95, pv_konfiguriert=True, akku_konfiguriert=True, **kw)
    assert logic.pv_ueberschuss_roh(3.0, None, pv_konfiguriert=True, akku_konfiguriert=False, **kw)
    assert logic.pv_ueberschuss_roh(None, 95, pv_konfiguriert=False, akku_konfiguriert=True, **kw)
    assert not logic.pv_ueberschuss_roh(9.0, 99, pv_konfiguriert=False, akku_konfiguriert=False, **kw)


# --- Laufende Aufheizung ---------------------------------------------------------


def verlauf(**kw: object) -> logic.Aufheizverlauf:
    return logic.Aufheizverlauf(
        start=t(23, 12, 30), erfolg_ab=59.5, max_dauer=timedelta(hours=3.5), **kw
    )


def test_verlauf_erfolg() -> None:
    v = verlauf()
    assert v.pruefe(t(23, 12, 31), 45.6, False, False) is None
    assert v.pruefe(t(23, 12, 40), 46.0, True, False) is None
    assert v.pruefe(t(23, 14, 50), 59.5, True, False) is Ergebnis.ERFOLGREICH
    assert v.hoechste_temperatur == 59.5


def test_verlauf_waermepumpe_startet_nicht() -> None:
    v = verlauf()
    assert v.pruefe(t(23, 12, 49), 45.6, False, False) is None
    assert v.pruefe(t(23, 12, 50), 45.6, False, False) is Ergebnis.NICHT_GESTARTET


def test_verlauf_sperre_verlaengert_startfrist() -> None:
    v = verlauf()
    zeit = t(23, 12, 30)
    assert v.pruefe(zeit, 45.6, False, True) is None  # erste Prüfung direkt beim Start
    for _ in range(60):  # eine Stunde EVU-Sperre, Prüfung jede Minute
        zeit += timedelta(minutes=1)
        assert v.pruefe(zeit, 45.6, False, True) is None
    assert v.pruefe(zeit + timedelta(minutes=19), 45.6, False, False) is None
    assert v.pruefe(zeit + timedelta(minutes=21), 45.6, False, False) is Ergebnis.NICHT_GESTARTET


def test_verlauf_waermepumpe_hoert_zu_frueh_auf() -> None:
    v = verlauf()
    assert v.pruefe(t(23, 12, 35), 46.0, True, False) is None
    assert v.pruefe(t(23, 14, 0), 57.8, False, False) is None
    assert v.pruefe(t(23, 14, 10), 57.9, True, False) is None  # Abtauen o. Ä.
    assert v.pruefe(t(23, 14, 20), 58.0, False, False) is None
    assert v.pruefe(t(23, 14, 35), 58.0, False, False) is Ergebnis.NICHT_ERREICHT
    assert v.hoechste_temperatur == 58.0


def test_verlauf_zeitlimit() -> None:
    v = verlauf()
    assert v.pruefe(t(23, 12, 35), 46.0, True, False) is None
    assert v.pruefe(t(23, 16, 0), 58.9, True, False) is Ergebnis.ZEITLIMIT


def test_verlauf_ohne_heizsensor() -> None:
    v = verlauf(hat_heizsensor=False)
    assert v.pruefe(t(23, 13, 30), 45.6, None, False) is None
    assert v.pruefe(t(23, 15, 0), 60.0, None, False) is Ergebnis.ERFOLGREICH


def test_verlauf_heizsensor_unbekannt_pausiert() -> None:
    v = verlauf()
    zeit = t(23, 12, 30)
    for _ in range(30):
        zeit += timedelta(minutes=1)
        assert v.pruefe(zeit, 45.6, None, False) is None
    assert v.pruefe(zeit + timedelta(minutes=10), 45.6, False, False) is None


# --- Hilfsfunktionen ---------------------------------------------------------------


def test_zeit_und_zeitpunkt_aus_text() -> None:
    assert logic.zeit_aus_text("12:30:00", time(0)) == time(12, 30)
    assert logic.zeit_aus_text("7:5", time(1)) == time(1)
    assert logic.zeit_aus_text(None, time(1)) == time(1)
    wert = logic.zeitpunkt_aus_text("2026-11-23T11:30:00+00:00")
    assert wert == datetime(2026, 11, 23, 11, 30, tzinfo=UTC)
    assert logic.zeitpunkt_aus_text("2026-11-23T11:30:00") == wert
    assert logic.zeitpunkt_aus_text("kaputt") is None
    assert logic.zeitpunkt_aus_text(None) is None
