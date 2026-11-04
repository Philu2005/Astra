<p align="center">
  <img src="cogs/assets/banner.svg?v=11" alt="Astra Banner" width="100%" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Version-2.9.6-4b46c8?style=flat&logo=git&logoColor=white" alt="Version" />
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Library-discord.py-5865F2?style=flat&logo=discord&logoColor=white" alt="discord.py" />
  <img src="https://img.shields.io/badge/Database-MySQL-4479A1?style=flat&logo=mysql&logoColor=white" alt="MySQL" />
  <a href="License/License"><img src="https://img.shields.io/badge/License-MIT-4b46c8?style=flat" alt="License" /></a>
  <img src="https://img.shields.io/github/stars/Philu2005/astra?style=social" alt="Stars" />
</p>

---

# Astra

Astra ist ein vielseitiger, modularer Discord-Bot zur Serververwaltung, Community-Interaktion und Automatisierung. Entwickelt in Python auf Basis von `discord.py` und einer asynchronen MySQL/MariaDB-Anbindung, vereint Astra zahlreiche Funktionen für Moderation, Levelsysteme, Tickets, Minispiele und Unterhaltung in einer performanten Gesamtlösung.

Diese Dokumentation führt Schritt für Schritt durch die Vorbereitung, Konfiguration und Installation des Bots und dokumentiert die vollständige Datenbankstruktur sowie alle Konfigurationsoptionen.

---

## Inhaltsverzeichnis

