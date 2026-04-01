import os
import json
from io import BytesIO
from typing import Literal
import random
import discord
from discord import app_commands, File
from discord.ext import commands
from PIL import Image, ImageDraw, ImageChops, ImageFont

# ──────────────────────────────────────────────────────────────────────────────
# Assets & Styles
# ──────────────────────────────────────────────────────────────────────────────
ASSETS_DIR = "cogs/assets/Levelcards"
DEFAULT_STYLE = "standard"  # entspricht standard.png


def list_styles():
    if not os.path.isdir(ASSETS_DIR):
        return []
    return sorted(
        os.path.splitext(f)[0]
        for f in os.listdir(ASSETS_DIR)
        if f.lower().endswith(".png")
    )


def style_to_path(style_name: str) -> str:
    if not os.path.isdir(ASSETS_DIR):
        return os.path.join(ASSETS_DIR, f"{DEFAULT_STYLE}.png")
    for f in os.listdir(ASSETS_DIR):
        if f.lower().endswith(".png") and os.path.splitext(f)[0].lower() == style_name.lower():
            return os.path.join(ASSETS_DIR, f)
    return os.path.join(ASSETS_DIR, f"{DEFAULT_STYLE}.png")


# ──────────────────────────────────────────────────────────────────────────────
# Layout-Gruppen + Skalierung
# ──────────────────────────────────────────────────────────────────────────────
def _layout_key_for_style(style: str) -> str:
    s = (style or "").lower()
    if s in ("levelcard_astra", "standard"):
        return "standard"
    return "new"


BASE_BY_GROUP = {
    "new": (1075, 340),
    "standard": (1064, 339),
}


def _deepcopy(obj):
    import json as _json
    return _json.loads(_json.dumps(obj))


def _merge_overrides(base: dict, ovr: dict | None) -> dict:
    res = _deepcopy(base)
    for k, v in (ovr or {}).items():
        if isinstance(v, dict) and isinstance(res.get(k), dict):
            res[k].update(v)
        else:
            res[k] = v
    return res


def _scale_layout(layout: dict, dst_w: int, dst_h: int, base_w: int, base_h: int) -> dict:
    sx = dst_w / float(base_w)
    sy = dst_h / float(base_h)
    sfont = (sx + sy) / 2.0

    def sc(d: dict) -> dict:
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out[k] = sc(v)
            elif k in ("x", "w", "size", "border", "pad_x", "r", "max_w", "ring_width", "inset", "x0", "x1"):
                out[k] = int(round(v * sx))
            elif k in ("y", "h", "pad_y", "y0", "y1"):
                out[k] = int(round(v * sy))
            elif k in ("font", "min_font", "base_font"):
                out[k] = max(8, int(round(v * sfont)))
            else:
                out[k] = v
        return out

    return sc(layout)


def _resolved_layout(style: str, img_w: int, img_h: int) -> dict:
    key = _layout_key_for_style(style)
    base = LAYOUTS[key]
    merged = _merge_overrides(base, STYLE_OVERRIDES.get(key))
    bw, bh = BASE_BY_GROUP[key]
    return _scale_layout(merged, img_w, img_h, bw, bh)


# ──────────────────────────────────────────────────────────────────────────────
# Progressbar-Farben
# ──────────────────────────────────────────────────────────────────────────────
DEFAULT_HEX = "#61BFC4"
BAR_COLORS = {
    "türkis_stripes": "#C980E8",
    "Halloween_stripes": "#61BFC4",
    "Christmas_stripes": "#61BFC4",
    "Easter Stripes": "#61BFC4",
    "Easter_stripes": "#61BFC4",
    "standard_stripes_left_star": "#61BFC4",
    "standard_stripes_right_star": "#61BFC4",
    "standard": "#61BFC4",
}


def bar_color_for(style: str) -> str:
    return BAR_COLORS.get(style, DEFAULT_HEX)


# ──────────────────────────────────────────────────────────────────────────────
# Pixelgenaue Layouts (Avatar/Text + exakte Boxen für Name/Level/XP)
# ──────────────────────────────────────────────────────────────────────────────
LAYOUTS = {
    # Alle anderen (1075 x 340)
    "new": {
        "avatar": {"x": 57, "y": 93, "size": 155, "inset": 8, "draw_ring": False, "ring_width": 0},
        "rank": {"x": 393, "y": 157, "font": 53},

        # Name-Box leicht nach rechts; zentriert im Balken
        "name_box": {"x0": 252, "y0": 89, "x1": 818, "y1": 143, "base_font": 36, "min_font": 24, "pad_x": 22,
                     "pad_y": 10},

        # Level/XP-Boxen – hohe Schrift möglich dank kleiner pad_y
        "level_box": {"x0": 853, "y0": 89, "x1": 1021, "y1": 129, "base_font": 52, "min_font": 24, "pad_x": 10,
                      "pad_y": 4},
        "xp_box": {"x0": 853, "y0": 204, "x1": 1021, "y1": 244, "base_font": 40, "min_font": 20, "pad_x": 10,
                   "pad_y": 6},
    },

    # Standard (1064 x 339)
    "standard": {
        "avatar": {"x": 64, "y": 98, "size": 142, "inset": 0, "draw_ring": True, "ring_width": 12},
        "rank": {"x": 393, "y": 157, "font": 53},

        # Name-Box etwas nach rechts verschoben (vorher 232..808)
        "name_box": {"x0": 246, "y0": 88, "x1": 813, "y1": 142, "base_font": 36, "min_font": 24, "pad_x": 22,
                     "pad_y": 10},

        "level_box": {"x0": 847, "y0": 88, "x1": 1015, "y1": 128, "base_font": 52, "min_font": 24, "pad_x": 10,
                      "pad_y": 4},
        "xp_box": {"x0": 847, "y0": 205, "x1": 1015, "y1": 243, "base_font": 40, "min_font": 20, "pad_x": 10,
                   "pad_y": 6},
    }
}

STYLE_OVERRIDES = {}
FONT_PATH = "cogs/fonts/Poppins-SemiBold.ttf"

# -------------------------------------------
# Pretty names -> interne Dateinamen (ohne .png)
# -------------------------------------------
PRETTY_TO_FILENAME = {
    "Standard": "standard",
    "Türkis": "türkis_stripes",
    "Halloween": "Halloween_stripes",
    "Weihnachten": "Christmas_stripes",
    "Ostern": "Easter_stripes",
    "Standard mit Streifen – Stern links": "standard_stripes_left_star",
    "Standard mit Streifen – Stern rechts": "standard_stripes_right_star",
}

