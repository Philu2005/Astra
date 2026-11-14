# Astra Bot – Interne API-Dokumentation (API Contract)

Dieses Dokument definiert den verbindlichen API-Vertrag zwischen dem **Astra Discord-Bot** und dem separat entwickelten **Astra Dashboard-Backend**.

---

## 1. Allgemeine Übersicht & Architektur

- **Dienst:** Interne Flask-API des Astra Discord-Bots
- **Netzwerk-Bindung:** `127.0.0.1:5000` (ausschließlich localhost / IPv4-Loopback)
- **Kommunikationsrichtung:**
  ```text
  Dashboard Frontend  ──>  Dashboard Backend  ──[Interne API]──>  Astra Bot (Port 5000)
  ```
- **Sicherheitsprinzip:**
  - Das Dashboard-Frontend darf niemals direkten Zugriff auf die interne API haben.
  - Nur das Dashboard-Backend kommuniziert mit Astra über diese API.
  - Das Dashboard-Backend ist verantwortlich für die Benutzerauthentifizierung (z. B. Discord OAuth2 / Session) und übermittelt die verifizierte Discord `user_id`.
  - Astra prüft bei jedem Aufruf eigenständig die tatsächlichen Discord-Berechtigungen (Mitgliedschaft, Server-Owner, Administrator, Manage-Guild).

---

## 2. Authentifizierung (Service-to-Service)

Alle geschützten Endpoints erfordern eine Service-Authentifizierung via Secret Token im HTTP-Header.

- **Quelle auf dem Host:** `/root/Astra/.env`
- **Konfigurationsvariable:** `ASTRA_INTERNAL_API_KEY=...`
- **Ladevorgang:** Wird beim Start der internen Flask-API explizit aus `/root/Astra/.env` eingelesen. Falls die Datei oder der Schlüssel fehlt/leer ist, bleibt der interne API-Port geschlossen.
- **Header:**
  ```http
  Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
  ```
- **Prüfung:** Timing-sicherer Vergleich via `hmac.compare_digest`.
- **Fehlgeschlagene Authentifizierung:** HTTP `401 Unauthorized` mit einheitlichem Fehler-JSON.

---

## 3. Einheitliches Antwort- und Fehlerformat

Alle JSON-Antworten der internen API besitzen ein einheitliches Basis-Schema:

### Erfolgsantwort
```json
{
  "success": true,
  "...": "spezifische Nutzdaten"
}
```

### Fehlerantwort
```json
{
  "success": false,
  "error": "Fehlerbeschreibung"
}
```

### Relevante HTTP-Statuscodes
| Statuscode | Bedeutung | Beschreibung |
|------------|-----------|--------------|
| `200 OK` | Erfolg | Die Anfrage wurde erfolgreich verarbeitet. |
| `400 Bad Request` | Ungültige Anfrage | Fehlende oder syntaktisch ungültige Parameter (z. B. ungültige `user_id`). |
| `401 Unauthorized` | Nicht authentifiziert | Fehlender, falscher oder falsch formatierter API-Schlüssel im `Authorization`-Header. |
| `403 Forbidden` | Verboten | Der angegebene Benutzer ist kein Mitglied oder besitzt keine ausreichenden Berechtigungen (weder Owner, Admin noch Manage-Guild). |
| `404 Not Found` | Nicht gefunden | Der angeforderte Server existiert nicht oder Astra ist nicht darauf installiert. |
| `405 Method Not Allowed` | Methode unzulässig | Die aufgerufene HTTP-Methode wird auf diesem Endpoint nicht unterstützt. |
| `500 Internal Server Error` | Serverfehler | Unerwarteter interner Verarbeitungsfehler. |
| `503 Service Unavailable` | Bot nicht bereit | Astra befindet sich im Startvorgang oder der Discord-Event-Loop ist noch nicht bereit. |

---

## 4. Endpoints

---

### `GET /status`

Öffentlicher Healthcheck-Endpoint für den internen Prozessstatus.

