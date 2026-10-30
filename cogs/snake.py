import discord
from discord.ext import commands
from discord.app_commands import Group
from discord.ui import Button, View
from discord import app_commands
import random
from utils.branding import get_current_colour

# Neuer Spielzustand
snake_game = {
    "current_score": 0,
    "game": False,
    "snake": [[1, 1]],  # Schlange mit Kopf
    "direction": 6,
    "food": [],
}

class SnakeGameView(View):
    def __init__(self, player: discord.User, bot: commands.Bot):
        super().__init__(timeout=None)
        self.player = player
        self.bot = bot

        # Richtung-Buttons
        self.up_button = Button(label='⬆️', style=discord.ButtonStyle.primary)
        self.down_button = Button(label='⬇️', style=discord.ButtonStyle.primary)
        self.left_button = Button(label='⬅️', style=discord.ButtonStyle.primary)
        self.right_button = Button(label='➡️', style=discord.ButtonStyle.primary)
        
        # Abbrechen-Button
        self.quit_button = Button(label='❌ Abbrechen', style=discord.ButtonStyle.danger)

        # Callback-Methoden für Buttons
        self.up_button.callback = self.move_upF
        self.down_button.callback = self.move_down
        self.left_button.callback = self.move_left
        self.right_button.callback = self.move_right
        self.quit_button.callback = self.quit_game

        # Buttons zur View hinzufügen
        self.add_item(self.up_button)
        self.add_item(self.down_button)
        self.add_item(self.left_button)
        self.add_item(self.right_button)
        self.add_item(self.quit_button)

    async def move_up(self, interaction):
        if snake_game['direction'] != 2:
            snake_game['direction'] = 8
        await self.move(interaction)

    async def move_down(self, interaction):
        if snake_game['direction'] != 8:
            snake_game['direction'] = 2
        await self.move(interaction)

    async def move_left(self, interaction):
        if snake_game['direction'] != 6:
            snake_game['direction'] = 4
        await self.move(interaction)

    async def move_right(self, interaction):
        if snake_game['direction'] != 4:
            snake_game['direction'] = 6
        await self.move(interaction)

    async def move(self, interaction):
        if interaction.user.id != self.player.id:
            return await interaction.response.send_message("Nicht dein Spiel!", ephemeral=True)

        direction = snake_game['direction']
        head = snake_game['snake'][0].copy()

        if direction == 2:
            head[0] += 1
        elif direction == 4:
            head[1] -= 1
        elif direction == 6:
            head[1] += 1
        elif direction == 8:
            head[0] -= 1

        if head[0] == 0 or head[1] == 0 or head[0] == 7 or head[1] == 7:
            return await self.end_game(interaction)

        if head in snake_game['snake']:
            return await self.end_game(interaction)

        snake_game['snake'].insert(0, head)

        if head == snake_game['food']:
            snake_game['current_score'] += 1
            snake_game['food'] = await self.spawn_food()
        else:
            snake_game['snake'].pop()

        plot = await self.plot_grid()
        # Highscore wird immer aus der DB geholt
        highscore = await self.get_highscore(interaction.user.id)

        embed = discord.Embed(title="Snake Spiel", description=plot, color=get_current_colour())
        embed.add_field(name="Punkte", value=str(snake_game['current_score']))
        embed.add_field(name="Highscore", value=str(highscore))

        await interaction.message.edit(embed=embed)
        await interaction.response.defer()

    async def plot_grid(self):
        plot = ""
        for x in range(8):
            for y in range(8):
                pos = [x, y]
                if pos == snake_game['snake'][0]:
                    plot += ":green_circle:"
                elif pos in snake_game['snake'][1:]:
                    plot += ":green_square:"
                elif pos == snake_game['food']:
                    plot += ":apple:"
                elif x == 0 or y == 0 or x == 7 or y == 7:
                    plot += ":brick:"
                else:
                    plot += ":white_large_square:"
            plot += '\n'
        return plot

    async def spawn_food(self):
        while True:
            food = [random.randint(1, 6), random.randint(1, 6)]
            if food not in snake_game['snake']:
                return food

    async def end_game(self, interaction):
        # Highscore prüfen und aktualisieren
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT highscore FROM snake WHERE userID = %s", (interaction.user.id,))
                result = await cur.fetchone()

                if result is None:
                    # Falls der Spieler noch keinen Highscore hat
                    await cur.execute("INSERT INTO snake (userID, highscore) VALUES (%s, %s)", (interaction.user.id, snake_game['current_score']))
                else:
                    # Wenn der Spieler bereits einen Highscore hat, dann aktualisieren, falls der neue Score höher ist
                    if snake_game['current_score'] > result[0]:
                        await cur.execute("UPDATE snake SET highscore = %s WHERE userID = %s", (snake_game['current_score'], interaction.user.id))

        snake_game['game'] = False
        highscore = await self.get_highscore(interaction.user.id)

        embed = discord.Embed(title="Game Over", description="Kollision erkannt!", color=discord.Color.red())
        embed.add_field(name="Punkte", value=str(snake_game['current_score']))
        embed.add_field(name="Highscore", value=str(highscore))

        # Deaktivieren der Buttons
        self.up_button.disabled = True
        self.down_button.disabled = True
        self.left_button.disabled = True
        self.right_button.disabled = True
        self.quit_button.disabled = True

        # Setze die Callbacks der Buttons auf None, um sicherzustellen, dass keine Interaktionen mehr ausgeführt werden
        self.up_button.callback = None
        self.down_button.callback = None
        self.left_button.callback = None
        self.right_button.callback = None
        self.quit_button.callback = None

        # Nachricht mit dem aktualisierten Embed und deaktivierten Buttons
        await interaction.message.edit(embed=embed, view=self)

        await interaction.response.send_message("Spiel beendet.", ephemeral=True)

    async def quit_game(self, interaction):
        # Abbrechen des Spiels
        # Highscore prüfen und aktualisieren, falls nötig
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT highscore FROM snake WHERE userID = %s", (interaction.user.id,))
                result = await cur.fetchone()

                if result is None:
                    # Falls der Spieler noch keinen Highscore hat
                    await cur.execute("INSERT INTO snake (userID, highscore) VALUES (%s, %s)", (interaction.user.id, snake_game['current_score']))
                else:
                    # Wenn der Spieler bereits einen Highscore hat, dann aktualisieren, falls der neue Score höher ist
                    if snake_game['current_score'] > result[0]:
                        await cur.execute("UPDATE snake SET highscore = %s WHERE userID = %s", (snake_game['current_score'], interaction.user.id))

        snake_game['game'] = False
        highscore = await self.get_highscore(interaction.user.id)

        embed = discord.Embed(title="Spiel Abgebrochen", description="Das Spiel wurde abgebrochen.", color=discord.Color.red())
        embed.add_field(name="Punkte", value=str(snake_game['current_score']))
        embed.add_field(name="Highscore", value=str(highscore))

        # Deaktivieren der Buttons und Setzen der Callbacks auf None
        self.up_button.disabled = True
        self.down_button.disabled = True
        self.left_button.disabled = True
        self.right_button.disabled = True
        self.quit_button.disabled = True

        self.up_button.callback = None
        self.down_button.callback = None
        self.left_button.callback = None
        self.right_button.callback = None
        self.quit_button.callback = None

        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("Spiel abgebrochen.", ephemeral=True)

    async def get_highscore(self, user_id):
        # Highscore aus der DB abfragen
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT highscore FROM snake WHERE userID = %s", (user_id,))
                result = await cur.fetchone()
                if result:
                    return result[0]
                else:
                    return 0

