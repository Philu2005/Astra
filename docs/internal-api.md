
Request
```http
GET /tickets/panels/1141116981697859736?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
```

Response (`200 OK`)
```json
{
  "success": true,
  "count": 1,
  "panels": [
    {
      "channel_id": 122233344455566677,
      "channel_name": "support-panel",
      "category_id": 133344455566677788,
      "category_name": "Tickets",
      "role_id": 144455566677788899,
      "role_name": "Support",
      "thema": "Support"
    }
  ]
}
```

Fehlerfälle: wie oben (`400`/`403`/`404`/`503`/`500`).

Hinweise:
- `channel_name`, `category_name`, `role_name` werden nur ergänzt, wenn sie im synchronisierten Guild‑Snapshot vorhanden sind.
- Panel‑Texte im Embed werden im Bot erzeugt; in der DB steht als thematischer Titel `thema`.

#### `GET /tickets/status/{guild_id}`
- Zweck: Offene Tickets einer Guild abrufen.
- Datenquelle: `ticketsystem_channels` (nur offene Tickets; geschlossene werden entfernt).

Request
```http
GET /tickets/status/1141116981697859736?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
```

Response (`200 OK`)
```json
{
  "success": true,
  "count": 1,
  "open_tickets": [
    {
      "channel_id": 155566677788899900,
      "message_id": 166677788899900011,
      "opened_by": 123456789012345678,
      "claimed_by": 234567890123456789,
      "opened_at": "15. November 2026 21:00"
    }
  ]
}
```

Fehlerfälle: wie oben (`400`/`403`/`404`/`503`/`500`).

Anmerkungen:
- `claimed_by` kann `null` sein (oder fehlt im Bot als "Not Set"). Die API normalisiert auf `null`.
- Geschlossene Tickets werden im Bot entfernt; es gibt keine persistente Historie außer den Log‑Nachrichten im `ticketlog`‑Kanal.

#### Ticket-Log verwalten

`GET /tickets/log/{guild_id}`
- Zweck: Aktuell konfigurierten Ticket‑Log‑Kanal abrufen (falls gesetzt).

Response (`200 OK`)
```json
{ "success": true, "channelId": "122233344455566677" }
```

`PUT /tickets/log/{guild_id}`
- Zweck: Ticket‑Log‑Kanal setzen/ändern.
- Body:
```json
{ "channel_id": 122233344455566677 }
```

`DELETE /tickets/log/{guild_id}`
- Zweck: Ticket‑Log‑Kanal entfernen (deaktivieren).

Fehlerfälle (für alle drei): `400` ungültige/fehlende Werte, `403`/`404`/`503`/`500` gemäß Schema.

Backend-/Bot-Zuordnung:
- Beim Schließen eines Tickets erzeugt der Bot ein Text‑Transkript (.log) und sendet es in den konfigurierten `ticketlog`‑Kanal. Zusätzlich wird eine Reopen‑Aktion mit Ablauf gemäß `reopen_hours` angeboten.

---

---

## 5. Thread-Sicherheit & Discord-Kommunikation

- Die API läuft im Waitress WSGI-Server in einem separaten Thread.
- Zugriffe auf den Bot-Guild-Cache sind über Locks geschützt.
- Eventuelle asynchrone Discord-Mitgliederabfragen werden über `asyncio.run_coroutine_threadsafe` mit einem Timeout von 5 Sekunden im Discord Event-Loop ausgeführt.
- Wenn eine Abfrage wegen API-Fehler, Nichterreichbarkeit oder Timeout fehlschlägt, verweigert Astra den Zugriff sicher mit `403 Forbidden` oder `404 Not Found` (keine unsicheren Fallbacks).

---

## 6. Integrations-Hinweise für das Dashboard-Backend

1. **Session-Validierung:** Ermittle die `user_id` stets serverseitig aus einer authentifizierten Session (z. B. Discord OAuth2 Access Token). Vertraue niemals ungesicherten Angaben aus dem Client/Frontend.
2. **API-Schlüssel-Schutz:** Der `ASTRA_INTERNAL_API_KEY` darf ausschließlich serverseitig in Umgebungsvariablen des Dashboard-Backends liegen und niemals im Frontend-Code oder in Logdateien auftauchen.
3. **Netzwerk:** Die Kommunikation findet rein über `http://127.0.0.1:5000` auf demselben Host bzw. internen Netzwerk statt.

#### `POST /tickets/panels/{guild_id}/publish`
- Zweck: Ein Ticket-Panel konfigurieren, im Zielkanal veröffentlichen und die echte Discord-Message-ID speichern.
- Auth/Berechtigung: wie oben; veröffentlicht wird nur, wenn der Bot online ist und ausreichende Kanalrechte hat.

Request
```http
POST /tickets/panels/1141116981697859736/publish?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
Content-Type: application/json

{
  "channel_id": 122233344455566677,
  "category_id": 199988877766655544,
  "role_id": 144455566677788899,
  "title": "Support",
  "description": "Stelle hier deine Fragen an das Team."
}
```

Response (`200 OK`)
```json
{
  "success": true,
  "published": {
    "message_id": 121212121212121212,
    "channel_id": 122233344455566677
  }
}
```

Fehlerfälle:
- `400` fehlende/ungültige Felder; Kanal gehört nicht zur Guild.
- `403` unzureichende Berechtigungen.
- `404` unbekannte Guild.
- `409` bereits veröffentlicht (`status: "already_published"`).
- `409` fehlende Discord-Rechte (z. B. `Embed Links`) mit `status: "permission_error"`.
- `503` Bot/Service nicht bereit.
- `504` Timeout (`status: "timeout"`).
- `500` generischer Veröffentlichungsfehler (`status: "publish_failed"`).

Hinweise:
- Die tatsächliche Nachricht wird vom bestehenden Bot erstellt; es werden keine Bot-Tokens offengelegt.
- Die veröffentlichte Message-ID wird in `ticketsystem.panelMsgID` persistiert (Migration erforderlich, siehe opt/migrations).

#### `PUT /tickets/panels/{guild_id}/{channel_id}/update`
- Zweck: Vorhandenes veröffentlichtes Panel (Embed/Komponenten) aktualisieren.
- Verhalten: Beibehaltung der bestehenden Message-ID. Wenn die Nachricht fehlt, `410 Gone`.

Request
```http
PUT /tickets/panels/1141116981697859736/122233344455566677/update?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
Content-Type: application/json

{
  "title": "Support & Hilfe",
  "description": "Bitte lies die Hinweise bevor du ein Ticket erstellst."
}
```

Response (`200 OK`)
```json
{
  "success": true,
  "updated": {
    "message_id": 121212121212121212,
    "channel_id": 122233344455566677
  }
}
```

Fehlerfälle: `404 not_published`, `410 gone`, `503`, `504`, `500` analog.

#### `GET /tickets/panels/{guild_id}/status`
- Zweck: Veröffentlichungsstatus je konfiguriertem Panel zurückgeben.
- Response-Felder pro Panel: `channel_id`, `category_id`, `role_id`, `thema`, `panel_message_id`, `status` (`not_published`|`published`).

Beispiel (`200 OK`)
```json
{
  "success": true,
  "count": 1,
  "panels": [
    {
      "channel_id": 122233344455566677,
      "category_id": 199988877766655544,
      "role_id": 144455566677788899,
      "thema": "Support",
      "panel_message_id": 121212121212121212,
      "status": "published"
    }
  ]
}
```

Hinweis: Es werden keine direkten Discord-Live-Checks durchgeführt; der Status basiert auf gespeicherten Daten.