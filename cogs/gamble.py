import asyncio
import random
from datetime import datetime, timedelta, timezone
from typing import Literal

import discord
from discord import app_commands, ui

from cogs.economy import EconomyMixin

MAX_BET = 10000
MAX_WIN_MULTIPLIER = 50

WILD = "⭐"
SCAT = "🔔"

REEL_STRIPS = [
    [
        "🍒",
        "🍒",
        "🍋",
        "🍊",
        "🍇",
        "🍓",
        "🍒",
        "🍋",
        "🍊",
        "🍉",
        "🍒",
        "🍋",
        "🍇",
        "🍓",
        "🍊",
        "🍍",
        SCAT,
        "🍒",
        WILD,
        "🍋",
    ],
    [
        "🍒",
        "🍋",
        "🍊",
        "🍇",
        "🍓",
        "🍉",
        "🍒",
        "🍋",
        "🍊",
        "🍇",
        "🍓",
        "🍒",
        "🍋",
        "🍊",
        "🍍",
        "🍉",
        WILD,
        SCAT,
        "🍇",
        "🍋",
    ],
    [
        "🍒",
        "🍋",
        "🍊",
        "🍇",
        "🍓",
        "🍉",
        "🍒",
        "🍋",
        "🍊",
        "🍇",
        "🍓",
        "🍒",
        "🍋",
        "🍊",
        "🍍",
        "🍉",
        SCAT,
        "🍇",
        WILD,
        "🍋",
    ],
]

PAYLINES = [
    ([(0, 0), (0, 1), (0, 2)], "Obere Reihe"),
    ([(1, 0), (1, 1), (1, 2)], "Mittlere Reihe"),
    ([(2, 0), (2, 1), (2, 2)], "Untere Reihe"),
    ([(0, 0), (1, 0), (2, 0)], "Linke Spalte"),
    ([(0, 1), (1, 1), (2, 1)], "Mittlere Spalte"),
    ([(0, 2), (1, 2), (2, 2)], "Rechte Spalte"),
    ([(0, 0), (1, 1), (2, 2)], "↘ Diagonale"),
    ([(2, 0), (1, 1), (0, 2)], "↗ Diagonale"),
    ([(1, 0), (1, 1), (1, 2)], "Mittellinie (Bonus)"),
]

PAYTABLE = {"🍒": 2, "🍋": 3, "🍊": 4, "🍇": 7, "🍓": 10, "🍉": 15, "🍍": 25, WILD: 0}
WILD_LINE_MULT = {0: 1, 1: 1.5, 2: 2.5}
PURE_WILDS_MULTI = 20
SCATTER_PAYS = {3: 2, 4: 4, 5: 8}
FREESPINS_FOR_3_SCAT = 6
NUDGE_SCATTER_CHANCE = 0.20
NUDGE_LINE_CHANCE = 0.10
SPIN_FRAMES = 5
FRAME_DELAY = 0.35

try:
    from wcwidth import wcswidth
except ImportError:
    import unicodedata

    def wcswidth(text: str) -> int:
        width = 0
        for char in text:
            if unicodedata.combining(char):
                continue
            width += (
                2
                if unicodedata.east_asian_width(char) in ("W", "F")
                or ord(char) >= 0x1F300
                else 1
            )
        return width


CELL_W = 7
VERT = "│"
HOR = "─"

CARD_VALUES = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "10": 10,
    "J": 10,
    "Q": 10,
    "K": 10,
    "A": 11,
}


def spin_reels():
    cols = []
    for strip in REEL_STRIPS:
        start = random.randint(0, len(strip) - 1)
        cols.append([strip[(start + i) % len(strip)] for i in range(3)])
    return [list(row) for row in zip(*cols)]