PRETTY_CHOICES = tuple(PRETTY_TO_FILENAME.keys())

# ──────────────────────────────────────────────────────────────────────────────
# Diskrete Progressbar-Geometrie (exakt nach deinen Koordinaten)
# ──────────────────────────────────────────────────────────────────────────────
PB_GEOM = {
    "standard": {  # 1064 x 339
        "left_cap": {
            214: (275, 312), 213: (276, 311), 212: (276, 311), 211: (276, 310),
            210: (278, 309), 209: (279, 308), 208: (281, 306),
        },
        "right_cap": {
            881: (275, 312), 882: (276, 311), 883: (276, 311), 884: (277, 310),
            885: (278, 309), 886: (279, 308), 887: (281, 306),
        },
        "y_full": (275, 312),
        "x_span": (208, 887),
    },
    "new": {  # 1075 x 340
        "left_cap": {
            220: (276, 313), 219: (277, 312), 218: (277, 312), 217: (278, 311),
            216: (279, 310), 215: (280, 309), 214: (282, 307),
        },
        "right_cap": {
            887: (276, 313), 888: (277, 312), 889: (277, 312), 890: (278, 311),
            891: (279, 310), 892: (280, 309), 893: (282, 307),
        },
        "y_full": (276, 313),
        "x_span": (214, 893),
    }
}

# Cache für Slot-Masken
_SLOT_MASK_CACHE: dict[tuple[str, tuple[int, int]], Image.Image] = {}


def _geom_key(img_w: int, img_h: int, style: str) -> str:
    if (img_w, img_h) == (1064, 339) or (style or "").lower() in ("standard", "levelcard_astra"):
        return "standard"
    return "new"


def _slot_mask_from_coords(img_w: int, img_h: int, layout_key: str) -> Image.Image:
    cache_key = (layout_key, (img_w, img_h))
    if cache_key in _SLOT_MASK_CACHE:
        return _SLOT_MASK_CACHE[cache_key]

    geom = PB_GEOM[layout_key]
    x0, x1 = geom["x_span"]
    y0, y1 = geom["y_full"]
    left_cap = geom["left_cap"]
    right_cap = geom["right_cap"]

    mask = Image.new("L", (img_w, img_h), 0)
    d = ImageDraw.Draw(mask)

    # Mittelteil
    mid_x0 = max(x0, max(left_cap.keys()) + 1)
    mid_x1 = min(x1, min(right_cap.keys()) - 1)
    if mid_x1 >= mid_x0:
        d.rectangle((mid_x0, y0, mid_x1, y1), fill=255)

    # Kappen
    for x, (yt, yb) in left_cap.items():
        d.line((x, yt, x, yb), fill=255)
    for x, (yt, yb) in right_cap.items():
        d.line((x, yt, x, yb), fill=255)

    _SLOT_MASK_CACHE[cache_key] = mask
    return mask


# ──────────────────────────────────────────────────────────────────────────────
# Render-Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _mk_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=max(8, int(size)))


def _truncate_to_width(draw, text: str, font, max_px: int) -> str:
    if draw.textlength(text, font=font) <= max_px:
        return text
    ell = "…"
    while text and draw.textlength(text + ell, font=font) > max_px:
        text = text[:-1]
    return text + ell


def _center_text(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                 text: str, font: ImageFont.FreeTypeFont, fill: str):
    w = draw.textlength(text, font=font)
    x0, y0, x1, y1 = font.getbbox(text)
    y_mid = (y0 + y1) / 2.0
    draw.text((cx - w / 2.0, cy - y_mid), text, font=font, fill=fill)


def _draw_centered_in_box(draw: ImageDraw.ImageDraw, text: str, box: dict,
                          base_font: int, min_font: int, fill: str = "white", pad: int | None = None):
    """
    Zentriert Text in Box {x0,y0,x1,y1} und skaliert ihn maximal hinein.
    Unterstützt pad_x/pad_y (falls nicht vorhanden -> pad oder 0).
    """
    x0, y0, x1, y1 = box["x0"], box["y0"], box["x1"], box["y1"]
    pad_x = box.get("pad_x", pad if pad is not None else 0)
    pad_y = box.get("pad_y", pad if pad is not None else 0)

    max_w = max(1, (x1 - x0) - 2 * pad_x)
    max_h = max(1, (y1 - y0) - 2 * pad_y)

    size = int(base_font)
    font = _mk_font(size)

    # ggf. verkleinern
    while True:
        w = draw.textlength(text, font=font)
        bx0, by0, bx1, by1 = font.getbbox(text)
        h = by1 - by0
        if w <= max_w and h <= max_h:
            break
        size -= 1
        if size < int(min_font):
            break
        font = _mk_font(size)

    # so lange vergrößern, bis knapp vor Limit
    while True:
        w = draw.textlength(text, font=font)
        bx0, by0, bx1, by1 = font.getbbox(text)
        h = by1 - by0
        if w >= max_w or h >= max_h:
            break
        test = _mk_font(size + 1)
        w2 = draw.textlength(text, font=test)
        bx0, by0, bx1, by1 = test.getbbox(text)
        h2 = by1 - by0
        if w2 > max_w or h2 > max_h:
            break
        size += 1
        font = test

    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    _center_text(draw, cx, cy, text, font, fill)


def _draw_progressbar(background: Image.Image, lay: dict,
                      xp_start: int | float, xp_end: int | float,
                      style_key: str):
    perc = 0.0 if xp_end <= 0 else max(0.0, min(1.0, float(xp_start) / float(xp_end)))
    if perc <= 0.0:
        return

    img_w, img_h = background.size
    geom_key = _geom_key(img_w, img_h, style_key)
    geom = PB_GEOM[geom_key]

    x0, x1 = geom["x_span"]
    y0, y1 = geom["y_full"]

    total_w = x1 - x0 + 1
    fill_w = max(1, min(int(round(total_w * perc)), total_w))
    x_fill_end = x0 + fill_w - 1

    slot_mask = _slot_mask_from_coords(img_w, img_h, geom_key)

    fill_mask = Image.new("L", (img_w, img_h), 0)
    d = ImageDraw.Draw(fill_mask)
    d.rectangle((x0, y0, x_fill_end, y1), fill=255)
    fill_mask = ImageChops.multiply(slot_mask, fill_mask)

    fill_img = Image.new("RGBA", (img_w, img_h), bar_color_for(style_key))
    background.paste(fill_img, (0, 0), fill_mask)


