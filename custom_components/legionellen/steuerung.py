"""Steuerung der Legionellen-Aufheizung für einen Warmwasserspeicher."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import copy
from datetime import datetime, time, timedelta
from functools import partial
import logging
import math
from typing import TYPE_CHECKING, Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, STATE_OFF, STATE_ON
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_started
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_AKKU,
    CONF_AKKU_AB,
    CONF_BENACHRICHTIGEN,
    CONF_ERFOLG_AB,
    CONF_HEIZT,
    CONF_MAX_DAUER,
    CONF_PFLICHT_UHRZEIT,
    CONF_PV,
    CONF_PV_AB,
    CONF_PV_AB_TAG,
    CONF_PV_BIS,
    CONF_PV_DAUER,
    CONF_PV_VON,
    CONF_SOLLWERTE,
    CONF_SPAETESTENS_TAG,
    CONF_SPERREN,
    CONF_STILLSTAND_TAGE,
    CONF_TEMPERATUR,
    CONF_ZAPF_SCHWELLE,
    CONF_ZIEL,
    DOMAIN,
    PRUEF_INTERVALL_S,
    SPEICHER_VERSION,
    STANDARDWERTE,
    VERLAUF_TAGE,
    VERSION,
)
from .logic import (
    ZAPF_FENSTER,
    ZAPF_NACHLAUF,
    Aufheizverlauf,
    Ausloeser,
    Entprellung,
    Ergebnis,
    Lage,
    Status,
    Zapferkennung,
    Zeitplan,
    entscheide,
    leistung_in_kw,
    naechste_pflicht,
    pause_bis,
    pv_moeglich_ab,
    pv_ueberschuss_roh,
    status_ermitteln,
    stillstand,
    tage_seit,
    zeit_aus_text,
    zeitpunkt_aus_text,
)
from .texte import text, zahl

if TYPE_CHECKING:
    from homeassistant.core import Event, EventStateChangedData

_LOGGER = logging.getLogger(__name__)

type LegionellenConfigEntry = ConfigEntry[LegionellenSteuerung]


class _SollwertFehler(Exception):
    """Ein Sollwert ließ sich nicht lesen oder setzen."""


def _zahl(wert: Any) -> float | None:
    """Zustand als Zahl lesen; „unavailable“, „unknown“ usw. ergeben ``None``."""
    try:
        ergebnis = float(wert)
    except (TypeError, ValueError):
        return None
    return ergebnis if math.isfinite(ergebnis) else None


class LegionellenSteuerung:
    """Zustand und Ablauf der Legionellen-Aufheizung eines Speichers."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Einstellungen aus dem Konfigurationseintrag übernehmen."""
        self.hass = hass
        self.entry = entry
        optionen: dict[str, Any] = {**STANDARDWERTE, **entry.options}
        self.temperatur_id: str = optionen[CONF_TEMPERATUR]
        self.sollwert_ids: list[str] = list(optionen.get(CONF_SOLLWERTE) or [])
        self.heizt_id: str | None = optionen.get(CONF_HEIZT) or None
        self.sperr_ids: list[str] = list(optionen.get(CONF_SPERREN) or [])
        self.pv_ids: list[str] = list(optionen.get(CONF_PV) or [])
        self.akku_id: str | None = optionen.get(CONF_AKKU) or None
        self.benachrichtigen: list[str] = list(optionen.get(CONF_BENACHRICHTIGEN) or [])
        self.ziel = float(optionen[CONF_ZIEL])
        self.erfolg_ab = float(optionen[CONF_ERFOLG_AB])
        self.max_dauer = timedelta(hours=float(optionen[CONF_MAX_DAUER]))
        self.pv_ab_kw = float(optionen[CONF_PV_AB])
        self.akku_ab = float(optionen[CONF_AKKU_AB])
        self.zapf_schwelle = float(optionen[CONF_ZAPF_SCHWELLE])
        self.plan = Zeitplan(
            pv_ab_tag=float(optionen[CONF_PV_AB_TAG]),
            spaetestens_tag=float(optionen[CONF_SPAETESTENS_TAG]),
            pflicht_uhrzeit=zeit_aus_text(optionen[CONF_PFLICHT_UHRZEIT], time(12, 30)),
            pv_von=zeit_aus_text(optionen[CONF_PV_VON], time(10, 0)),
            pv_bis=zeit_aus_text(optionen[CONF_PV_BIS], time(14, 30)),
            stillstand_tage=float(optionen[CONF_STILLSTAND_TAGE]),
        )
        self.pv_aktiv = bool(self.pv_ids) or self.akku_id is not None
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            entry_type=DeviceEntryType.SERVICE,
            sw_version=VERSION,
        )

        self._speicher: Store[dict[str, Any]] = Store(
            hass, SPEICHER_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._daten: dict[str, Any] = {}
        self._erstlauf = False
        self._zuhoerer: list[Callable[[], None]] = []
        self._abmelden: list[Callable[[], None]] = []
        self._zapf = Zapferkennung()
        self._pv = Entprellung(timedelta(minutes=float(optionen[CONF_PV_DAUER])))
        self._ueber_schwelle: bool | None = None
        self._lauf: asyncio.Task[None] | None = None
        self._verlauf: Aufheizverlauf | None = None
        self._lauf_info: dict[str, Any] | None = None
        self._von_hand_abgebrochen = False
        self._wiederherstellung: asyncio.Task[None] | None = None
        self._aktiv = False
        self._gestoppt = False

    # ------------------------------------------------------------------
    # Lebenszyklus

    async def async_laden(self) -> None:
        """Gespeicherten Zustand laden."""
        geladen = await self._speicher.async_load()
        self._erstlauf = geladen is None
        self._daten = dict(geladen) if isinstance(geladen, dict) else {}
        self._daten.setdefault("automatik", True)
        if self._erstlauf:
            # Stillstand zählt ab der Einrichtung.
            self._daten["letzte_zapfung"] = dt_util.utcnow().isoformat()
        lauf = self._daten.pop("lauf", None)
        if isinstance(lauf, dict):
            # Home Assistant wurde während einer Aufheizung beendet.
            self._daten["ergebnis"] = Ergebnis.ABGEBROCHEN.value
            self._daten["ergebnis_info"] = {**lauf, "ende": dt_util.utcnow().isoformat()}
        self._speichern_bald()

    @callback
    def async_starten(self) -> None:
        """Nach dem Einrichten der Entitäten aufrufen."""
        self._abmelden.append(async_at_started(self.hass, self._async_ha_laeuft))

    async def _async_ha_laeuft(self, _hass: HomeAssistant) -> None:
        """Beobachtung starten, sobald Home Assistant vollständig läuft."""
        if self._gestoppt:
            return
        if self._erstlauf:
            await self._async_verlauf_auswerten()
            if self._gestoppt:
                return
        self._abmelden.append(
            async_track_state_change_event(
                self.hass, [self.temperatur_id], self._temperatur_geaendert
            )
        )
        pv_ids = [*self.pv_ids, *([self.akku_id] if self.akku_id else [])]
        if pv_ids:
            self._abmelden.append(
                async_track_state_change_event(self.hass, pv_ids, self._pv_geaendert)
            )
        sonstige = [*self.sollwert_ids, *self.sperr_ids, *([self.heizt_id] if self.heizt_id else [])]
        if sonstige:
            self._abmelden.append(
                async_track_state_change_event(self.hass, sonstige, self._sonstiges_geaendert)
            )
        self._abmelden.append(
            async_track_time_interval(self.hass, self._minute, timedelta(minutes=1))
        )
        self._aktiv = True
        self._temperatur_auswerten()
        self._minute(dt_util.utcnow())

    async def async_stoppen(self) -> None:
        """Beim Entladen: Beobachtung beenden, laufende Aufheizung zurückstellen."""
        self._gestoppt = True
        self._aktiv = False
        while self._abmelden:
            self._abmelden.pop()()
        offen = [
            aufgabe
            for aufgabe in (self._lauf, self._wiederherstellung)
            if aufgabe is not None and not aufgabe.done()
        ]
        if self._lauf is not None and not self._lauf.done():
            self._lauf.cancel()
        if offen:
            await asyncio.wait(offen, timeout=20)
        await self._speicher.async_save(self._kopie())

    # ------------------------------------------------------------------
    # Anbindung der Entitäten

    @callback
    def async_zuhoerer_hinzufuegen(self, zuhoerer: Callable[[], None]) -> Callable[[], None]:
        """Entität bei Änderungen benachrichtigen; liefert die Abmeldung."""
        self._zuhoerer.append(zuhoerer)

        @callback
        def entfernen() -> None:
            if zuhoerer in self._zuhoerer:
                self._zuhoerer.remove(zuhoerer)

        return entfernen

    @callback
    def _aktualisieren(self) -> None:
        for zuhoerer in list(self._zuhoerer):
            zuhoerer()

    @property
    def sprache(self) -> str:
        """Systemsprache für Meldungen."""
        return self.hass.config.language or "de"

    @property
    def automatik(self) -> bool:
        """Darf automatisch aufgeheizt werden?"""
        return bool(self._daten.get("automatik", True))

    @property
    def laeuft(self) -> bool:
        """Läuft gerade eine Aufheizung?"""
        return self._verlauf is not None

    @property
    def pv_ueberschuss(self) -> bool:
        """Entprellter PV-Überschuss."""
        return self._pv.wert

    @property
    def letzte_aufheizung(self) -> datetime | None:
        """Wann der Speicher zuletzt die Zieltemperatur erreicht hat."""
        return zeitpunkt_aus_text(self._daten.get("letzte_aufheizung"))

    @property
    def letzte_zapfung(self) -> datetime | None:
        """Wann zuletzt eine Zapfung erkannt wurde."""
        return zeitpunkt_aus_text(self._daten.get("letzte_zapfung"))

    @property
    def tage_seit_aufheizung(self) -> float | None:
        """Tage seit der letzten Aufheizung."""
        tage = tage_seit(self.letzte_aufheizung, dt_util.utcnow())
        return None if tage is None else round(max(tage, 0.0), 1)

    @property
    def tage_ohne_zapfung(self) -> float | None:
        """Tage seit der letzten erkannten Zapfung."""
        tage = tage_seit(self.letzte_zapfung, dt_util.utcnow())
        return None if tage is None else round(max(tage, 0.0), 1)

    @property
    def naechste_pflicht(self) -> datetime | None:
        """Spätester Termin der nächsten automatischen Aufheizung."""
        if not self.automatik:
            return None
        return naechste_pflicht(self._lage(), self.plan)

    @property
    def gesperrt(self) -> bool:
        """Ist eine der Sperr-Entitäten eingeschaltet?"""
        for eid in self.sperr_ids:
            zustand = self.hass.states.get(eid)
            if zustand is not None and zustand.state == STATE_ON:
                return True
        return False

    @property
    def stoerung(self) -> str | None:
        """Erste benötigte Entität, die gerade keinen Wert liefert."""
        if self._temperatur() is None:
            return self.temperatur_id
        for eid in self.sollwert_ids:
            if self._sollwert_lesen(eid) is None:
                return eid
        return None

    @property
    def status(self) -> Status:
        """Status für die Anzeige."""
        if self.laeuft:
            return Status.HEIZT
        if self.stoerung is not None:
            return Status.STOERUNG
        if not self.automatik:
            return Status.AUS
        return status_ermitteln(self._lage(), self.plan, pv_aktiv=self.pv_aktiv)

    @property
    def status_attribute(self) -> dict[str, Any]:
        """Zusatzinfos zum Status."""
        lage = self._lage()
        attribute: dict[str, Any] = {"stillstand": stillstand(lage, self.plan)}
        if self._lauf_info is not None:
            attribute["grund"] = self._lauf_info["grund"]
            attribute["gestartet"] = self._lauf_info["start"]
        if self._verlauf is not None and self._verlauf.hoechste_temperatur is not None:
            attribute["hoechste_temperatur"] = self._verlauf.hoechste_temperatur
        if (fehlt := self.stoerung) is not None:
            attribute["nicht_verfuegbar"] = fehlt
        if self.pv_aktiv and (ab := pv_moeglich_ab(lage, self.plan)) is not None:
            attribute["pv_moeglich_ab"] = ab.isoformat()
        if (pause := pause_bis(lage)) is not None:
            attribute["pause_bis"] = pause.isoformat()
        return attribute

    @property
    def ergebnis(self) -> str | None:
        """Ergebnis des letzten Versuchs."""
        wert = self._daten.get("ergebnis")
        return wert if wert in {e.value for e in Ergebnis} else None

    @property
    def ergebnis_attribute(self) -> dict[str, Any]:
        """Details zum letzten Versuch."""
        info = self._daten.get("ergebnis_info") or {}
        return {schluessel: wert for schluessel, wert in info.items() if wert is not None}

    # ------------------------------------------------------------------
    # Bedienung

    async def async_automatik_setzen(self, an: bool) -> None:
        """Automatik ein- oder ausschalten."""
        self._daten["automatik"] = an
        self._speichern_bald()
        if an:
            self._entscheiden()
        self._aktualisieren()

    async def async_von_hand_starten(self) -> None:
        """Aufheizung sofort starten."""
        if self.laeuft:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="laeuft_bereits")
        if self._wiederherstellung is not None and not self._wiederherstellung.done():
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="wiederherstellung")
        if (fehlt := self.stoerung) is not None:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="nicht_verfuegbar",
                translation_placeholders={"entitaet": fehlt},
            )
        self._lauf_starten(Ausloeser.HAND)

    async def async_abbrechen(self) -> None:
        """Laufende Aufheizung abbrechen und Sollwerte zurückstellen."""
        lauf = self._lauf
        if lauf is None or lauf.done() or not self.laeuft:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="laeuft_nicht")
        self._von_hand_abgebrochen = True
        lauf.cancel()
        await asyncio.wait([lauf], timeout=30)

    # ------------------------------------------------------------------
    # Beobachtung

    @callback
    def _temperatur_geaendert(self, _event: Event[EventStateChangedData]) -> None:
        self._temperatur_auswerten()
        self._aktualisieren()

    @callback
    def _pv_geaendert(self, _event: Event[EventStateChangedData]) -> None:
        self._pv_auswerten()
        self._entscheiden()
        self._aktualisieren()

    @callback
    def _sonstiges_geaendert(self, _event: Event[EventStateChangedData]) -> None:
        self._aktualisieren()

    @callback
    def _minute(self, _jetzt: datetime) -> None:
        self._pv_auswerten()
        self._wiederherstellen_falls_noetig()
        self._entscheiden()
        self._aktualisieren()

    @callback
    def _temperatur_auswerten(self) -> None:
        """Erkennt Aufheizungen von außen und Zapfungen."""
        jetzt = dt_util.utcnow()
        temperatur = self._temperatur()
        if temperatur is None:
            self._zapf.zuruecksetzen()
            return
        ueber = temperatur >= self.erfolg_ab
        if ueber and self._ueber_schwelle is False and not self.laeuft:
            # Z. B. eigenes Legionellenprogramm der Wärmepumpe oder Nachheizen von Hand
            self._daten["letzte_aufheizung"] = jetzt.isoformat()
            self._speichern_bald()
        self._ueber_schwelle = ueber
        abfall = self._zapf.neuer_wert(jetzt, temperatur)
        if abfall >= self.zapf_schwelle and not self.laeuft and self._heizt_lange_nicht(jetzt):
            self._daten["letzte_zapfung"] = jetzt.isoformat()
            self._speichern_bald()

    @callback
    def _pv_auswerten(self) -> None:
        if self.pv_aktiv:
            self._pv.aktualisieren(self._pv_roh(), dt_util.utcnow())

    def _pv_roh(self) -> bool:
        pv_kw: float | None = None
        for eid in self.pv_ids:
            zustand = self.hass.states.get(eid)
            if zustand is None or (wert := _zahl(zustand.state)) is None:
                continue  # z. B. Wechselrichter nachts „nicht verfügbar“
            einheit = zustand.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            pv_kw = (pv_kw or 0.0) + leistung_in_kw(wert, einheit)
        akku: float | None = None
        if self.akku_id and (zustand := self.hass.states.get(self.akku_id)) is not None:
            akku = _zahl(zustand.state)
        return pv_ueberschuss_roh(
            pv_kw,
            akku,
            pv_ab=self.pv_ab_kw,
            akku_ab=self.akku_ab,
            pv_konfiguriert=bool(self.pv_ids),
            akku_konfiguriert=self.akku_id is not None,
        )

    def _temperatur(self) -> float | None:
        zustand = self.hass.states.get(self.temperatur_id)
        return None if zustand is None else _zahl(zustand.state)

    def _heizt(self) -> bool | None:
        if not self.heizt_id:
            return None
        zustand = self.hass.states.get(self.heizt_id)
        if zustand is None or zustand.state not in (STATE_ON, STATE_OFF):
            return None
        return zustand.state == STATE_ON

    def _heizt_lange_nicht(self, jetzt: datetime) -> bool:
        """Heizt die Wärmepumpe schon so lange nicht, dass ein Abfall Zapfen bedeutet?"""
        if not self.heizt_id:
            return True
        zustand = self.hass.states.get(self.heizt_id)
        if zustand is None or zustand.state != STATE_OFF:
            return False
        return jetzt - zustand.last_changed >= ZAPF_FENSTER + ZAPF_NACHLAUF

    def _lage(self) -> Lage:
        return Lage(
            jetzt=dt_util.now(),
            letzte_aufheizung=self.letzte_aufheizung,
            letzte_zapfung=self.letzte_zapfung,
            letzter_versuch=zeitpunkt_aus_text(self._daten.get("letzter_versuch")),
            pv_ueberschuss=self._pv.wert,
            gesperrt=self.gesperrt,
        )

    # ------------------------------------------------------------------
    # Entscheiden und aufheizen

    @callback
    def _entscheiden(self) -> None:
        if (
            not self._aktiv
            or self.laeuft
            or not self.automatik
            or self._daten.get("gemerkte_sollwerte")
            or (self._wiederherstellung is not None and not self._wiederherstellung.done())
            or self.hass.state is not CoreState.running
            or self.stoerung is not None
        ):
            return
        ausloeser = entscheide(self._lage(), self.plan, pv_aktiv=self.pv_aktiv)
        if ausloeser is not None:
            self._lauf_starten(ausloeser)

    def _grund_text(self, ausloeser: Ausloeser) -> str:
        if ausloeser is Ausloeser.STILLSTAND:
            tage = tage_seit(self.letzte_zapfung, dt_util.utcnow()) or 0.0
            return self._t("grund_stillstand", tage=int(tage))
        return self._t(f"grund_{ausloeser.value}")

    @callback
    def _lauf_starten(self, ausloeser: Ausloeser) -> None:
        jetzt = dt_util.utcnow()
        self._verlauf = Aufheizverlauf(
            start=jetzt,
            erfolg_ab=self.erfolg_ab,
            max_dauer=self.max_dauer,
            hat_heizsensor=self.heizt_id is not None,
        )
        self._lauf_info = {
            "start": jetzt.isoformat(),
            "ausloeser": ausloeser.value,
            "grund": self._grund_text(ausloeser),
        }
        self._von_hand_abgebrochen = False
        self._daten["letzter_versuch"] = jetzt.isoformat()
        self._daten["lauf"] = dict(self._lauf_info)
        self._speichern_bald()
        _LOGGER.info("Legionellen-Aufheizung startet (%s)", self._lauf_info["grund"])
        self._lauf = self.entry.async_create_background_task(
            self.hass, self._async_lauf(), f"{DOMAIN} Aufheizung {self.entry.title}"
        )
        self._aktualisieren()

    async def _async_lauf(self) -> None:
        """Sollwerte anheben, bis zum Ergebnis warten, Sollwerte zurückstellen."""
        verlauf, info = self._verlauf, self._lauf_info
        if verlauf is None or info is None:
            return
        ergebnis = Ergebnis.ABGEBROCHEN
        fehler: str | None = None
        gemerkt: dict[str, float] = {}
        try:
            self._logbuch(self._t("log_start", ziel=zahl(self.sprache, self.ziel), grund=info["grund"]))
            temperatur = self._temperatur()
            if temperatur is not None and temperatur >= self.erfolg_ab:
                verlauf.hoechste_temperatur = temperatur
                ergebnis = Ergebnis.ERFOLGREICH
                return
            gemerkt = self._sollwerte_merken()
            # Erst sicher speichern, dann an der Wärmepumpe drehen: so lassen
            # sich die alten Werte auch nach einem Absturz zurückstellen.
            self._daten["gemerkte_sollwerte"] = dict(gemerkt)
            await self._speicher.async_save(self._kopie())
            await self._async_sollwerte_setzen({eid: self._zielwert(eid) for eid in gemerkt})
            while True:
                neu = verlauf.pruefe(
                    dt_util.utcnow(), self._temperatur(), self._heizt(), self.gesperrt
                )
                self._aktualisieren()
                if neu is not None:
                    ergebnis = neu
                    break
                await asyncio.sleep(PRUEF_INTERVALL_S)
        except asyncio.CancelledError:
            ergebnis = Ergebnis.ABGEBROCHEN
            raise
        except _SollwertFehler as err:
            ergebnis = Ergebnis.FEHLER
            fehler = str(err)
        except Exception as err:
            _LOGGER.exception("Unerwarteter Fehler bei der Legionellen-Aufheizung")
            ergebnis = Ergebnis.FEHLER
            fehler = str(err) or type(err).__name__
        finally:
            try:
                if gemerkt:
                    await self._async_sollwerte_zuruecksetzen(gemerkt)
            finally:
                self._lauf_beenden(ergebnis, fehler)

    @callback
    def _lauf_beenden(self, ergebnis: Ergebnis, fehler: str | None) -> None:
        verlauf, info = self._verlauf, self._lauf_info
        von_hand = self._von_hand_abgebrochen
        self._verlauf = None
        self._lauf_info = None
        self._lauf = None
        self._von_hand_abgebrochen = False
        if info is None:
            return
        ende = dt_util.utcnow()
        start = zeitpunkt_aus_text(info["start"]) or ende
        dauer = max(0, round((ende - start).total_seconds() / 60))
        hoechste = verlauf.hoechste_temperatur if verlauf is not None else None
        if ergebnis is Ergebnis.ERFOLGREICH:
            self._daten["letzte_aufheizung"] = ende.isoformat()
            self._ueber_schwelle = True
        self._daten.pop("lauf", None)
        self._daten["ergebnis"] = ergebnis.value
        self._daten["ergebnis_info"] = {
            "start": info["start"],
            "ende": ende.isoformat(),
            "ausloeser": info["ausloeser"],
            "grund": info["grund"],
            "dauer_minuten": dauer,
            "hoechste_temperatur": hoechste,
            "fehler": fehler,
        }
        self._speichern_bald()
        self._ergebnis_melden(
            ergebnis,
            grund=info["grund"],
            dauer=dauer,
            hoechste=hoechste,
            fehler=fehler,
            von_hand=von_hand,
        )
        self._aktualisieren()

    @callback
    def _ergebnis_melden(
        self,
        ergebnis: Ergebnis,
        *,
        grund: str,
        dauer: int,
        hoechste: float | None,
        fehler: str | None,
        von_hand: bool,
    ) -> None:
        temperatur = zahl(self.sprache, hoechste)
        wichtig = False
        if ergebnis is Ergebnis.ERFOLGREICH:
            titel = self._t("titel_erfolgreich", temperatur=temperatur)
            inhalt = self._t("text_erfolgreich", grund=grund, dauer=dauer)
        elif ergebnis is Ergebnis.ABGEBROCHEN:
            if not von_hand:
                _LOGGER.info(
                    "Legionellen-Aufheizung (%s) wegen Neustart oder Neuladen beendet", grund
                )
                return
            titel = self._t("titel_abgebrochen")
            inhalt = self._t("text_abgebrochen", temperatur=temperatur)
        else:
            wichtig = True
            titel = self._t("titel_fehlschlag")
            if ergebnis is Ergebnis.FEHLER:
                inhalt = self._t("text_fehler", grund=grund, fehler=fehler or "?")
            else:
                inhalt = " ".join(
                    (
                        self._t(f"text_{ergebnis.value}", grund=grund, dauer=dauer, temperatur=temperatur),
                        self._t("zusatz_neuer_versuch"),
                    )
                )
        _LOGGER.info("%s: %s", titel, inhalt)
        self._logbuch(f"{titel}: {inhalt}")
        self._benachrichtigen_senden(titel, inhalt, wichtig=wichtig)

    # ------------------------------------------------------------------
    # Sollwerte

    def _sollwert_lesen(self, eid: str) -> float | None:
        zustand = self.hass.states.get(eid)
        if zustand is None:
            return None
        if eid.startswith("water_heater."):
            return _zahl(zustand.attributes.get("temperature"))
        return _zahl(zustand.state)

    def _sollwerte_merken(self) -> dict[str, float]:
        """Aktuelle Sollwerte merken. Noch offene alte Werte haben Vorrang."""
        offen: dict[str, Any] = self._daten.get("gemerkte_sollwerte") or {}
        gemerkt: dict[str, float] = {}
        for eid in self.sollwert_ids:
            if (alt := _zahl(offen.get(eid))) is not None:
                gemerkt[eid] = alt
                continue
            wert = self._sollwert_lesen(eid)
            if wert is None:
                raise _SollwertFehler(self._t("fehler_sollwert_lesen", entitaet=eid))
            gemerkt[eid] = wert
        return gemerkt

    def _zielwert(self, eid: str) -> float:
        """Zieltemperatur, begrenzt auf das, was die Entität zulässt."""
        zustand = self.hass.states.get(eid)
        if zustand is None:
            return self.ziel
        schluessel = "max_temp" if eid.startswith("water_heater.") else "max"
        hoechst = _zahl(zustand.attributes.get(schluessel))
        if hoechst is not None and hoechst < self.ziel:
            _LOGGER.warning("%s erlaubt höchstens %s °C, setze %s °C", eid, hoechst, hoechst)
            return hoechst
        return self.ziel

    async def _async_sollwert_setzen(self, eid: str, wert: float) -> None:
        domain = eid.split(".", 1)[0]
        if domain == "water_heater":
            await self.hass.services.async_call(
                "water_heater",
                "set_temperature",
                {ATTR_ENTITY_ID: eid, "temperature": wert},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                domain, "set_value", {ATTR_ENTITY_ID: eid, "value": wert}, blocking=True
            )

    async def _async_sollwerte_setzen(self, werte: dict[str, float]) -> None:
        for eid, wert in werte.items():
            try:
                await self._async_sollwert_setzen(eid, wert)
            except Exception as err:
                raise _SollwertFehler(self._t("fehler_sollwert_setzen", entitaet=eid)) from err

    async def _async_sollwerte_zuruecksetzen(self, gemerkt: dict[str, float]) -> None:
        """Alte Sollwerte zurückstellen; was nicht klappt, bleibt für später gemerkt."""
        offen: dict[str, float] = {}
        for eid, wert in gemerkt.items():
            try:
                await self._async_sollwert_setzen(eid, wert)
            except Exception:
                _LOGGER.warning(
                    "%s konnte nicht auf %s zurückgestellt werden, neuer Versuch in einer Minute",
                    eid,
                    wert,
                    exc_info=True,
                )
                offen[eid] = wert
        if offen:
            self._daten["gemerkte_sollwerte"] = offen
        else:
            self._daten.pop("gemerkte_sollwerte", None)
        await self._speicher.async_save(self._kopie())

    @callback
    def _wiederherstellen_falls_noetig(self) -> None:
        """Nach Absturz oder Fehler gemerkte Sollwerte zurückstellen."""
        offen: dict[str, Any] = self._daten.get("gemerkte_sollwerte") or {}
        if (
            not offen
            or self.laeuft
            or (self._wiederherstellung is not None and not self._wiederherstellung.done())
        ):
            return
        bekannt = {
            eid: wert
            for eid, wert in offen.items()
            if eid in self.sollwert_ids and _zahl(wert) is not None
        }
        if len(bekannt) != len(offen):
            _LOGGER.warning(
                "Gemerkte Sollwerte verworfen (nicht mehr eingerichtet): %s",
                ", ".join(sorted(set(offen) - set(bekannt))),
            )
            if bekannt:
                self._daten["gemerkte_sollwerte"] = bekannt
            else:
                self._daten.pop("gemerkte_sollwerte", None)
            self._speichern_bald()
            if not bekannt:
                return
        if any(self._sollwert_lesen(eid) is None for eid in bekannt):
            return  # Wärmepumpe noch nicht erreichbar
        _LOGGER.info("Stelle Sollwerte der unterbrochenen Aufheizung zurück: %s", bekannt)
        self._wiederherstellung = self.entry.async_create_background_task(
            self.hass,
            self._async_sollwerte_zuruecksetzen({eid: float(w) for eid, w in bekannt.items()}),
            f"{DOMAIN} Sollwerte zurückstellen",
        )

    # ------------------------------------------------------------------
    # Meldungen

    def _t(self, schluessel: str, **werte: object) -> str:
        return text(self.sprache, schluessel, **werte)

    @callback
    def _benachrichtigen_senden(self, titel: str, inhalt: str, *, wichtig: bool) -> None:
        for ziel in self.benachrichtigen:
            dienst = ziel.removeprefix("notify.")
            daten: dict[str, Any] = {"title": titel, "message": inhalt}
            if dienst.startswith("mobile_app_"):
                daten["data"] = {
                    "tag": f"{DOMAIN}_{self.entry.entry_id}",
                    "notification_icon": "mdi:bacteria-outline",
                    # Android legt je Kanal eine eigene Wichtigkeit an
                    "channel": "Legionellen" if wichtig else "Legionellen-Info",
                    "importance": "default" if wichtig else "low",
                }
            self.entry.async_create_task(
                self.hass,
                self._async_dienst("notify", dienst, daten),
                name=f"{DOMAIN} Benachrichtigung",
            )

    @callback
    def _logbuch(self, nachricht: str) -> None:
        if "logbook" not in self.hass.config.components:
            return
        daten: dict[str, Any] = {"name": self.entry.title, "message": nachricht}
        status_id = er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, f"{self.entry.entry_id}_status"
        )
        if status_id:
            daten[ATTR_ENTITY_ID] = status_id
        self.entry.async_create_task(
            self.hass, self._async_dienst("logbook", "log", daten), name=f"{DOMAIN} Logbuch"
        )

    async def _async_dienst(self, domain: str, dienst: str, daten: dict[str, Any]) -> None:
        try:
            await self.hass.services.async_call(domain, dienst, daten, blocking=True)
        except (HomeAssistantError, vol.Invalid) as err:
            _LOGGER.warning("Aktion %s.%s fehlgeschlagen: %s", domain, dienst, err)

    # ------------------------------------------------------------------
    # Speichern und Verlauf

    def _kopie(self) -> dict[str, Any]:
        return copy.deepcopy(self._daten)

    @callback
    def _speichern_bald(self) -> None:
        self._speicher.async_delay_save(self._kopie, 5)

    async def _async_verlauf_auswerten(self) -> None:
        """Beim ersten Start die letzte Aufheizung aus dem Verlauf übernehmen."""
        try:
            from homeassistant.components.recorder import (
                get_instance,
                history,
            )

            ende = dt_util.utcnow()
            zustaende = await get_instance(self.hass).async_add_executor_job(
                partial(
                    history.state_changes_during_period,
                    self.hass,
                    ende - timedelta(days=VERLAUF_TAGE),
                    ende,
                    entity_id=self.temperatur_id,
                    no_attributes=True,
                )
            )
        except Exception:
            _LOGGER.debug("Verlauf von %s nicht lesbar", self.temperatur_id, exc_info=True)
            return
        zuletzt: datetime | None = None
        for zustand in zustaende.get(self.temperatur_id, []):
            wert = _zahl(zustand.state)
            if wert is not None and wert >= self.erfolg_ab:
                zuletzt = zustand.last_changed
        if zuletzt is not None and not self._daten.get("letzte_aufheizung"):
            _LOGGER.info("Letzte Aufheizung laut Verlauf: %s", zuletzt)
            self._daten["letzte_aufheizung"] = zuletzt.isoformat()
            self._speichern_bald()