def nudge_for_scatter(board):
    scatters = [
        (row, col) for row in range(3) for col in range(3) if board[row][col] == SCAT
    ]
    if len(scatters) != 2 or random.random() > NUDGE_SCATTER_CHANCE:
        return board

    for col in range(3):
        strip = REEL_STRIPS[col]
        idx = (strip.index(board[0][col]) + 1) % len(strip)
        new_col = [strip[(idx + offset) % len(strip)] for offset in range(3)]
        candidate = [row[:] for row in board]
        for row in range(3):
            candidate[row][col] = new_col[row]
        if (
            sum(
                1
                for row in range(3)
                for current_col in range(3)
                if candidate[row][current_col] == SCAT
            )
            >= 3
        ):
            return candidate
    return board


def _pad_center(text: str, width: int) -> str:
    text_width = max(0, wcswidth(text))
    if text_width >= width:
        return text
    left = (width - text_width) // 2
    return (" " * left) + text + (" " * (width - text_width - left))


def render_board(board, winline_idxs=None, freespins_left=0):
    winline_idxs = set(winline_idxs or [])
    idx_to_coords = {i: coords for i, (coords, _name) in enumerate(PAYLINES)}
    highlight = [[False] * 3 for _ in range(3)]

    for idx in winline_idxs:
        for row, col in idx_to_coords.get(idx, []):
            highlight[row][col] = True

    def fmt_cell(row, col):
        symbol = board[row][col]
        if highlight[row][col]:
            symbol = f"〔{symbol}〕"
        return _pad_center(symbol, CELL_W)

    def row_line(row):
        return f"{VERT}{fmt_cell(row, 0)}{VERT}{fmt_cell(row, 1)}{VERT}{fmt_cell(row, 2)}{VERT}"

    bar = HOR * CELL_W
    lines = [
        "```",
        f"┌{bar}┬{bar}┬{bar}┐",
        f"{row_line(0)} {'▶' if 0 in winline_idxs else ' '}",
        f"├{bar}┼{bar}┼{bar}┤",
        f"{row_line(1)} {'▶' if 1 in winline_idxs else ' '}",
        f"├{bar}┼{bar}┼{bar}┤",
        f"{row_line(2)} {'▶' if 2 in winline_idxs else ' '}",
        f"└{bar}┴{bar}┴{bar}┘",
        "```",
    ]

    extra = []
    if winline_idxs:
        extra.append(
            "Gewinnlinien: "
            + ", ".join(PAYLINES[idx][1] for idx in sorted(winline_idxs))
        )
    if freespins_left > 0:
        extra.append(f"Freespins verbleibend: **{freespins_left}**")

    text = "\n".join(lines)
    return text if not extra else text + "\n" + "\n".join(extra)


def build_spin_frames(final_board, spin_frames=5):
    frames = [spin_reels() for _ in range(max(1, spin_frames))]
    last = [row[:] for row in frames[-1]]
    for col in range(3):
        step = [
            [
                final_board[row][current] if current <= col else last[row][current]
                for current in range(3)
            ]
            for row in range(3)
        ]
        frames.append(step)
        last = step
    frames.append(final_board)
    return frames


def nudge_for_line(board):
    if random.random() > NUDGE_LINE_CHANCE:
        return board

    for coords, _name in PAYLINES:
        symbols = [board[row][col] for row, col in coords]
        if SCAT in symbols:
            continue
        base = next((symbol for symbol in symbols if symbol != WILD), WILD)
        matches = sum(1 for symbol in symbols if symbol == base or symbol == WILD)
        if matches != 2:
            continue

        for row, col in coords:
            if board[row][col] == base or board[row][col] == WILD:
                continue
            strip = REEL_STRIPS[col]
            idx = strip.index(board[0][col])
            for step in (+1, -1):
                idx2 = (idx + step) % len(strip)
                new_col = [strip[(idx2 + offset) % len(strip)] for offset in range(3)]
                candidate = [current[:] for current in board]
                for current_row in range(3):
                    candidate[current_row][col] = new_col[current_row]
                values = [
                    candidate[current_row][current_col]
                    for current_row, current_col in coords
                ]
                if all(value == base or value == WILD for value in values):
                    return candidate
    return board