class LevelSystemConfigView(discord.ui.LayoutView):

    def __init__(self, bot: commands.Bot, invoker: discord.User, guild: discord.Guild):
        super().__init__(timeout=None)

        self.bot = bot
        self.invoker = invoker
        self.guild = guild

        self.help_mode = False

        self.xp_boost = False
        self.xp_multiplier = 1.0

        self.channel_type = "Last Channel"
        self.level_message = None
        self.roles: list[tuple[int, int]] = []

    # ================= LOAD =================

    async def _load(self):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                await cur.execute("SELECT xp FROM levelxp WHERE guildID=%s", (self.guild.id,))
                r = await cur.fetchone()

                if r:
                    self.xp_boost = True
                    self.xp_multiplier = float(r[0])
                else:
                    self.xp_boost = False
                    self.xp_multiplier = 1.0

                await cur.execute("SELECT type FROM levelchannel WHERE guildID=%s", (self.guild.id,))
                r = await cur.fetchone()
                self.channel_type = r[0] if r else "Last Channel"

                await cur.execute("SELECT message FROM levelmsg WHERE guildID=%s", (self.guild.id,))
                r = await cur.fetchone()
                self.level_message = r[0] if r else None

                await cur.execute("SELECT roleID, levelreq FROM levelroles WHERE guildID=%s", (self.guild.id,))
                self.roles = await cur.fetchall() or []

    async def start(self, interaction: discord.Interaction):
        await self._load()
        self._build()
        await interaction.response.send_message(view=self, ephemeral=True)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.invoker.id:
            await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Nicht dein Panel.",
                ephemeral=True
            )
            return False
        return True

    # ================= BUILD =================

    def _build(self):
        self.clear_items()

        container = discord.ui.Container(
            accent_color=discord.Colour.from_rgb(88, 101, 242).value
        )

        # ================= HEADER =================

        help_btn = discord.ui.Button(
            emoji="<:Astra_support:1141303923752325210>",
            style=discord.ButtonStyle.secondary
        )

        async def help_cb(i):
            self.help_mode = True
            await self.refresh(i)

        help_btn.callback = help_cb

        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                "# <:Astra_settings:1141303908778639490> LEVELSYSTEM CONFIG\n\n"
                "<:Astra_punkt:1141303896745201696> XP Boost & Multiplier\n"
                "<:Astra_punkt:1141303896745201696> Channel & Messages\n"
                "<:Astra_punkt:1141303896745201696> Rollen Rewards\n\n"
                "<:Astra_light_on:1141303864134467675> "
                "Zentrale Steuerung für dein Levelsystem."
            ),
            accessory=help_btn
        ))

        container.add_item(discord.ui.Separator())

        # ================= HELP =================

        if self.help_mode:
            container.add_item(discord.ui.TextDisplay(
                "## <:Astra_support:1141303923752325210> SYSTEM GUIDE\n\n"

                "### <:Astra_boost:1141303827107164270> XP SYSTEM\n"
                "<:Astra_punkt:1141303896745201696> Boost aktivieren / deaktivieren\n"
                "<:Astra_punkt:1141303896745201696> Multiplier bestimmt XP Stärke\n"
                "<:Astra_punkt:1141303896745201696> x1 = normal\n"
                "<:Astra_punkt:1141303896745201696> x2 = doppelt\n"
                "<:Astra_punkt:1141303896745201696> x3+ = insane\n\n"

                "### <:Astra_news:1141303885533827072> CHANNEL SYSTEM\n"
                "<:Astra_punkt:1141303896745201696> Last Channel → Standard\n"
                "<:Astra_punkt:1141303896745201696> Private Message → DM\n"
                "<:Astra_punkt:1141303896745201696> Deactivated → kein Output\n\n"

                "### <:Astra_messages:1141303867850641488> MESSAGE SYSTEM\n"
                "<:Astra_punkt:1141303896745201696> %member → User Ping\n"
                "<:Astra_punkt:1141303896745201696> %level → Level\n\n"

                "### <:Astra_pokal:1141825582108258334> ROLE SYSTEM\n"
                "<:Astra_punkt:1141303896745201696> Auto Rewards bei Level-Up\n"
                "<:Astra_punkt:1141303896745201696> Perfekt für Progression\n\n"

                "<:Astra_light_on:1141303864134467675> PRO TIP\n"
                "XP Boost + Rollen = maximale Aktivität 🚀"
            ))

            back = discord.ui.Button(
                label="Zurück",
                style=discord.ButtonStyle.secondary,
                emoji="<:Astra_arrow_backwards:1392540551546671348>"
            )

            async def back_cb(i):
                self.help_mode = False
                await self.refresh(i)

            back.callback = back_cb

            container.add_item(discord.ui.ActionRow(back))
            self.add_item(container)
            return

        # ================= XP =================

        xp_btn = discord.ui.Button(
            label="Deaktivieren" if self.xp_boost else "Aktivieren",
            style=discord.ButtonStyle.danger if self.xp_boost else discord.ButtonStyle.success
        )

        set_multi = discord.ui.Button(label="Multiplier setzen", style=discord.ButtonStyle.primary)
        reset_multi = discord.ui.Button(label="Reset x1", style=discord.ButtonStyle.secondary)

        async def xp_cb(i):
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    if not self.xp_boost:
                        await cur.execute(
                            "INSERT INTO levelxp(guildID,xp) VALUES(%s,%s)",
                            (self.guild.id, self.xp_multiplier)
                        )
                    else:
                        await cur.execute("DELETE FROM levelxp WHERE guildID=%s", (self.guild.id,))
            await self.refresh(i)

        async def set_multi_cb(i):

            class Modal(discord.ui.Modal, title="XP Multiplier"):

                def __init__(self, view):
                    super().__init__()
                    self.view = view

                value = discord.ui.TextInput(label="Multiplier", required=True)

                async def on_submit(self, inter):

                    raw = self.value.value.strip().replace(",", ".")

                    try:
                        val = float(raw)
                    except ValueError:
                        return await inter.response.send_message(
                            "<:Astra_x:1141303954555289600> Ungültiger Wert.",
                            ephemeral=True
                        )

                    if val <= 0:
                        return await inter.response.send_message(
                            "<:Astra_x:1141303954555289600> Multiplier muss größer als 0 sein.",
                            ephemeral=True
                        )

                    if val > 10:
                        return await inter.response.send_message(
                            "<:Astra_x:1141303954555289600> Maximal x10.",
                            ephemeral=True
                        )

                    async with self.view.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "INSERT INTO levelxp(guildID,xp) VALUES(%s,%s) "
                                "ON DUPLICATE KEY UPDATE xp=%s",
                                (self.view.guild.id, val, val)
                            )

                    await self.view.refresh(inter)
                    return None

            await i.response.send_modal(Modal(view=self))

        async def reset_cb(i):
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM levelxp WHERE guildID=%s", (self.guild.id,))
            await self.refresh(i)

        xp_btn.callback = xp_cb
        set_multi.callback = set_multi_cb
        reset_multi.callback = reset_cb

        status_emoji = (
            "<:Astra_accept:1141303821176422460>"
            if self.xp_boost else
            "<:Astra_x:1141303954555289600>"
        )

        container.add_item(discord.ui.Section(
            discord.ui.TextDisplay(
                "## <:Astra_boost:1141303827107164270> XP SYSTEM\n\n"
                f"{status_emoji} **Status:** {'Aktiv' if self.xp_boost else 'Deaktiviert'}\n"
                f"<:Astra_punkt:1141303896745201696> Multiplier: **x{self.xp_multiplier}**\n\n"
            ),
            accessory=xp_btn
        ))

        container.add_item(discord.ui.ActionRow(set_multi, reset_multi))
        container.add_item(discord.ui.Separator())

        # ================= CHANNEL =================

        channel_display = self.channel_type
        if channel_display.isdigit():
            channel_display = f"<#{channel_display}>"

        container.add_item(discord.ui.TextDisplay(
            "## <:Astra_news:1141303885533827072> CHANNEL SYSTEM\n\n"
            f"<:Astra_punkt:1141303896745201696> Aktuell: **{channel_display}**"
        ))

        mode_select = discord.ui.Select(
            placeholder=f"Aktuell: {self.channel_type}",
            options=[
                discord.SelectOption(label="Letzter Kanal", value="Last Channel"),
                discord.SelectOption(label="Private Nachricht", value="Private Message"),
                discord.SelectOption(label="Deaktiviert", value="Deactivated"),
            ]
        )

        async def mode_cb(i):
            val = mode_select.values[0]

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM levelchannel WHERE guildID=%s", (self.guild.id,))
                    await cur.execute(
                        "INSERT INTO levelchannel(guildID,type) VALUES(%s,%s)",
                        (self.guild.id, val)
                    )

            await self.refresh(i)

        mode_select.callback = mode_cb

        channel_select = discord.ui.ChannelSelect(
            channel_types=[discord.ChannelType.text],
            placeholder="Festen Kanal wählen..."
        )

        async def channel_cb(i):
            ch = channel_select.values[0]

            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM levelchannel WHERE guildID=%s", (self.guild.id,))
                    await cur.execute(
                        "INSERT INTO levelchannel(guildID,type) VALUES(%s,%s)",
                        (self.guild.id, str(ch.id))
                    )

            await self.refresh(i)

        channel_select.callback = channel_cb

        container.add_item(discord.ui.ActionRow(mode_select))
        container.add_item(discord.ui.ActionRow(channel_select))
        container.add_item(discord.ui.Separator())

        # ================= MESSAGE =================

        container.add_item(discord.ui.TextDisplay(
            "## <:Astra_messages:1141303867850641488> LEVEL MESSAGE\n\n"
            f"{self.level_message or '*Standard Nachricht aktiv*'}\n\n"
            "<:Astra_light_on:1141303864134467675> "
            "Nutze %member und %level."
        ))

        edit = discord.ui.Button(label="Bearbeiten", style=discord.ButtonStyle.primary)
        reset = discord.ui.Button(label="Reset", style=discord.ButtonStyle.secondary)

        async def edit_cb(i):

            class Modal(discord.ui.Modal, title="Level Nachricht"):

                def __init__(self, view):
                    super().__init__()
                    self.view = view  # 🔥 DAS FEHLT BEI DIR

                text = discord.ui.TextInput(
                    label="Level-Up Nachricht",
                    placeholder=(
                        "🎉 %member ist jetzt Level %level!\n"
                        "(%member = User | %level = Level)"
                    ),
                    style=discord.TextStyle.paragraph,
                    required=True,
                    max_length=2000
                )

                async def on_submit(self, inter):
                    async with self.view.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "INSERT INTO levelmsg(guildID,message) VALUES(%s,%s) "
                                "ON DUPLICATE KEY UPDATE message=%s",
                                (self.view.guild.id, self.text.value, self.text.value)
                            )

                    await self.view.refresh(inter)

            await i.response.send_modal(Modal(view=self))

        async def reset_cb(i):
            async with self.bot.pool.acquire() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("DELETE FROM levelmsg WHERE guildID=%s", (self.guild.id,))
            await self.refresh(i)

        edit.callback = edit_cb
        reset.callback = reset_cb

        container.add_item(discord.ui.ActionRow(edit, reset))
        container.add_item(discord.ui.Separator())

        # ================= ROLES =================

        role_text = (
            "\n".join(
                f"<:Astra_punkt:1141303896745201696> Level **{lvl}** → <@&{rid}>"
                for rid, lvl in self.roles
            )
            if self.roles else
            "<:Astra_x:1141303954555289600> Keine Rollen gesetzt."
        )

        container.add_item(discord.ui.TextDisplay(
            "## <:Astra_pokal:1141825582108258334> ROLE REWARDS\n\n"
            f"{role_text}"
        ))

        add = discord.ui.Button(label="Hinzufügen", style=discord.ButtonStyle.success)
        remove = discord.ui.Button(label="Entfernen", style=discord.ButtonStyle.danger)

        async def add_cb(i):

            class Modal(discord.ui.Modal, title="Neue Levelrolle"):

                def __init__(self, view):
                    super().__init__()
                    self.view = view  # 🔥 wichtig

                role = discord.ui.TextInput(label="Role ID")
                level = discord.ui.TextInput(label="Level")

                async def on_submit(self, inter):
                    # ✅ HIER REIN (GANZ OBEN!)
                    if not self.role.value.isdigit() or not self.level.value.isdigit():
                        return await inter.response.send_message(
                            "<:Astra_x:1141303954555289600> Ungültige Eingabe.",
                            ephemeral=True
                        )

                    async with self.view.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "INSERT INTO levelroles(guildID,roleID,levelreq) VALUES(%s,%s,%s)",
                                (self.view.guild.id, self.role.value, self.level.value)
                            )

                    await self.view.refresh(inter)

            await i.response.send_modal(Modal(view=self))

        async def remove_cb(i):

            class Modal(discord.ui.Modal, title="Levelrolle entfernen"):
                level = discord.ui.TextInput(label="Level")

                async def on_submit(self, inter):
                    async with self.view.bot.pool.acquire() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                "DELETE FROM levelroles WHERE guildID=%s AND levelreq=%s",
                                (self.view.guild.id, self.level.value)
                            )
                    await self.view.refresh(inter)

            await i.response.send_modal(Modal())

        add.callback = add_cb
        remove.callback = remove_cb

        container.add_item(discord.ui.ActionRow(add, remove))

        self.add_item(container)

    # ================= REFRESH =================

    async def refresh(self, interaction):
        await self._load()
        self._build()

        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)


