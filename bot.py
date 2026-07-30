"""
Who Dis? — Discord bot

Slash commands:
  /whodis-rules                                             Learn how to play (skip anytime)
  /whodis-start points:<3|5|7|10>                            Create a lobby in this channel
  /whodis-join                                              Join the open lobby
  /whodis-leave                                              Leave the lobby (before start)
  /whodis-begin                                              Deal hands and start the game
  /submit                                                    (Ephemeral) pick your Reply card
  /vote                                                      (Ephemeral, Judge only) pick the winning Reply
  /whodis-scores                                              Show the current scoreboard
  /whodis-end                                                Cancel/end the game in this channel

The lobby also has a "How to Play" button (optional — just skip it and hit
Join Game if you already know the rules).

One game runs per channel at a time, stored in memory (state resets on bot restart).
"""
import os
import random
from pathlib import Path
from typing import Dict, Optional

import discord
from discord import app_commands
from discord.ext import commands

from game import WhoDisGame, GameError
import card_images as ci

SOUNDS = Path(__file__).parent / "assets" / "sounds"
SOUND_NEW_ROUND = SOUNDS / "new_round.wav"
SOUND_SUBMIT = SOUNDS / "submit.wav"
SOUND_ROUND_WIN = SOUNDS / "round_win.wav"
SOUND_GAME_WIN = SOUNDS / "game_win.wav"

INTENTS = discord.Intents.default()

# Solo test mode: password-gated so randos can't spin up throwaway games.
# Gate is a modal (private input), never a visible slash-command argument,
# since Discord shows "User used /command option:value" publicly even when
# the bot's own reply is ephemeral.
TEST_MODE_PASSWORD = "D3RcMbh#"
TEST_BOT_PLAYERS = [(-1, "Test Bot Ava"), (-2, "Test Bot Ben")]

# Requested palette: red / dark green / yellow
COLOR_RED = discord.Color(0xA40607)
COLOR_GREEN = discord.Color(0x07504E)
COLOR_YELLOW = discord.Color(0xFEC103)

RULES_TEXT = (
    "**Goal:** Make the funniest text-message reply and score points. First to the target score wins.\n\n"
    "**Each round:**\n"
    "1️⃣ The Judge draws an **Inbox** card and reads the message aloud.\n"
    "2️⃣ Everyone else secretly picks their funniest **Reply** card with `/submit`.\n"
    "3️⃣ Once all replies are in, the Judge reviews them anonymously with `/vote` and "
    "picks a winner.\n"
    "4️⃣ The winner scores a point, hands refill back to 7 cards, and the Judge role "
    "moves to the next player.\n\n"
    "**Notes:** 3–20 players (best with 4–8). The Judge doesn't submit a reply that round."
)

bot = commands.Bot(command_prefix="!whodis-unused!", intents=INTENTS)

# channel_id -> WhoDisGame
games: Dict[int, WhoDisGame] = {}

# channel_id -> the current round's announcement message (edited live to show
# submission progress)
round_messages: Dict[int, discord.Message] = {}


def get_game(channel_id: int) -> Optional[WhoDisGame]:
    return games.get(channel_id)


# ---------------------------------------------------------------------------
# Voice sound effects
#
# Entirely optional/automatic: the bot joins whichever voice channel the host
# is in when the game starts, and leaves when it ends. If the host isn't in
# voice, or the bot lacks Connect/Speak permission there, every function here
# just no-ops -- sound is a bonus, never a requirement, and can never break
# the actual game.
# ---------------------------------------------------------------------------

async def connect_voice_if_possible(interaction: discord.Interaction) -> None:
    voice_state = interaction.user.voice
    if voice_state is None or voice_state.channel is None:
        return
    if interaction.guild is None or interaction.guild.voice_client is not None:
        return
    try:
        await voice_state.channel.connect()
    except (discord.ClientException, discord.Forbidden, discord.HTTPException):
        pass


async def disconnect_voice(guild: Optional[discord.Guild]) -> None:
    if guild is not None and guild.voice_client is not None:
        try:
            await guild.voice_client.disconnect(force=True)
        except discord.HTTPException:
            pass


async def play_sound(guild: Optional[discord.Guild], path: Path) -> None:
    if guild is None or guild.voice_client is None:
        return
    vc = guild.voice_client
    if vc.is_playing():
        return  # skip rather than interrupt whatever's already playing
    try:
        vc.play(discord.FFmpegPCMAudio(str(path)))
    except Exception:
        pass  # never let a playback failure break the game


# ---------------------------------------------------------------------------
# UI Components
# ---------------------------------------------------------------------------