def line_payout(coords, board, bet):
    symbols = [board[row][col] for row, col in coords]
    if any(symbol == SCAT for symbol in symbols):
        return 0, None

    wilds = sum(1 for symbol in symbols if symbol == WILD)
    nonwild = [symbol for symbol in symbols if symbol != WILD]

    if wilds == 3:
        return bet * PURE_WILDS_MULTI, WILD
    if not nonwild:
        return 0, None

    base = nonwild[0]
    if any(symbol != base for symbol in nonwild):
        return 0, None

    base_multi = PAYTABLE.get(base, 0)
    if base_multi <= 0:
        return 0, None

    return bet * base_multi * WILD_LINE_MULT.get(wilds, 1), base


def evaluate(board, bet):
    total = 0
    winlines = []
    breakdown = []

    for idx, (coords, name) in enumerate(PAYLINES):
        payout, symbol = line_payout(coords, board, bet)
        if payout > 0:
            total += payout
            winlines.append(idx)
            breakdown.append((name, symbol, payout))

    scatters = sum(1 for row in range(3) for col in range(3) if board[row][col] == SCAT)
    if scatters >= 3:
        tier = max(key for key in sorted(SCATTER_PAYS) if scatters >= key)
        scatter_pay = bet * SCATTER_PAYS[tier]
        total += scatter_pay
        breakdown.append((f"{scatters}x Scatter", SCAT, scatter_pay))
        breakdown.append(("Freespins", SCAT, 0))
        free = FREESPINS_FOR_3_SCAT
    else:
        free = 0

    return total, winlines, free, breakdown


def render_cards(cards):
    return " ".join(cards)


def calculate_hand_value(hand):
    value = 0
    aces = 0
    for card in hand:
        rank = card[:-1] if card[:-1] != "" else card[0]
        value += CARD_VALUES.get(rank, 0)
        if rank == "A":
            aces += 1
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


