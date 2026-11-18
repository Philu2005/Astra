Endpoint-Inventur (Astra Dashboard API)

Hinweis: Diese Inventur spiegelt den aktuellen Codezustand in diesem Repository wider. Server‑/E2E‑Tests wurden lokal nicht gegen den produktiven VPS ausgeführt.

| Methode | Endpoint | Status | Zweck | Dashboard-Verwendung | IPC | Authentifizierung | Verifikation |
|---|---|---|---|---|---|---|---|
| GET | /servers/{guild_id} | Bereits vorhanden | Serverdetails abrufen | Server-Detailseite, Rechteprüfung | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /servers/{guild_id}/roles | Bereits vorhanden | Rollen abrufen | Dropdowns für Support‑Rolle | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /servers/{guild_id}/channels | Bereits vorhanden | Kanäle abrufen | Kanal-/Zielauswahl | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /servers/{guild_id}/categories | Bereits vorhanden | Kategorien abrufen | Ticket‑Kategorieauswahl | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /servers/{guild_id}/members | Neu implementiert | Mitglieder abrufen (paginiert) | Ressourcenliste (kein Ticket‑Feature) | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /tickets/panels/{guild_id} | Bereits vorhanden | Panels des Servers listen | Panel-Übersicht | keine | Service‑Bearer + user_id | Statisch geprüft |
| GET | /tickets/panels/{guild_id}/status | Bereits vorhanden | Veröffentlichungsstatus je Panel | UI‑Statusanzeigen | keine | Service‑Bearer + user_id | Statisch geprüft |
| POST | /tickets/panels/{guild_id}/publish | Bereits vorhanden | Panel veröffentlichen | Panel anlegen/veröffentlichen | /ipc/panel/publish | Service‑Bearer + user_id | Statisch geprüft |
| PUT | /tickets/panels/{guild_id}/{channel_id}/update | Bereits vorhanden | Panel‑Texte aktualisieren | Titel/Beschreibung anpassen | /ipc/panel/update | Service‑Bearer + user_id | Statisch geprüft |
| PUT | /tickets/panels/{guild_id}/{channel_id}/config | Überarbeitet | Meta ändern/Panel verschieben | Thema/Rolle/Kategorie setzen, Move | /ipc/panel/move | Service‑Bearer + user_id | Statisch geprüft |
| DELETE | /tickets/panels/{guild_id}/{channel_id}/{message_id} | Neu implementiert | Panel löschen (Discord + DB) | Panel entfernen | /ipc/panel/delete | Service‑Bearer + user_id | Statisch geprüft |

Neue Dateien
- docs/api/TICKETS.md (neu in dieser Session)
- docs/api/SERVER.md (neu)
- docs/api/README.md (neu)
- docs/api/INVENTORY.md (diese Datei)

Geänderte Dateien
- api/routes.py (neuer Members‑Endpoint; Delete/Move‑Flows für Panels zuvor überarbeitet)
- utils/ipc_server.py (IPC‑Route /ipc/panel/delete zuvor ergänzt)

Nicht implementierte Punkte / Hinweise
- Mitglieder-Endpunkt benötigt Discord Members‑Intent. Ohne Intent wird `503 Members intent unavailable` zurückgegeben.
- Die Spalte `panelMsgID` ist in einigen lokalen Schemata evtl. nicht vorhanden. Code behandelt dies über Fallback‑SELECT; Migration nur bei Bedarf.
- Tests: Siehe geplante Testabdeckung in der Aufgabenbeschreibung; vollständige Ausführung gegen Live‑Umgebung nicht Teil dieser Session.
