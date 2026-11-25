"""Einrichtungsseiten der Legionellen-Aufheizung."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import time
import math
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

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
    DEFAULT_NAME,
    DOMAIN,
    SCHLUESSEL_PV,
    SCHLUESSEL_WAERMEPUMPE,
    SCHLUESSEL_ZEITPLAN,
    STANDARDWERTE,
)
from .logic import zeit_aus_text

try:  # Ab Home Assistant 2025.8 lädt die Integration nach dem Speichern selbst neu.
    from homeassistant.config_entries import OptionsFlowWithReload as _OptionenBasis

    NEU_LADEN_EINGEBAUT = True
except ImportError:  # pragma: no cover – ältere Versionen
    from homeassistant.config_entries import OptionsFlow as _OptionenBasis  # type: ignore[assignment]

    NEU_LADEN_EINGEBAUT = False

_LEERE_PLATZHALTER: dict[str, str] = {"entitaet": "", "maximum": ""}


# ----------------------------------------------------------------------
# Felder


def _zahl_feld(
    minimum: float, maximum: float, schritt: float, einheit: str | None = None
) -> selector.NumberSelector:
    konfig: dict[str, Any] = {
        "min": minimum,
        "max": maximum,
        "step": schritt,
        "mode": selector.NumberSelectorMode.BOX,
    }
    if einheit:
        konfig["unit_of_measurement"] = einheit
    return selector.NumberSelector(selector.NumberSelectorConfig(**konfig))


def _entitaet_feld(
    domain: str | list[str], *, geraeteklasse: str | None = None, mehrere: bool = False
) -> selector.EntitySelector:
    filter_: dict[str, Any] = {"domain": domain}
    if geraeteklasse:
        filter_["device_class"] = geraeteklasse
    return selector.EntitySelector(
        selector.EntitySelectorConfig(filter=filter_, multiple=mehrere)  # type: ignore[typeddict-item]
    )


def _schema_waermepumpe(mit_name: bool) -> vol.Schema:
    felder: dict[vol.Marker, Any] = {}
    if mit_name:
        felder[vol.Required(CONF_NAME, default=DEFAULT_NAME)] = selector.TextSelector()
    felder.update(
        {
            vol.Required(CONF_TEMPERATUR): _entitaet_feld("sensor", geraeteklasse="temperature"),
            vol.Required(CONF_SOLLWERTE): _entitaet_feld(
                ["number", "input_number", "water_heater"], mehrere=True
            ),
            vol.Optional(CONF_HEIZT): _entitaet_feld("binary_sensor"),
            vol.Optional(CONF_SPERREN): _entitaet_feld(
                ["binary_sensor", "input_boolean", "switch", "script"], mehrere=True
            ),
            vol.Required(CONF_ZIEL, default=STANDARDWERTE[CONF_ZIEL]): _zahl_feld(45, 75, 0.5, "°C"),
            vol.Required(CONF_ERFOLG_AB, default=STANDARDWERTE[CONF_ERFOLG_AB]): _zahl_feld(
                40, 75, 0.1, "°C"
            ),
            vol.Required(CONF_MAX_DAUER, default=STANDARDWERTE[CONF_MAX_DAUER]): _zahl_feld(
                0.5, 8, 0.5, "h"
            ),
        }
    )
    return vol.Schema(felder)


def _schema_pv() -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_PV): _entitaet_feld("sensor", geraeteklasse="power", mehrere=True),
            vol.Required(CONF_PV_AB, default=STANDARDWERTE[CONF_PV_AB]): _zahl_feld(0, 50, 0.1, "kW"),
            vol.Optional(CONF_AKKU): _entitaet_feld("sensor", geraeteklasse="battery"),
            vol.Required(CONF_AKKU_AB, default=STANDARDWERTE[CONF_AKKU_AB]): _zahl_feld(0, 100, 1, "%"),
            vol.Required(CONF_PV_DAUER, default=STANDARDWERTE[CONF_PV_DAUER]): _zahl_feld(
                0, 60, 1, "min"
            ),
            vol.Required(CONF_PV_VON, default=STANDARDWERTE[CONF_PV_VON]): selector.TimeSelector(),
            vol.Required(CONF_PV_BIS, default=STANDARDWERTE[CONF_PV_BIS]): selector.TimeSelector(),
        }
    )


def _notify_auswahl(hass: HomeAssistant, gewaehlt: list[str]) -> list[selector.SelectOptionDict]:
    """Benachrichtigungsdienste (notify.*) zur Auswahl anbieten."""
    dienste = hass.services.async_services().get("notify", {})
    werte = [f"notify.{name}" for name in sorted(dienste) if name != "send_message"]
    werte.extend(wert for wert in gewaehlt if wert not in werte)
    return [
        selector.SelectOptionDict(value=wert, label=wert.removeprefix("notify."))
        for wert in werte
    ]


def _schema_zeitplan(hass: HomeAssistant, gewaehlt: list[str]) -> vol.Schema:
    felder: dict[vol.Marker, Any] = {
        vol.Required(CONF_PV_AB_TAG, default=STANDARDWERTE[CONF_PV_AB_TAG]): _zahl_feld(
            1, 14, 0.5, "d"
        ),
        vol.Required(CONF_SPAETESTENS_TAG, default=STANDARDWERTE[CONF_SPAETESTENS_TAG]): _zahl_feld(
            1, 30, 0.5, "d"
        ),
        vol.Required(
            CONF_PFLICHT_UHRZEIT, default=STANDARDWERTE[CONF_PFLICHT_UHRZEIT]
        ): selector.TimeSelector(),
        vol.Required(CONF_STILLSTAND_TAGE, default=STANDARDWERTE[CONF_STILLSTAND_TAGE]): _zahl_feld(
            0, 14, 0.5, "d"
        ),
        vol.Required(CONF_ZAPF_SCHWELLE, default=STANDARDWERTE[CONF_ZAPF_SCHWELLE]): _zahl_feld(
            0.1, 5, 0.1, "K"
        ),
    }
    if auswahl := _notify_auswahl(hass, gewaehlt):
        felder[vol.Optional(CONF_BENACHRICHTIGEN)] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=auswahl,
                multiple=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
                sort=True,
            )
        )
    return vol.Schema(felder)


# ----------------------------------------------------------------------
# Prüfungen


def _als_zahl(wert: Any) -> float | None:
    try:
        ergebnis = float(wert)
    except (TypeError, ValueError):
        return None
    return ergebnis if math.isfinite(ergebnis) else None


def _pruefe_waermepumpe(
    hass: HomeAssistant, eingabe: Mapping[str, Any], eigener_eintrag: str | None
) -> tuple[dict[str, str], dict[str, str]]:
    fehler: dict[str, str] = {}
    platzhalter = dict(_LEERE_PLATZHALTER)
    ziel = float(eingabe[CONF_ZIEL])
    if not eingabe.get(CONF_SOLLWERTE):
        fehler[CONF_SOLLWERTE] = "keine_sollwerte"
    if float(eingabe[CONF_ERFOLG_AB]) > ziel:
        fehler[CONF_ERFOLG_AB] = "erfolg_ueber_ziel"
    for eid in eingabe.get(CONF_SOLLWERTE) or []:
        zustand = hass.states.get(eid)
        if zustand is None:
            continue
        schluessel = "max_temp" if eid.startswith("water_heater.") else "max"
        maximum = _als_zahl(zustand.attributes.get(schluessel))
        if maximum is not None and maximum < ziel:
            fehler[CONF_ZIEL] = "ziel_zu_hoch"
            platzhalter = {"entitaet": zustand.name, "maximum": f"{maximum:g}"}
            break
    for eintrag in hass.config_entries.async_entries(DOMAIN):
        if (
            eintrag.entry_id != eigener_eintrag
            and eintrag.options.get(CONF_TEMPERATUR) == eingabe.get(CONF_TEMPERATUR)
        ):
            fehler[CONF_TEMPERATUR] = "schon_verwendet"
    return fehler, platzhalter


def _pruefe_pv(eingabe: Mapping[str, Any]) -> dict[str, str]:
    von = zeit_aus_text(eingabe.get(CONF_PV_VON), time(10, 0))
    bis = zeit_aus_text(eingabe.get(CONF_PV_BIS), time(14, 30))
    return {CONF_PV_BIS: "pv_fenster"} if von >= bis else {}


def _pruefe_zeitplan(eingabe: Mapping[str, Any]) -> dict[str, str]:
    if float(eingabe[CONF_PV_AB_TAG]) > float(eingabe[CONF_SPAETESTENS_TAG]):
        return {CONF_PV_AB_TAG: "pv_nach_pflicht"}
    return {}


def _uebernehmen(ziel: dict[str, Any], eingabe: Mapping[str, Any], schluessel: tuple[str, ...]) -> None:
    """Eingaben übernehmen; geleerte optionale Felder werden entfernt."""
    for key in schluessel:
        wert = eingabe.get(key)
        if wert is None or wert in ("", []):
            ziel.pop(key, None)
        else:
            ziel[key] = wert


# ----------------------------------------------------------------------
# Einrichtung


class LegionellenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Neuen Speicher einrichten (drei Seiten)."""

    VERSION = 1

    def __init__(self) -> None:
        """Eingaben der Seiten sammeln."""
        self._daten: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> LegionellenOptionsFlow:
        """Einstellungen später ändern."""
        return LegionellenOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Seite 1: Wärmepumpe und Speicher."""
        fehler: dict[str, str] = {}
        platzhalter = dict(_LEERE_PLATZHALTER)
        if user_input is not None:
            fehler, platzhalter = _pruefe_waermepumpe(self.hass, user_input, None)
            if not fehler:
                self._daten[CONF_NAME] = user_input.get(CONF_NAME) or DEFAULT_NAME
                _uebernehmen(self._daten, user_input, SCHLUESSEL_WAERMEPUMPE)
                return await self.async_step_pv()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _schema_waermepumpe(mit_name=True), user_input or {}
            ),
            errors=fehler,
            description_placeholders=platzhalter,
        )

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Seite 2: Photovoltaik und Hausakku."""
        fehler: dict[str, str] = {}
        if user_input is not None:
            fehler = _pruefe_pv(user_input)
            if not fehler:
                _uebernehmen(self._daten, user_input, SCHLUESSEL_PV)
                return await self.async_step_zeitplan()
        return self.async_show_form(
            step_id="pv",
            data_schema=self.add_suggested_values_to_schema(_schema_pv(), user_input or {}),
            errors=fehler,
        )

    async def async_step_zeitplan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Seite 3: Zeitplan und Benachrichtigung."""
        fehler: dict[str, str] = {}
        if user_input is not None:
            fehler = _pruefe_zeitplan(user_input)
            if not fehler:
                _uebernehmen(self._daten, user_input, SCHLUESSEL_ZEITPLAN)
                titel = str(self._daten.pop(CONF_NAME, "") or "").strip() or DEFAULT_NAME
                return self.async_create_entry(title=titel, data={}, options=self._daten)
        return self.async_show_form(
            step_id="zeitplan",
            data_schema=self.add_suggested_values_to_schema(
                _schema_zeitplan(self.hass, []), user_input or {}
            ),
            errors=fehler,
        )


class LegionellenOptionsFlow(_OptionenBasis):
    """Einstellungen eines eingerichteten Speichers ändern."""

    def __init__(self) -> None:
        """Änderungen der Seiten sammeln."""
        self._optionen: dict[str, Any] = {}

    def _aktuell(self) -> dict[str, Any]:
        if not self._optionen:
            self._optionen = {**STANDARDWERTE, **self.config_entry.options}
        return self._optionen

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Seite 1: Wärmepumpe und Speicher."""
        optionen = self._aktuell()
        fehler: dict[str, str] = {}
        platzhalter = dict(_LEERE_PLATZHALTER)
        if user_input is not None:
            fehler, platzhalter = _pruefe_waermepumpe(
                self.hass, user_input, self.config_entry.entry_id
            )
            if not fehler:
                _uebernehmen(optionen, user_input, SCHLUESSEL_WAERMEPUMPE)
                return await self.async_step_pv()
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                _schema_waermepumpe(mit_name=False), user_input or optionen
            ),
            errors=fehler,
            description_placeholders=platzhalter,
        )

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Seite 2: Photovoltaik und Hausakku."""
        optionen = self._aktuell()
        fehler: dict[str, str] = {}
        if user_input is not None:
            fehler = _pruefe_pv(user_input)
            if not fehler:
                _uebernehmen(optionen, user_input, SCHLUESSEL_PV)
                return await self.async_step_zeitplan()
        return self.async_show_form(
            step_id="pv",
            data_schema=self.add_suggested_values_to_schema(_schema_pv(), user_input or optionen),
            errors=fehler,
        )

    async def async_step_zeitplan(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Seite 3: Zeitplan und Benachrichtigung."""
        optionen = self._aktuell()
        fehler: dict[str, str] = {}
        if user_input is not None:
            fehler = _pruefe_zeitplan(user_input)
            if not fehler:
                _uebernehmen(optionen, user_input, SCHLUESSEL_ZEITPLAN)
                return self.async_create_entry(title="", data=optionen)
        gewaehlt = list(optionen.get(CONF_BENACHRICHTIGEN) or [])
        return self.async_show_form(
            step_id="zeitplan",
            data_schema=self.add_suggested_values_to_schema(
                _schema_zeitplan(self.hass, gewaehlt), user_input or optionen
            ),
            errors=fehler,
        )
