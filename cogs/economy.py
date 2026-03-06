import discord
from discord import app_commands
from discord.app_commands import Group
from discord.ui import Button, View
from discord.ext import commands
import aiomysql
import asyncio
from typing import Literal
import random
from datetime import datetime, timezone, timedelta
from discord import ui
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)
# ---------- Slot-Config (balanciert & lohnend) ----------
WILD = "⭐"
SCAT = "🔔"

# Reels: 1x ⭐ pro Reel, 1–2x 🔔, mehr Low/Mid, wenige Highs
REEL_STRIPS = [
    # Reel 1
    ["🍒","🍒","🍋","🍊","🍇","🍓","🍒","🍋","🍊","🍉",
     "🍒","🍋","🍇","🍓","🍊","🍍", SCAT, "🍒", WILD, "🍋"],
    # Reel 2
    ["🍒","🍋","🍊","🍇","🍓","🍉","🍒","🍋","🍊","🍇",
     "🍓","🍒","🍋","🍊","🍍","🍉", WILD, SCAT, "🍇","🍋"],
    # Reel 3
    ["🍒","🍋","🍊","🍇","🍓","🍉","🍒","🍋","🍊","🍇",
     "🍓","🍒","🍋","🍊","🍍","🍉", SCAT, "🍇", WILD, "🍋"],
]

# 9 Gewinnlinien
PAYLINES = [
    ([(0,0),(0,1),(0,2)], "Obere Reihe"),
    ([(1,0),(1,1),(1,2)], "Mittlere Reihe"),
    ([(2,0),(2,1),(2,2)], "Untere Reihe"),
    ([(0,0),(1,0),(2,0)], "Linke Spalte"),
    ([(0,1),(1,1),(2,1)], "Mittlere Spalte"),
    ([(0,2),(1,2),(2,2)], "Rechte Spalte"),
    ([(0,0),(1,1),(2,2)], "↘ Diagonale"),
    ([(2,0),(1,1),(0,2)], "↗ Diagonale"),
    ([(1,0),(1,1),(1,2)], "Mittellinie (Bonus)"),
]

# Basis-Multis (größer als vorher, damit Treffer lohnen)
PAYTABLE = {
    "🍒": 2,
    "🍋": 3,
    "🍊": 4,
    "🍇": 7,
    "🍓": 10,
    "🍉": 15,
    "🍍": 25,
    WILD: 0,  # 3×⭐ wird separat behandelt (siehe line_payout)
}

# Wild-Boost für gemischte Linien (Base + 1–2 Wilds)
WILD_LINE_MULT = {
    0: 1,  # ohne ⭐
    1: 2,  # 1 Wild ≈ x2
    2: 4,  # 2 Wilds ≈ x4
}
PURE_WILDS_MULTI = 40  # 3×⭐ auf einer Linie

# Scatter zahlt + Freespins
SCATTER_PAYS = {3: 3, 4: 6, 5: 12}  # => payout = bet * factor
FREESPINS_FOR_3_SCAT = 6            # spürbarer Bonus

# Nudges etwas konservativer, damit „Rettungen“ selten bleiben
NUDGE_SCATTER_CHANCE = 0.30
NUDGE_LINE_CHANCE    = 0.14

SPIN_FRAMES = 5
FRAME_DELAY = 0.35

def spin_reels():
    """Pro Spalte einen Startindex wählen und ein 3er-Fenster lesen (echtes Reel-Feeling)."""
    cols = []
    for strip in REEL_STRIPS:
        start = random.randint(0, len(strip) - 1)
        window = [strip[(start + i) % len(strip)] for i in range(3)]
        cols.append(window)  # Spalte
    # Spalten → Zeilen transponieren: board[row][col]
    return [list(row) for row in zip(*cols)]

def nudge_for_scatter(board):
    # Wenn genau 2 Scatter sichtbar, Chance eine Spalte zu nudgen -> 3. Scatter
    flat = [(r,c) for r in range(3) for c in range(3)]
    scs = [(r,c) for (r,c) in flat if board[r][c] == SCAT]
    if len(scs) != 2 or random.random() > NUDGE_SCATTER_CHANCE:
        return board
    for col in range(3):
        top = board[0][col]
        strip = REEL_STRIPS[col]
        idx = strip.index(top)
        idx = (idx + 1) % len(strip)
        new_col = [strip[idx % len(strip)], strip[(idx+1) % len(strip)], strip[(idx+2) % len(strip)]]
        new_board = [row[:] for row in board]
        for r in range(3):
            new_board[r][col] = new_col[r]
        if sum(1 for r in range(3) for c in range(3) if new_board[r][c] == SCAT) >= 3:
            return new_board
    return board

# ========= zuverlässige Breitenmessung =========
try:
    from wcwidth import wcswidth  # pip install wcwidth
except ImportError:
    import unicodedata
    def wcswidth(s: str) -> int:
        w = 0
        for ch in s:
            if unicodedata.combining(ch):
                continue
            ea = unicodedata.east_asian_width(ch)
            if ea in ("W", "F") or ord(ch) >= 0x1F300:  # Emojis ~2
                w += 2
            else:
                w += 1
        return w

# ========= Board-Renderer =========
CELL_W = 7   # Breite jeder Zelle
VERT   = "│"
HOR    = "─"

def _pad_center(s: str, width: int) -> str:
    w = max(0, wcswidth(s))
    if w >= width:
        return s
    left = (width - w) // 2
    right = width - w - left
    return " " * left + s + " " * right

def render_board(board, winline_idxs=None, freespins_left=0):
    """
    Stabiles 3×3 Board (monospace), Emojis zentriert.
    Gewinnfelder werden mit 〔 〕 markiert.
    """
    winline_idxs = set(winline_idxs or [])

    # Highlight-Zellen bestimmen
    idx_to_coords = {i: coords for i,(coords,_name) in enumerate(PAYLINES)}
    highlight = [[False]*3 for _ in range(3)]
    for i in winline_idxs:
        for (r,c) in idx_to_coords.get(i, []):
            highlight[r][c] = True

    def fmt_cell(r, c):
        s = board[r][c]
        if highlight[r][c]:
            s = f"〔{s}〕"
        return _pad_center(s, CELL_W)

    def row_line(r):
        return f"{VERT}{fmt_cell(r,0)}{VERT}{fmt_cell(r,1)}{VERT}{fmt_cell(r,2)}{VERT}"

    # Rahmen
    bar = HOR * CELL_W
    top    = f"┌{bar}┬{bar}┬{bar}┐"
    mid    = f"├{bar}┼{bar}┼{bar}┤"
    bottom = f"└{bar}┴{bar}┴{bar}┘"

    # Pfeile für horizontale Gewinne
    arrows = [" ", " ", " "]
    if 0 in winline_idxs: arrows[0] = "▶"
    if 1 in winline_idxs: arrows[1] = "▶"
    if 2 in winline_idxs: arrows[2] = "▶"

    lines = [
        "```",
        top,
        f"{row_line(0)} {arrows[0]}",
        mid,
        f"{row_line(1)} {arrows[1]}",
        mid,
        f"{row_line(2)} {arrows[2]}",
        bottom,
        "```"
    ]

    # Legende
    extra = []
    if winline_idxs:
        names = [PAYLINES[i][1] for i in sorted(winline_idxs)]
        extra.append("Gewinnlinien: " + ", ".join(names))
    if freespins_left > 0:
        extra.append(f"Freespins verbleibend: **{freespins_left}**")

    txt = "\n".join(lines)
    if extra:
        txt += "\n" + "\n".join(extra)
    return txt

