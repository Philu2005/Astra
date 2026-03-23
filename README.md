<p align="center">
  <img src="/cogs/assets/banner.svg?v=8" alt="Astra Banner" />
</p>

# 🚀 Astra

![Version](https://img.shields.io/badge/Projekt_Version-2.8.4-blue)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python\&logoColor=white)
![discord.py](https://img.shields.io/badge/Library-discord.py-5865F2?logo=discord\&logoColor=white)
![MySQL](https://img.shields.io/badge/Database-MySQL-4479A1?logo=mysql\&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-2ea44f)
![Stars](https://img.shields.io/github/stars/Philu2005/astra?style=social)




**Astra** ist ein modularer Discord-Bot zur **Serververwaltung, Automatisierung und Community-Interaktion**.

Der Bot kombiniert Moderation, Community-Systeme, Automationen und Unterhaltung in einem leistungsstarken System auf Basis von **discord.py**.

---

## ✨ Übersicht

Astra unterstützt Discord-Server dabei, **organisiert, aktiv und automatisiert** zu bleiben.

## ⚙️ Wichtige Funktionen

| Kategorie      | Beschreibung                 |
|:---------------|:-----------------------------|
| 🛡 Moderation  | Automod, Moderationstools    |
| 📈 Community   | Levelsystem, Economy, Events |
| ⚙ Automationen| Server-Automationen          |
| 🎮 Fun         | Spiele & Commands            |
| 📊 Utility     | Infos & Tools                |
| 💾 Backups     | Server-Backups               |


---

## ⚡ Installation & Einrichtung

```bash
# Repository klonen
git clone https://github.com/Philu2005/astra.git
cd astra

# Abhängigkeiten installieren
pip install -r requirements.txt

# Konfigurationsdatei erstellen
touch .env

# Beispielkonfiguration (.env)

# Discord
DISCORD_TOKEN=

# Datenbank
DB_HOST=
DB_USER=
DB_PASS=
DB_NAME=

# Top.gg
DBL_TOKEN=
DBL_PASS=
DBL_PORT=

# Webhooks
WEBHOOK_SECRET=

# APIs
YOUTUBE_API_KEY=
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=

# Bot starten
python main.py
```

---

## 📁 Projektstruktur

```text
astra
│
├── cogs/            # Bot Commands & Features
├── main.py          # Bot entry point
├── requirements.txt # Python dependencies
└── README.md
```

---

## 🤝 Mitwirken

Dieses Projekt ist hauptsächlich **Open Source für Transparenz und Inspiration**.

Du kannst gerne:

• den Code erkunden  
• Ideen übernehmen  
• Pull Requests öffnen  

---

## 📄 Lizenz

Dieses Projekt steht unter der **MIT License**.