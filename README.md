# Legionellen-Aufheizung für Home Assistant

Eigene Integration mit Einrichtungsseiten: Sie heizt den Warmwasserspeicher einer
Wärmepumpe regelmäßig auf 60 °C auf – bevorzugt mit PV-Überschuss, spätestens
nach einer Woche notfalls mit Netzstrom – und stellt die Warmwasser-Sollwerte
danach wieder zurück. Alle Entitäten (Speichertemperatur, Sollwerte, PV, Akku …)
wählst du bei der Einrichtung aus.

Version 1.0.0 · geschrieben für Home Assistant 2026.11

---

## So arbeitet sie (Standardwerte)

| Regel | Wann |
|---|---|
| **Mit PV-Überschuss** | ab Tag 5 nach der letzten Aufheizung, zwischen 10:00 und 14:30 Uhr, wenn der Akku mindestens 90 % hat und die PV mindestens 2,5 kW liefert – 10 Minuten am Stück |
| **Pflicht** | spätestens an Tag 7 um 12:30 Uhr, notfalls mit Netzstrom. Ist um 12:30 Uhr eine Sperre aktiv (z. B. EVU), startet sie bis zu 6 Stunden später |
| **Stillstand** | wurde 3 Tage kein Warmwasser gezapft, wird schon früher aufgeheizt (bevorzugt mit PV, sonst zur Pflicht-Uhrzeit) |
| **Von Hand** | Taste „Jetzt aufheizen“ – geht immer, auch bei ausgeschalteter Automatik |

**Ablauf einer Aufheizung**

1. Die aktuellen Sollwerte werden gespeichert – erst dann wird etwas verändert.
2. Alle gewählten Sollwerte (z. B. Komfort und Eco) gehen auf 60 °C.
3. Die Integration wartet, bis der Speicher 59,5 °C erreicht.
4. Danach – und auch bei jedem Abbruch – kommen die alten Sollwerte zurück.

**Abbruch**, wenn die Wärmepumpe nicht innerhalb von 20 Minuten anfängt zu heizen,
vor dem Ziel 15 Minuten lang aufhört oder nach 3,5 Stunden noch nicht fertig ist.
Nach jedem Versuch startet die Automatik frühestens 12 Stunden später wieder.

**Was sie außerdem erkennt**

- **Aufheizungen von außen**: Erreicht der Speicher 59,5 °C auf anderem Weg (z. B.
  durch das eigene Legionellenprogramm der Wärmepumpe), zählt das mit.
- **Zapfungen**: Fällt die Speichertemperatur in 15 Minuten um mindestens 0,3 K,
  während die Wärmepumpe nicht heizt, wurde Warmwasser gezapft.
- **Neustart oder Absturz mitten in der Aufheizung**: Die gespeicherten alten
  Sollwerte werden beim nächsten Start automatisch zurückgestellt.

---

## Installation

### Über den Marketplace (ab Home Assistant 2026.11) bzw. HACS

1. **Marketplace → Über Link hinzufügen** (bei HACS: ⋮ → Benutzerdefinierte
   Repositories) und `https://github.com/bryce2071/PeBs_ha_legionellen` mit dem
   Typ **Integration** eintragen.
2. „Legionellen-Aufheizung“ installieren und Home Assistant neu starten.
3. **Einstellungen → Geräte & Dienste → Integration hinzufügen** und nach
   „Legionellen-Aufheizung“ suchen.
4. Die drei Seiten ausfüllen (siehe unten).
5. Aufs Dashboard: Gerät öffnen → **„Zum Dashboard hinzufügen“**.

### Von Hand

Den Ordner `custom_components/legionellen` nach `/config/custom_components/`
kopieren (z. B. mit der Samba-Freigabe, Studio Code Server oder dem File Editor),
Home Assistant neu starten und weiter bei Schritt 3.

### ⚠️ Vorher: keine zweite Steuerung

An den Warmwasser-Sollwerten darf nur eine Stelle drehen. Gibt es im System schon
eine Automation, die regelmäßig auf 60 °C aufheizt, diese **vorher deaktivieren** –
sonst heizen beide.

- **Testsystem als Kopie eines bestehenden Systems:** Die Kopie spricht über die
  Wärmepumpen-Integration mit derselben echten Wärmepumpe. Dort die Automatik direkt
  nach der Einrichtung ausschalten, solange im Hauptsystem noch eine andere
  Steuerung läuft.
- Eigene Nachheiz-Skripte oder Schalter (z. B. `input_boolean.warmwasser_nachheizen`)
  bei „Nicht starten, solange eingeschaltet“ eintragen.

### Nach der Einrichtung

Die Automatik ist sofort an. Für den Start schaut die Integration 14 Tage in den
Verlauf, wann der Speicher zuletzt 59,5 °C hatte. Findet sie nichts, gilt der
Speicher als fällig und wird beim nächsten PV-Überschuss oder spätestens zur
Pflicht-Uhrzeit aufgeheizt.

---

## Die drei Einrichtungsseiten

Beispielwerte für eine Stiebel-Eltron-Wärmepumpe (Integration „ISG“) und eine
Fronius-PV-Anlage:

### 1. Wärmepumpe und Speicher