def build_spin_frames(final_board, spin_frames=5):
    frames = [spin_reels() for _ in range(max(1, spin_frames))]
    last = [row[:] for row in frames[-1]]
    for col in range(3):
        step = [[final_board[r][c] if c <= col else last[r][c] for c in range(3)] for r in range(3)]
        frames.append(step)
        last = step
    frames.append(final_board)
    return frames

def nudge_for_line(board):
    """Kleine Chance (NUDGE_LINE_CHANCE), eine 2/3-Linie zu 3/3 zu schieben."""
    if random.random() > NUDGE_LINE_CHANCE:
        return board

    for idx, (coords, _name) in enumerate(PAYLINES):
        syms = [board[r][c] for (r,c) in coords]
        if SCAT in syms:
            continue
        base = next((s for s in syms if s != WILD), WILD)
        match = sum(1 for s in syms if s == base or s == WILD)
        if match != 2:
            continue

        for k, (r,c) in enumerate(coords):
            if not (board[r][c] == base or board[r][c] == WILD):
                strip = REEL_STRIPS[c]
                top = board[0][c]
                i = strip.index(top)
                for step in (+1, -1):
                    i2 = (i + step) % len(strip)
                    new_col = [strip[(i2 + d) % len(strip)] for d in range(3)]
                    candidate = [row[:] for row in board]
                    for rr in range(3):
                        candidate[rr][c] = new_col[rr]
                    vals = [candidate[rr][cc] for (rr,cc) in coords]
                    ok = all(v == base or v == WILD for v in vals)
                    if ok:
                        return candidate
    return board

# ---------- ROBUSTE AUSZAHLUNGSLOGIK ----------
def line_payout(coords, board, bet):
    """
    - 🔔 blockiert Liniengewinne (Scatter zahlt separat)
    - ⭐ ist Joker für Basissymbole
    - 3×⭐ zahlt separat (PURE_WILDS_MULTI)
    - 1–2 ⭐ boosten die Linie (WILD_LINE_MULT)
    """
    syms = [board[r][c] for r,c in coords]
    if any(s == SCAT for s in syms):
        return 0, None

    wilds = sum(1 for s in syms if s == WILD)
    nonwild = [s for s in syms if s != WILD]

    if wilds == 3:
        return bet * PURE_WILDS_MULTI, WILD

    if not nonwild:
        return 0, None

    base = nonwild[0]
    if any(s != base for s in nonwild):
        # z.B. 🍒 ⭐ 🍋 -> kein Gewinn
        return 0, None

    base_multi = PAYTABLE.get(base, 0)
    if base_multi <= 0:
        return 0, None

    extra = WILD_LINE_MULT.get(wilds, 1)
    return bet * base_multi * extra, base

def evaluate(board, bet):
    total = 0
    winlines = []
    breakdown = []
    # Linien
    for idx, (coords, name) in enumerate(PAYLINES):
        payout, sym = line_payout(coords, board, bet)
        if payout > 0:
            total += payout
            winlines.append(idx)
            breakdown.append((name, sym, payout))
    # Scatter zahlt unabhängig von Linien
    scatters = sum(1 for r in range(3) for c in range(3) if board[r][c] == SCAT)
    if scatters >= 3:
        # Payout
        keys = sorted(SCATTER_PAYS.keys())
        tier = max(k for k in keys if scatters >= k)
        scat_pay = bet * SCATTER_PAYS[tier]
        total += scat_pay
        breakdown.append((f"{scatters}x Scatter", SCAT, scat_pay))
        # Freespins
        breakdown.append(("Freespins", SCAT, 0))
        free = FREESPINS_FOR_3_SCAT
    else:
        free = 0
    return total, winlines, free, breakdown


