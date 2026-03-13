<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);

try {

$pdo = new PDO(
"mysql:host=localhost;dbname=AstraDB;charset=utf8mb4",
"root",
"*AveMaria1108",
[
PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC
]
);

} catch(PDOException $e){
echo "DB ERROR: ".$e->getMessage();
exit;
}

$action = $_POST["action"] ?? $_GET["action"] ?? null;


if($action === "clear_logs"){

$pdo->query("TRUNCATE TABLE bot_logs");

echo "ok";
exit;

}

/* =========================
   BOT STATUS
========================= */

if($action === "bot_status"){

$status = trim(shell_exec("sudo /bin/systemctl is-active astrabot.service"));

echo $status;

exit;

}

/* =========================
   BOT INFO
========================= */

if($action === "bot_info"){

$status = trim(shell_exec("/bin/systemctl is-active astrabot.service"));

$pid = trim(shell_exec("systemctl show -p MainPID --value astrabot.service"));

$cpu = "0";
$ram = "0";

if($pid && $pid != "0"){

$cpu = trim(shell_exec("ps -p $pid -o %cpu="));
$ram = trim(shell_exec("ps -p $pid -o rss="));

$ram = round($ram/1024)." MB";

}

$start = trim(shell_exec("systemctl show -p ActiveEnterTimestamp --value astrabot.service"));

$startTime = strtotime($start);
$now = time();

$diff = $now - $startTime;

$weeks = floor($diff / 604800);
$diff %= 604800;

$days = floor($diff / 86400);
$diff %= 86400;

$hours = floor($diff / 3600);
$diff %= 3600;

$minutes = floor($diff / 60);
$seconds = $diff % 60;

$uptime = "";

if($weeks) $uptime .= $weeks."w ";
if($days) $uptime .= $days."d ";
if($hours) $uptime .= $hours."h ";
if($minutes) $uptime .= $minutes."m ";
$uptime .= $seconds."s";

echo json_encode([
"status"=>$status,
"pid"=>$pid,
"cpu"=>$cpu,
"ram"=>$ram,
"uptime"=>$uptime
]);

exit;

}

/* =========================
   BOT START
========================= */

if($action === "start_bot"){

shell_exec("sudo systemctl start astrabot.service");

echo "ok";
exit;

}

/* =========================
   BOT STOP
========================= */

if($action === "stop_bot"){

shell_exec("sudo systemctl stop astrabot.service");

echo "ok";
exit;

}


if($action === "restart_bot"){

shell_exec("sudo systemctl restart astrabot.service");

echo "ok";
exit;

}

if(!$action){
$action = null;
}

/* =========================
   LIST TASKS
========================= */