class SubmitButton(discord.ui.Button):
    """One numbered button per hand card, mirroring the numbered image grid
    shown above it -- one tap instead of opening a dropdown and choosing."""
    def __init__(self, game: WhoDisGame, card: dict, index: int):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.primary, row=index // 5)
        self.game = game
        self.card = card

    async def callback(self, interaction: discord.Interaction):
        game = get_game(interaction.channel_id)
        if game is None or game is not self.game:
            await interaction.response.edit_message(content="This game has ended.", view=None)
            return
        try:
            game.submit_reply(interaction.user.id, self.card["id"])
        except GameError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)
            return

        await interaction.response.edit_message(
            content="✅ Reply submitted! Waiting on the rest of the group…", view=None
        )

        await play_sound(interaction.guild, SOUND_SUBMIT)
        await update_submission_progress(interaction.channel, game)
        await auto_advance(interaction.channel, game)


class SubmitView(discord.ui.View):
    def __init__(self, game: WhoDisGame, player_hand):
        super().__init__(timeout=300)
        for i, card in enumerate(player_hand):
            self.add_item(SubmitButton(game, card, i))


class VoteButton(discord.ui.Button):
    """One numbered button per anonymized reply, mirroring the numbered image
    grid shown above it."""
    def __init__(self, game: WhoDisGame, submission, index: int):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.success, row=index // 5)
        self.game = game
        self.submission = submission

    async def callback(self, interaction: discord.Interaction):
        game = get_game(interaction.channel_id)
        if game is None or game is not self.game:
            await interaction.response.edit_message(content="This game has ended.", view=None)
            return
        try:
            result = game.judge_pick(interaction.user.id, self.submission.card["id"])
        except GameError as e:
            await interaction.response.edit_message(content=f"⚠️ {e}", view=None)
            return

        await interaction.response.edit_message(content="✅ Winner locked in!", view=None)
        await announce_round_result(interaction.channel, game, result)
        await auto_advance(interaction.channel, game)


class VoteView(discord.ui.View):
    def __init__(self, game: WhoDisGame, submissions):
        super().__init__(timeout=300)
        for i, sub in enumerate(submissions):
            self.add_item(VoteButton(game, sub, i))


def lobby_embed(game: WhoDisGame) -> discord.Embed:
    names = ", ".join(p.name for p in game.players.values())
    embed = discord.Embed(
        title="📱 Who Dis? — lobby open",
        description=(
            f"Playing to **{game.points_to_win}** points\n"
            f"Players ({game.player_count()}): {names}\n\n"
            f"Tap **Join Game** to join, then the host runs `/whodis-begin` (need 3+ players)."
        ),
        color=COLOR_GREEN,
    )
    embed.set_thumbnail(url="attachment://back.png")
    return embed


class RulesView(discord.ui.View):
    """A standalone view so /whodis-rules also gets a Skip-style dismiss button."""
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Got it, skip", style=discord.ButtonStyle.secondary, emoji="👍")
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Have fun! 🎉", embed=None, view=None)


def rules_embed() -> discord.Embed:
    embed = discord.Embed(title="📖 How to Play — Who Dis?", description=RULES_TEXT, color=COLOR_GREEN)
    embed.set_thumbnail(url="attachment://back.png")
    return embed


class JoinView(discord.ui.View):
    def __init__(self, game: WhoDisGame):
        super().__init__(timeout=600)
        self.game = game

    @discord.ui.button(label="Join Game", style=discord.ButtonStyle.success, emoji="📱")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = get_game(interaction.channel_id)
        if game is None or game is not self.game:
            await interaction.response.send_message("This lobby has closed.", ephemeral=True)
            return
        try:
            game.add_player(interaction.user.id, interaction.user.display_name)
        except GameError as e:
            await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
            return

        await interaction.response.edit_message(embed=lobby_embed(game), view=self)

    @discord.ui.button(label="How to Play", style=discord.ButtonStyle.secondary, emoji="📖")
    async def how_to_play(self, interaction: discord.Interaction, button: discord.ui.Button):
        file = discord.File(ci.back_card_path(), filename="back.png")
        await interaction.response.send_message(embed=rules_embed(), file=file, ephemeral=True)


# ---------------------------------------------------------------------------
# Announcement helpers
# ---------------------------------------------------------------------------

async def announce_submissions_ready(channel: discord.abc.Messageable, game: WhoDisGame):
    judge = game.players[game.current_judge_id()]
    await channel.send(
        f"📨 All replies are in! <@{judge.user_id}>, use **/vote** to read them and pick a winner."
    )