- [1. Projektvorstellung](#1-projektvorstellung)
  - [Funktionsübersicht](#funktionsübersicht)
  - [Verwendete Technologien](#verwendete-technologien)
- [2. Voraussetzungen](#2-voraussetzungen)
- [3. Discord-Bot einrichten](#3-discord-bot-einrichten)
  - [Schritt 1: Application erstellen](#schritt-1-application-erstellen)
  - [Schritt 2: Bot erstellen und Bot-Token sichern](#schritt-2-bot-erstellen-und-bot-token-sichern)
  - [Schritt 3: Privileged Gateway Intents aktivieren](#schritt-3-privileged-gateway-intents-aktivieren)
  - [Schritt 4: OAuth2-Einladungslink generieren und Berechtigungen festlegen](#schritt-4-oauth2-einladungslink-generieren-und-berechtigungen-festlegen)
- [4. Installation und Einrichtung](#4-installation-und-einrichtung)
  - [Schritt 1: Repository herunterladen](#schritt-1-repository-herunterladen)
  - [Schritt 2: In das Projektverzeichnis wechseln](#schritt-2-in-das-projektverzeichnis-wechseln)
  - [Schritt 3: Virtuelle Python-Umgebung erstellen und aktivieren](#schritt-3-virtuelle-python-umgebung-erstellen-und-aktivieren)
  - [Schritt 4: Abhängigkeiten installieren](#schritt-4-abhängigkeiten-installieren)
  - [Schritt 5: MySQL/MariaDB-Datenbank und Benutzer erstellen](#schritt-5-mysqlmariadb-datenbank-und-benutzer-erstellen)
  - [Schritt 6: Datenbankschema bereitstellen](#schritt-6-datenbankschema-bereitstellen)
  - [Schritt 7: Umgebungsvariablen (.env) konfigurieren](#schritt-7-umgebungsvariablen-env-konfigurieren)
  - [Schritt 8: Astra starten](#schritt-8-astra-starten)
- [5. Umgebungsvariablen](#5-umgebungsvariablen)
  - [Übersicht aller Konfigurationsvariablen](#übersicht-aller-konfigurationsvariablen)
  - [Beispiel einer .env-Datei](#beispiel-einer-env-datei)
- [6. Datenbankschema](#6-datenbankschema)
  - [Schema-Initialisierung](#schema-initialisierung)
  - [Vollständiges SQL-Schema](#vollständiges-sql-schema)
- [7. Projektstruktur](#7-projektstruktur)
- [8. Fehlerbehebung](#8-fehlerbehebung)
- [Lizenz](#lizenz)

---

## 1. Projektvorstellung

Astra bündelt moderne Community- und Administrationswerkzeuge in einem modularen Cog-System. Anstatt mehrere einzelne Bots für Tickets, Level oder Moderation betreiben zu müssen, stellt Astra alle Kernfunktionen in einer einheitlichen, performanten Struktur bereit.

### Funktionsübersicht

- **Moderation und Sicherheit:** Befehle für Verwarnungen (`/warn`, `/unwarn`), Timeouts, Kicks und Bans, automatisches Audit-Logging (`modlog`), Massenlöschung von Nachrichten (`/clear`), AutoMod-Wortfilter und Capslock-Dämpfung.
- **Levelsystem:** Aktivitätsbasiertes Erfahrungspunkte-System (XP für Chat- und Sprachaktivität), anpassbare Rang-Karten mit dynamischer Bildgenerierung, automatische Rollenbelohnungen und serverweite Ranglisten.
- **Ticket- und Supportsystem:** Interaktive Ticketerstellung über Buttons und Modals, private Support-Kanäle mit Rechteverwaltung, Audit-Logging und automatische Schließung inaktiver Tickets.
- **Serververwaltung und Backups:** Vollständige Sicherung von Rollen, Kanälen und Berechtigungen (`/backup`) mit Wiederherstellungsfunktion sowie benutzerdefinierte Text-Tags (`/tag`).
- **Rollenverwaltung:** Automatische Rollenvergabe bei Serverbeitritt (`autorole`) sowie interaktive Reaktions- und Button-Rollen (`reactionrole`).
- **Automatisierungen:** Temporäre Sprachkanäle („Join-to-Create“), konfigurierbare Willkommens- und Abschiedsnachrichten mit dynamischen Grafiken, AutoReact und Abwesenheitsstatus (`/afk`).
- **Benachrichtigungen:** Automatische Alerts bei neuen YouTube-Uploads oder Twitch-Livestreams sowie zeitgesteuerte Erinnerungen (`/reminder`).
- **Giveaways:** Zeitgesteuerte Verlosungen mit Button-Teilnahme, Teilnahmebedingungen und automatischem Reroll.
- **Geburtstage:** Erfassung von Benutzergeburtstagen und automatische Gratulationen mit Zeitzonenunterstützung.
- **Community-Funktionen:** Gemeinsame Server-Meilensteine (`community_goals`) sowie globale Chat-Punkte und -Verbindungen.
- **Spiele und Unterhaltung:** Minispiele wie Emoji-Quiz, Galgenmännchen (Hangman), Snake, Zahlenraten und Zählkanäle sowie Spaßbefehle (z. B. Wanted-Poster und QR-Codes).
- **Economy:** Virtuelles Wirtschaftssystem mit Bargeld- und Bankkonten, Jobs, täglichen Belohnungen (`/daily`) und Geldüberweisungen.
- **Statistiken:** Detaillierte Aktivitätsanalysen für Nachrichten, Sprachzeiten und Befehlsnutzung.

### Verwendete Technologien

| Bereich | Technologie | Beschreibung |
|:---|:---|:---|
| **Programmiersprache** | Python (3.10+) | Moderne asynchrone Programmierung mit `asyncio` |
| **Discord API** | discord.py | Offizielles Framework für Gateway-Events, Slash-Commands und UI-Elemente |
| **Datenbank** | MySQL / MariaDB | Relationales Datenbanksystem für persistente Einstellungen und Daten |
| **Datenbanktreiber** | aiomysql | Asynchroner Datenbank-Client mit Connection-Pooling |
| **Bildverarbeitung** | Pillow (PIL) | Dynamische Generierung von Rank-Karten und Willkommensbannern |
| **Webdienste** | aiohttp / Flask & Waitress | Webhook-Verarbeitung für Top.gg und interne Status-Schnittstellen |

---

## 2. Voraussetzungen

Für die Installation und den Betrieb von Astra werden folgende Systemkomponenten benötigt:

- **Python 3.10 oder neuer:** Inklusive des Paketmanagers `pip` und des Moduls `venv`.
- **Git:** Zum Klonen des Quellcodes über die Befehlszeile.
- **MySQL (ab Version 8.0) oder MariaDB (ab Version 10.5):** Ein aktiver Datenbankserver mit Rechten zum Anlegen von Datenbanken und Tabellen.
- **Discord-Konto:** Ein Discord-Account mit Zugriff auf das [Discord Developer Portal](https://discord.com/developers/applications) zur Erstellung der Bot-Anwendung.
- **Datenbankschema (`schema.sql`):** Die SQL-Schemadatei für die Tabellendefinitionen (siehe Abschnitt [Datenbankschema](#6-datenbankschema)).

---

## 3. Discord-Bot einrichten

Dieser Abschnitt beschreibt Schritt für Schritt, wie die Anwendung im Discord Developer Portal registriert, konfiguriert und auf den eigenen Server eingeladen wird.

### Schritt 1: Application erstellen

1. Öffne das [Discord Developer Portal](https://discord.com/developers/applications) im Browser und melde dich mit deinem Discord-Konto an.
2. Klicke oben rechts auf die Schaltfläche **New Application**.
3. Gib im Dialogfeld einen Namen für den Bot ein (z. B. `Astra`) und bestätige mit **Create**.

### Schritt 2: Bot erstellen und Bot-Token sichern

1. Navigiere im linken Menü zum Reiter **Bot**.
2. Klicke im Bereich **Token** auf **Reset Token** (bzw. **Copy**, falls frisch erstellt).
3. Kopiere den angezeigten Token und speichere ihn vorübergehend sicher ab. Dieser Token wird später in der Konfigurationsdatei als `DISCORD_TOKEN` eingetragen.

> **Wichtiger Sicherheitshinweis:** Der Bot-Token gewährt vollständigen Zugriff auf die Identität und Aktionen des Bots. Behandle ihn wie ein Passwort: Teile den Token niemals mit anderen Personen und veröffentliche ihn unter keinen Umständen in öffentlichen Repositories.

### Schritt 3: Privileged Gateway Intents aktivieren

Damit Astra Mitgliederlisten verwalten, Chat-Nachrichten für Level-XP verarbeiten und auf Aktionen reagieren kann, müssen im Developer Portal bestimmte Berechtigungen auf Gateway-Ebene aktiviert werden:

1. Scrolle im Reiter **Bot** nach unten zum Abschnitt **Privileged Gateway Intents**.
2. Aktiviere folgende Schalter:
   - **Server Members Intent:** Notwendig für Willkommensnachrichten, Rollenverwaltung, Geburtstage und Moderationsprüfungen.
   - **Message Content Intent:** Notwendig für XP-Tracking, AutoMod-Wortfilter, Capslock-Erkennung, Zählspiele und Chat-Befehle.
3. Klicke unten auf **Save Changes**, um die Einstellungen zu speichern.

> **Hinweis:** Der Presence Intent wird von Astra nicht benötigt und kann deaktiviert bleiben.

### Schritt 4: OAuth2-Einladungslink generieren und Berechtigungen festlegen

1. Navigiere im linken Menü zum Punkt **OAuth2** und wähle den Unterpunkt **URL Generator**.
2. Wähle im Kasten **Scopes** folgende Optionen aus:
   - `bot`
   - `applications.commands` (ermöglicht die Registrierung von Slash-Befehlen)
3. Wähle im darunter erscheinenden Kasten **Bot Permissions** die benötigten Berechtigungen aus. Für eine reibungslose Funktion aller Moderations-, Kanal- und Rollenfeatures empfiehlt sich die Berechtigung **Administrator** oder alternativ mindestens:
   - *Manage Roles*, *Manage Channels*, *Kick Members*, *Ban Members*, *Moderate Members (Timeout)*
   - *View Channels*, *Send Messages*, *Embed Links*, *Attach Files*, *Read Message History*, *Add Reactions*, *Manage Messages*
   - *Mute Members*, *Deafen Members*, *Move Members*, *Manage Webhooks*
4. Kopiere die ganz unten generierte URL und öffne sie in einem neuen Browser-Tab.
5. Wähle deinen Discord-Server aus und bestätige die Autorisierung, um Astra auf den Server einzuladen.

---

## 4. Installation und Einrichtung

Folge dieser Anleitung, um Astra vom Herunterladen des Projekts bis zum ersten Start einzurichten.

### Schritt 1: Repository herunterladen

Klone das Repository mit Git auf dein System:

```bash
git clone https://github.com/Philu2005/astra.git
```

### Schritt 2: In das Projektverzeichnis wechseln

Wechsle in den neu erstellten Projektordner:

```bash
cd astra
```

### Schritt 3: Virtuelle Python-Umgebung erstellen und aktivieren

Es wird empfohlen, eine isolierte virtuelle Umgebung (`venv`) zu verwenden, um Paketkonflikte mit dem Betriebssystem zu vermeiden.

**Unter Linux / macOS:**

```bash
# Virtuelle Umgebung erstellen
python3 -m venv venv

# Virtuelle Umgebung aktivieren
source venv/bin/activate
```

**Unter Windows (PowerShell):**

```powershell
# Virtuelle Umgebung erstellen
python -m venv venv

# Virtuelle Umgebung aktivieren
.\venv\Scripts\Activate.ps1
```

> **Hinweis:** Nach der Aktivierung steht `(venv)` am Anfang der Terminal-Eingabezeile.

### Schritt 4: Abhängigkeiten installieren

Aktualisiere den Paketmanager `pip` und installiere alle benötigten Bibliotheken aus der `requirements.txt`:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Schritt 5: MySQL/MariaDB-Datenbank und Benutzer erstellen

Erstelle auf deinem MySQL- oder MariaDB-Server eine neue Datenbank und einen dedizierten Benutzer.

Verbinde dich mit der MySQL-Konsole:

```bash
mysql -u root -p
```

Führe anschließend folgende SQL-Befehle aus (ersetze `DeinSicheresPasswort` durch ein eigenes Kennwort):

```sql
CREATE DATABASE astra CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'astra_user'@'localhost' IDENTIFIED BY 'DeinSicheresPasswort';
GRANT ALL PRIVILEGES ON astra.* TO 'astra_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

### Schritt 6: Datenbankschema bereitstellen

Astra liest beim Start eine SQL-Datei ein, um alle erforderlichen Tabellen automatisch zu erzeugen.

- Erstelle einen Ordner `opt` im Projektverzeichnis und speichere dort die Datei `schema.sql` mit dem Inhalt aus dem Abschnitt [Datenbankschema](#6-datenbankschema):
  ```bash
  mkdir opt
  ```
- *Standardpfad:* Astra sucht standardmäßig unter `opt/schema.sql` relativ zum Projektverzeichnis (bzw. `/root/Astra/opt/schema.sql` auf dem Produktivserver).
- Falls die Datei an einem anderen Ort liegt, kann der Pfad über die Variable `SCHEMA_PATH` in der `.env`-Datei konfiguriert werden.

### Schritt 7: Umgebungsvariablen (.env) konfigurieren

Erstelle eine Datei mit dem Namen `.env` im Hauptverzeichnis des Projekts:

**Unter Linux / macOS:**
```bash
touch .env
```

**Unter Windows (PowerShell):**
```powershell
New-Item -ItemType File .env
```

Trage die erforderlichen Zugangsdaten ein (siehe Abschnitt [Umgebungsvariablen](#5-umgebungsvariablen) für eine vollständige Vorlage).

### Schritt 8: Astra starten

Starte den Bot über die Hauptdatei `main.py`:

**Unter Linux / macOS:**
```bash
python3 main.py
```

**Unter Windows (PowerShell):**
```powershell
python main.py
```

Beim Start initialisiert Astra automatisch die Datenbanktabellen, lädt alle Erweiterungen (Cogs) und meldet sich im Discord-Netzwerk an. Wenn in der Konsole `Astra ist online!` erscheint, ist der Bot betriebsbereit.

---

## 5. Umgebungsvariablen

Astra liest sensible Konfigurationsdaten über Umgebungsvariablen aus der `.env`-Datei im Projektstammverzeichnis ein.

### Übersicht aller Konfigurationsvariablen

| Variable | Pflicht | Beschreibung | Bezug / Herkunft                                                       |
|:---|:---:|:---|:-----------------------------------------------------------------------|
| `DISCORD_TOKEN` | **Ja** | Geheimer Authentifizierungs-Token des Discord-Bots | Discord Developer Portal ➔ *Bot* ➔ *Reset Token*                       |
| `DB_HOST` | **Ja** | Hostname oder IP-Adresse des MySQL/MariaDB-Servers | Standardmäßig `127.0.0.1` oder `localhost`                             |
| `DB_USER` | **Ja** | Benutzername für den Datenbankzugriff | Der beim Anlegen der Datenbank erstellte Benutzer (z. B. `astra_user`) |
| `DB_PASS` | **Ja** | Passwort des Datenbankbenutzers | Das für den Datenbankbenutzer festgelegte Passwort                     |
| `DB_NAME` | **Ja** | Name der verwendeten MySQL-Datenbank | Name der erstellten Datenbank (z. B. `astra`)                          |
| `SCHEMA_PATH` | Nein | Pfad zur `schema.sql`-Datei für die automatische Initialisierung | Optional, falls die Datei nicht unter `opt/schema.sql` liegt           |
| `DBL_TOKEN` | Nein | API-Token für Top.gg zur automatischen Serverzähler-Aktualisierung | Top.gg Bot Dashboard ➔ *Webhooks / API*                                |
| `DBL_PASS` | Nein | Autorisierungspasswort für Top.gg Webhook-Anfragen | Eigene Definition im Top.gg Webhook-Dashboard                          |
| `DBL_PORT` | Nein | Lokaler Netzwerkport für den internen Top.gg Webhook-Server | Standardmäßig `8082`                                                   |
| `DBL_SECRET_NEW` | Nein | Signaturschlüssel zur HMAC-SHA256-Validierung von Votes | Eigene Definition im Top.gg Webhook-Dashboard                          |

### Beispiel einer .env-Datei

```env
# ==========================================
# Astra Discord Bot – Umgebungskonfiguration
# ==========================================

# Discord Bot Authentifizierung (Erforderlich)
DISCORD_TOKEN=DEIN_DISCORD_BOT_TOKEN

# Datenbankverbindung (Erforderlich)
DB_HOST=127.0.0.1
DB_USER=astra_user
DB_PASS=DeinSicheresDatenbankPasswort
DB_NAME=astra

# Schema-Pfad (Optional – Standard ist opt/schema.sql)
# SCHEMA_PATH=/root/Astra/opt/schema.sql

# Top.gg Integration (Optional)
DBL_TOKEN=
DBL_PASS=
DBL_PORT=8082
DBL_SECRET_NEW=
```

---

## 6. Datenbankschema

Dieser Abschnitt dokumentiert die vollständige Datenbankstruktur von Astra.

### Schema-Initialisierung

Astra verfügt in `utils/db_scheme.py` über eine automatische Schema-Verwaltung (`run_sql_file`):

- **Automatische Initialisierung:** Sofern die Datei `schema.sql` am Standardpfad (`opt/schema.sql`) oder unter dem Pfad aus `SCHEMA_PATH` liegt, prüft Astra beim Start die Datenbank.
- **Tabellenerstellung:** Noch nicht vorhandene Tabellen werden automatisch über `CREATE TABLE IF NOT EXISTS` angelegt.
- **Spalten- und Index-Migration:** Fehlende Spalten und Indizes werden dynamisch per `ALTER TABLE` hinzugefügt.
- **Standarddaten:** Initiale Datensätze (wie die Standardfragen für das Emoji-Quiz) werden automatisch eingefügt, wenn die jeweilige Tabelle noch leer ist.

### Vollständiges SQL-Schema

Nachfolgend ist das verbindliche Datenbankschema mit allen 58 Tabellen und den initialen Datensätzen aufgeführt:

<details>
<summary><b>Vollständiges SQL-Schema anzeigen (58 Tabellen & Datensätze)</b></summary>

```sql
CREATE TABLE IF NOT EXISTS clear_jobs (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, channel_id BIGINT NOT NULL, amount INT NOT NULL, requested_by VARCHAR(128) NOT NULL, status ENUM('pending','processing','done') NOT NULL DEFAULT 'pending', PRIMARY KEY (id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS subscriptions (guild_id BIGINT NOT NULL, discord_channel_id BIGINT NOT NULL, platform ENUM('youtube','twitch') NOT NULL, content_id VARCHAR(255) NOT NULL, ping_role_id BIGINT NULL, last_item_id VARCHAR(255) NULL, PRIMARY KEY (guild_id, platform, content_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS notifier_settings (guild_id BIGINT NOT NULL, platform ENUM('youtube','twitch') NOT NULL, enabled TINYINT(1) NOT NULL DEFAULT 1, PRIMARY KEY (guild_id, platform)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelstyle (guild_id BIGINT NOT NULL, client_id BIGINT NOT NULL, style VARCHAR(128) NOT NULL, PRIMARY KEY (guild_id, client_id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS backups (code VARCHAR(32) PRIMARY KEY, guild_id BIGINT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, includes TEXT NULL, version INT NOT NULL, size_bytes INT NOT NULL, hash BINARY(16) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS backup_jobs (job_id BIGINT PRIMARY KEY AUTO_INCREMENT, guild_id BIGINT NOT NULL, code VARCHAR(64), type ENUM('create','restore','undo') NOT NULL, status ENUM('pending','running','done','error') NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS community_goals (id INT AUTO_INCREMENT PRIMARY KEY, guild_id BIGINT NOT NULL, started_at BIGINT NOT NULL, ends_at BIGINT NOT NULL, reward_role_id BIGINT NULL, reward_text VARCHAR(255) NULL, active BOOLEAN NOT NULL DEFAULT TRUE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS community_goal_conditions (id INT AUTO_INCREMENT PRIMARY KEY, goal_id INT NOT NULL, type VARCHAR(32) NOT NULL, target BIGINT NOT NULL, progress BIGINT NOT NULL DEFAULT 0, FOREIGN KEY (goal_id) REFERENCES community_goals(id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS goal_bans (id INT AUTO_INCREMENT PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, mod_id BIGINT, time DATETIME NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS gc_users (id BIGINT PRIMARY KEY, lvl_points INT NOT NULL DEFAULT 0, team BOOLEAN NOT NULL DEFAULT FALSE, banned BOOLEAN NOT NULL DEFAULT FALSE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS gc_servers (id INT AUTO_INCREMENT PRIMARY KEY, guildid BIGINT NOT NULL, channelid BIGINT NOT NULL, invite VARCHAR(255)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reactionrole_messages (message_id BIGINT UNSIGNED PRIMARY KEY, guild_id BIGINT UNSIGNED NOT NULL, channel_id BIGINT UNSIGNED NOT NULL, style VARCHAR(10) NOT NULL, embed_title VARCHAR(256) NOT NULL, embed_description TEXT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reactionrole_entries (id INT AUTO_INCREMENT PRIMARY KEY, message_id BIGINT UNSIGNED NOT NULL, role_id BIGINT UNSIGNED NOT NULL, label VARCHAR(100) NOT NULL, emoji VARCHAR(100), CONSTRAINT fk_rr_msg FOREIGN KEY (message_id) REFERENCES reactionrole_messages(message_id) ON DELETE CASCADE) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS emojiquiz (guildID BIGINT, channelID BIGINT, messageID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS emojiquiz_lsg (guildID BIGINT PRIMARY KEY, lösung TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS emojiquiz_quizzez (question TEXT, answer VARCHAR(255), hint TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS emojiquiz_messages (guildID BIGINT, channelID BIGINT, messageID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO emojiquiz_quizzez (question, answer, hint) VALUES ('🎬🚗👻', 'Ghostbusters', 'Ein Film über Geisterjäger'), ('🦇👨‍👩‍👧‍👦', 'Batman', 'Ein Superheld, der Gotham City beschützt'), ('🔗🌳🛤️', 'Linkin Park', 'Eine US-Rockband mit elektronischen Elementen, bekannt durch Songs wie "In the End"'), ('🤠🎸🌾', 'Country', 'Ein Musikgenre mit ländlichen Themen'), ('🔴🔵🟡', 'Twister', 'Ein Spiel, bei dem man Körperteile auf Farbpunkte legt'), ('🚀👾', 'E.T.', 'Ein Außerirdischer wird von Kindern gefunden'), ('🕵️‍♂️🔍', 'Sherlock Holmes', 'Ein berühmter Detektiv mit messerscharfem Verstand'), ('🦁👑', 'Der König der Löwen', 'Ein Zeichentrickfilm über Tiere in der Savanne'), ('🧙‍♂️⚡', 'Harry Potter', 'Ein Zauberer erlebt Abenteuer in einer magischen Welt'), ('🌌🚀', 'Star Wars', 'Eine epische Weltraumsaga zwischen Gut und Böse'), ('🍫🏭', 'Charlie und die Schokoladenfabrik', 'Ein Junge gewinnt eine Tour durch eine Fabrik'), ('🎤🐠', 'Findet Nemo', 'Ein Clownfisch sucht seinen Sohn'), ('🌈🍭', 'Der Zauberer von Oz', 'Ein Mädchen sucht einen Zauberer in einer Fantasiewelt'), ('🧛‍♂️🦇', 'Dracula', 'Ein Vampir, der nachts Blut trinkt'), ('🚶‍♂️👨‍🚀', 'Der Marsianer', 'Ein Astronaut kämpft ums Überleben auf dem Mars'), ('🏹👧', 'Die Tribute von Panem', 'Ein Mädchen wird zu einem tödlichen Spiel gezwungen'), ('🚢🌊', 'Titanic', 'Ein Liebesdrama auf einem berühmten Schiff'), ('🧊⛄', 'Die Eiskönigin', 'Eine Prinzessin mit Eiskräften'), ('🧟‍♂️🧟‍♀️', 'The Walking Dead', 'Eine Serie über eine Zombieapokalypse'), ('🐶🐱', 'Haustiere', 'Tiere, die oft als Begleiter gehalten werden'), ('🍎🍌', 'Früchte', 'Gesundes, essbares Obst'), ('☀️🌈', 'Regenbogen', 'Ein farbenfrohes Wetterphänomen'), ('📚📖', 'Bücher', 'Gedruckte oder digitale Literaturwerke'), ('🍕🍔', 'Fast Food', 'Schnell zubereitetes Essen zum Mitnehmen'), ('🚗🚦', 'Verkehr', 'Transportmittel und Straßenschilder'), ('🌳🌺', 'Natur', 'Die belebte und unbelebte Umwelt'), ('👶🍼', 'Baby', 'Ein neugeborenes oder kleines Kind'), ('🌞🏖️', 'Strand', 'Ein Ort mit Sand und Wasser'), ('🎮🕹️', 'Videospiele', 'Elektronische Spiele auf Bildschirmen'), ('🌙🌠', 'Nachthimmel', 'Der Himmel mit Mond und Sternen'), ('🎨🖌️', 'Malerei', 'Künstlerische Darstellung mit Farben'), ('🍲🥗', 'Essen', 'Verschiedene Arten von Gerichten'), ('📺🎬', 'Fernsehen', 'Sendungen und Filme auf dem Bildschirm'), ('📱📞', 'Handy', 'Ein Kommunikationsgerät'), ('📆⏰', 'Zeit', 'Messung von Momenten und Abläufen'), ('👩‍🍳🍳', 'Kochen', 'Zubereitung von Mahlzeiten'), ('🚴‍♂️🚶‍♀️', 'Aktivitäten', 'Was du draußen machst, wenn dir langweilig ist'), ('🎈🥳', 'Party', 'Ein soziales Treffen zum Feiern'), ('❤️🌹', 'Liebe', 'Ein starkes Gefühl der Zuneigung'), ('🌞🌻', 'Sonnenblume', 'Eine fröhliche, helle Blume'), ('📚✏️', 'Schule', 'Ein Ort zum Lernen'), ('🐶🏠', 'Hundehütte', 'Ein Unterschlupf für Hunde'), ('📆🎂', 'Jahrestag', 'Jährliche Feier eines Ereignisses'), ('🚴‍♀️🚴', 'Fahrrad', 'Ein zweirädriges Fortbewegungsmittel'), ('🏀👟', 'Basketball', 'Ein Mannschaftssport mit zwei Teams'), ('🛒🛍️', 'Einkaufen', 'Kleidung und andere Dinge kaufen'), ('🎭🤡', 'Zirkus', 'Reisende Künstler mit Akrobatik und Clowns'), ('🌧️🌈', 'Wetter', 'Meteorologische Erscheinungen'), ('🐍⚡🏰', 'Slytherin', 'Ein Haus in Hogwarts – grün, ehrgeizig, listig'), ('🐵🪄', 'Dschungelbuch', 'Ein Junge wächst im Urwald mit Tieren auf'), ('🕸️🕷️', 'Spider-Man', 'Ein Superheld mit Spinnenkräften'), ('🍔👨‍🍳', 'Burger King', 'Ein Fast-Food-Restaurant mit königlichem Namen'), ('👓⚗️', 'Chemie', 'Eine Naturwissenschaft mit Formeln und Reaktionen'), ('🎤🎶', 'Musik', 'Etwas, das du hörst und fühlst'), ('🗺️🧭', 'Abenteuer', 'Eine spannende Reise ins Unbekannte'), ('💻⌨️', 'Computer', 'Ein digitales Gerät für alles Mögliche'), ('👽🔭', 'Außerirdischer', 'Ein Wesen nicht von dieser Welt');
CREATE TABLE IF NOT EXISTS economy_users (user_id BIGINT PRIMARY KEY, wallet INT DEFAULT 0, bank INT DEFAULT 0, job VARCHAR(100), hours_worked INT DEFAULT 0, last_work DATETIME) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS snake (userID BIGINT, highscore BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS topgg (userID BIGINT PRIMARY KEY, count INT NOT NULL DEFAULT 0, last_reset DATE NULL, last_vote DATETIME NULL, last_vote_epoch BIGINT NULL, next_vote_epoch BIGINT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS website_stats (servers BIGINT, users BIGINT, channels BIGINT, commands BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS afk (guildID BIGINT, userID BIGINT, reason TEXT, prevName TEXT, time TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS autoreact (guildID BIGINT, channelID BIGINT, emoji TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;;
CREATE TABLE IF NOT EXISTS capslock (guildID BIGINT, percent BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS counter (guildID BIGINT, channelID BIGINT, number BIGINT, lastuserID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS leavemsg (guildID BIGINT, channelID BIGINT, msg TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS guessthenumber (guildID BIGINT, channelID BIGINT, number BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS modlog (serverID BIGINT, channelID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS tags (id INT AUTO_INCREMENT PRIMARY KEY, guildID BIGINT NOT NULL, tagname VARCHAR(100) NOT NULL, tagoutput TEXT NOT NULL, UNIQUE KEY unique_tag (guildID, tagname));
CREATE TABLE IF NOT EXISTS tempchannels (guild_id BIGINT, channel_id BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS welcome (guildID BIGINT NOT NULL PRIMARY KEY, channelID BIGINT NOT NULL, message TEXT, mode ENUM('banner','embed') NOT NULL);
CREATE TABLE IF NOT EXISTS ticketsystem_channels (guildID BIGINT, channelID BIGINT, msgID BIGINT, opened BIGINT, claimed TEXT, closed TEXT, time TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS usertempchannels (guildID BIGINT, userID BIGINT, channelID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ticket_config (guildID BIGINT PRIMARY KEY, autoclose_hours INT DEFAULT 0, remind_minutes INT DEFAULT 0, reopen_hours INT DEFAULT 24, ping_throttle_minutes INT DEFAULT 0) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ticket_autoclose_state (channelID BIGINT PRIMARY KEY, reminded TINYINT DEFAULT 0) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ticketsystem (guildID BIGINT, channelID BIGINT, categoryID BIGINT, roleID BIGINT, thema TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS ticketlog (guildID BIGINT, channelID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reminder (userID BIGINT, grund TEXT, time TEXT, remindID BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelsystem (user_xp BIGINT, user_level BIGINT, client_id TEXT, guild_id TEXT, enabled BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelchannel (guildID BIGINT, type TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelmsg (guildID BIGINT, message TEXT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelxp (guildID BIGINT, xp BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS levelroles (guildID BIGINT, roleID BIGINT, levelreq BIGINT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS user_message_counts (guildID BIGINT NOT NULL, userID BIGINT NOT NULL, count INT NOT NULL DEFAULT 0, PRIMARY KEY (guildID, userID), KEY idx_guild (guildID), KEY idx_user (userID)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS command_usage (id BIGINT AUTO_INCREMENT PRIMARY KEY, guild_id BIGINT NOT NULL, user_id BIGINT NOT NULL, command VARCHAR(100) NOT NULL, subcommand VARCHAR(100) DEFAULT NULL, used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, INDEX idx_command (command), INDEX idx_guild (guild_id), INDEX idx_used_at (used_at));
CREATE TABLE IF NOT EXISTS giveaway_active (guildID BIGINT NOT NULL, creatorID BIGINT NOT NULL, channelID BIGINT NOT NULL, messageID BIGINT NOT NULL, role_name VARCHAR(255) NULL, entrys INT NOT NULL DEFAULT 0, prize TEXT NOT NULL, winners INT NOT NULL DEFAULT 1, time BIGINT NOT NULL, role TEXT NULL, level TEXT NULL, messages_required INT NULL, ended TINYINT(1) NOT NULL DEFAULT 0, PRIMARY KEY (messageID), KEY idx_guild (guildID), KEY idx_channel (channelID), KEY idx_guild_ended (guildID, ended), KEY idx_endtime (time)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS giveway_ids (guildID BIGINT NOT NULL, gwID INT NOT NULL, messageID BIGINT NOT NULL, PRIMARY KEY (guildID, gwID), UNIQUE KEY uniq_message (messageID), KEY idx_guild (guildID)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS giveaway_entrys (guildID BIGINT NOT NULL, channelID BIGINT NOT NULL, messageID BIGINT NOT NULL, userID BIGINT NOT NULL, PRIMARY KEY (messageID, userID), KEY idx_guild_user (guildID, userID), KEY idx_channel (channelID)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS birthday_settings ( guild_id BIGINT UNSIGNED NOT NULL, channel_id BIGINT UNSIGNED NULL, message_template VARCHAR(500) NOT NULL DEFAULT '', send_hour TINYINT UNSIGNED NOT NULL DEFAULT 9, send_minute TINYINT UNSIGNED NOT NULL DEFAULT 0, tz_name VARCHAR(64) NOT NULL DEFAULT 'Europe/Berlin', use_embed TINYINT(1) NOT NULL DEFAULT 1, enabled TINYINT(1) NOT NULL DEFAULT 1, updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, PRIMARY KEY (guild_id) ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS birthdays_guild ( guild_id BIGINT UNSIGNED NOT NULL, user_id BIGINT UNSIGNED NOT NULL, birth_str VARCHAR(10) NOT NULL, day TINYINT UNSIGNED NOT NULL, month TINYINT UNSIGNED NOT NULL, year SMALLINT UNSIGNED NOT NULL, next_epoch INT UNSIGNED NOT NULL, PRIMARY KEY (guild_id, user_id), KEY idx_next_epoch (next_epoch), KEY idx_guild (guild_id) ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS analytics_messages (guild_id BIGINT, user_id BIGINT, channel_id BIGINT, date DATE, count INT DEFAULT 0, PRIMARY KEY (guild_id, user_id, date));
CREATE TABLE IF NOT EXISTS analytics_voice (guild_id BIGINT, user_id BIGINT, date DATE, minutes INT DEFAULT 0, PRIMARY KEY (guild_id, user_id, date));
CREATE TABLE IF NOT EXISTS analytics_daily_guild (guild_id BIGINT, date DATE, messages INT DEFAULT 0, voice_minutes INT DEFAULT 0, PRIMARY KEY (guild_id, date));
CREATE TABLE IF NOT EXISTS analytics_voice_sessions (guild_id BIGINT, user_id BIGINT, joined_at DATETIME, PRIMARY KEY (guild_id, user_id));
CREATE TABLE IF NOT EXISTS automod (guildID BIGINT NOT NULL, warns BIGINT NOT NULL, action VARCHAR(20) NOT NULL, timeout_seconds BIGINT DEFAULT NULL, PRIMARY KEY (guildID, warns)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS autorole (guildID BIGINT PRIMARY KEY, botRoleID BIGINT NULL, botEnabled TINYINT(1) NOT NULL DEFAULT 0, joinRoleID BIGINT NULL, joinEnabled TINYINT(1) NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS warns (guildID BIGINT NOT NULL, userID BIGINT NOT NULL, reason TEXT, warnID INT NOT NULL, PRIMARY KEY (guildID, userID, warnID)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS reported_messages (messageID BIGINT PRIMARY KEY, reporterID BIGINT NOT NULL, reportedAt TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

</details>

---

## 7. Projektstruktur

Die Codebasis ist übersichtlich in funktionale Module gegliedert:

```text
Astra/
├── cogs/                   # Erweiterungen und Funktionsmodule (Cogs)
│   ├── assets/             # Grafische Ressourcen (Banner, Badges, Icons)
│   ├── mod.py              # Moderationsbefehle (Ban, Kick, Timeout)
│   ├── levels.py           # Level- und Erfahrungspunkte-System
│   ├── ticket.py           # Ticket- und Support-System
│   ├── backups.py          # Server-Backups und Wiederherstellung
│   ├── welcome.py          # Willkommensbanner und Begrüßungen
│   └── ...                 # Weitere funktionale Cogs (32 Module insgesamt)
├── docs/                   # Weiterführende technische Dokumentation
│   └── ARCHITECTURE.md     # Detaillierte Architekturübersicht und Designentscheidungen
├── events/                 # Event-Handler und externe Schnittstellen (z. B. Top.gg)
├── utils/                  # Hilfsfunktionen und interne Werkzeuge
│   ├── db_scheme.py        # Automatische Datenbankmigration und Schema-Initialisierung
│   ├── branding.py         # Saisonale Designanpassungen
│   ├── logger.py           # Zentrales Logging-System
│   ├── presence.py         # Rotierende Bot-Statusanzeigen
│   └── cleanup.py          # Bereinigung veralteter Log-Einträge
├── opt/                    # Ablageort für private Konfigurationen (z. B. schema.sql)
├── License/                # Lizenzverzeichnis
│   └── License             # Vollständiger MIT-Lizenztext
├── main.py                 # Hauptdatei und Einstiegspunkt des Bots
├── requirements.txt        # Liste aller Python-Abhängigkeiten
└── README.md               # Projektdokumentation und Installationsanleitung
```

> **Hinweis zur Architektur:** Ausführliche Informationen zu internen Abläufen, Caching-Strategien, Fehlerbehandlung und dem Lifecycle der Anwendung findest du in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## 8. Fehlerbehebung

Hier findest du Lösungen für typische Probleme, die während der Installation oder des Betriebs auftreten können:

### Der Bot startet nicht oder bricht mit `LoginFailure` ab
- **Ursache:** Der in der `.env`-Datei angegebene `DISCORD_TOKEN` ist ungültig oder unvollständig.
- **Lösung:** Generiere im Discord Developer Portal unter dem Reiter **Bot** einen neuen Token und trage ihn exakt ohne Anführungszeichen in die `.env`-Datei ein.

### Privileged Intents Fehler (`PrivilegedIntentsRequired`)
- **Ursache:** Die für Astra erforderlichen Gateway Intents wurden im Developer Portal nicht aktiviert.
- **Lösung:** Öffne das [Discord Developer Portal](https://discord.com/developers/applications), wähle deine Application, navigiere zu **Bot ➔ Privileged Gateway Intents** und aktiviere sowohl **Server Members Intent** als auch **Message Content Intent**.

### Fehlende Berechtigungen auf dem Discord-Server
- **Ursache:** Die Bot-Rolle steht in der Rollenhierarchie zu weit unten oder es fehlen administrative Rechte.
- **Lösung:** Verschiebe die Rolle von Astra in den Servereinstellungen unter **Rollen** möglichst weit nach oben und stelle sicher, dass Berechtigungen wie *Manage Roles*, *Manage Channels* und *Moderate Members* gewährt sind.

### Datenbankverbindung schlägt fehl (`OperationalError` / `ConnectionRefusedError`)
- **Ursache:** Der MySQL/MariaDB-Dienst läuft nicht, oder die Zugangsdaten in der `.env` sind nicht korrekt.
- **Lösung:**
  - Prüfe, ob der Datenbankdienst aktiv ist (z. B. unter Linux mit `sudo systemctl status mysql` oder `mariadb`).
  - Überprüfe `DB_HOST`, `DB_USER`, `DB_PASS` und `DB_NAME` in der `.env`-Datei auf Tippfehler.
  - Stelle sicher, dass der angegebene Benutzer die nötigen Berechtigungen auf der Zieldatenbank besitzt (`GRANT ALL PRIVILEGES`).

### Probleme mit dem Datenbankschema (`[DB] SQL-Datei nicht gefunden`)
- **Ursache:** Die Datei `schema.sql` liegt nicht am erwarteten Speicherort.
- **Lösung:** Lege die `schema.sql` im Ordner `opt/schema.sql` innerhalb deines Projektverzeichnisses ab oder passe den Pfad in der `.env`-Datei über `SCHEMA_PATH=/dein/pfad/schema.sql` an.

### Fehlende Python-Abhängigkeiten (`ModuleNotFoundError`)
- **Ursache:** Die Pakete wurden nicht in der aktuellen Umgebung installiert oder die virtuelle Umgebung ist nicht aktiv.
- **Lösung:**
  - Vergewissere dich, dass deine virtuelle Umgebung aktiviert ist (`source venv/bin/activate` bzw. `.\venv\Scripts\Activate.ps1`).
  - Führe den Installationsbefehl erneut aus: `pip install -r requirements.txt`.

### Befehle reagieren nicht oder Slash-Commands tauchen nicht auf
- **Ursache:** Dem Bot fehlen die notwendigen Scopes oder Berechtigungen auf dem Server.
- **Lösung:** Vergewissere dich, dass der Bot mit dem Scope `applications.commands` eingeladen wurde und auf dem Server über ausreichende Rechte verfügt. Nach dem ersten Start kann die globale Synchronisation von Slash-Commands bei Discord wenige Minuten dauern.

---

## Lizenz

Astra wird unter den Bedingungen der [MIT License](License/License) veröffentlicht.
