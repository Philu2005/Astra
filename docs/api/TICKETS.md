# Tickets: Panel-Konfiguration und -Verwaltung (Dashboard API)

Diese Datei beschreibt die API-Endpunkte zur Verwaltung von Ticket-Panels. Operative Ticket-Aktionen (öffnen, schließen, claimen, Reopen, Transcripts etc.) sind nicht Teil dieser API und verbleiben im Bot.

Hinweise:
- Alle Endpunkte verlangen Service-Auth (Header/API-Key) und prüfen Benutzerrechte gegen den synchronisierten Guild-Snapshot.
- Fehler werden als JSON mit `success=false` und stabilem `code` zurückgegeben.
- Bot-Operationen (Publish/Update/Move/Delete) erfolgen lokal über den internen IPC-Kanal. Zeitüberschreitungen und Berechtigungsfehler werden differenziert gemeldet.

## Ressourcenauflistung fürs Dashboard

- GET `/servers/<guild_id>` – Guild-Details (interne Nutzung)
- GET `/servers/<guild_id>/roles` – Rollen
- GET `/servers/<guild_id>/channels` – Textkanäle
- GET `/servers/<guild_id>/categories` – Channel-Kategorien

## Panels lesen

- GET `/tickets/panels/<guild_id>`
  - Antwort: `panels: [{ channel_id, category_id|null, role_id|null, thema, panel_message_id|null, channel_name?, category_name?, role_name? }]`

- GET `/tickets/panels/<guild_id>/status`
  - Antwort: `status` für jedes Panel: `published` wenn `panel_message_id` bekannt, sonst `not_published`.

## Panel veröffentlichen

- POST `/tickets/panels/<guild_id>/publish?user_id=<id>`
  - Body: `{ channel_id, category_id, role_id, title, description }`
  - Validiert Zugehörigkeit des Zielkanals. Verhindert parallele Publishes (Idempotenzfenster).
  - Antwort: `{ success, status: "published", channel_id, message_id }`
  - Konflikt: `409 already_published` wenn Panel bereits mit Message-ID existiert.

## Panel-Text bearbeiten (Embed)

- PUT `/tickets/panels/<guild_id>/<channel_id>/update?user_id=<id>`
  - Body: `{ title?, description? }` (mind. ein Feld)
  - Erfordert vorhandene `panel_message_id` in der DB.
  - Antwort: `{ success, status: "updated" }`
  - `410 gone` wenn Nachricht nicht mehr existiert.

## Panel-Konfiguration anpassen / verschieben

- PUT `/tickets/panels/<guild_id>/<channel_id>/config?user_id=<id>`
  - Body (beliebige Teilmenge): `{ title?, description?, thema?, role_id?, category_id?, new_channel_id? }`
  - Ohne `new_channel_id`: 
    - Aktualisiert DB-Felder (`thema`, `roleID`, `categoryID`) und bei Bedarf den Panel-Text per Update-Flow.
  - Mit `new_channel_id` (Move-Flow):
    - Bot postet das Panel im Zielkanal (neue Message), setzt dort `panelMsgID`.
    - DB: Setzt optional Metadaten für den neuen Kanal und löscht die alte Panel-Zeile, um Duplikate zu vermeiden.
    - Antwort: `{ success, status: "moved" | "moved_old_delete_failed" | "moved_db_update_failed", channel_id, message_id }`

## Panel löschen

- DELETE `/tickets/panels/<guild_id>/<channel_id>/<message_id>?user_id=<id>`
  - Ablauf und Garantien:
    1) Berechtigungen prüfen.
    2) Optional: Plausibilisierung gegen gespeicherte `panel_message_id` (falls vorhanden). Weicht sie ab → `409 conflict_message_id`.
    3) Bot versucht, die Discord-Nachricht zu löschen.
       - Ist sie bereits weg (`404/NotFound`) → trotzdem fortfahren.
       - Fehlende Rechte (`403`) → Abbruch, DB bleibt unverändert.
    4) Löscht die Panel-Zeile aus `ticketsystem`.
    5) Löscht niemals aktive Tickets aus `ticketsystem_channels`.
  - Antwort: `{ success, status: "deleted" | "message_missing" }`

## Fehlercodes (Auszug)

- `service_unavailable` – Bot/Guild-Snapshot nicht bereit
- `permission_denied` – unzureichende Berechtigungen
- `invalid_user_id` / `invalid_payload` – ungültige Parameter
- `server_not_found` / `invalid_channel` – ungültige Guild/Kanalangabe
- `already_published` – Konflikt bei Publish
- `not_published` – kein veröffentlichtes Panel für Update/Move
- `timeout` – Zeitüberschreitung bei Bot-Operation
- `ipc_unavailable` – lokaler IPC nicht erreichbar
- `move_failed` / `update_failed` / `publish_failed` / `delete_failed` – generische Bot-Fehler
- `conflict_message_id` – angegebene Message-ID weicht von der DB ab
- `db_delete_failed` – Panel konnte nach Bot-Löschung nicht aus der DB entfernt werden

## Hinweise zu Datenbankfeldern

- Tabelle `ticketsystem` enthält u. a. `guildID`, `channelID`, `categoryID`, `roleID`, `thema`.
- Das optionale Feld `panelMsgID` wird vom Bot beim Veröffentlichen gesetzt (Migration ggf. notwendig). Die API liest es best-effort und toleriert dessen Abwesenheit.

## Nicht umfasst

- Tickets öffnen/schließen/claimen/reopen, Transcripts, Auto-Close/Reminder/Ping-Throttle – verbleiben im Bot und sind hier nicht Gegenstand.