async def announce_round_result(channel: discord.abc.Messageable, game: WhoDisGame, result: dict):
    inbox = result["inbox"]
    composite = ci.make_round_result_image(
        ci.inbox_card_path(inbox["id"]), ci.reply_card_path(result["winning_card"]["id"])
    )
    file = discord.File(ci.image_to_file_bytes(composite), filename="result.png")
    embed = discord.Embed(
        title=f"Round {result['round_number']} winner",
        description=f"🏆 **{result['winner_name']}** won with that reply!",
        color=COLOR_YELLOW,
    )
    embed.set_image(url="attachment://result.png")
    embed.set_footer(text=f"{result['winner_name']} now has {result['winner_score']} point(s).")
    result_msg = await channel.send(embed=embed, file=file)
    try:
        await result_msg.add_reaction("🏆")
    except discord.HTTPException:
        pass

    if game.phase == WhoDisGame.PHASE_FINISHED:
        await play_sound(getattr(channel, "guild", None), SOUND_GAME_WIN)
        board = "\n".join(f"**{p.score}** — {p.name}" for p in game.scoreboard())
        await channel.send(
            f"🎉 **{result['winner_name']} wins the game!** 🎉\n\n**Final scores:**\n{board}"
        )
        games.pop(channel.id, None)
        round_messages.pop(channel.id, None)
        await disconnect_voice(getattr(channel, "guild", None))
        return

    await play_sound(getattr(channel, "guild", None), SOUND_ROUND_WIN)
    await announce_new_round(channel, game)


def _round_footer_text(game: WhoDisGame, judge_name: str) -> str:
    submitted = len(game.submissions)
    total = len(game.non_judge_players())
    return f"Judge: {judge_name} • {submitted}/{total} submitted"


async def announce_new_round(channel: discord.abc.Messageable, game: WhoDisGame):
    judge = game.players[game.current_judge_id()]
    judge_mention = f"<@{judge.user_id}>" if not judge.is_bot else f"**{judge.name}**"
    inbox = game.current_inbox
    file = discord.File(ci.inbox_card_path(inbox["id"]), filename="inbox.png")
    embed = discord.Embed(
        title=f"Round {game.round_number} — Incoming message",
        color=COLOR_RED,
    )
    embed.set_image(url="attachment://inbox.png")
    embed.set_footer(text=_round_footer_text(game, judge.name))
    msg = await channel.send(
        content=f"Everyone except {judge_mention} (this round's Judge): use **/submit** to play your reply!",
        embed=embed,
        file=file,
    )
    round_messages[channel.id] = msg
    await play_sound(getattr(channel, "guild", None), SOUND_NEW_ROUND)


async def update_submission_progress(channel: discord.abc.Messageable, game: WhoDisGame):
    """Live-edits the round announcement to show X/Y submitted as replies come in."""
    msg = round_messages.get(channel.id)
    if msg is None or not msg.embeds:
        return
    judge = game.players[game.current_judge_id()]
    embed = msg.embeds[0]
    embed.set_footer(text=_round_footer_text(game, judge.name))
    try:
        await msg.edit(embed=embed)
    except discord.HTTPException:
        pass


async def auto_advance(channel: discord.abc.Messageable, game: WhoDisGame):
    """Solo test-mode helper: fast-forwards through any bot-controlled turns
    (auto-submitting replies, auto-judging) until a real player needs to act,
    or the game ends. A no-op in games with no bot players."""
    while True:
        if game.phase == WhoDisGame.PHASE_COLLECTING:
            judge_id = game.current_judge_id()
            for uid, p in list(game.players.items()):
                if p.is_bot and uid != judge_id and uid not in game.submissions:
                    card = random.choice(p.hand)
                    game.submit_reply(uid, card["id"])
            if not game.all_submitted():
                return
            if game.players[judge_id].is_bot:
                continue
            await announce_submissions_ready(channel, game)
            return
        elif game.phase == WhoDisGame.PHASE_JUDGING:
            judge_id = game.current_judge_id()
            if not game.players[judge_id].is_bot:
                return
            winning_sub = random.choice(list(game.submissions.values()))
            result = game.judge_pick(judge_id, winning_sub.card["id"])
            await announce_round_result(channel, game, result)
            if game.phase == WhoDisGame.PHASE_FINISHED:
                return
            continue
        else:
            return


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="whodis-rules", description="Learn how to play Who Dis? (skip anytime)")
async def whodis_rules(interaction: discord.Interaction):
    file = discord.File(ci.back_card_path(), filename="back.png")
    await interaction.response.send_message(embed=rules_embed(), file=file, view=RulesView(), ephemeral=True)