- **Authentifizierung erforderlich:** Nein
- **Zweck:** Überprüfung, ob der Flask-Service läuft.
- **Sicherheitsgarantie:** Gibt bewusst keine sensiblen Daten, Guild-Details, Secrets oder interne Bot-Zustände preis.

#### Request
```http
GET /status HTTP/1.1
Host: 127.0.0.1:5000
```

#### Response (`200 OK`)
```json
{
  "online": true
}
```

---

### `GET /servers`

Gibt alle Server zurück, auf denen Astra installiert ist und für die der angegebene Discord-Benutzer Verwaltungsrechte besitzt.

- **Authentifizierung erforderlich:** Ja (`Authorization: Bearer <ASTRA_INTERNAL_API_KEY>`)
- **Query-Parameter:**
  - `user_id` (string/integer, erforderlich): Die verifizierte Discord Snowflake-ID des Benutzers.
- **Berechtigungsfilter:**
  Ein Server wird nur zurückgegeben, wenn der Benutzer mindestens eine der folgenden Bedingungen erfüllt:
  1. Ist Serverbesitzer (`guild.owner_id == user_id`)
  2. Besitzt die Berechtigung `Administrator`
  3. Besitzt die Berechtigung `Manage Server` (`manage_guild`)

#### Request
```http
GET /servers?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
```

#### Response (`200 OK`)
```json
{
  "success": true,
  "count": 1,
  "servers": [
    {
      "id": "1141116981697859736",
      "name": "Astra Community",
      "icon": "a_123456789abcdef",
      "memberCount": 250,
      "owner": true,
      "permissions": {
        "administrator": true,
        "manage_guild": true
      }
    }
  ]
}
```

---

### `GET /servers/{guild_id}`

Gibt Detailinformationen zu einem bestimmten Discord-Server zurück.

- **Authentifizierung erforderlich:** Ja (`Authorization: Bearer <ASTRA_INTERNAL_API_KEY>`)
- **Pfad-Parameter:**
  - `guild_id` (integer, erforderlich): Die Discord Snowflake-ID des Servers.
- **Query-Parameter:**
  - `user_id` (string/integer, erforderlich): Die verifizierte Discord Snowflake-ID des Benutzers.
- **Berechtigungsprüfung:**
  Astra verifiziert die Mitgliedschaft und Berechtigung des Benutzers. Besitzt der Benutzer keine Verwaltungsrechte, wird HTTP `403 Forbidden` zurückgegeben.

#### Request
```http
GET /servers/1141116981697859736?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
```

#### Response (`200 OK`)
```json
{
  "success": true,
  "server": {
    "id": "1141116981697859736",
    "name": "Astra Community",
    "icon": "a_123456789abcdef",
    "memberCount": 250,
    "channelCount": 24,
    "roleCount": 18,
    "ownerId": "123456789012345678",
    "owner": true,
    "permissions": {
      "administrator": true,
      "manage_guild": true
    }
  }
}
```

---

### `GET /servers/{guild_id}/roles`

Gibt die Liste aller Rollen des angegebenen Servers zurück (ausgenommen `@everyone`).

- **Authentifizierung erforderlich:** Ja (`Authorization: Bearer <ASTRA_INTERNAL_API_KEY>`)
- **Pfad-Parameter:**
  - `guild_id` (integer, erforderlich): Die Discord Snowflake-ID des Servers.
- **Query-Parameter:**
  - `user_id` (string/integer, erforderlich): Die verifizierte Discord Snowflake-ID des Benutzers.
- **Berechtigungsprüfung:**
  Erfordert Verwaltungsrechte (Owner, Admin oder Manage Guild) des übergebenen Benutzers auf dem angegebenen Server.

#### Request
```http
GET /servers/1141116981697859736/roles?user_id=123456789012345678 HTTP/1.1
Host: 127.0.0.1:5000
Authorization: Bearer <ASTRA_INTERNAL_API_KEY>
```

#### Response (`200 OK`)
```json
{
  "success": true,
  "count": 2,
  "roles": [
    {
      "id": "1141116983815962821",
      "name": "Administrator"
    },
    {
      "id": "1141116983815962822",
      "name": "Moderator"
    }
  ]
}
```

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