class SlotView(ui.View):
    def __init__(self, cog, interaction, bet):
        super().__init__(timeout=120)
        self.cog = cog
        self.user_id = interaction.user.id
        self.bet = min(MAX_BET, max(10, bet))
        self.freespins = 0
        self.last_win = 0
        self.msg = None
        self.lock = asyncio.Lock()

    async def ensure_owner(self, interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Nur der ursprüngliche Spieler kann hier interagieren.", ephemeral=True
            )
            return False
        return True

    async def spin_once(self, interaction):
        user_data = await self.cog.get_user(self.user_id)
        wallet = user_data[0]
        if self.freespins == 0:
            if self.bet <= 0 or wallet < self.bet:
                await interaction.followup.send(
                    "<:Astra_x:1141303954555289600> Zu wenig Coins oder ungültiger Einsatz.",
                    ephemeral=True,
                )
                return None, None, None, None
            await self.cog.update_balance(self.user_id, wallet_change=-self.bet)

        final = nudge_for_line(nudge_for_scatter(spin_reels()))
        frames = build_spin_frames(final, SPIN_FRAMES)

        for board in frames[:-1]:
            await asyncio.sleep(FRAME_DELAY)
            embed = discord.Embed(
                colour=discord.Colour.blurple(),
                title="🎰 Slots",
                description=f"Einsatz: **{self.bet}** <:Coin:1359178077011181811>{' (Freespin)' if self.freespins > 0 else ''}",
            )
            embed.add_field(
                name="Walzen",
                value=render_board(board, freespins_left=self.freespins),
                inline=False,
            )
            await self.msg.edit(embed=embed)

        payout, winlines, freespins_got, breakdown = evaluate(final, self.bet)
        payout = min(int(payout), self.bet * MAX_WIN_MULTIPLIER)
        breakdown = [(name, symbol, int(value)) for name, symbol, value in breakdown]

        if freespins_got:
            self.freespins += freespins_got
        if payout > 0:
            await self.cog.update_balance(self.user_id, wallet_change=payout)
        self.last_win = payout
        if self.freespins > 0:
            self.freespins -= 1

        details = "Keine Gewinnlinien."
        if breakdown:
            details = "\n".join(
                f"• {name} {symbol or ''} {'→ **+%s**' % value if value > 0 else ''}"
                for name, symbol, value in breakdown
            )

        result = (
            f"<:Astra_gw1:1141303852889550928> Gewinn: **+{payout}** <:Coin:1359178077011181811>"
            if payout > 0
            else "Kein Gewinn."
        )
        embed = discord.Embed(
            colour=discord.Colour.blue(), title="🎰 Slots - Ergebnis "
        )
        embed.add_field(
            name="Walzen",
            value=render_board(final, winlines, self.freespins),
            inline=False,
        )
        embed.add_field(name="Ergebnis", value=result, inline=False)
        embed.add_field(name="Details", value=details, inline=False)
        await self.msg.edit(embed=embed, view=self)
        return final, payout, winlines, breakdown

    @ui.button(label="▶️ Spin", style=discord.ButtonStyle.green)
    async def spin(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction):
            return
        async with self.lock:
            await interaction.response.defer()
            await self.spin_once(interaction)

    @ui.button(label="🔁 Auto x5", style=discord.ButtonStyle.primary)
    async def auto(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction):
            return
        async with self.lock:
            await interaction.response.defer()
            for _ in range(5):
                await self.spin_once(interaction)
                await asyncio.sleep(0.3)
                user_data = await self.cog.get_user(self.user_id)
                if user_data[0] < self.bet and self.freespins == 0:
                    break

    @ui.button(label="🎲 Gamble", style=discord.ButtonStyle.red)
    async def gamble(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction):
            return
        async with self.lock:
            await interaction.response.defer(ephemeral=True)
            if self.last_win <= 0:
                await interaction.followup.send(
                    "Kein Gewinn zum Verdoppeln.", ephemeral=True
                )
                return
            if random.random() < 0.48:
                await self.cog.update_balance(self.user_id, wallet_change=self.last_win)
                self.last_win *= 2
                await interaction.followup.send(
                    f"🎉 Verdoppelt! Neuer Gewinn: **+{self.last_win}**", ephemeral=True
                )
            else:
                await self.cog.update_balance(
                    self.user_id, wallet_change=-self.last_win
                )
                self.last_win = 0
                await interaction.followup.send(
                    "💥 Verloren - Gewinn futsch.", ephemeral=True
                )

    @ui.button(label="➖", style=discord.ButtonStyle.secondary)
    async def bet_minus(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction):
            return
        self.bet = max(10, int(self.bet * 0.5))
        await interaction.response.send_message(
            f"Einsatz: **{self.bet}**", ephemeral=True
        )

    @ui.button(label="➕", style=discord.ButtonStyle.secondary)
    async def bet_plus(self, interaction: discord.Interaction, button: ui.Button):
        if not await self.ensure_owner(interaction):
            return
        self.bet = min(MAX_BET, int(self.bet * 1.5) or self.bet + 10)
        await interaction.response.send_message(
            f"Einsatz: **{self.bet}**", ephemeral=True
        )