@bot.tree.command(name="whodis-start", description="Start a new Who Dis? lobby in this channel")
@app_commands.describe(points="Points needed to win")
@app_commands.choices(
    points=[
        app_commands.Choice(name="Quick (3 points)", value=3),
        app_commands.Choice(name="Standard (5 points)", value=5),
        app_commands.Choice(name="Longer (7 points)", value=7),
        app_commands.Choice(name="Longest (10 points)", value=10),
    ],
)
async def whodis_start(interaction: discord.Interaction, points: app_commands.Choice[int]):
    if get_game(interaction.channel_id) is not None:
        await interaction.response.send_message(
            "⚠️ There's already a Who Dis? game running in this channel. Use `/whodis-end` to cancel it first.",
            ephemeral=True,
        )
        return

    game = WhoDisGame(host_id=interaction.user.id, points_to_win=points.value)
    game.add_player(interaction.user.id, interaction.user.display_name)
    games[interaction.channel_id] = game

    view = JoinView(game)
    file = discord.File(ci.back_card_path(), filename="back.png")
    await interaction.response.send_message(embed=lobby_embed(game), view=view, file=file)


class TestModePasswordModal(discord.ui.Modal, title="Solo Test Mode"):
    password = discord.ui.TextInput(
        label="Password", style=discord.TextStyle.short, required=True, max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.password.value != TEST_MODE_PASSWORD:
            await interaction.response.send_message("⚠️ Incorrect password.", ephemeral=True)
            return
        if get_game(interaction.channel_id) is not None:
            await interaction.response.send_message(
                "⚠️ There's already a Who Dis? game running in this channel. Use `/whodis-end` to cancel it first.",
                ephemeral=True,
            )
            return

        game = WhoDisGame(host_id=interaction.user.id, points_to_win=3)
        game.add_player(interaction.user.id, interaction.user.display_name)
        for bot_id, bot_name in TEST_BOT_PLAYERS:
            game.add_player(bot_id, bot_name)
            game.players[bot_id].is_bot = True
        games[interaction.channel_id] = game
        game.start()

        await interaction.response.send_message(
            "🧪 Solo test mode started — you + 2 auto-playing test bots, first to 3 points wins.",
            ephemeral=True,
        )
        await announce_new_round(interaction.channel, game)
        await auto_advance(interaction.channel, game)


@bot.tree.command(name="whodis-testmode", description="(Password-gated) Start a solo test game with 2 auto-playing bots")
async def whodis_testmode(interaction: discord.Interaction):
    await interaction.response.send_modal(TestModePasswordModal())


@bot.tree.command(name="whodis-join", description="Join the open Who Dis? lobby in this channel")
async def whodis_join(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("No lobby is open here. Start one with `/whodis-start`.", ephemeral=True)
        return
    try:
        game.add_player(interaction.user.id, interaction.user.display_name)
    except GameError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ {interaction.user.display_name} joined! ({game.player_count()} players)")


@bot.tree.command(name="whodis-leave", description="Leave the Who Dis? lobby before the game starts")
async def whodis_leave(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None or game.phase != WhoDisGame.PHASE_LOBBY:
        await interaction.response.send_message("There's no open lobby to leave right now.", ephemeral=True)
        return
    game.remove_player(interaction.user.id)
    await interaction.response.send_message(f"👋 {interaction.user.display_name} left the lobby.")


@bot.tree.command(name="whodis-begin", description="Deal hands and start the Who Dis? game")
async def whodis_begin(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("No lobby is open here. Start one with `/whodis-start`.", ephemeral=True)
        return
    if interaction.user.id != game.host_id:
        await interaction.response.send_message("Only the player who started the lobby can begin the game.", ephemeral=True)
        return
    try:
        game.start()
    except GameError as e:
        await interaction.response.send_message(f"⚠️ {e}", ephemeral=True)
        return

    await interaction.response.send_message(
        f"🎬 Game on! {game.player_count()} players, first to **{game.points_to_win}** points wins.\n"
        f"Everyone's been dealt 7 Reply cards — use **/submit** each round to play one."
    )
    await connect_voice_if_possible(interaction)
    await announce_new_round(interaction.channel, game)
    await auto_advance(interaction.channel, game)


@bot.tree.command(name="submit", description="Play a Reply card for the current round")
async def submit(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("There's no game running here.", ephemeral=True)
        return
    if game.phase != WhoDisGame.PHASE_COLLECTING:
        await interaction.response.send_message("Submissions aren't open right now.", ephemeral=True)
        return
    if interaction.user.id not in game.players:
        await interaction.response.send_message("You're not in this game.", ephemeral=True)
        return
    if game.is_judge(interaction.user.id):
        await interaction.response.send_message("You're the Judge this round — sit back and wait for replies!", ephemeral=True)
        return
    if interaction.user.id in game.submissions:
        await interaction.response.send_message("You've already submitted a reply this round.", ephemeral=True)
        return

    player = game.players[interaction.user.id]
    inbox = game.current_inbox
    view = SubmitView(game, player.hand)

    grid = ci.make_grid(
        [ci.reply_card_path(c["id"]) for c in player.hand],
        labels=[f"Card {i + 1}" for i in range(len(player.hand))],
        thumb_width=220,
    )
    grid_file = discord.File(ci.image_to_file_bytes(grid), filename="hand.png")
    embed = discord.Embed(
        title="📱 Incoming text",
        description=inbox["text"],
        color=COLOR_RED,
    )
    embed.set_image(url="attachment://hand.png")
    await interaction.response.send_message(
        content="Your hand — pick your reply below (only you can see this):",
        embed=embed,
        file=grid_file,
        view=view,
        ephemeral=True,
    )


@bot.tree.command(name="vote", description="(Judge only) Pick the winning reply for this round")
async def vote(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("There's no game running here.", ephemeral=True)
        return
    if game.phase != WhoDisGame.PHASE_JUDGING:
        await interaction.response.send_message("Judging isn't open yet — waiting on submissions.", ephemeral=True)
        return
    if interaction.user.id != game.current_judge_id():
        await interaction.response.send_message("Only this round's Judge can vote.", ephemeral=True)
        return

    submissions = game.anonymized_submissions()
    inbox = game.current_inbox
    view = VoteView(game, submissions)

    grid = ci.make_grid(
        [ci.reply_card_path(sub.card["id"]) for sub in submissions],
        labels=[f"Reply {i + 1}" for i in range(len(submissions))],
        thumb_width=220,
    )
    grid_file = discord.File(ci.image_to_file_bytes(grid), filename="submissions.png")
    embed = discord.Embed(
        title="📱 Incoming text",
        description=inbox["text"],
        color=COLOR_YELLOW,
    )
    embed.set_image(url="attachment://submissions.png")
    await interaction.response.send_message(
        content="Pick the winner below (only you can see this):",
        embed=embed,
        file=grid_file,
        view=view,
        ephemeral=True,
    )


async def fetch_avatar_bytes(client: discord.Client, user_id: int) -> Optional[bytes]:
    try:
        user = client.get_user(user_id) or await client.fetch_user(user_id)
        return await user.display_avatar.replace(size=128, format="png").read()
    except discord.HTTPException:
        return None


@bot.tree.command(name="whodis-scores", description="Show the current Who Dis? scoreboard")
async def whodis_scores(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("There's no game running here.", ephemeral=True)
        return

    # Fetching avatars is a network call per player -- defer so a slow one
    # can't blow the 3-second interaction budget (same crash shape as the
    # font bug: an unhandled delay/exception here would silently eat the
    # response and Discord would show "The application did not respond").
    await interaction.response.defer()

    entries = []
    for p in game.scoreboard():
        avatar_bytes = None if p.is_bot else await fetch_avatar_bytes(bot, p.user_id)
        entries.append((p.name, p.score, avatar_bytes))

    board_img = ci.make_scoreboard(entries, game.points_to_win)
    file = discord.File(ci.image_to_file_bytes(board_img), filename="scoreboard.png")
    embed = discord.Embed(
        title="📊 Scoreboard",
        description=f"Playing to **{game.points_to_win}** points",
        color=COLOR_GREEN,
    )
    embed.set_image(url="attachment://scoreboard.png")
    await interaction.followup.send(embed=embed, file=file)


@bot.tree.command(name="whodis-end", description="End/cancel the Who Dis? game in this channel")
async def whodis_end(interaction: discord.Interaction):
    game = get_game(interaction.channel_id)
    if game is None:
        await interaction.response.send_message("There's no game running here.", ephemeral=True)
        return
    if interaction.user.id != game.host_id and not interaction.user.guild_permissions.manage_guild:
        await interaction.response.send_message(
            "Only the host or a server manager can end the game.", ephemeral=True
        )
        return
    games.pop(interaction.channel_id, None)
    round_messages.pop(interaction.channel_id, None)
    await interaction.response.send_message("🛑 Game ended.")
    await disconnect_voice(interaction.guild)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user} — slash commands synced.")


def main():
    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("Set the DISCORD_BOT_TOKEN environment variable before running the bot.")
    bot.run(token)


if __name__ == "__main__":
    main()