@app_commands.guild_only()
class Snake(app_commands.Group):
    def __init__(self, bot):
        self.bot = bot  # <--- Hinzufügen!
        super().__init__(
            name="snake",
            description="snake!"
        )

    @app_commands.command(name="start", description="Starte Snake!")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    async def snake(self, interaction: discord.Interaction):
        """Spiele Snake."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Überprüfen, ob der Spieler bereits einen Highscore hat
                await cur.execute("SELECT highscore FROM snake WHERE userID = %s", (interaction.user.id,))
                result = await cur.fetchone()

                if result is None:
                    # Kein Highscore in der DB, also wird ein neuer Eintrag gemacht
                    if snake_game['game']:
                        return await interaction.response.send_message("Spiel läuft bereits!", ephemeral=True)

                    snake_game['game'] = True
                    snake_game['current_score'] = 0
                    snake_game['snake'] = [[1, 1]]
                    snake_game['direction'] = 6
                    snake_game['food'] = await self.spawn_food()

                    view = SnakeGameView(interaction.user, self.bot)
                    plot = await view.plot_grid()

                    # Highscore wird immer aus der DB geholt
                    highscore = await view.get_highscore(interaction.user.id)

                    embed = discord.Embed(title="Snake Spiel", description=plot, color=get_current_colour())
                    embed.add_field(name="Punkte", value="0")
                    embed.add_field(name="Highscore", value=str(highscore))

                    await cur.execute("INSERT INTO snake (userID, highscore) VALUES (%s, %s)",
                                      (interaction.user.id, snake_game['current_score']))

                    await interaction.response.send_message(embed=embed, view=view)
                else:
                    # Wenn das Spiel läuft, wird nichts getan
                    if snake_game['game']:
                        return await interaction.response.send_message("Spiel läuft bereits!", ephemeral=True)

                    # Spiel starten
                    snake_game['game'] = True
                    snake_game['current_score'] = 0
                    snake_game['snake'] = [[1, 1]]
                    snake_game['direction'] = 6
                    snake_game['food'] = await self.spawn_food()

                    view = SnakeGameView(interaction.user, self.bot)
                    plot = await view.plot_grid()

                    # Highscore wird immer aus der DB geholt
                    highscore = await view.get_highscore(interaction.user.id)

                    embed = discord.Embed(title="Snake Spiel", description=plot, color=get_current_colour())
                    embed.add_field(name="Punkte", value="0")
                    embed.add_field(name="Highscore", value=str(highscore))

                    await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="highscore", description="Zeige den Highscore eines Spielers")
    async def highscore(self, interaction: discord.Interaction, player: discord.User = None):
        # Highscore eines anderen Spielers abfragen
        if player is None:
            player = interaction.user
            highscore = await self.get_highscore(player.id)

            embed = discord.Embed(title=f"Highscore von {player.name}", description=f"Der Highscore ist {highscore}",
                                  color=get_current_colour())
            await interaction.response.send_message(embed=embed)
        else:
            highscore = await self.get_highscore(player.id)

            embed = discord.Embed(title=f"Highscore von {player.name}", description=f"Der Highscore ist {highscore}",
                                  color=get_current_colour())
            await interaction.response.send_message(embed=embed)

    async def spawn_food(self):
        while True:
            food = [random.randint(1, 6), random.randint(1, 6)]
            if food not in snake_game['snake']:
                return food

    async def get_highscore(self, user_id):
        # Highscore aus der DB abfragen
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT highscore FROM snake WHERE userID = %s", (user_id,))
                result = await cur.fetchone()
                if result:
                    return result[0]
                else:
                    return 0

class SnakeBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(SnakeBot(bot))
    bot.tree.add_command(Snake(bot))