class BlackjackView(discord.ui.View):
    def __init__(self, bot, interaction, bet, economy):
        super().__init__(timeout=180)
        self.bot = bot
        self.interaction = interaction
        self.bet = bet
        self.original_bet = bet
        self.economy = economy
        self.user_id = interaction.user.id
        self.player_hand = []
        self.split_hand = None
        self.current_hand = 1
        self.split_mode = False
        self.dealer_hand = []
        self.deck = self.create_deck()
        self.message = None
        self.stand_called = False
        self.result_shown = False
        self.deal_initial_cards()

    def create_deck(self):
        suits = ["♠", "♥", "♦", "♣"]
        ranks = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
        deck = [f"{rank}{suit}" for suit in suits for rank in ranks]
        random.shuffle(deck)
        return deck

    def deal_initial_cards(self):
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def can_split(self):
        return (
            len(self.player_hand) == 2
            and self.player_hand[0][:-1] == self.player_hand[1][:-1]
        )

    async def update_message(self):
        player_value = calculate_hand_value(self.player_hand)
        dealer_value = calculate_hand_value(self.dealer_hand)
        embed = discord.Embed(title="Blackjack", color=discord.Color.blue())
        embed.add_field(
            name="<:Astra_user:1141303940365959241> Deine Karten:",
            value=f"```{render_cards(self.player_hand)}```\nWert: **{player_value}**",
            inline=False,
        )

        if self.split_mode and self.split_hand:
            split_value = calculate_hand_value(self.split_hand)
            embed.add_field(
                name="🂡 Zweite Hand:",
                value=f"```{render_cards(self.split_hand)}```\nWert: **{split_value}**",
                inline=False,
            )

        dealer_cards_display = (
            f"{render_cards([self.dealer_hand[0]])} ❓"
            if not self.stand_called
            else render_cards(self.dealer_hand)
        )
        dealer_value_display = "?" if not self.stand_called else str(dealer_value)
        embed.add_field(
            name="<:Astra_dev:1141303833407017001> Karten des Dealers:",
            value=f"```{dealer_cards_display}```\nWert: **{dealer_value_display}**",
            inline=False,
        )

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
            embed.add_field(
                name="<:Astra_wichtig:1141303951862534224> Ergebnis",
                value=result_text,
                inline=False,
            )
            for child in self.children:
                child.disabled = True
            if not self.result_shown:
                self.result_shown = True
                if player_value <= 21 and (
                    player_value > dealer_value or dealer_value > 21
                ):
                    await self.economy.update_balance(
                        self.user_id, wallet_change=self.bet * 2
                    )
                elif player_value == dealer_value:
                    await self.economy.update_balance(
                        self.user_id, wallet_change=self.bet
                    )

        if self.message is None:
            self.message = await self.interaction.original_response()
        await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.green)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.split_mode and self.current_hand == 2:
            if calculate_hand_value(self.split_hand) >= 21:
                return
            self.split_hand.append(self.deck.pop())
        else:
            if calculate_hand_value(self.player_hand) >= 21:
                return
            self.player_hand.append(self.deck.pop())
        await self.update_message()

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.red)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if self.split_mode and self.current_hand == 1:
            self.current_hand = 2
            await self.update_message()
            return
        self.stand_called = True
        await self.animate_dealer_cards()
        await self.update_message()

    @discord.ui.button(label="Double", style=discord.ButtonStyle.blurple)
    async def double(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        wallet = (await self.economy.get_user(self.user_id))[0]
        if wallet < self.bet:
            await interaction.followup.send(
                "Du hast nicht genug Coins für Double Down.", ephemeral=True
            )
            return
        await self.economy.update_balance(self.user_id, wallet_change=-self.bet)
        self.bet *= 2
        self.player_hand.append(self.deck.pop())
        self.stand_called = True
        await self.animate_dealer_cards()
        await self.update_message()

    @discord.ui.button(label="Split", style=discord.ButtonStyle.grey)
    async def split(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if not self.can_split():
            await interaction.followup.send(
                "Diese Karten können nicht gesplittet werden.", ephemeral=True
            )
            return
        wallet = (await self.economy.get_user(self.user_id))[0]
        if wallet < self.bet:
            await interaction.followup.send(
                "Nicht genug Coins zum Splitten.", ephemeral=True
            )
            return
        await self.economy.update_balance(self.user_id, wallet_change=-self.bet)
        self.split_mode = True
        self.split_hand = [self.player_hand.pop()]
        self.player_hand.append(self.deck.pop())
        self.split_hand.append(self.deck.pop())
        await self.update_message()

    async def animate_dealer_cards(self):
        await asyncio.sleep(0.8)
        await self.update_message()
        await asyncio.sleep(1)
        while calculate_hand_value(self.dealer_hand) < 17:
            embed = discord.Embed(
                title="Blackjack",
                description="🎴 Dealer zieht eine Karte...",
                color=discord.Color.blue(),
            )
            await self.message.edit(embed=embed, view=self)
            await asyncio.sleep(0.7)
            self.dealer_hand.append(self.deck.pop())
            await self.update_message()
            await asyncio.sleep(1.1)
        await asyncio.sleep(0.6)


@app_commands.guild_only()
class GambleGroup(EconomyMixin, app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(name="gamble", description="Alles rund um Glücksspiele.")

    @app_commands.command(
        name="slot", description="Spiele ein realistisches 3x3 Slot-Spiel."
    )
    @app_commands.describe(einsatz="Wie viele Coins willst du setzen?")
    async def slot(self, interaction: discord.Interaction, einsatz: int):
        wallet = (await self.get_user(interaction.user.id))[0]
        if einsatz <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Ungültiger Einsatz.", ephemeral=True
            )
            return
        if einsatz > MAX_BET:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Der maximale Einsatz beträgt **{MAX_BET}** <:Coin:1359178077011181811>.",
                ephemeral=True,
            )
            return
        if einsatz > wallet:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du hast nicht genug Coins.",
                ephemeral=True,
            )
            return

        view = SlotView(self, interaction, einsatz)
        embed = discord.Embed(
            colour=discord.Colour.blurple(),
            title="🎰 Slots",
            description=f"Einsatz: **{einsatz}** <:Coin:1359178077011181811>\nViel Glück, {interaction.user.mention}!",
        )
        embed.add_field(name="Walzen", value=render_board(spin_reels()), inline=False)
        embed.set_author(
            name=str(interaction.user),
            icon_url=(
                interaction.user.display_avatar.url
                if interaction.user.display_avatar
                else None
            ),
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.msg = await interaction.original_response()

    @app_commands.command(
        name="rps", description="Spiele Schere, Stein, Papier gegen den Bot."
    )
    @app_commands.describe(choice="Wähle 'Schere', 'Stein' oder 'Papier'.")
    async def rps(
        self,
        interaction: discord.Interaction,
        choice: Literal["Stein", "Schere", "Papier"],
    ):
        choice = choice.lower()
        bot_choice = random.choice(["schere", "stein", "papier"])
        if choice == bot_choice:
            result = "Unentschieden!"
        elif (
            (choice == "schere" and bot_choice == "papier")
            or (choice == "stein" and bot_choice == "schere")
            or (choice == "papier" and bot_choice == "stein")
        ):
            result = "<:Astra_gw1:1141303852889550928> Du hast gewonnen!"
        else:
            result = "<:Astra_x:1141303954555289600> Du hast verloren!"

        embed = discord.Embed(title="Schere, Stein, Papier", color=discord.Color.blue())
        embed.add_field(
            name="Deine Wahl", value=f"**{choice.capitalize()}**", inline=False
        )
        embed.add_field(
            name="Bot's Wahl", value=f"**{bot_choice.capitalize()}**", inline=False
        )
        embed.add_field(name="Ergebnis", value=result, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="coinflip", description="Münzwurf: Wähle Kopf oder Zahl und setze."
    )
    @app_commands.describe(
        wahl="Deine Wahl: 'Kopf' oder 'Zahl'",
        betrag="Der Betrag, den du setzen möchtest.",
    )
    async def coinflip(self, interaction: discord.Interaction, wahl: str, betrag: int):
        guess = wahl.lower()
        if guess not in ["kopf", "zahl"]:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte wähle entweder 'Kopf' oder 'Zahl'.",
                ephemeral=True,
            )
            return
        if betrag <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte gib einen gültigen Betrag ein, der größer als 0 ist.",
                ephemeral=True,
            )
            return

        wallet = (await self.get_user(interaction.user.id))[0]
        if betrag > MAX_BET:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Der maximale Einsatz beträgt **{MAX_BET}** <:Coin:1359178077011181811>.",
                ephemeral=True,
            )
            return
        if wallet < betrag:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Du hast nicht genug Münzen. Dein aktueller Kontostand ist {wallet} <:Coin:1359178077011181811>.",
                ephemeral=True,
            )
            return

        result = random.choice(["Kopf", "Zahl"])
        embed = discord.Embed(title="Münzwurf", color=discord.Color.blue())
        embed.add_field(
            name="Deine Wahl", value=f"**{guess.capitalize()}**", inline=False
        )
        embed.add_field(name="Ergebnis", value=f"**{result}**", inline=False)
        if guess == result.lower():
            gewonnen = betrag * 2
            await self.update_balance(interaction.user.id, gewonnen, 0)
            embed.add_field(
                name="<:Astra_gw1:1141303852889550928> Glückwunsch!",
                value=f"Du hast gewonnen! Du erhältst {gewonnen} <:Coin:1359178077011181811>.",
                inline=False,
            )
        else:
            await self.update_balance(interaction.user.id, -betrag, 0)
            embed.add_field(
                name="<:Astra_x:1141303954555289600> Leider verloren",
                value=f"Du hast verloren und {betrag} <:Coin:1359178077011181811> verloren.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="rob", description="Versuche, einen anderen Nutzer auszurauben!"
    )
    @app_commands.describe(ziel="Wen willst du ausrauben?")
    async def rob(self, interaction: discord.Interaction, ziel: discord.User):
        user_id = interaction.user.id
        target_id = ziel.id
        if user_id == target_id:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Du kannst dich nicht selbst ausrauben.",
                ephemeral=True,
            )
            return

        user_data = await self.get_user(user_id)
        target_data = await self.get_user(target_id)
        last_rob = user_data[6]
        now = datetime.now(timezone.utc)
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
            await interaction.response.send_message(
                f"<:Astra_time:1141303932061233202> Du kannst in **{' '.join(parts)}** wieder rauben.",
                ephemeral=True,
            )
            return

        if target_data[0] < 50:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Ziel hat zu wenig Geld zum Ausrauben.",
                ephemeral=True,
            )
            return

        if random.random() < 0.5:
            amount = random.randint(20, min(200, target_data[0]))
            await self.update_balance(user_id, wallet_change=amount)
            await self.update_balance(target_id, wallet_change=-amount)
            message = f"<:Astra_accept:1141303821176422460> Du hast erfolgreich {amount} <:Coin:1359178077011181811> von {ziel.mention} gestohlen!"
        else:
            fine = random.randint(10, 30)
            await self.update_balance(user_id, wallet_change=-fine)
            message = f"<:Astra_x:1141303954555289600> Du wurdest erwischt! Du zahlst eine Strafe von {fine} <:Coin:1359178077011181811>."

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE economy_users SET last_rob = %s WHERE user_id = %s",
                    (now, user_id),
                )

        await interaction.response.send_message(message)

    @app_commands.command(name="blackjack", description="Spiele eine Runde Blackjack.")
    @app_commands.describe(einsatz="Der Betrag, den du setzen möchtest.")
    async def blackjack(self, interaction: discord.Interaction, einsatz: int):
        wallet = (await self.get_user(interaction.user.id))[0]
        if einsatz > MAX_BET:
            await interaction.response.send_message(
                f"<:Astra_x:1141303954555289600> Der maximale Einsatz beträgt **{MAX_BET}** <:Coin:1359178077011181811>.",
                ephemeral=True,
            )
            return
        if einsatz <= 0:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Bitte gib einen gültigen Einsatz an.",
                ephemeral=True,
            )
            return
        if wallet < einsatz:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> hast nicht genug Münzen.",
                ephemeral=True,
            )
            return

        await self.update_balance(interaction.user.id, wallet_change=-einsatz)
        view = BlackjackView(self.bot, interaction, einsatz, self)
        embed = discord.Embed(
            title="Blackjack wird gestartet!",
            description="Ziehe Karten mit `Hit` oder beende mit `Stand`. Ziel: So nah wie möglich an 21!",
            color=discord.Color.blue(),
        )
        embed.add_field(
            name="Einsatz", value=f"{einsatz} <:Coin:1359178077011181811>", inline=False
        )
        await interaction.response.send_message(embed=embed, view=view)
        view.message = await interaction.original_response()
        await view.update_message()


async def setup(bot):
    bot.tree.add_command(GambleGroup(bot))