if($action === "list"){

header("Content-Type: application/json");
$stmt = $pdo->query("
SELECT *
FROM tasks
ORDER BY
    pinned DESC,
    (due IS NOT NULL AND due < CURDATE()) DESC,
    FIELD(priority,'KRITISCH','HOCH','MITTEL','NIEDRIG'),
    id DESC
");

echo json_encode($stmt->fetchAll());
exit;

}

/* =========================
   ADD TASK
========================= */
if($action === "add"){

$due = $_POST["due"] ?? null;

/* leeren String zu NULL konvertieren */
if($due === ""){
    $due = null;
}

$stmt = $pdo->prepare("
INSERT INTO tasks
(item, priority, risk, author, assignee, category, issue, due, file, `line`, pinned)
VALUES
(?,?,?,?,?,?,?,?,?,?,0)
");

$stmt->execute([
$_POST["item"] ?? null,
$_POST["priority"] ?? null,
$_POST["risk"] ?? null,
$_POST["author"] ?? null,
$_POST["assignee"] ?? null,
$_POST["category"] ?? null,
$_POST["issue"] ?? null,
$due,
$_POST["file"] ?? null,
$_POST["line"] ?? null
]);

$id = $pdo->lastInsertId();

$stmt = $pdo->prepare("SELECT * FROM tasks WHERE id = ?");
$stmt->execute([$id]);

header("Content-Type: application/json");
echo json_encode($stmt->fetch());

exit;

}
/* =========================
   UPDATE TASK
========================= */

if($action === "update"){

$due = $_POST["due"] ?? null;

if($due === ""){
    $due = null;
}

$stmt = $pdo->prepare("
UPDATE tasks SET
item=?,
priority=?,
risk=?,
author=?,
assignee=?,
category=?,
issue=?,
due=?,
file=?,
`line`=?
WHERE id=?
");

$stmt->execute([
$_POST["item"] ?? null,
$_POST["priority"] ?? null,
$_POST["risk"] ?? null,
$_POST["author"] ?? null,
$_POST["assignee"] ?? null,
$_POST["category"] ?? null,
$_POST["issue"] ?? null,
$due,
$_POST["file"] ?? null,
$_POST["line"] ?? null,
$_POST["id"] ?? 0
]);

$id = $_POST["id"] ?? 0;

$stmt = $pdo->prepare("SELECT * FROM tasks WHERE id = ?");
$stmt->execute([$id]);

header("Content-Type: application/json");
echo json_encode($stmt->fetch());

exit;

}

/* =========================
   DELETE TASK
========================= */

if($action === "delete"){

$stmt = $pdo->prepare("DELETE FROM tasks WHERE id = ?");
$stmt->execute([ $_POST["id"] ?? 0 ]);

echo "ok";
exit;

}

/* =========================
   PIN TASK
========================= */

if($action === "pin"){

$stmt = $pdo->prepare("UPDATE tasks SET pinned = ? WHERE id = ?");
$stmt->execute([
$_POST["pinned"] ?? 0,
$_POST["id"] ?? 0
]);

echo "ok";
exit;

}
?>

<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Astra Taskboard</title>

<style>

:root{

--hintergrund:#0d1117;
--karte:#161b22;
--text:#c9d1d9;
--rand:#30363d;

--akzent:#3b82f6;

--kritisch:#8b5cf6;
--hoch:#ef4444;
--mittel:#f59e0b;
--niedrig:#22c55e;

--tag-kategorie:#3b82f6;
--tag-problem:#ec4899;
--tag-faellig:#eab308;

--pinned:#22c55e;

}

*{box-sizing:border-box;}

body{
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial;
background:#0d1117;
color:var(--text);
margin:0;
padding:40px;
position:relative;
overflow-x:hidden;
}

/* Animated light blobs */

body::before,
body::after{
content:"";
position:fixed;
width:600px;
height:600px;
border-radius:50%;
filter:blur(160px);
opacity:0.25;
z-index:-1;
animation:moveGlow 18s infinite alternate ease-in-out;
}

body::before{
background:#3b82f6;
top:-200px;
left:-200px;
}

body::after{
background:#8b5cf6;
bottom:-200px;
right:-200px;
animation-delay:6s;
}

@keyframes moveGlow{

0%{
transform:translate(0,0) scale(1);
}

50%{
transform:translate(200px,-100px) scale(1.2);
}

100%{
transform:translate(-150px,150px) scale(1);
}

}

.container{
max-width:1200px;
margin:auto;
}

.header{
display:flex;
justify-content:space-between;
align-items:center;
margin-bottom:20px;
border-bottom:1px solid var(--rand);
padding-bottom:20px;
}

h1{font-weight:600;}

button{
background:var(--akzent);
border:none;
color:white;
padding:10px 16px;
border-radius:8px;
cursor:pointer;
font-weight:600;
transition:all .2s;
}

button:hover{
transform:translateY(-2px);
box-shadow:0 4px 12px rgba(0,0,0,0.4);
}

.delete-btn{background:#ef4444;}

td:last-child{
width:150px;
}

.action-buttons{
display:flex;
justify-content:flex-end;
gap:6px;
}

.pin-btn{
background:#374151;
}

.pin-btn.pinned{
background:var(--pinned);
color:black;
font-weight:bold;
}

.toolbar{
display:flex;
gap:10px;
margin-bottom:20px;
}

.search{
flex:1;
padding:10px;
border-radius:8px;
border:1px solid var(--rand);
background:#0d1117;
color:white;
}

.stats{
display:flex;
gap:20px;
margin-bottom:40px;
}

.stat-card{
background:var(--karte);
border:1px solid var(--rand);
border-radius:10px;
padding:20px;
flex:1;
text-align:center;
transition:all .2s;
}

.stat-card:hover{transform:translateY(-3px);}

.stat-value{
font-size:30px;
font-weight:bold;
}

.stat-KRITISCH{color:var(--kritisch)}
.stat-HOCH{color:var(--hoch)}
.stat-MITTEL{color:var(--mittel)}
.stat-NIEDRIG{color:var(--niedrig)}

table{
width:100%;
border-collapse:collapse;
background:var(--karte);
border-radius:10px;
overflow:hidden;
border:1px solid var(--rand);
}

th,td{
padding:14px 16px;
text-align:left;
border-bottom:1px solid var(--rand);
}

th{background:#1c2128;}

tr:hover{background:rgba(255,255,255,0.03);}

tr.pinned-row{
background:rgba(34,197,94,0.08);
border-left:4px solid var(--pinned);
}

.badge{
padding:5px 10px;
border-radius:20px;
font-size:12px;
font-weight:600;
}

.badge-KRITISCH{background:rgba(139,92,246,.2);color:#c4b5fd;border:1px solid var(--kritisch)}
.badge-HOCH{background:rgba(239,68,68,.2);color:#fca5a5;border:1px solid var(--hoch)}
.badge-MITTEL{background:rgba(245,158,11,.2);color:#fde68a;border:1px solid var(--mittel)}
.badge-NIEDRIG{background:rgba(34,197,94,.2);color:#86efac;border:1px solid var(--niedrig)}

.tag-list{display:flex;gap:6px;flex-wrap:wrap;}

.tag{
padding:4px 8px;
border-radius:6px;
font-size:11px;
font-weight:600;
}

.tag-kategorie{background:rgba(59,130,246,.2);border:1px solid var(--tag-kategorie);color:#93c5fd;}
.tag-problem{background:rgba(236,72,153,.2);border:1px solid var(--tag-problem);color:#f9a8d4;}
.tag-faellig{background:rgba(234,179,8,.2);border:1px solid var(--tag-faellig);color:#fde047;}


.overdue{
background:rgba(239,68,68,0.08);
border-left:4px solid #ef4444;
}

.tag-overdue{
background:rgba(239,68,68,0.2);
border:1px solid #ef4444;
color:#fca5a5;
}

.code-ref{font-family:monospace;color:#93c5fd;font-size:13px;}

.more-link{
color:#8b949e;
cursor:pointer;
font-size:13px;
margin-left:6px;
}

.more-link:hover{
color:white;
text-decoration:underline;
}

.modal{
position:fixed;
top:0;
left:0;
right:0;
bottom:0;
background:rgba(0,0,0,.7);
display:none;
align-items:center;
justify-content:center;
padding:20px;
overflow-y:auto;
}

.modal-content{
background:linear-gradient(180deg,#161b22,#0f141a);
padding:30px;
border-radius:12px;
width:100%;
max-width:560px;
border:1px solid var(--rand);
position:relative;

max-height:90vh;
overflow-y:auto;
}

.modal-title{
font-size:22px;
font-weight:600;
margin-bottom:25px;
border-bottom:1px solid var(--rand);
padding-bottom:12px;
}

.section{margin-bottom:20px;}

.grid{
display:grid;
grid-template-columns:1fr 1fr;
gap:14px;
}

.feld{display:flex;flex-direction:column;gap:5px;}

label{font-size:12px;color:#8b949e;font-weight:600;}

input,select{
padding:10px;
border-radius:8px;
border:1px solid var(--rand);
background:#0d1117;
color:white;
}

.modal-buttons{display:flex;gap:10px;margin-top:20px;}

.abbrechen{background:#30363d;}

.big-view{
max-width:700px;
}

.big-text{
font-size:16px;
line-height:1.6;
white-space:pre-wrap;
}

.close-x{
position:absolute;
top:12px;
right:18px;
font-size:22px;
cursor:pointer;
color:#8b949e;
}

.close-x:hover{color:white;}


.dev-grid{
display:grid;
grid-template-columns:340px 1fr;
gap:22px;
margin-bottom:32px;
}

/* Panels */

.panel{
background:linear-gradient(
180deg,
rgba(22,27,34,0.95),
rgba(13,17,23,0.95)
);

border:1px solid rgba(255,255,255,0.05);
border-radius:14px;

padding:22px;

box-shadow:
0 10px 30px rgba(0,0,0,0.5),
inset 0 1px 0 rgba(255,255,255,0.05);

backdrop-filter:blur(6px);

transition:all .2s ease;
}

.panel:hover{
transform:translateY(-3px);
box-shadow:
0 14px 35px rgba(0,0,0,0.6),
inset 0 1px 0 rgba(255,255,255,0.08);
}

/* Panel Header */

.panel-header{
display:flex;
justify-content:space-between;
align-items:center;
margin-bottom:14px;
}

/* Bot Info Grid */

.status-info{
display:grid;
grid-template-columns:1fr 1fr;
gap:12px;
margin:16px 0 14px 0;
}

.stat-box{
background:linear-gradient(
180deg,
rgba(255,255,255,0.04),
rgba(0,0,0,0.25)
);

border:1px solid rgba(255,255,255,0.05);
border-radius:10px;

padding:10px 12px;

display:flex;
flex-direction:column;
gap:4px;

transition:all .15s ease;
}

.stat-box:hover{
background:rgba(255,255,255,0.06);
}

.stat-label{
font-size:11px;
letter-spacing:.8px;
color:#6b7280;
font-weight:600;
}

.stat-box-value{
font-size:15px;
font-weight:600;
color:#e5e7eb;
}

/* Status Badge */

.status-badge{
padding:5px 12px;
border-radius:999px;
font-size:12px;
font-weight:600;
letter-spacing:.4px;
}

.status-online{
background:rgba(34,197,94,.15);
color:#22c55e;
border:1px solid rgba(34,197,94,.6);
box-shadow:0 0 10px rgba(34,197,94,.25);
}

.status-offline{
background:rgba(239,68,68,.15);
color:#ef4444;
border:1px solid rgba(239,68,68,.6);
}

/* Bot Actions */

.status-actions{
display:flex;
gap:10px;
margin-top:12px;
}

.status-actions button{
padding:8px 14px;
border-radius:8px;
font-size:13px;
font-weight:600;
cursor:pointer;
border:none;
transition:all .15s ease;
}

.status-actions button:hover{
transform:translateY(-1px);
}

/* Buttons */

.btn-start{
background:#22c55e;
}

.btn-stop{
background:#ef4444;
}

.btn-restart{
background:#f59e0b;
}

/* Logs */

.console-wrapper{
position:relative;
height:260px;
}

/* LOG BOX */

#logs{
position:absolute;
top:0;
left:0;
right:0;
bottom:0;

overflow:auto;

background:linear-gradient(
180deg,
#0b0f14,
#05080c
);

border:1px solid rgba(255,255,255,0.06);
border-radius:12px;

/* FIX */
padding:14px;

font-family:
JetBrains Mono,
Fira Code,
monospace;

font-size:12.5px;
line-height:1.45;

box-shadow:
inset 0 0 20px rgba(0,0,0,0.8);
}

/* Scrollbar */

#logs::-webkit-scrollbar{
width:8px;
}

#logs::-webkit-scrollbar-thumb{
background:#2b323a;
border-radius:6px;
}

#logs::-webkit-scrollbar-thumb:hover{
background:#3b4550;
}

/* BUTTON POSITION */

.console-controls{
position:absolute;
top:12px;
right:14px;
z-index:20;
}

/* GLASS BUTTON */

.console-controls button{

background:rgba(34,197,94,0.15);

backdrop-filter:blur(10px);
-webkit-backdrop-filter:blur(10px);

border:1px solid rgba(34,197,94,0.5);

color:#86efac;

padding:5px 12px;
border-radius:10px;

font-size:11px;
font-weight:600;

cursor:pointer;

box-shadow:
0 4px 10px rgba(0,0,0,0.35),
0 0 10px rgba(34,197,94,0.2),
inset 0 1px 0 rgba(255,255,255,0.25);

transition:all .18s ease;
}

.console-controls button:hover{

background:rgba(34,197,94,0.25);

transform:translateY(-1px);

box-shadow:
0 0 14px rgba(34,197,94,0.5),
0 6px 14px rgba(0,0,0,0.45),
inset 0 1px 0 rgba(255,255,255,0.35);

color:white;
}


.cpu{
color:#22c55e;
}

.ram{
color:#38bdf8;
}

.pid{
color:#a78bfa;
}

.uptime{
color:#f59e0b;
}
</style>
<style>
/* =========================
   RESPONSIVE LAYOUT
========================= */

@media (max-width: 1100px){

.dev-grid{
grid-template-columns:1fr;
}

}

/* =========================
   TABLET
========================= */

@media (max-width: 900px){

body{
padding:20px;
}

/* Header */

.header{
flex-direction:column;
align-items:flex-start;
gap:15px;
}

.status-info{
grid-template-columns:1fr;
}

h1{
font-size:22px;
}

/* Bot Panels */

.dev-grid{
grid-template-columns:1fr;
gap:16px;
}

.panel{
padding:16px;
}

/* Logs */

#logs{
height:200px;
font-size:12px;
}

/* Toolbar */

.toolbar{
flex-direction:column;
gap:10px;
}

.search{
width:100%;
}

/* Stats */

.stats{
flex-direction:column;
gap:12px;
margin-bottom:25px;
}

.stat-card{
padding:16px;
}

/* TABLE -> CARDS */

table{
border:none;
background:none;
}

thead{
display:none;
}

tbody{
display:flex;
flex-direction:column;
gap:12px;
}

tr{
display:block;
background:var(--karte);
border:1px solid var(--rand);
border-radius:10px;
padding:14px;
}

/* Cells */

td{
display:flex;
justify-content:space-between;
align-items:center;
padding:6px 0;
border:none;
}

/* Beschreibung */

td:nth-child(4){
flex-direction:column;
align-items:flex-start;
font-size:15px;
margin-bottom:6px;
word-break:break-word;
overflow-wrap:anywhere;
}

/* Tags */

td:nth-child(7){
flex-direction:column;
align-items:flex-start;
gap:6px;
}

/* Datei */

td:nth-child(8){
font-size:12px;
opacity:0.8;
}

/* Buttons */

td:last-child{
justify-content:flex-end;
margin-top:8px;
}

.delete-btn{
width:100%;
}

/* Modal */

.modal-content{
width:100%;
max-width:none;
padding:20px;
}

.modal-title{
font-size:18px;
}

.modal-buttons{
flex-direction:column;
}

.modal-buttons button{
width:100%;
}

/* Formular */

.grid{
grid-template-columns:1fr;
}

}

/* =========================
   SMALL PHONES
========================= */

@media (max-width: 500px){

body{
padding:14px;
}

h1{
font-size:20px;
}

.panel{
padding:14px;
}

#logs{
height:160px;
font-size:11px;
}

/* Stats */

.stat-card{
padding:14px;
}

.stat-value{
font-size:24px;
}

/* Buttons */

button{
padding:8px 12px;
font-size:13px;
}

/* Status Buttons */

.status-actions{
flex-direction:column;
}

.status-actions button{
width:100%;
}

}
</style>
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

<script>

let tasks=[]
let deleteIndex=null
let editingId = null
let logOffset = 0
let logCount = 0
let logCursor = localStorage.getItem("logCursor") || ""
let logSource = null

async function loadTasks(){

let res = await fetch("index.php?t="+Date.now(),{
method:"POST",
headers:{
"Content-Type":"application/x-www-form-urlencoded"
},
body:"action=list"
})

tasks = await res.json()

render()

}

async function saveTask(){

let res = await fetch("index.php",{
method:"POST",
headers:{
"Content-Type":"application/x-www-form-urlencoded"
},
body:new URLSearchParams({
action: editingId ? "update" : "add",
id: editingId,
item:document.getElementById("item").value,
priority:document.getElementById("priority").value,
risk:document.getElementById("risk").value,
author:document.getElementById("author").value,
assignee:document.getElementById("assignee").value,
category:document.getElementById("category").value,
issue:document.getElementById("issue").value,
due:document.getElementById("due").value,
file:document.getElementById("file").value,
line:document.getElementById("line").value
})
})

closeModal()

// immer neu laden -> SQL sortiert korrekt
await loadTasks()

editingId = null

}

async function confirmDelete(){

await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=delete&id="+deleteIndex
})

deleteIndex = null

await loadTasks()

closeConfirm()

}
function createTask(){

editingId = null

document.getElementById("taskModalTitle").innerText =
"Neue Aufgabe erstellen"
document.querySelectorAll("#modal input").forEach(i=>i.value="")

openModal()

}

async function togglePin(id){

let t = tasks.find(x => x.id == id)

if(!t) return

await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:new URLSearchParams({
action:"pin",
id:id,
pinned:t.pinned ? 0 : 1
})
})

loadTasks()

}

function render(){

const search=document.getElementById("search").value.toLowerCase()
const pFilter=document.getElementById("filterPriority")?.value || ""
const rFilter=document.getElementById("filterRisk")?.value || ""

const table=document.getElementById("taskTable")
table.innerHTML=""

let kritisch=0,hoch=0,mittel=0,niedrig=0

tasks.forEach(t=>{

const p=(t.priority||"").trim().toUpperCase()

if(p==="KRITISCH")kritisch++
if(p==="HOCH")hoch++
if(p==="MITTEL")mittel++
if(p==="NIEDRIG")niedrig++

})

let filtered = tasks.filter(t => {

if(pFilter && t.priority !== pFilter) return false
if(rFilter && t.risk !== rFilter) return false

const text = (
(t.item||"")+
(t.author||"")+
(t.assignee||"")+
(t.category||"")+
(t.issue||"")+
(t.file||"")
).toLowerCase()

if(!text.includes(search)) return false

return true

})

filtered.forEach((t,i)=>{

let overdue=false

if(t.due){
let today=new Date().toISOString().split("T")[0]

if(t.due < today){
overdue=true
}
}

const text=(
(t.item||"")+
(t.author||"")+
(t.assignee||"")+
(t.category||"")+
(t.issue||"")+
(t.file||"")
).toLowerCase()

let location=""
if(t.file){
location=t.file
if(t.line){location+=":"+t.line}
}

let description = (t.item ?? "").toString().trim()

let previewLength = 18
let short = description

if(description.length > previewLength){

let preview = description.substring(0,previewLength)

short = preview + `… <span class="more-link" onclick="openView('${description.replace(/'/g,"\\'")}')">mehr anzeigen</span>`

}

table.innerHTML+=`

<tr class="${t.pinned==1?'pinned-row':''} ${overdue?'overdue':''}">

<td>
<button class="pin-btn ${t.pinned==1?'pinned':''}" onclick="togglePin(${t.id})">
${t.pinned==1?"📌":"📍"}
</button>
</td>

<td><span class="badge badge-${t.priority}">${t.priority}</span></td>

<td>${t.risk||""}</td>

<td style="font-weight:500;color:white">${short}</td>

<td>@${t.author||""}</td>

<td>${t.assignee ? "@"+t.assignee : ""}</td>

<td>

<div class="tag-list">

${t.category?`<span class="tag tag-kategorie">${t.category}</span>`:""}
${t.issue?`<span class="tag tag-problem">${t.issue}</span>`:""}
${t.due?`<span class="tag tag-faellig">${t.due}</span>`:""}
${overdue?`<span class="tag tag-overdue">Überfällig</span>`:""}

</div>

</td>

<td><span class="code-ref">${location}</span></td>

<td>
<div class="action-buttons">
<button onclick="editTask(${t.id})">Edit</button>
<button class="delete-btn" onclick="askDelete(${t.id})">Löschen</button>
</div>
</td>

</tr>

`

})

document.getElementById("total").innerText=tasks.length
document.getElementById("kritisch").innerText=kritisch
document.getElementById("hoch").innerText=hoch
document.getElementById("mittel").innerText=mittel
document.getElementById("niedrig").innerText=niedrig

}

function askDelete(id){
deleteIndex=id
document.getElementById("confirmModal").style.display="flex"
}

function closeConfirm(){
document.getElementById("confirmModal").style.display="none"
}

function openView(text){
document.getElementById("bigText").innerText=text
document.getElementById("viewModal").style.display="flex"
}

function closeView(){
document.getElementById("viewModal").style.display="none"
}

function openModal(){

document.getElementById("taskModalTitle").innerText =
"Neue Aufgabe erstellen"

document.getElementById("modal").style.display="flex"

}

function closeModal(){
document.getElementById("modal").style.display="none"
}

function openFilter(){
document.getElementById("filterModal").style.display="flex"
}

function closeFilter(){
document.getElementById("filterModal").style.display="none"
}

loadTasks()
startLogStream()
loadBotStatus()

setInterval(loadBotStatus,5000)


function startLogStream(){

const logBox = document.getElementById("logs")
let savedLogs = localStorage.getItem("savedLogs")

if(savedLogs){
logBox.insertAdjacentHTML("beforeend", savedLogs)
logBox.scrollTop = logBox.scrollHeight
}

if(logSource){
logSource.close()
}

let url = "logs.php"

if(logCursor){
url += "?cursor=" + encodeURIComponent(logCursor)
}

logSource = new EventSource(url)

logSource.onmessage = function(event){

let data = JSON.parse(event.data)

let line = data.msg
let cursor = data.cursor

if(cursor){
logCursor = cursor
localStorage.setItem("logCursor", cursor)
}

let color = "#c9d1d9"

if(line.includes("ERROR")) color = "#ef4444"
if(line.includes("WARN")) color = "#f59e0b"
if(line.includes("INFO")) color = "#22c55e"

let div=document.createElement("div")
div.style.color=color
div.textContent=line

logBox.appendChild(div)

/* HIER HINZUFÜGEN */
localStorage.setItem("savedLogs", logBox.innerHTML)

if(logBox.children.length > 300){
logBox.removeChild(logBox.firstChild)
}

logBox.scrollTop = logBox.scrollHeight

}

logSource.onerror = function(){
logSource.close()
setTimeout(startLogStream,2000)
}

}


async function clearLogs(){

const logBox = document.getElementById("logs")

logBox.innerHTML=""

await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=clear_logs"
})

localStorage.removeItem("savedLogs")
localStorage.removeItem("logCursor")

logCursor=""

if(logSource){
logSource.close()
}

startLogStream()

}

async function loadBotStatus(){

try{

let res = await fetch("index.php?action=bot_info&t=" + Date.now())

if(!res.ok){
throw new Error("API error")
}

let data = await res.json()

let badge = document.getElementById("botState")
let actions = document.getElementById("botActions")

document.getElementById("botPid").innerHTML =
'<span class="pid">'+(data.pid || "-")+'</span>'

document.getElementById("botCpu").innerHTML =
'<span class="cpu">'+data.cpu+' %</span>'

document.getElementById("botRam").innerHTML =
'<span class="ram">'+data.ram+'</span>'

document.getElementById("botUptime").innerHTML =
'<span class="uptime">'+(data.uptime || "-")+'</span>'

actions.innerHTML=""

if(data.status === "active"){

badge.innerText="Online"
badge.className="status-badge status-online"

actions.innerHTML=`
<button class="btn-stop" onclick="openBotConfirm('stop')">Stop</button>
<button class="btn-restart" onclick="openBotConfirm('restart')">Restart</button>
`

}else{

badge.innerText="Offline"
badge.className="status-badge status-offline"

actions.innerHTML=`
<button class="btn-start" onclick="startBot()">Start</button>
`

}

}catch(e){

console.error(e)
document.getElementById("botState").innerText="Unknown"

}

}

async function startBot(){

await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=start_bot"
})

/* Logs neu starten */
logCursor = ""
localStorage.removeItem("logCursor")

startLogStream()

loadBotStatus()

}

async function stopBot(){

if(!confirm("Bot wirklich stoppen?")) return

/* SSE sofort killen */
if(logSource){
logSource.close()
logSource = null
}

/* Cursor reset */
logCursor = ""

/* local storage löschen */
localStorage.removeItem("savedLogs")
localStorage.removeItem("logCursor")

/* Konsole sofort leeren */
const logBox = document.getElementById("logs")
logBox.innerHTML=""

/* Bot stoppen */
await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=stop_bot"
})

/* Bot Status neu laden */
loadBotStatus()

}


