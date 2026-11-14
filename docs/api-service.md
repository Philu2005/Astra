### Astra API als eigenständiger Dienst

Die interne API läuft jetzt als eigener Prozess und ist vom Bot-Start entkoppelt.

### Voraussetzungen

- Code liegt auf dem VPS unter `/root/Astra`
- Python-Umgebung ist eingerichtet (z. B. `/root/Astra/.venv`)
- `.env` im Projektroot enthält mindestens `ASTRA_INTERNAL_API_KEY`

### API installieren

- Optional nur API-Abhängigkeiten installieren:
  - `pip install -r api/requirements.txt`
- API starten (manuell):
  - `python -m api.run_api`

### systemd-Service installieren

- Service-Datei kopieren:
  - `sudo cp deploy/systemd/astra-api.service /etc/systemd/system/astra-api.service`
- systemd neu laden:
  - `sudo systemctl daemon-reload`
- Auto-Start aktivieren:
  - `sudo systemctl enable astra-api.service`
- Dienst starten:
  - `sudo systemctl start astra-api.service`

### Betrieb

- Status prüfen:
  - `sudo systemctl status astra-api.service`
- Neustarten:
  - `sudo systemctl restart astra-api.service`
- Stoppen:
  - `sudo systemctl stop astra-api.service`
- Logs ansehen:
  - `sudo journalctl -u astra-api.service -f`

### Trennung Bot/API

- Bot und API sind unabhängig startbar/stoppbar.
- Wenn API läuft und Bot ausfällt, bleibt `/health` erreichbar und `/status` zeigt nach Heartbeat-Timeout `offline`.