class SlotView(ui.View):
    def __init__(self, cog, interaction, bet):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = interaction.user.id
        self.bet = max(10, bet)
        self.freespins = 0
        self.last_win = 0
        self.msg = None
        self.lock = asyncio.Lock()

    async def ensure_owner(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Nur der ursprüngliche Spieler kann hier interagieren.", ephemeral=True)
            return False
        return True

    async def spin_once(self, interaction):
        # Balance check/Abzug nur wenn keine Freespins laufen
        user_data = await self.cog.get_user(self.user_id)
        wallet = user_data[0]
        if self.freespins == 0:
            if self.bet <= 0 or wallet < self.bet:
                await interaction.followup.send(
                    "<:Astra_x:1141303954555289600> Zu wenig Coins oder ungültiger Einsatz.",
                    ephemeral=True
                )
                return None, None, None, None
            await self.cog.update_balance(self.user_id, wallet_change=-self.bet)

        # --- Finale ermitteln + kleine Hilfen (Nudges) ---
        final = spin_reels()
        final = nudge_for_scatter(final)
        final = nudge_for_line(final)

        # --- Animationsframes: Spalten nacheinander stoppen ---
        frames = build_spin_frames(final, SPIN_FRAMES)

        # --- Animation abspielen (alle bis kurz vor final) ---
        for b in frames[:-1]:
            await asyncio.sleep(FRAME_DELAY)
            em = discord.Embed(
                colour=discord.Colour.blurple(),
                title="🎰 Slots",
                description=f"Einsatz: **{self.bet}** <:Coin:1359178077011181811>{' (Freespin)' if self.freespins > 0 else ''}"
            )
            em.add_field(name="Walzen", value=render_board(b, freespins_left=self.freespins), inline=False)
            await self.msg.edit(embed=em)

        # --- Ergebnis ---
        payout, winlines, freespins_got, breakdown = evaluate(final, self.bet)
        if freespins_got:
            self.freespins += freespins_got

        # Gewinne gutschreiben (Einsatz wurde ggf. oben abgezogen)
        if payout > 0:
            await self.cog.update_balance(self.user_id, wallet_change=payout)
        self.last_win = payout

        # Freespin runterzählen
        if self.freespins > 0:
            self.freespins -= 1

        # Anzeige
        board_text = render_board(final, winlines, self.freespins)
        res = (f"<:Astra_gw1:1141303852889550928> Gewinn: **+{payout}** <:Coin:1359178077011181811>"
               if payout > 0 else "Kein Gewinn.")

        details = "Keine Gewinnlinien."
        if breakdown:
            parts = []
            for name, sym, val in breakdown:
                parts.append(f"• {name} {sym or ''} {'→ **+%s**' % val if val > 0 else ''}")
            details = "\n".join(parts)

        end = discord.Embed(colour=discord.Colour.blue(), title="🎰 Slots – Ergebnis")
        end.add_field(name="Walzen", value=board_text, inline=False)
        end.add_field(name="Ergebnis", value=res, inline=False)
        end.add_field(name="Details", value=details, inline=False)
        await self.msg.edit(embed=end, view=self)

        return final, payout, winlines, breakdown

    # ---- Buttons ----

    @ui.button(label="▶️ Spin", style=discord.ButtonStyle.green)
    async def spin(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction): return
        async with self.lock:
            await interaction.response.defer()
            await self.spin_once(interaction)

    @ui.button(label="🔁 Auto x5", style=discord.ButtonStyle.primary)
    async def auto(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction): return
        async with self.lock:
            await interaction.response.defer()
            for _ in range(5):
                await self.spin_once(interaction)
                await asyncio.sleep(0.3)
                # Stop wenn User kein Geld mehr hat
                user_data = await self.cog.get_user(self.user_id)
                if user_data[0] < self.bet and self.freespins == 0:
                    break

    @ui.button(label="🎲 Gamble", style=discord.ButtonStyle.red)
    async def gamble(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction): return
        async with self.lock:
            await interaction.response.defer(ephemeral=True)
            if self.last_win <= 0:
                await interaction.followup.send("Kein Gewinn zum Verdoppeln.", ephemeral=True)
                return
            # 48% Gewinnchance – house edge 😈
            if random.random() < 0.48:
                await self.cog.update_balance(self.user_id, wallet_change=self.last_win)
                self.last_win *= 2
                await interaction.followup.send(f"🎉 Verdoppelt! Neuer Gewinn: **+{self.last_win}**", ephemeral=True)
            else:
                await self.cog.update_balance(self.user_id, wallet_change=-self.last_win)
                self.last_win = 0
                await interaction.followup.send("💥 Verloren – Gewinn futsch.", ephemeral=True)

    @ui.button(label="➖", style=discord.ButtonStyle.secondary)
    async def bet_minus(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction): return
        self.bet = max(10, int(self.bet * 0.5))
        await interaction.response.send_message(f"Einsatz: **{self.bet}**", ephemeral=True)

    @ui.button(label="➕", style=discord.ButtonStyle.secondary)
    async def bet_plus(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction): return
        self.bet = min(1_000_000, int(self.bet * 1.5) or self.bet+10)
        await interaction.response.send_message(f"Einsatz: **{self.bet}**", ephemeral=True)

JOBS = [{"name": "Küchenhilfe", "req": 0,
         "desc": "\nVerdiene zwischen 20 und 30 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **0** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [20, 30]},
        {"name": "Kassierer", "req": 5,
         "desc": "\nVerdiene zwischen 30 und 40 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **5** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [30, 40]},
        {"name": "Kebap-Mann", "req": 10,
         "desc": "\nVerdiene zwischen 40 und 50 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **10** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [40, 50]},
        {"name": "Elektroniker", "req": 15,
         "desc": "\nVerdiene zwischen 50 und 60 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **15** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [50, 60]},
        {"name": "Betreuer", "req": 20,
         "desc": "\nVerdiene zwischen 60 und 70 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **20** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [60, 70]},
        {"name": "Bäcker", "req": 25,
         "desc": "\nVerdiene zwischen 70 und 80 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **25** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [70, 80]},
        {"name": "Bauarbeiter", "req": 30,
         "desc": "\nVerdiene zwischen 80 und 90 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **30** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [80, 90]},
        {"name": "Gärtner", "req": 35,
         "desc": "\nVerdiene zwischen 90 und 100 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **35** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [90, 100]},
        {"name": "Lehrer", "req": 40,
         "desc": "\nVerdiene zwischen 100 und 110 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **40** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [100, 110]},
        {"name": "Koch", "req": 45,
         "desc": "\nVerdiene zwischen 110 und 120 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **45** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [110, 120]},
        {"name": "Sanitäter", "req": 50,
         "desc": "\nVerdiene zwischen 120 und 130 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **50** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [120, 130]},
        {"name": "TV-Moderator", "req": 60,
         "desc": "\nVerdiene zwischen 130 und 140 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **60** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [130, 140]},
        {"name": "Schauspieler", "req": 70,
         "desc": "\nVerdiene zwischen 140 und 150 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **70** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [140, 150]},
        {"name": "Ingenieur", "req": 80,
         "desc": "\nVerdiene zwischen 140 und 150 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **80** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [150, 160]},
        {"name": "Streamer", "req": 90,
         "desc": "\nVerdiene zwischen 160 und 170 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **90** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [160, 170]},
        {"name": "Athlet", "req": 100,
         "desc": "\nVerdiene zwischen 170 und 180 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **100** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [170, 180]},
        {"name": "Polizist", "req": 120,
         "desc": "\nVerdiene zwischen 180 und 190 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **120** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [180, 190]},
        {"name": "Programmierer", "req": 140,
         "desc": "\nVerdiene zwischen 190 und 200 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **140** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [190, 200]},
        {"name": "Chirurg", "req": 160,
         "desc": "\nVerdiene zwischen 170 und 180 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **160** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [220, 240]},
        {"name": "Chefarzt", "req": 180,
         "desc": "\nVerdiene zwischen 240 und 250 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **180** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [240, 250]},
        {"name": "Rechtsanwalt", "req": 200,
         "desc": "\nVerdiene zwischen 250 und 260 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **200** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [250, 260]},
        {"name": "Unternehmensleiter", "req": 250,
         "desc": "\nVerdiene zwischen 260 und 270 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **250** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [260, 270]},
        {"name": "Richter", "req": 300,
         "desc": "\nVerdiene zwischen 270 und 280 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **300** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [270, 300]},
        {"name": "Astronaut", "req": 350,
         "desc": "\nVerdiene zwischen 300 und 310 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **400** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [300, 330]},
        {"name": "Pilot", "req": 400,
         "desc": "\nVerdiene zwischen 300 und 310 <:Coin:1359178077011181811>  pro Stunde.\nDu musst mindestens **400** Stunden gearbeitet haben, um diesen Job freizuschalten.",
         "amt": [330, 400]}]

JOBS += [
    {"name": "Wissenschaftler", "req": 450,
     "desc": "\nVerdiene zwischen 410 und 430 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **450** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [410, 430]},
    {"name": "Professor", "req": 500,
     "desc": "\nVerdiene zwischen 440 und 460 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **500** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [440, 460]},
    {"name": "Pharmaforscher", "req": 550,
     "desc": "\nVerdiene zwischen 470 und 490 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **550** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [470, 490]},
    {"name": "Bankmanager", "req": 600,
     "desc": "\nVerdiene zwischen 500 und 530 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **600** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [500, 530]},
    {"name": "Politiker", "req": 650,
     "desc": "\nVerdiene zwischen 530 und 560 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **650** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [530, 560]},
    {"name": "Unternehmensberater", "req": 700,
     "desc": "\nVerdiene zwischen 560 und 590 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **700** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [560, 590]},
    {"name": "Chefredakteur", "req": 750,
     "desc": "\nVerdiene zwischen 590 und 620 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **750** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [590, 620]},
    {"name": "Finanzanalyst", "req": 800,
     "desc": "\nVerdiene zwischen 620 und 650 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **800** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [620, 650]},
    {"name": "Medienproduzent", "req": 850,
     "desc": "\nVerdiene zwischen 650 und 680 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **850** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [650, 680]},
    {"name": "Entwicklungsleiter", "req": 900,
     "desc": "\nVerdiene zwischen 680 und 710 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **900** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [680, 710]},
    {"name": "Regierungsberater", "req": 1000,
     "desc": "\nVerdiene zwischen 710 und 750 <:Coin:1359178077011181811> pro Stunde.\nDu musst mindestens **1000** Stunden gearbeitet haben, um diesen Job freizuschalten.",
     "amt": [710, 750]}
]

# ---------------------- Blackjack ----------------------

# Kartenwert berechnung
CARD_VALUES = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6,
    '7': 7, '8': 8, '9': 9, '10': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11
}

def calculate_hand_value(hand):
    value = 0
    aces = 0
    for card in hand:
        rank = card[:-1] if card[:-1] != '' else card[0]
        card_value = CARD_VALUES.get(rank, 0)
        value += card_value
        if rank == 'A':
            aces += 1
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value

class BlackjackView(discord.ui.View):
    def __init__(self, bot, interaction, bet, economy):
        super().__init__(timeout=180)
        self.bot = bot
        self.interaction = interaction
        self.bet = bet
        self.economy = economy
        self.user_id = interaction.user.id

        self.player_hand = []
        self.dealer_hand = []
        self.deck = self.create_deck()
        self.message = None
        self.stand_called = False
        self.result_shown = False

        self.deal_initial_cards()

    def create_deck(self):
        suits = ['♠', '♥', '♦', '♣']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
        deck = [f'{rank}{suit}' for suit in suits for rank in ranks]
        random.shuffle(deck)
        return deck

    def deal_initial_cards(self):
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    async def update_message(self):
        player_value = calculate_hand_value(self.player_hand)
        dealer_value = calculate_hand_value(self.dealer_hand)

        player_cards = " ".join(self.player_hand)
        dealer_cards_display = self.dealer_hand[0] + " ❓" if not self.stand_called else " ".join(self.dealer_hand)
        dealer_value_display = "?" if not self.stand_called else str(dealer_value)

        embed = discord.Embed(title="Blackjack", color=discord.Color.blue())

        embed.add_field(name="<:Astra_user:1141303940365959241> Deine Karten:", value=f"```{player_cards}```Wert: **{player_value}**", inline=False)
        embed.add_field(name="<:Astra_dev:1141303833407017001> Karten des Dealers:", value=f"```{dealer_cards_display}```Wert: **{dealer_value_display}**", inline=False)

        game_over = False
        result_text = ""

        if player_value > 21:
            game_over = True
            result_text = "<:Astra_x:1141303954555289600> Du hast den Wert von 21 überschritten. Du hast verloren."
        elif dealer_value > 21:
            game_over = True
            result_text = "<:Astra_gw1:1141303852889550928> Der Dealer hat überzogen. Du hast gewonnen!"
        elif self.stand_called and dealer_value >= 17:
            game_over = True
            if player_value > dealer_value:
                result_text = "<:Astra_gw1:1141303852889550928> Du hast gewonnen!"
            elif player_value < dealer_value:
                result_text = "<:Astra_x:1141303954555289600> Der Dealer hat gewonnen."
            else:
                result_text = "<:Astra_x:1141303954555289600> Unentschieden."

        if game_over:
            embed.add_field(name="<:Astra_wichtig:1141303951862534224> Ergebnis", value=result_text, inline=False)
            for child in self.children:
                child.disabled = True
            if not self.result_shown:
                self.result_shown = True
                if player_value <= 21 and (player_value > dealer_value or dealer_value > 21):
                    await self.economy.update_balance(self.user_id, wallet_change=self.bet * 2)
                elif player_value == dealer_value:
                    await self.economy.update_balance(self.user_id, wallet_change=self.bet)

        if self.message is None:
            self.message = await self.interaction.original_response()
            await self.message.edit(embed=embed, view=self)
        else:
            await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if calculate_hand_value(self.player_hand) >= 21:
            return

        self.player_hand.append(self.deck.pop())
        await self.update_message()

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.stand_called = True

        await self.animate_dealer_cards()
        await self.update_message()

    async def animate_dealer_cards(self):
        await asyncio.sleep(1)
        while calculate_hand_value(self.dealer_hand) < 17:
            self.dealer_hand.append(self.deck.pop())
            await self.update_message()
            await asyncio.sleep(1.2)

# ---------------------- Jobliste & Economy ----------------------

class JobListView(discord.ui.View):
    def __init__(self, jobs, user_hours):
        super().__init__()
        self.jobs = jobs
        self.user_hours = user_hours
        self.page = 0
        self.items_per_page = 5

    def generate_job_embed(self):
        embed = discord.Embed(
            title="<:Astra_file1:1141303837181886494> Jobliste",
            color=discord.Color.blue()
        )
        start_idx = self.page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        jobs_to_display = self.jobs[start_idx:end_idx]

        for job in jobs_to_display:
            locked = self.user_hours < job["req"]
            status = "<:Astra_locked:1141824745243942912> Gesperrt" if locked else "<:Astra_unlock:1141824750851731486> Verfügbar"
            embed.add_field(
                name=f"{job['name']} ({status})",
                value=f"{job['desc']}\nBenötigte Stunden: **{job['req']}**",
                inline=False
            )

        total_pages = (len(self.jobs) + self.items_per_page - 1) // self.items_per_page
        embed.set_footer(text=f"Seite {self.page + 1} von {total_pages}")
        return embed

    @discord.ui.button(label="Zurück", style=discord.ButtonStyle.primary, emoji="<:Astra_arrow_backwards:1392540551546671348>", row=0)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
            embed = self.generate_job_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Weiter", style=discord.ButtonStyle.primary, emoji="<:Astra_arrow:1141303823600717885>", row=0)
    async def next_page_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (self.page + 1) * self.items_per_page < len(self.jobs):
            self.page += 1
            embed = self.generate_job_embed()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="🏠", style=discord.ButtonStyle.secondary, row=0)
    async def go_home(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page != 0:
            self.page = 0
            embed = self.generate_job_embed()
            await interaction.response.edit_message(embed=embed, view=self)

@app_commands.guild_only()
class EconomyClass(app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            name="eco",
            description="Alles rund um Economy."
        )

    async def get_user(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT wallet, bank, job, hours_worked, last_work, last_beg, last_rob FROM economy_users WHERE user_id = %s",
                    (user_id,)
                )
                data = await cur.fetchone()

                if not data:
                    await cur.execute(
                        "INSERT INTO economy_users (user_id, wallet, bank, job, hours_worked, last_work, last_beg, last_rob) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, 0, 0, None, 0, None, None, None)
                    )
                    return 0, 0, None, 0, None, None, None

                return data

    async def update_balance(self, user_id: int, wallet_change=0, bank_change=0):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, bank = bank + %s WHERE user_id = %s",
                    (wallet_change, bank_change, user_id)
                )

    async def get_balance(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT wallet, bank FROM economy_users WHERE user_id = %s", (user_id,))
                return await cur.fetchone()

    @app_commands.command(name="balance", description="Zeigt deinen aktuellen Kontostand an.")
    @app_commands.guild_only()
    async def balance(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = await self.get_user(user_id)
        wallet, bank = user_data[0], user_data[1]
        job_name = user_data[2]
        hours = user_data[3]

        embed = discord.Embed(title=f"{interaction.user}'s Kontostand", description="> Erhalte Hier Infos über deinen Kontostand und über deinen aktuellen Beruf.", color=discord.Color.blue())
        embed.add_field(name="Barvermögen", value=f"{wallet} <:Coin:1359178077011181811>", inline=True)
        embed.add_field(name="Bank", value=f"{bank} <:Coin:1359178077011181811>", inline=True)
        embed.add_field(name="Beruf", value=f"{job_name}, <:Astra_time:1141303932061233202> {hours} Stunden", inline=True)
        embed.set_thumbnail(url=interaction.user.avatar)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deposit", description="Zahle Geld auf dein Bankkonto ein.")
    @app_commands.guild_only()
    @app_commands.describe(betrag="Der Betrag, den du einzahlen möchtest.")
    async def deposit(self, interaction: discord.Interaction, betrag: int):
        if betrag <= 0:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein.", ephemeral=True)
            return

        user_data = await self.get_user(interaction.user.id)
        if user_data[0] < betrag:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Du hast nicht genug Geld in deinem Wallet.", ephemeral=True)
            return

        await self.update_balance(interaction.user.id, -betrag, betrag)
        await interaction.response.send_message(f"Du hast {betrag} <:Coin:1359178077011181811> auf dein Bankkonto eingezahlt.", ephemeral=True)

    @app_commands.command(name="withdraw", description="Hebe Geld von deinem Bankkonto ab.")
    @app_commands.guild_only()
    @app_commands.describe(betrag="Der Betrag, den du abheben möchtest.")
    async def withdraw(self, interaction: discord.Interaction, betrag: int):
        if betrag <= 0:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein.", ephemeral=True)
            return

        user_data = await self.get_user(interaction.user.id)
        if user_data[1] < betrag:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Du hast nicht genug Geld auf deinem Bankkonto.", ephemeral=True)
            return

        await self.update_balance(interaction.user.id, betrag, -betrag)
        await interaction.response.send_message(f"Du hast {betrag} <:Coin:1359178077011181811> von deinem Bankkonto abgehoben.")

    @app_commands.command(name="beg", description="Bitte um ein kleines Trinkgeld.")
    @app_commands.guild_only()
    async def beg(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        user_data = await self.get_user(user_id)

        last_beg = user_data[5]  # neue Spalte
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)

        # MySQL DATETIME ist oft naive → zu UTC machen
        if last_beg and last_beg.tzinfo is None:
            last_beg = last_beg.replace(tzinfo=timezone.utc)

        if last_beg:
            cooldown_end = last_beg + timedelta(hours=3)

            if now < cooldown_end:
                remaining = cooldown_end - now
                total_seconds = int(remaining.total_seconds())

                hours_left, remainder = divmod(total_seconds, 3600)
                minutes_left, seconds_left = divmod(remainder, 60)

                parts = []
                if hours_left:
                    parts.append(f"{hours_left}h")
                if minutes_left:
                    parts.append(f"{minutes_left}m")
                if seconds_left or not parts:
                    parts.append(f"{seconds_left}s")

                time_string = " ".join(parts)

                await interaction.response.send_message(
                    f"<:Astra_time:1141303932061233202> Du kannst in **{time_string}** wieder betteln.",
                    ephemeral=True
                )
                return

        amount = random.randint(5, 25)

        await self.update_balance(user_id, wallet_change=amount)

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET last_beg = %s WHERE user_id = %s",
                    (now, user_id)
                )

        await interaction.response.send_message(
            f"<:Astra_accept:1141303821176422460> Du hast {amount} <:Coin:1359178077011181811> von einem freundlichen Fremden erhalten!"
        )

    @app_commands.command(name="slot", description="Spiele ein realistisches 3×3 Slot-Spiel.")
    @app_commands.guild_only()
    @app_commands.describe(einsatz="Wie viele Coins willst du setzen?")
    async def slot(self, interaction: discord.Interaction, einsatz: int):
        user_id = interaction.user.id
        user_data = await self.get_user(user_id)
        wallet = user_data[0]

        if einsatz <= 0 or einsatz > wallet:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Ungültiger Einsatz.",
                                                    ephemeral=True)
            return

        view = SlotView(self, interaction, einsatz)

        em = discord.Embed(
            colour=discord.Colour.blurple(),
            title="🎰 Slots",
            description=f"Einsatz: **{einsatz}** <:Coin:1359178077011181811>\nViel Glück, {interaction.user.mention}!"
        )
        em.add_field(name="Walzen", value=render_board(spin_reels()), inline=False)
        em.set_author(name=str(interaction.user),
                      icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None)

        await interaction.response.send_message(embed=em, view=view)
        view.msg = await interaction.original_response()

    @app_commands.command(name="rps", description="Spiele Schere, Stein, Papier gegen den Bot.")
    @app_commands.guild_only()
    @app_commands.describe(choice="Wähle 'Schere', 'Stein' oder 'Papier'.")
    async def rps(self, interaction: discord.Interaction, choice: Literal['Stein', 'Schere', 'Papier']):
        choice = choice.lower()
        if choice not in ["schere", "stein", "papier"]:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Bitte wähle entweder 'Schere', 'Stein' oder 'Papier'.",
                                                    ephemeral=True)
            return

        bot_choice = random.choice(["schere", "stein", "papier"])
        result = ""

        if choice == bot_choice:
            result = "Unentschieden!"
        elif (choice == "schere" and bot_choice == "papier") or \
                (choice == "stein" and bot_choice == "schere") or \
                (choice == "papier" and bot_choice == "stein"):
            result = "<:Astra_gw1:1141303852889550928> Du hast gewonnen!"
        else:
            result = "<:Astra_x:1141303954555289600> Du hast verloren!"

        embed = discord.Embed(title="Schere, Stein, Papier", color=discord.Color.blue())
        embed.add_field(name="Deine Wahl", value=f"**{choice.capitalize()}**", inline=False)
        embed.add_field(name="Bot's Wahl", value=f"**{bot_choice.capitalize()}**", inline=False)
        embed.add_field(name="Ergebnis", value=result, inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="coinflip", description="Münzwurf: Wähle Kopf oder Zahl und setze.")
    @app_commands.guild_only()
    @app_commands.describe(wahl="Deine Wahl: 'Kopf' oder 'Zahl'", betrag="Der Betrag, den du setzen möchtest.")
    async def coinflip(self, interaction: discord.Interaction, wahl: str, betrag: int):
        guess = wahl.lower()
        if guess not in ["kopf", "zahl"]:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Bitte wähle entweder 'Kopf' oder 'Zahl'.", ephemeral=True)
            return

        if betrag <= 0:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein, der größer als 0 ist.",
                                                    ephemeral=True)
            return

        user_data = await self.get_user(interaction.user.id)
        wallet = user_data[0]

        if wallet < betrag:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Du hast nicht genug Münzen. Dein aktueller Kontostand ist {wallet} <:Coin:1359178077011181811>.", ephemeral=True)
            return

        result = random.choice(["Kopf", "Zahl"])

        embed = discord.Embed(title="Münzwurf", color=discord.Color.blue())
        embed.add_field(name="Deine Wahl", value=f"**{guess.capitalize()}**", inline=False)
        embed.add_field(name="Ergebnis", value=f"**{result}**", inline=False)

        if guess == result.lower():
            gewonnen = betrag * 2
            await self.update_balance(interaction.user.id, gewonnen, 0)
            embed.add_field(name="<:Astra_gw1:1141303852889550928> Glückwunsch!", value=f"Du hast gewonnen! Du erhältst {gewonnen} <:Coin:1359178077011181811>.", inline=False)
        else:
            await self.update_balance(interaction.user.id, -betrag, 0)
            embed.add_field(name="<:Astra_x:1141303954555289600>  Leider verloren", value=f"Du hast verloren und {betrag} <:Coin:1359178077011181811> verloren.", inline=False)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="rob", description="Versuche, einen anderen Nutzer auszurauben!")
    @app_commands.guild_only()
    @app_commands.describe(ziel="Wen willst du ausrauben?")
    async def rob(self, interaction: discord.Interaction, ziel: discord.User):
        user_id = interaction.user.id
        target_id = ziel.id

        if user_id == target_id:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du kannst dich nicht selbst ausrauben.",
                ephemeral=True
            )
            return

        user_data = await self.get_user(user_id)
        target_data = await self.get_user(target_id)

        last_rob = user_data[6]  # neue Spalte
        now = datetime.now(timezone.utc)

        # MySQL DATETIME ist oft naive → zu UTC machen
        if last_rob and last_rob.tzinfo is None:
            last_rob = last_rob.replace(tzinfo=timezone.utc)

        if last_rob and now < last_rob + timedelta(hours=8):
            remaining = (last_rob + timedelta(hours=8)) - now
            total_seconds = int(remaining.total_seconds())

            hours_left, remainder = divmod(total_seconds, 3600)
            minutes_left, seconds_left = divmod(remainder, 60)

            parts = []
            if hours_left:
                parts.append(f"{hours_left}h")
            if minutes_left:
                parts.append(f"{minutes_left}m")
            if seconds_left or not parts:
                parts.append(f"{seconds_left}s")

            time_string = " ".join(parts)

            await interaction.response.send_message(
                f"<:Astra_time:1141303932061233202> Du kannst in **{time_string}** wieder rauben.",
                ephemeral=True
            )
            return

        if target_data[0] < 50:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Ziel hat zu wenig Geld zum Ausrauben.",
                ephemeral=True
            )
            return

        erfolg = random.random() < 0.5

        if erfolg:
            betrag = random.randint(20, min(200, target_data[0]))

            await self.update_balance(user_id, wallet_change=betrag)
            await self.update_balance(target_id, wallet_change=-betrag)

            msg = f"<:Astra_accept:1141303821176422460> Du hast erfolgreich {betrag} <:Coin:1359178077011181811> von {ziel.mention} gestohlen!"

        else:
            strafe = random.randint(10, 30)

            await self.update_balance(user_id, wallet_change=-strafe)

            msg = f"<:Astra_x:1141303954555289600> Du wurdest erwischt! Du zahlst eine Strafe von {strafe} <:Coin:1359178077011181811>."

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET last_rob = %s WHERE user_id = %s",
                    (now, user_id)
                )

        await interaction.response.send_message(msg)

    @app_commands.command(name="leaderboard", description="Zeige die reichsten Spieler.")
    @app_commands.guild_only()
    @app_commands.describe(scope="Wähle, ob die globale oder serverbezogene Rangliste angezeigt wird.")
    async def leaderboard(
            self,
            interaction: discord.Interaction,
            scope: Literal["global", "server"]
    ):
        try:
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:

                    if scope == "global":
                        await cur.execute("""
                                          SELECT user_id, wallet + bank AS gesamt
                                          FROM economy_users
                                          ORDER BY gesamt DESC
                                          LIMIT 10
                                          """)
                        top_users = await cur.fetchall()

                    else:  # server leaderboard

                        member_ids = [member.id for member in interaction.guild.members if not member.bot]

                        if not member_ids:
                            await interaction.response.send_message("Keine Benutzer gefunden.", ephemeral=True)
                            return

                        placeholders = ",".join(["%s"] * len(member_ids))

                        query = f"""
                            SELECT user_id, wallet + bank AS gesamt
                            FROM economy_users
                            WHERE user_id IN ({placeholders})
                            ORDER BY gesamt DESC
                            LIMIT 10
                        """

                        await cur.execute(query, tuple(member_ids))
                        top_users = await cur.fetchall()

            if not top_users:
                await interaction.response.send_message(
                    "Es wurden keine Benutzer gefunden oder die Rangliste ist leer."
                )
                return

            embed = discord.Embed(
                title="<:Astra_users:1141303946602872872> Rangliste (Global)"
                if scope == "global"
                else f"<:Astra_users:1141303946602872872> Rangliste ({interaction.guild.name})",
                color=discord.Color.blue()
            )

            for i, (user_id, gesamt) in enumerate(top_users, start=1):
                user = self.bot.get_user(user_id)

                if user is None:
                    try:
                        user = await self.bot.fetch_user(user_id)
                    except:
                        user = None

                name = user.name if user else f"Unbekannt ({user_id})"

                embed.add_field(
                    name=f"{i}. {name}",
                    value=f"{gesamt} <:Coin:1359178077011181811>",
                    inline=False
                )

            await interaction.response.send_message(embed=embed)

        except Exception as e:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Fehler beim Abrufen der Rangliste: {e}",
                ephemeral=True
            )
            print(f"Leaderboard Error: {e}")

    @app_commands.command(name="blackjack", description="Spiele eine Runde Blackjack.")
    @app_commands.guild_only()
    @app_commands.describe(einsatz="Der Betrag, den du setzen möchtest.")
    async def blackjack(self, interaction: discord.Interaction, einsatz: int):
        user_data = await self.get_user(interaction.user.id)
        wallet = user_data[0]

        if einsatz <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte gib einen gültigen Einsatz an.", ephemeral=True)
            return

        if wallet < einsatz:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> hast nicht genug Münzen.",
                                                    ephemeral=True)
            return

        await self.update_balance(interaction.user.id, wallet_change=-einsatz)

        view = BlackjackView(self.bot, interaction, einsatz, self)

        embed = discord.Embed(
            title="Blackjack wird gestartet!",
            description="Ziehe Karten mit `Hit` oder beende mit `Stand`. Ziel: So nah wie möglich an 21!",
            color=discord.Color.blue()
        )
        embed.add_field(name="Einsatz", value=f"{einsatz} <:Coin:1359178077011181811>", inline=False)

        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        await view.update_message()

@app_commands.guild_only()
class Job(app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(
            name="job",
            description="Alles rund um deinen Job"
        )

    async def get_user(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT wallet, bank, job, hours_worked, last_work, last_beg, last_rob FROM economy_users WHERE user_id = %s",
                    (user_id,)
                )
                data = await cur.fetchone()

                if not data:
                    await cur.execute(
                        "INSERT INTO economy_users (user_id, wallet, bank, job, hours_worked, last_work, last_beg, last_rob) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, 0, 0, None, 0, None, None, None)
                    )
                    return 0, 0, None, 0, None, None, None

                return data

    @app_commands.command(name="work", description="Arbeite in deinem aktuellen Job.")
    @app_commands.guild_only()
    async def work(self, interaction: discord.Interaction):

        user_id = interaction.user.id
        user_data = await self.get_user(user_id)

        wallet = user_data[0]
        bank = user_data[1]
        job_name= user_data[2]
        hours = user_data[3]
        last_work = user_data[4]
        logging.info(f"RAW last_work from DB: {last_work}")

        if not job_name:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast keinen Job. Nutze `/job apply`, um einen Job zu wählen.",
                ephemeral=True
            )
            return

        now = datetime.now(timezone.utc)

        # MySQL DATETIME ist oft naive → zu UTC machen
        if last_work and last_work.tzinfo is None:
            last_work = last_work.replace(tzinfo=timezone.utc)

        if last_work and now < last_work + timedelta(hours=8):
            remaining = (last_work + timedelta(hours=8)) - now
            total_seconds = int(remaining.total_seconds())

            hours_left, remainder = divmod(total_seconds, 3600)
            minutes_left, seconds_left = divmod(remainder, 60)

            logging.info(f"NOW: {now}")
            logging.info(f"LAST_WORK: {last_work}")
            logging.info(f"DIFF: {now - last_work if last_work else None}")

            parts = []
            if hours_left:
                parts.append(f"{hours_left}h")
            if minutes_left:
                parts.append(f"{minutes_left}m")
            if seconds_left or not parts:
                parts.append(f"{seconds_left}s")

            time_string = " ".join(parts)

            await interaction.response.send_message(
                f"<:Astra_time:1141303932061233202> Du musst noch **{time_string}** warten, bevor du wieder arbeiten kannst.",
                ephemeral=True
            )
            return

        job = next((j for j in JOBS if j["name"] == job_name), None)

        if not job:
            await interaction.response.send_message(
                "Fehler: Dein Job wurde nicht gefunden.",
                ephemeral=True
            )
            return

        coins_per_hour = random.randint(*job["amt"])
        earned = coins_per_hour

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, hours_worked = hours_worked + 1, last_work = %s WHERE user_id = %s",
                    (earned, now, user_id)
                )

        await interaction.response.send_message(
            f"<:Astra_time:1141303932061233202> Du hast 1 Stunde als **{job_name}** gearbeitet und {earned} <:Coin:1359178077011181811> verdient!"
        )

    @app_commands.command(name="list", description="Zeigt die Jobliste.")
    @app_commands.guild_only()
    async def job_list(self, interaction: discord.Interaction):
        user_data = await self.get_user(interaction.user.id)
        user_hours = user_data[3]

        view = JobListView(JOBS, user_hours)
        embed = view.generate_job_embed()
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="apply", description="Bewirb dich auf einen verfügbaren Job.")
    @app_commands.guild_only()
    @app_commands.describe(name="Name des Jobs, den du annehmen möchtest.")
    async def job_apply(self, interaction: discord.Interaction, name: str):
        user_data = await self.get_user(interaction.user.id)
        user_hours = user_data[3]
        job = next((j for j in JOBS if j["name"].lower() == name.lower()), None)

        if not job:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Dieser Job existiert nicht.",
                                                    ephemeral=True)
            return

        if user_hours < job["req"]:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast noch nicht genug Stunden gearbeitet, um diesen Job zu bekommen.",
                ephemeral=True)
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE economy_users SET job = %s WHERE user_id = %s",
                                  (job["name"], interaction.user.id))

        await interaction.response.send_message(
            f"<:Astra_accept:1141303821176422460> Du arbeitest jetzt als **{job['name']}**!")

    @app_commands.command(name="quit", description="Kündige deinen aktuellen Job.")
    @app_commands.guild_only()
    async def job_quit(self, interaction: discord.Interaction):
        user_data = await self.get_user(interaction.user.id)
        if not user_data[2]:
            await interaction.response.send_message("<:Astra_x:1141303954555289600> Du hast momentan keinen Job.",
                                                    ephemeral=True)
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE economy_users SET job = NULL WHERE user_id = %s", (interaction.user.id,))

        await interaction.response.send_message(
            "<:Astra_accept:1141303821176422460> Du hast deinen Job erfolgreich gekündigt.")


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pool = None

    async def get_user(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT wallet, bank, job, hours_worked, last_work, last_beg, last_rob FROM economy_users WHERE user_id = %s",
                    (user_id,)
                )
                data = await cur.fetchone()

                if not data:
                    await cur.execute(
                        "INSERT INTO economy_users (user_id, wallet, bank, job, hours_worked, last_work, last_beg, last_rob) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                        (user_id, 0, 0, None, 0, None, None, None)
                    )
                    return 0, 0, None, 0, None, None, None

                return data

    async def update_balance(self, user_id: int, wallet_change=0, bank_change=0):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET wallet = wallet + %s, bank = bank + %s WHERE user_id = %s",
                    (wallet_change, bank_change, user_id)
                )

    async def get_balance(self, user_id: int):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT wallet, bank FROM economy_users WHERE user_id = %s", (user_id,))
                return await cur.fetchone()

    @commands.command(name="unlockjobs")
    @commands.is_owner()
    async def unlock_jobs(self, ctx, user: discord.User, max_hours: int):
        """
        Schaltet einem User Jobs bis zu einer bestimmten Stundenanforderung frei.
        Beispiel: astra!unlockjobs @User 200
        """
        if max_hours < 0:
            await ctx.send("<:Astra_x:1141303954555289600> Ungültiger Wert.")
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # User anlegen falls nicht existiert
                await cur.execute("SELECT * FROM economy_users WHERE user_id=%s", (user.id,))
                row = await cur.fetchone()
                if not row:
                    await cur.execute("INSERT INTO economy_users (user_id, hours_worked) VALUES (%s, %s)",
                                      (user.id, max_hours))
                else:
                    # Stunden hochsetzen
                    await cur.execute("UPDATE economy_users SET hours_worked = %s WHERE user_id=%s",
                                      (max_hours, user.id))

        await ctx.send(
            f"<:Astra_accept:1141303821176422460> {user.mention} wurden alle Jobs bis **{max_hours} Stunden** freigeschaltet!")

    @commands.command(name="addcoins",
                      description="Füge einem Nutzer <:Coin:1359178077011181811> hinzu (Nur für Botbesitzer).")
    @commands.is_owner()
    async def addcoins(self, ctx, user: discord.User, betrag: int, balance_type: str = "wallet"):
        """Fügt einem Nutzer Coins hinzu. Kann Bar- oder Bank-Balance verwenden."""
        if betrag <= 0:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Betrag.")
            return

        # Überprüfen, ob balance_type korrekt ist (wallet oder bank)
        if balance_type not in ["wallet", "bank"]:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Balance-Typ. Verwende `wallet` oder `bank`.")
            return

        # User Balance abrufen
        user_data = await self.get_balance(user.id)
        current_balance = user_data[0] if balance_type == "wallet" else user_data[1]

        # Balance aktualisieren
        await self.update_balance(user.id, wallet_change=betrag if balance_type == "wallet" else 0,
                                  bank_change=betrag if balance_type == "bank" else 0)
        await ctx.channel.send(
            f"<:Astra_accept:1141303821176422460> {betrag} <:Coin:1359178077011181811> wurden {user.mention} zu {balance_type} hinzugefügt.")

    @commands.command(name="removecoins",
                      description="Entferne einem Nutzer <:Coin:1359178077011181811> (Nur für Botbesitzer).")
    @commands.is_owner()
    async def removecoins(self, ctx, user: discord.User, betrag: int, balance_type: str = "wallet"):
        """Entfernt einem Nutzer Coins. Kann Bar- oder Bank-Balance verwenden."""
        if betrag <= 0:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Betrag.")
            return

        # Überprüfen, ob balance_type korrekt ist (wallet oder bank)
        if balance_type not in ["wallet", "bank"]:
            await ctx.channel.send("<:Astra_x:1141303954555289600> Ungültiger Balance-Typ. Verwende `wallet` oder `bank`.")
            return

        # User Balance abrufen
        user_data = await self.get_balance(user.id)
        current_balance = user_data[0] if balance_type == "wallet" else user_data[1]

        # Überprüfen, ob der Betrag entfernt werden kann
        if current_balance < betrag:
            await ctx.channel.send(f"<:Astra_x:1141303954555289600> {user.mention} hat nicht genug {balance_type} um {betrag} zu entfernen.")
            return

        # Balance aktualisieren
        await self.update_balance(user.id, wallet_change=-betrag if balance_type == "wallet" else 0,
                                  bank_change=-betrag if balance_type == "bank" else 0)
        await ctx.channel.send(
            f"<:Astra_accept:1141303821176422460> {betrag} <:Coin:1359178077011181811> wurden {user.mention} von {balance_type} entfernt.")


async def setup(bot):
    await bot.add_cog(Economy(bot))
    bot.tree.add_command(EconomyClass(bot))
    bot.tree.add_command(Job(bot))
