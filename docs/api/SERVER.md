Server-Ressourcen (Dashboard API)

Hinweise
- Alle Endpunkte erfordern Service-Authentifizierung (API-Key im Header) und prüfen die Berechtigung des aufrufenden Benutzers per `user_id` gegen den synchronisierten Guild-Snapshot.
- Antworten enthalten immer `success: true|false`. Fehler liefern zusätzlich einen stabilen `code` und optional `error`.

GET /servers/{guild_id}
- Zweck: Basis-Infos zu einem Server (interne Nutzung, Detailansicht im Dashboard)
- Auth: Service‑Bearer + `user_id` als Query oder Header `X-User-ID`
- Rechte: Mitgliedschaft + ausreichende Rechte (Admin/Manage Guild, abhängig von Implementierung der Prüfung)
- Response: `{ success, server: { id, name, icon, permissions, ... } }`
- Fehler: 400 invalid/fehlender user_id, 403 permission_denied, 404 server_not_found, 503 service_unavailable

GET /servers/{guild_id}/roles
- Zweck: Rollenliste für Auswahlfelder
- Auth/Rechte: wie oben
- Response: `{ success, roles: [{ id, name, color }] }` (`@everyone` wird ausgelassen)
- Fehler: 400, 403, 404, 503, 500 (Fetch-Fehler)

GET /servers/{guild_id}/channels
- Zweck: Kanäle inkl. Typ und Parent-ID (Kategorie) für Zielauswahl
- Auth/Rechte: wie oben
- Response: `{ success, channels: [{ id, name, type, parent_id|null }] }`
- Fehler: 400, 403, 404, 503, 500

GET /servers/{guild_id}/categories
- Zweck: Kategorien für Ticket-Kategorie-Auswahl
- Auth/Rechte: wie oben
- Response: `{ success, categories: [{ id, name }] }`
- Fehler: 400, 403, 404, 503, 500

GET /servers/{guild_id}/members
- Zweck: Mitgliederliste als Dashboard-Ressource (kein Ticket-Feature!)
- Auth/Rechte: wie oben
- Query-Parameter:
  - `user_id` (erforderlich): ID des Dashboard-Benutzers
  - `limit` (optional, default 50, max 200): Anzahl Einträge
  - `after` (optional): Cursor als Snowflake (exklusiv) für Pagination
- Response: `{ success, members: [{ id, username, display_name, avatar }], next_after|null }`
- Besonderheiten: Erfordert Discord Intent Members. Ohne Intent → `503 Members intent unavailable`. Bei Discord 403 → `403 Forbidden by Discord`.
- Fehler: 400 invalid limit/after/user_id, 403, 404, 503, 504, 500

Sicherheit
- Authentifizierung: Service‑Bearer‑Token (bestehendes Astra‑Schema)
- Autorisierung: Guild‑Zugriff und Berechtigungen über den synchronisierten Snapshot (keine Fremdzugriffe)
- Rate Limits: server_members Endpoint ist limitiert (10/60s); weitere Limits können zentral ergänzt werden
