Astra Dashboard API – Übersicht

Authentifizierung
- Alle Endpunkte verwenden das bestehende Service‑Bearer‑Token (Header). Ohne gültigen Schlüssel bleibt die API geschlossen.
- Zusätzlich muss die `user_id` des Dashboard‑Benutzers als Query‑Parameter oder Header `X-User-ID` übermittelt werden, um Guild‑Berechtigungen zu prüfen.

Autorisierung und Sicherheit
- Jeder Guild‑bezogene Request prüft:
  - Mitgliedschaft/Zugriff auf die angefragte Guild
  - erforderliche Berechtigungen (z. B. Administrator/Manage Guild) gemäß implementierter Prüfungen
- Einheitliche Fehlerstruktur: `{ success: false, code, error? }`
- Einheitliche Statuscodes: 400 (ungültige Parameter), 401 (fehlende Auth), 403 (fehlende Rechte), 404 (nicht gefunden), 405 (Methode), 500 (Serverfehler), 503/504 (Service/Timeout)

Pfadkonventionen
- Server‑Ressourcen: `/servers/{guild_id}/…`
- Ticketsystem: `/tickets/...`
- Interne Bot‑Operationen laufen über lokalen IPC und sind von der externen API entkoppelt.

Rate Limiting
- Kritische Endpoints sind limitiert (z. B. `tickets_publish`, `tickets_panel_delete`, `server_members`). Weitere Limits können ergänzt werden.

Dokumentation
- Server‑Ressourcen: siehe `SERVER.md`
- Ticket‑Panels: siehe `TICKETS.md`
