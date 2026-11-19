-- Astra Panel-Key System Migration 2026
-- Dieses Script migriert die bestehende Datenbankstruktur auf das panel_key System.
-- Es fügt UUID-basierte Schlüssel zu allen panelbezogenen Tabellen hinzu.

-- 1. Spalten hinzufügen
-- Hinweis: Falls Spalten bereits existieren (z.B. durch einen vorherigen Teil-Lauf), schlägt dies fehl. 
-- In MySQL 8.0.19+ kann man IF NOT EXISTS nutzen, für ältere Versionen ist dies ein manueller Schritt.

ALTER TABLE ticketsystem ADD COLUMN panel_key VARCHAR(36) NULL;
ALTER TABLE ticketsystem_channels ADD COLUMN panel_key VARCHAR(36) NULL;
ALTER TABLE ticket_autoclose_state ADD COLUMN panel_key VARCHAR(36) NULL;
ALTER TABLE ticketlog ADD COLUMN panel_key VARCHAR(36) NULL;

-- 2. Indizes hinzufügen für Performance
CREATE INDEX idx_ts_panel_key ON ticketsystem(panel_key);
CREATE INDEX idx_tsc_panel_key ON ticketsystem_channels(panel_key);
CREATE INDEX idx_tas_panel_key ON ticket_autoclose_state(panel_key);
CREATE INDEX idx_tl_panel_key ON ticketlog(panel_key);

-- 3. Datenmigration
-- Führe NACH diesem SQL-Script den Bot-Befehl '!restorepanelids mode:apply' aus.
-- Das Python-Script 'scripts/restore_ticket_panel_descriptions.py' übernimmt:
-- a) Generierung der UUIDs für bestehende Panels in 'ticketsystem'.
-- b) Zuordnung bestehender Tickets in 'ticketsystem_channels' via Gilde/Kategorie.
-- c) Zuordnung der Autoclose-Zustände.

-- 4. Dokumentation der Beziehungen:
-- ticketsystem.panel_key (UUID) -> ticketsystem_channels.panel_key
-- ticketsystem.panel_key (UUID) -> ticket_autoclose_state.panel_key
-- ticketsystem.panel_key (UUID) -> ticketlog.panel_key (NULL = serverweit)