# ──────────────────────────────────────────────────────────────────────────────
# Slash-Gruppe nur für Levelkarten
# ──────────────────────────────────────────────────────────────────────────────
@app_commands.guild_only()
class Level(app_commands.Group):
    def __init__(self, bot):
        self.bot = bot
        super().__init__(name="levelsystem", description="Alles rund ums Levelsystem.")

    async def _style_autocomplete(self, interaction: discord.Interaction, current: str):
        names = list_styles()
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    @app_commands.command(name="rank", description="Zeigt dir dein aktuelles Level")
    @app_commands.describe(user="Das Mitglied, dessen Levelkarte angezeigt werden soll (Standard: du selbst).")
    @app_commands.checks.cooldown(1, 5, key=lambda i: (i.guild_id, i.user.id))
    @app_commands.guild_only()
    async def rank(self, interaction: discord.Interaction, user: discord.User | None = None):
        user = user or interaction.user

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT enabled FROM levelsystem WHERE guild_id=%s", (interaction.guild.id,))
                enabled = await cur.fetchone()
                if not enabled or enabled[0] == 0:
                    return await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Das Levelsystem ist auf diesem Server deaktiviert.**",
                        ephemeral=True
                    )

                await cur.execute(
                    "SELECT user_xp, user_level FROM levelsystem WHERE client_id=%s AND guild_id=%s",
                    (user.id, interaction.guild.id)
                )
                row = await cur.fetchone()
                if not row:
                    return await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Keine Einträge für diesen User gefunden.**",
                        ephemeral=True
                    )
                xp_start, lvl_start = row
                xp_end = 5.5 * (lvl_start ** 2) + 30 * lvl_start

                await cur.execute(
                    "SELECT style FROM levelstyle WHERE guild_id=%s AND client_id=%s",
                    (interaction.guild.id, user.id)
                )
                srow = await cur.fetchone()
                style_name = srow[0] if srow else DEFAULT_STYLE
                bg_path = style_to_path(style_name)

                await cur.execute(
                    "SELECT client_id FROM levelsystem WHERE guild_id=%s ORDER BY user_level DESC, user_xp DESC",
                    (interaction.guild.id,)
                )
                rows = await cur.fetchall()
                rank_pos = 0
                if rows:
                    for i, r in enumerate(rows, start=1):
                        if int(r[0]) == user.id:
                            rank_pos = i
                            break

        await interaction.response.defer(thinking=True)

        # Render
        background = Image.open(bg_path).convert("RGBA")
        draw = ImageDraw.Draw(background)
        img_w, img_h = background.size
        lay = _resolved_layout(style_name, img_w, img_h)

        # Avatar
        av = lay["avatar"]
        av_size = av["size"]
        av_x, av_y = av["x"], av["y"]

        avatar_asset = user.display_avatar.replace(size=256)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size))

        inset = av.get("inset", 0)
        if av.get("draw_ring", False):
            ring_w = av.get("ring_width", 10)
            ImageDraw.Draw(background).ellipse((av_x, av_y, av_x + av_size, av_y + av_size), outline="white",
                                               width=ring_w)
            inset = max(inset, ring_w)

        inner_d = (av_size - 2 * inset, av_size - 2 * inset)
        mask = Image.new("L", inner_d, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, inner_d[0], inner_d[1]), fill=255)
        avatar_cropped = avatar_img.resize(inner_d)
        background.paste(avatar_cropped, (av_x + inset, av_y + inset), mask)

        # Rang
        font_rank = _mk_font(lay["rank"]["font"])
        rx, ry = lay["rank"]["x"], lay["rank"]["y"]
        draw.text((rx, ry), f"#{rank_pos}", font=font_rank, fill="white")

        # Name exakt in Name-Box
        name_box = lay["name_box"]
        _draw_centered_in_box(draw, str(user.display_name), name_box,
                              name_box["base_font"], name_box["min_font"], fill="white")

        # Level & XP — exakt zentriert, maximal groß
        level_box = lay["level_box"]
        xp_box = lay["xp_box"]
        _draw_centered_in_box(draw, f"{lvl_start}", level_box,
                              level_box["base_font"], level_box["min_font"], fill="white")
        _draw_centered_in_box(draw, f"{xp_start}/{round(xp_end)}", xp_box,
                              xp_box["base_font"], xp_box["min_font"], fill="white")

        # Progressbar
        _draw_progressbar(background, lay, xp_start, xp_end, style_name)

        buf = BytesIO()
        background.save(buf, "PNG")
        buf.seek(0)
        await interaction.followup.send(file=File(buf, filename=f"rank_{style_name}.png"))
        return None

    @app_commands.command(name="setstyle", description="Wähle deine Rank-Card.")
    @app_commands.describe(style="Name des Stils, der für deine Levelkarte verwendet werden soll.")
    @app_commands.guild_only()
    async def setstyle(self, interaction: discord.Interaction, style: Literal[PRETTY_CHOICES]):

        internal_style = PRETTY_TO_FILENAME[style]
        available = set(list_styles())
        if internal_style not in available:
            return await interaction.response.send_message(
                f"❌ Der Style **{style}** ist (noch) nicht verfügbar.", ephemeral=True
            )

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO levelstyle (guild_id, client_id, style)
                        VALUES (%s, %s, %s) AS new
                    ON DUPLICATE KEY UPDATE style = new.style
                    """,
                    (interaction.guild.id, interaction.user.id, internal_style)
                )

        await interaction.response.send_message(f"✅ Style auf **{style}** gesetzt.", ephemeral=True)
        return None

    @app_commands.command(name="previewstyle",
                          description="Vorschau deiner Levelkarte anzeigen, ohne sie zu speichern.")
    @app_commands.describe(style="Name des Stils, der für die Vorschau verwendet werden soll.")
    @app_commands.guild_only()
    async def previewstyle(self, interaction: discord.Interaction, style: Literal[PRETTY_CHOICES]):

        internal_style = PRETTY_TO_FILENAME[style]
        if internal_style not in set(list_styles()):
            return await interaction.response.send_message(
                f"❌ Der Style **{style}** ist (noch) nicht verfügbar.", ephemeral=True
            )

        await interaction.response.defer(thinking=True, ephemeral=True)
        bg_path = style_to_path(internal_style)

        # Daten holen
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_xp, user_level FROM levelsystem WHERE client_id=%s AND guild_id=%s",
                    (interaction.user.id, interaction.guild.id)
                )
                row = await cur.fetchone()
                xp_start, lvl_start = row if row else (0, 0)
                xp_end = 5.5 * (lvl_start ** 2) + 30 * lvl_start

                await cur.execute(
                    "SELECT client_id FROM levelsystem WHERE guild_id=%s ORDER BY user_level DESC, user_xp DESC",
                    (interaction.guild.id,)
                )
                rows = await cur.fetchall()
                rank_pos = 0
                if rows:
                    for i, r in enumerate(rows, start=1):
                        if int(r[0]) == interaction.user.id:
                            rank_pos = i
                            break

        # Render
        background = Image.open(bg_path).convert("RGBA")
        draw = ImageDraw.Draw(background)
        img_w, img_h = background.size
        lay = _resolved_layout(internal_style, img_w, img_h)

        # Avatar
        av = lay["avatar"]
        av_size = av["size"]
        av_x, av_y = av["x"], av["y"]

        avatar_asset = interaction.user.display_avatar.replace(size=256)
        avatar_bytes = await avatar_asset.read()
        avatar_img = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((av_size, av_size))

        inset = av.get("inset", 0)
        if av.get("draw_ring", False):
            ring_w = av.get("ring_width", 10)
            ImageDraw.Draw(background).ellipse((av_x, av_y, av_x + av_size, av_y + av_size), outline="white",
                                               width=ring_w)
            inset = max(inset, ring_w)

        inner_d = (av_size - 2 * inset, av_size - 2 * inset)
        mask = Image.new("L", inner_d, 0)
        ImageDraw.Draw(mask).ellipse((0, 0, inner_d[0], inner_d[1]), fill=255)
        avatar_cropped = avatar_img.resize(inner_d)
        background.paste(avatar_cropped, (av_x + inset, av_y + inset), mask)

        # Rang
        font_rank = _mk_font(lay["rank"]["font"])
        rx, ry = lay["rank"]["x"], lay["rank"]["y"]
        draw.text((rx, ry), f"#{rank_pos or '—'}", font=font_rank, fill="white")

        # Name in Name-Box
        name_box = lay["name_box"]
        _draw_centered_in_box(draw, str(interaction.user.display_name), name_box,
                              name_box["base_font"], name_box["min_font"], fill="white")

        # Level & XP – exakt zentriert
        level_box = lay["level_box"]
        xp_box = lay["xp_box"]
        _draw_centered_in_box(draw, f"{lvl_start}", level_box,
                              level_box["base_font"], level_box["min_font"], fill="white")
        _draw_centered_in_box(draw, f"{xp_start}/{round(xp_end)}", xp_box,
                              xp_box["base_font"], xp_box["min_font"], fill="white")

        # Progressbar
        _draw_progressbar(background, lay, xp_start, xp_end, internal_style)

        buf = BytesIO()
        background.save(buf, "PNG")
        buf.seek(0)
        await interaction.followup.send(
            content=f"**Preview:** {style}",
            file=File(buf, filename=f"preview_{internal_style}.png"),
            ephemeral=True
        )
        return None

    @app_commands.command(name="status", description="Aktiviere oder deaktiviere das Levelsystem.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction, arg: Literal['Einschalten', 'Ausschalten']):

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:

                # 👉 CHECK EXISTENCE
                await cur.execute(
                    "SELECT enabled FROM levelsystem WHERE guild_id = %s",
                    (interaction.guild.id,)
                )
                row = await cur.fetchone()

                # 👉 AUTO CREATE SYSTEM
                if not row:
                    await cur.execute(
                        "INSERT INTO levelsystem (client_id, user_xp, user_level, guild_id, enabled) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (interaction.user.id, 0, 0, interaction.guild.id, 1 if arg == "Einschalten" else 0)
                    )

                    return await interaction.response.send_message(
                        f"<:Astra_accept:1141303821176422460> **Levelsystem wurde erstellt und {'aktiviert' if arg == 'Einschalten' else 'deaktiviert'}.**"
                    )

                enabled = row[0]

                # 👉 NORMAL LOGIC
                if arg == "Einschalten":
                    if enabled == 1:
                        return await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Bereits aktiviert.",
                            ephemeral=True
                        )

                    await cur.execute(
                        "UPDATE levelsystem SET enabled = 1 WHERE guild_id = %s",
                        (interaction.guild.id,)
                    )

                    return await interaction.response.send_message(
                        "<:Astra_accept:1141303821176422460> Levelsystem aktiviert."
                    )

                if arg == "Ausschalten":
                    if enabled == 0:
                        return await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> Bereits deaktiviert.",
                            ephemeral=True
                        )

                    await cur.execute(
                        "UPDATE levelsystem SET enabled = 0 WHERE guild_id = %s",
                        (interaction.guild.id,)
                    )

                    return await interaction.response.send_message(
                        "<:Astra_accept:1141303821176422460> Levelsystem deaktiviert."
                    )
                return None

    @app_commands.command(name="leaderboard", description="Zeigt das Top 10 Level und XP Leaderboard an.")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction):
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT client_id, user_level, user_xp FROM levelsystem WHERE guild_id = %s ORDER BY user_level DESC, user_xp DESC LIMIT 10",
                    (interaction.guild.id,)
                )
                top10 = await cur.fetchall()

        if not top10:
            return await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> Es wurden keine Daten für dieses Server-Leaderboard gefunden.",
                ephemeral=True
            )

        embed = discord.Embed(
            title=f"Top 10 Level Leaderboard für {interaction.guild.name}",
            color=discord.Color.blue()
        )

        description = ""
        place = 1
        for user_id, level, xp in top10:
            user = interaction.guild.get_member(user_id)
            name = user.display_name if user else f"User ID: {user_id}"
            description += f"**#{place}**: {name} — Level {level} ({xp} XP)\n"
            place += 1

        embed.description = description
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="config", description="Öffne das Levelsystem Control Panel.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config(self, interaction: discord.Interaction):

        # Check ob System existiert
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT enabled FROM levelsystem WHERE guild_id=%s",
                    (interaction.guild.id,)
                )
                enabled = await cur.fetchone()

        if not enabled:
            return await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> **Levelsystem wurde noch nicht initialisiert.**",
                ephemeral=True
            )

        # View starten
        view = LevelSystemConfigView(
            bot=self.bot,
            invoker=interaction.user,
            guild=interaction.guild
        )

        await view.start(interaction)


class levelsystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.cd_mapping = commands.CooldownMapping.from_cooldown(1, 3, commands.BucketType.guild)

    @commands.Cog.listener()
    async def on_message(self, msg):
        if not msg.guild:
            return
        if msg.author.bot:
            return

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # Cooldown pro Guild
                bucket = self.cd_mapping.get_bucket(msg)
                retry_after = bucket.update_rate_limit()
                if retry_after:
                    return

                # Datensatz laden/erstellen
                await cur.execute(
                    "SELECT user_xp, user_level FROM levelsystem WHERE client_id = (%s) AND guild_id = (%s)",
                    (msg.author.id, msg.guild.id)
                )
                rows = await cur.fetchall()

                await cur.execute("SELECT enabled FROM levelsystem WHERE guild_id = (%s)", (msg.guild.id,))
                enabled = await cur.fetchone()

                if len(rows) == 0:
                    # Ersteintrag (System-Flag bleibt 0 = deaktiviert bis /status einschaltet)
                    await cur.execute(
                        "INSERT INTO levelsystem (client_id, user_xp, user_level, guild_id, enabled) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (msg.author.id, 2, 0, msg.guild.id, 0)
                    )
                    return

                if enabled[0] == 0:
                    return

                # --- Aktuelle Werte
                xp_start = int(rows[0][0])
                lvl_start = int(rows[0][1])

                # XP bis Levelende (deine Formel)
                xp_end = 5.5 * (lvl_start ** 2) + 30 * lvl_start

                # XP-Boost prüfen
                await cur.execute("SELECT xp FROM levelxp WHERE guildID = %s", (msg.guild.id,))
                xpres = await cur.fetchone()

                multiplier = float(xpres[0]) if xpres else 1.0

                gain = int(random.randint(1, 5) * multiplier)

                # ------------------------------
                # HARD CAP & EARLY RETURN (Lvl 100)
                # ------------------------------
                if lvl_start >= 100:
                    # Wenn schon voll -> direkt raus
                    if xp_start >= 58000:
                        return

                    # Anheben, aber bei 58k deckeln
                    new_total = min(58000, xp_start + gain)
                    await cur.execute(
                        "UPDATE levelsystem SET user_xp = (%s) WHERE client_id = (%s) AND guild_id = (%s)",
                        (new_total, msg.author.id, msg.guild.id)
                    )
                    return

                # ------------------------------
                # Normale Logik für Level < 100
                # ------------------------------
                new_total = xp_start + gain

                # Nur XP erhöhen, falls unter Schwelle
                if new_total < xp_end:
                    await cur.execute(
                        "UPDATE levelsystem SET user_xp = (%s) WHERE client_id = (%s) AND guild_id = (%s)",
                        (new_total, msg.author.id, msg.guild.id)
                    )
                    return

                # --- Level-Up ---
                await cur.execute(
                    "UPDATE levelsystem SET user_level = (%s) WHERE client_id = (%s) AND guild_id = (%s)",
                    (lvl_start + 1, msg.author.id, msg.guild.id)
                )
                # Nach Level-Up startest du bei 1 XP (wie zuvor)
                await cur.execute(
                    "UPDATE levelsystem SET user_xp = (%s) WHERE client_id = (%s) AND guild_id = (%s)",
                    (1, msg.author.id, msg.guild.id)
                )

                # --- CommunityGoal: Levelup-Progress inkrementieren ---
                cog = self.bot.get_cog("CommunityGoalsCog")
                if cog:
                    await cog.count_levelup(msg.guild.id)

                # ------------------------------
                # Dein bestehender Benachrichtigungs-/Rollen-Code
                # (unverändert übernommen)
                # ------------------------------
                await cur.execute("SELECT type FROM levelchannel WHERE guildID = (%s)", (msg.guild.id,))
                result6 = await cur.fetchone()

                if not result6:
                    await cur.execute("SELECT message FROM levelmsg WHERE guildID = (%s)", (msg.guild.id))
                    messageres = await cur.fetchone()
                    if messageres is None:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result8 = await cur.fetchone()
                        if result8:
                            roleid = result8[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                            embed = discord.Embed(
                                title="Level-UP",
                                description=f"Weiter so {msg.author.mention}! Du hast Level {int(lvl_start) + 1} erreicht",
                                color=discord.Color.green()
                            )
                            await msg.channel.send(msg.author.mention, embed=embed)
                        if not result8:
                            embed = discord.Embed(
                                title="Level-UP",
                                description=f"Weiter so {msg.author.mention}! Du hast Level {int(lvl_start) + 1} erreicht",
                                color=discord.Color.green()
                            )
                            await msg.channel.send(msg.author.mention, embed=embed)
                    else:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result5 = await cur.fetchone()
                        lvl = int(lvl_start + 1)
                        finalmsg = messageres[0].replace("%member", str(msg.author.mention)).replace("%level", str(lvl))
                        if result5:
                            roleid = result5[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                            embed = discord.Embed(title="Level-UP", description=finalmsg, color=discord.Color.green())
                            await msg.channel.send(msg.author.mention, embed=embed)
                        if not result5:
                            embed = discord.Embed(title="Level-UP", description=finalmsg, color=discord.Color.green())
                            await msg.channel.send(msg.author.mention, embed=embed)
                    return

                if result6[0] == "Private Message":
                    await cur.execute("SELECT message FROM levelmsg WHERE guildID = (%s)", (msg.guild.id))
                    messageres = await cur.fetchone()
                    if messageres is None:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result11 = await cur.fetchone()
                        if result11:
                            roleid = result11[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(
                            title="Level-UP",
                            description=f"Weiter so {msg.author.mention}! Du hast Level {int(lvl_start) + 1} erreicht",
                            color=discord.Color.green()
                        )
                        await msg.author.send(msg.author.mention, embed=embed)
                    else:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result10 = await cur.fetchone()
                        lvl = int(lvl_start + 1)
                        finalmsg = messageres[0].replace("%member", str(msg.author.mention)).replace("%level", str(lvl))
                        if result10:
                            roleid = result10[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(title="Level-UP", description=finalmsg, color=discord.Color.green())
                        await msg.author.send(msg.author.mention, embed=embed)
                    return

                if result6[0] == "Deactivated":
                    await cur.execute(
                        "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                        (msg.guild.id, int(lvl_start) + 1)
                    )
                    result12 = await cur.fetchone()
                    if result12:
                        roleid = result12[0]
                        role = msg.guild.get_role(roleid)
                        member = msg.author
                        if role not in member.roles:
                            await member.add_roles(role)
                    return

                if result6[0] == "Last Channel":
                    await cur.execute("SELECT message FROM levelmsg WHERE guildID = (%s)", (msg.guild.id))
                    messageres = await cur.fetchone()
                    if messageres is None:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result15 = await cur.fetchone()
                        if result15:
                            roleid = result15[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(
                            title="Level-UP",
                            description=f"Weiter so {msg.author.mention}! Du hast Level {int(lvl_start) + 1} erreicht",
                            color=discord.Color.green()
                        )
                        await msg.channel.send(msg.author.mention, embed=embed)
                    else:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result14 = await cur.fetchone()
                        lvl = int(lvl_start + 1)
                        finalmsg = messageres[0].replace("%member", str(msg.author.mention)).replace("%level", str(lvl))
                        if result14 is not None:
                            roleid = result14[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(title="Level-UP", description=finalmsg, color=discord.Color.green())
                        await msg.channel.send(msg.author.mention, embed=embed)
                    return

                if result6[0].isnumeric():
                    await cur.execute("SELECT message FROM levelmsg WHERE guildID = (%s)", (msg.guild.id))
                    messageres = await cur.fetchone()

                    channel = self.bot.get_channel(int(result6[0]))
                    if messageres is None:
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result9 = await cur.fetchone()
                        if result9:
                            roleid = result9[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(
                            title="Level-UP",
                            description=f"Weiter so {msg.author.mention}! Du hast Level {int(lvl_start) + 1} erreicht.",
                            color=discord.Color.green()
                        )
                        try:
                            await channel.send(msg.author.mention, embed=embed)
                        except:
                            pass
                    else:
                        lvl = int(lvl_start + 1)
                        finalmsg = messageres[0].replace("%member", str(msg.author.mention)).replace("%level", str(lvl))
                        await cur.execute(
                            "SELECT roleID FROM levelroles WHERE guildID = (%s) and levelreq = (%s)",
                            (msg.guild.id, int(lvl_start) + 1)
                        )
                        result5 = await cur.fetchone()
                        if result5:
                            roleid = result5[0]
                            role = msg.guild.get_role(roleid)
                            member = msg.author
                            if role not in member.roles:
                                await member.add_roles(role)
                        embed = discord.Embed(title="Level-UP", description=finalmsg, color=discord.Color.green())
                        await channel.send(msg.author.mention, embed=embed)
                    return

    @app_commands.command(name="setlevel", description="Setze das Level eines Mitglieds auf deinem Server.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelsystem_setlevel(self, interaction: discord.Interaction, member: discord.Member, level: int):
        """Set the level from a user on your server."""
        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                if level > 100:
                    await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Das Level kann icht höher als 100 sein.**",
                        ephemeral=True)
                if level <= 100:
                    await cur.execute(f"SELECT enabled FROM levelsystem WHERE guild_id = (%s)",
                                      (interaction.guild.id))
                    enabled = await cur.fetchone()
                    if enabled[0] == 0:
                        await interaction.response.send_message(
                            "<:Astra_x:1141303954555289600> **Das Levelsystem ist auf diesem Server bereits deaktiviert.**",
                            ephemeral=True)
                    if enabled[0] == 1:
                        await cur.execute(
                            f"SELECT user_xp, user_level FROM levelsystem WHERE client_id = (%s) AND guild_id = (%s)",
                            (member.id, interaction.guild.id))
                        result = await cur.fetchall()
                        if not result:
                            await interaction.response.send_message(
                                "<:Astra_x:1141303954555289600> **Keine Einträge für diesen User gefunden.**",
                                ephemeral=True)
                        if result:
                            await cur.execute(
                                "UPDATE levelsystem SET user_level = (%s) WHERE guild_id = (%s) and client_id = (%s)",
                                (level, interaction.guild.id, member.id))
                            await cur.execute(
                                "UPDATE levelsystem SET user_xp = (%s) WHERE guild_id = (%s) and client_id = (%s) and user_level = (%s)",
                                (0 + 1, interaction.guild.id, member.id, level))
                            await interaction.response.send_message(
                                f"<:Astra_accept:1141303821176422460> **Der User {member.mention} wurde auf Level `{level}` gesetzt.**")

    @app_commands.command(name="setxp", description="Setze die XP eines Mitglieds innerhalb seines aktuellen Levels.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def levelsystem_setxp(self, interaction: discord.Interaction, member: discord.Member, xp: int):
        """Setzt die XP eines Users innerhalb seines aktuellen Levels."""
        # Negatives/Null sofort abfangen
        if xp < 1:
            return await interaction.response.send_message(
                "<:Astra_x:1141303954555289600> **XP muss mindestens 1 sein.**",
                ephemeral=True
            )

        async with self.bot.pool.acquire() as conn:
            async with conn.cursor() as cur:
                # System aktiv?
                await cur.execute("SELECT enabled FROM levelsystem WHERE guild_id = (%s)", (interaction.guild.id,))
                enabled = await cur.fetchone()
                if not enabled or enabled[0] == 0:
                    return await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Das Levelsystem ist auf diesem Server deaktiviert.**",
                        ephemeral=True
                    )

                # User-Datensatz laden
                await cur.execute(
                    "SELECT user_xp, user_level FROM levelsystem WHERE client_id = (%s) AND guild_id = (%s)",
                    (member.id, interaction.guild.id)
                )
                row = await cur.fetchone()
                if not row:
                    return await interaction.response.send_message(
                        "<:Astra_x:1141303954555289600> **Keine Einträge für diesen User gefunden.**",
                        ephemeral=True
                    )

                current_level = int(row[1])

                # Ziel-XP-Grenzen ermitteln (gleiches Modell wie überall)
                xp_end = 5.5 * (current_level ** 2) + 30 * current_level

                # Hard Cap wie in deinem Level-Up-Code
                if current_level >= 100 or xp_end >= 58000.0:
                    xp_end = 58000.0

                # Clamp: mindestens 1, höchstens xp_end-1 (damit kein sofortiger Level-Up erzwungen wird)
                max_xp_in_level = max(1, int(xp_end) - 1)
                new_xp = max(1, min(int(xp), max_xp_in_level))

                await cur.execute(
                    "UPDATE levelsystem SET user_xp = (%s) WHERE client_id = (%s) AND guild_id = (%s)",
                    (new_xp, member.id, interaction.guild.id)
                )

        await interaction.response.send_message(
            f"<:Astra_accept:1141303821176422460> **XP von {member.mention} auf `{new_xp}` gesetzt (Level `{current_level}`, Ziel `{int(xp_end)}`).**"
        )
        return None


async def setup(bot):
    await bot.add_cog(levelsystem(bot))
    bot.tree.add_command(Level(bot))
