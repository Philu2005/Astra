<!DOCTYPE html>
<html lang="de">

<head>

	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">

	<title>Astra Control Panel</title>

	<link rel="icon" href="https://astra-bot.de/public/favicon_transparent.png">

	<link rel="stylesheet" href="css/style.css">

	<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

</head>


<body>

<div class="container">

<div class="header">
<h1>Astra Control Panel</h1>
<button type="button" onclick="createTask()">+ Aufgabe hinzufügen</button>
</div>

<div class="dev-grid">

<div class="panel">

<div class="panel-header">
<h3>Bot Status</h3>
<span id="botState" class="status-badge">Loading...</span>
</div>

<div class="status-info">

<div class="stat-box">
<span class="stat-label">PID</span>
<span class="stat-box-value" id="botPid">-</span>
</div>

<div class="stat-box">
<span class="stat-label">CPU</span>
<span class="stat-box-value" id="botCpu">-</span>
</div>

<div class="stat-box">
<span class="stat-label">RAM</span>
<span class="stat-box-value" id="botRam">-</span>
</div>

<div class="stat-box">
<span class="stat-label">UPTIME</span>
<span class="stat-box-value" id="botUptime">-</span>
</div>

</div>

<div class="status-actions" id="botActions"></div>

</div>

<div class="panel">

<h3>Live Logs</h3>

<div class="console-wrapper">

<div class="console-controls">
<button onclick="clearLogs()">🧹 Clear</button>
</div>

<div id="logs"></div>

</div>

</div>


</div>


<div class="toolbar">
<input class="search" id="search" placeholder="Suche Aufgaben..." oninput="render()">
<button onclick="openFilter()">Filter</button>
</div>

<div class="stats">

<div class="stat-card">
<div class="stat-value" id="total">0</div>
<div>Gesamt</div>
</div>

<div class="stat-card">
<div class="stat-value stat-KRITISCH" id="kritisch">0</div>
<div>Kritisch</div>
</div>

<div class="stat-card">
<div class="stat-value stat-HOCH" id="hoch">0</div>
<div>Hoch</div>
</div>

<div class="stat-card">
<div class="stat-value stat-MITTEL" id="mittel">0</div>
<div>Mittel</div>
</div>

<div class="stat-card">
<div class="stat-value stat-NIEDRIG" id="niedrig">0</div>
<div>Niedrig</div>
</div>

</div>

<table>

<thead>

<tr>

<th>Pin</th>
<th>Priorität</th>
<th>Risiko</th>
<th>Beschreibung</th>
<th>Autor</th>
<th>Zuständig</th>
<th>Tags</th>
<th>Datei</th>
<th></th>

</tr>

</thead>

<tbody id="taskTable"></tbody>

</table>

<div class="modal" id="confirmModal">
<div class="modal-content">
<div class="modal-title">Wirklich löschen?</div>
<div>Diese Aufgabe wird dauerhaft gelöscht.</div>
<div class="modal-buttons">
<button onclick="confirmDelete()">Ja löschen</button>
<button class="abbrechen" onclick="closeConfirm()">Abbrechen</button>
</div>
</div>
</div>


<div class="modal" id="filterModal">
<div class="modal-content">
<div class="modal-title">Filter</div>

<div class="section grid">

<div class="feld">
<label>Priorität</label>
<select id="filterPriority">
<option value="">Alle</option>
<option>KRITISCH</option>
<option>HOCH</option>
<option>MITTEL</option>
<option>NIEDRIG</option>
</select>
</div>

<div class="feld">
<label>Risiko</label>
<select id="filterRisk">
<option value="">Alle</option>
<option>HOCH</option>
<option>MITTEL</option>
<option>NIEDRIG</option>
</select>
</div>

</div>

<div class="modal-buttons">
<button onclick="render();closeFilter()">Anwenden</button>
<button class="abbrechen" onclick="closeFilter()">Schließen</button>
</div>

</div>
</div>


<div class="modal" id="modal">

<div class="modal-content">

<div class="modal-title" id="taskModalTitle">Neue Aufgabe erstellen</div>

<div class="section">

<div class="feld">
<label>Beschreibung</label>
<input id="item">
</div>

</div>

<div class="section grid">

<div class="feld">
<label>Priorität</label>
<select id="priority">
<option>KRITISCH</option>
<option>HOCH</option>
<option>MITTEL</option>
<option>NIEDRIG</option>
</select>
</div>

<div class="feld">
<label>Risiko</label>
<select id="risk">
<option>HOCH</option>
<option>MITTEL</option>
<option>NIEDRIG</option>
</select>
</div>

</div>

<div class="section grid">

<div class="feld">
<label>Autor</label>
<input id="author">
</div>

<div class="feld">
<label>Zuständige Person</label>
<input id="assignee">
</div>

</div>

<div class="section grid">

<div class="feld">
<label>Kategorie</label>
<input id="category">
</div>

<div class="feld">
<label>Problem / Issue</label>
<input id="issue">
</div>

<div class="feld">
<label>Fälligkeitsdatum</label>
<input id="due" type="date">
</div>

</div>

<div class="section grid">

<div class="feld">
<label>Datei</label>
<input id="file">
</div>

<div class="feld">
<label>Zeile</label>
<input id="line">
</div>

</div>

<div class="modal-buttons">

<button onclick="saveTask()">Speichern</button>
<button class="abbrechen" onclick="closeModal()">Abbrechen</button>

</div>

</div>
</div>


<div class="modal" id="viewModal">
<div class="modal-content big-view">
<div class="close-x" onclick="closeView()">✕</div>
<div class="modal-title">Beschreibung</div>
<div class="big-text" id="bigText"></div>
</div>
</div>

	<script src="api/panel.js"></script>
<div class="modal" id="botConfirmModal">
<div class="modal-content">

<div class="modal-title" id="botConfirmTitle">Bestätigen</div>

<div id="botConfirmText">
Aktion wirklich ausführen?
</div>

<div class="modal-buttons">
<button id="botConfirmBtn">Ja</button>
<button class="abbrechen" onclick="closeBotConfirm()">Abbrechen</button>
</div>

</div>
</div>

</body>
</html>