| Feld | Beispiel | Hinweis |
|---|---|---|
| Speichertemperatur | `sensor.wp_actual_temperature_water` | Pflicht |
| Warmwasser-Sollwerte | `number.wp_comfort_water_temperature_target`, `number.wp_eco_water_temperature_target` | Pflicht; `number`, `input_number` oder `water_heater` |
| Wärmepumpe heizt Warmwasser | `binary_sensor.wp_is_heating_boiler` | optional, aber empfohlen |
| Nicht starten, solange eingeschaltet | `binary_sensor.wp_power_off` (EVU-Sperre) | optional |
| Zieltemperatur | 60 °C | Der Sollwert muss so hoch gehen dürfen – das wird geprüft |
| Geschafft ab | 59,5 °C | |
| Höchstdauer | 3,5 h | |

### 2. Photovoltaik und Hausakku (optional)

| Feld | Beispiel |
|---|---|
| PV-Leistung | ein oder mehrere Leistungssensoren (werden addiert; W/kW erkannt) |
| Überschuss ab PV-Leistung | 2,5 kW |
| Akku-Ladestand | Ladestand des Hausakkus in % |
| Überschuss ab Ladestand | 90 % |
| Mindestdauer | 10 min |
| PV-Zeitfenster | 10:00 bis 14:30 |

Ohne PV-Angaben heizt die Integration nur zur Pflicht-Uhrzeit.

### 3. Zeitplan und Benachrichtigung

| Feld | Standard |
|---|---|
| Mit PV-Überschuss ab Tag | 5 |
| Spätestens an Tag | 7 (= einmal pro Woche) |
| Uhrzeit der Pflicht-Aufheizung | 12:30 |
| Stillstand ab Tagen ohne Zapfen | 3 (0 = aus) |
| Zapfen erkannt ab Temperaturabfall | 0,3 K in 15 Minuten |
| Benachrichtigen über | z. B. `notify.mobile_app_…` |

Werden Sensoren in den Auswahllisten nicht angezeigt, fehlt ihnen meist die
Geräteklasse (Temperatur, Leistung bzw. Akku).

**Ändern:** Geräte & Dienste → Legionellen-Aufheizung → **Konfigurieren**. Beim
Speichern wird eine laufende Aufheizung abgebrochen und die Sollwerte gehen zurück.

---

## Entitäten

| Entität | Bedeutung |
|---|---|
| Schalter **Automatik** | automatisches Aufheizen an/aus |
| Taste **Jetzt aufheizen** | sofort starten |
| Taste **Aufheizung abbrechen** | stoppen, Sollwerte zurück |
| **Status** | Heizt auf · Fällig · Wartet auf PV-Überschuss · Nicht fällig · Automatik aus · Störung |
| **Letzte Aufheizung** | wann der Speicher zuletzt die Zieltemperatur erreicht hat |
| **Tage seit Aufheizung** | |
| **Spätestens nächste Aufheizung** | Termin der Pflicht-Aufheizung |
| **Letzte Zapfung** / **Tage ohne Zapfung** | Grundlage für die Stillstandserkennung |
| **Letzter Versuch** | Erfolgreich · Wärmepumpe nicht gestartet · Temperatur nicht erreicht · Zeitlimit überschritten · Abgebrochen · Fehler (Details in den Attributen) |
| **Aufheizung läuft** | |
| **PV-Überschuss** | nur, wenn PV oder Akku eingerichtet sind |

**Benachrichtigungen** an die Home Assistant App kommen in zwei Android-Kanälen:
„Legionellen-Info“ (Erfolg, leise) und „Legionellen“ (Probleme). Zusätzlich steht
jeder Start und jedes Ergebnis im Logbuch.

---

## Grenzen

- **Hysterese der Wärmepumpe:** Ist der Speicher schon fast heiß (z. B. 57 °C) und
  die Schalthysterese der Wärmepumpe größer als der Abstand zum Ziel, startet sie
  nicht. Das erscheint als „Wärmepumpe nicht gestartet“; der nächste Versuch kommt
  automatisch.
- **60 °C im Winter:** Viele Wärmepumpen schaffen 60 °C bei Frost nicht allein mit
  dem Verdichter. Dann meldet die Integration „Temperatur nicht erreicht“ mit der
  höchsten erreichten Temperatur. Abhilfe: Heizstab bzw. elektrische
  Nacherwärmung der Wärmepumpe für Warmwasser zulassen oder das Ziel senken.
- Getestet wurde der Ablauf mit nachgebauten Home-Assistant-Schnittstellen (PV,
  Pflicht, Stillstand, Abbruch, Fehler beim Setzen, Neustart mitten im Aufheizen).
  Die erste echte Aufheizung deshalb im Blick behalten.

## Tests

Die Tests laufen ohne Home Assistant (mit Attrappen der benötigten Schnittstellen):

```bash
pip install pytest
python -m pytest tests -q
```

## Entfernen

Geräte & Dienste → Legionellen-Aufheizung → Löschen, dann die Integration im
Marketplace entfernen (bzw. den Ordner `/config/custom_components/legionellen`
löschen) und Home Assistant neu starten.

## Lizenz

MIT