let botAction = null

function openBotConfirm(type){

botAction = type

const modal = document.getElementById("botConfirmModal")
const title = document.getElementById("botConfirmTitle")
const text = document.getElementById("botConfirmText")
const btn = document.getElementById("botConfirmBtn")

if(type === "stop"){
title.innerText = "Bot stoppen"
text.innerText = "Willst du den Bot wirklich stoppen?"
}

if(type === "restart"){
title.innerText = "Bot neu starten"
text.innerText = "Willst du den Bot wirklich neu starten?"
}

btn.onclick = executeBotAction

modal.style.display = "flex"

}

function closeBotConfirm(){
document.getElementById("botConfirmModal").style.display="none"
}

async function executeBotAction(){

const logBox = document.getElementById("logs")

if(botAction === "stop"){

/* SSE killen */
if(logSource){
logSource.close()
logSource = null
}

/* Cursor reset */
logCursor = ""

/* localStorage löschen */
localStorage.removeItem("savedLogs")
localStorage.removeItem("logCursor")

/* Konsole leeren */
logBox.innerHTML=""

/* Bot stoppen */
await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=stop_bot"
})

}

if(botAction === "restart"){

/* Logs auch resetten */
if(logSource){
logSource.close()
logSource = null
}

logCursor = ""
localStorage.removeItem("savedLogs")
localStorage.removeItem("logCursor")

logBox.innerHTML=""

/* Restart */
await fetch("index.php",{
method:"POST",
headers:{"Content-Type":"application/x-www-form-urlencoded"},
body:"action=restart_bot"
})

startLogStream()

}

closeBotConfirm()
loadBotStatus()

}

</script>
<script>
    function editTask(id){

let t = tasks.find(x => x.id == id)

if(!t) return

document.getElementById("item").value = t.item || ""
document.getElementById("priority").value = t.priority || "MITTEL"
document.getElementById("risk").value = t.risk || "MITTEL"
document.getElementById("author").value = t.author || ""
document.getElementById("assignee").value = t.assignee || ""
document.getElementById("category").value = t.category || ""
document.getElementById("issue").value = t.issue || ""
document.getElementById("due").value = t.due || ""
document.getElementById("file").value = t.file || ""
document.getElementById("line").value = t.line || ""

editingId = id

document.getElementById("taskModalTitle").innerText =
"Aufgabe bearbeiten"

openModal()

}
</script>

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