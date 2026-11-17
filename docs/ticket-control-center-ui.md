# Ticket-Control-Center (Discord UI)

Diese Datei beschreibt Aufbau und Verhalten der neuen, interaktiven Ticket-Oberflächen in Discord.

## Befehle

- /ticket config
  - Öffnet ein ephemeres Control‑Center (ConfigCenterView) mit Tabs:
    1. Übersicht (Thema, Kanal, Rolle, Kategorie, Status, Message‑ID)
    2. Panel bearbeiten (Texte via Modal; aktualisiert bestehende Nachricht wenn `panelMsgID` vorhanden ist)
    3. Discord‑Zuordnungen (Role‑Select, Category‑Select, Verschieben in anderen Textkanal)
    4. Ticket‑Einstellungen (`autoclose_hours`, `reopen_hours` – Werte per Modal setzen)
    5. Erinnerungen (`remind_minutes`, `ping_throttle_minutes` – 0=deaktiviert)
    6. Protokollierung (aktuellen Log‑Kanal anzeigen/setzen/deaktivieren)

- /ticket anzeigen
  - Öffnet eine interaktive Übersicht (PanelOverviewView) mit Dropdown zur Panel‑Auswahl, Details und Aktionen (Status aktualisieren, Wechsel ins Control‑Center).

## Sicherheits- und Validierungslogik

- Alle Interaktionen sind ephemer und erfordern Manage‑Channels/Manage‑Guild Berechtigungen wie im Command dekoriert.
- Kanal‑/Rollen‑/Kategorie‑Auswahlen basieren auf echten Discord‑Objekten der aktuellen Guild (RoleSelect/ChannelSelect).
- Panel‑Verschieben erfolgt sicher: Neue Nachricht im Zielkanal veröffentlichen → neue IDs speichern → alte Nachricht löschen (Best‑Effort) → alter Datensatz entfernt. Bei Teilfehlern erfolgt verständliche Rückmeldung; alter Zustand bleibt erhalten.

## Abhängigkeiten

- Schreiben/Lesen erfolgt über die bestehenden Tabellen `ticketsystem`, `ticketlog`, `ticket_config`; es werden keine Migrationen ausgeführt.
- Aktualisierung der bestehenden Panel‑Nachricht benötigt `panelMsgID` (falls Spalte noch fehlt, wird nur der Text gespeichert und darauf hingewiesen).

## Tests (lokal)

- /ticket config ohne/mit mehreren Panels: Auswahl, Tab‑Wechsel, Modals öffnen/speichern.
- Discord‑Zuordnungen: Rolle/Kategorie ändern; Zielkanal verschieben (Fehlerpfade: fehlende Rechte, Löschen alter Nachricht fehlgeschlagen).
- Ticket‑Einstellungen/Erinnerungen: Werte speichern (Ganzzahlen), 0 als Deaktivierung.
- /ticket anzeigen: Auswahl und Detailanzeige, Wechsel ins Control‑Center.

Bekannte Einschränkungen: Ohne ausgerollte `panelMsgID`‑Spalte kann die Aktualisierung der bestehenden Panel‑Nachricht nicht durchgeführt werden; in diesem Fall wird nur die Konfiguration gespeichert und eine Info ausgegeben.
