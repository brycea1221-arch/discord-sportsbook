import os
import sqlite3
import threading
from flask import Flask
import discord
from discord.ext import commands

# --- RENDER DUMMY WEB SERVER ---
app = Flask(__name__)


@app.route("/")
def home():
  return "Bot is running!"


def run_server():
  port = int(os.environ.get("PORT", 10000))
  app.run(host="0.0.0.0", port=port)


# --- DATABASE SETUP ---
db = sqlite3.connect("sportsbook.db", check_same_thread=False)
cursor = db.cursor()

cursor.execute("""
    CREATE TABLE IF NOT EXISTS games (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1 TEXT,
        team2 TEXT,
        odds_team1 INTEGER,
        odds_team2 INTEGER,
        status TEXT
    )
""")
db.commit()

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
  print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
  print("Bot is online and listening.")


# --- PING COMMAND ---
@bot.command(name="ping")
async def ping(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass

  await ctx.send(f"Pong! 🏓 Bot latency: {round(bot.latency * 1000)}ms")


# --- CREATE GAME COMMAND ---
@bot.command(name="creategame")
@commands.has_permissions(administrator=True)
async def creategame(ctx, *, arg: str):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass

  lower_arg = arg.lower()
  if " vs " not in lower_arg:
    await ctx.send(
        "❌ Please use 'vs' between teams. Example: `!creategame Ohio State 100"
        " vs Texas -118`",
        delete_after=10,
    )
    return

  idx = lower_arg.find(" vs ")
  side1 = arg[:idx].strip()
  side2 = arg[idx + 4 :].strip()

  s1_words = side1.split()
  try:
    odds1 = int(s1_words[-1])
    team1 = " ".join(s1_words[:-1])
  except ValueError:
    await ctx.send("❌ Error parsing Team 1 odds.", delete_after=10)
    return

  s2_words = side2.split()
  try:
    odds2 = int(s2_words[-1])
    team2 = " ".join(s2_words[:-1])
  except ValueError:
    await ctx.send("❌ Error parsing Team 2 odds.", delete_after=10)
    return

  cursor.execute(
      "INSERT INTO games (team1, team2, odds_team1, odds_team2, status) VALUES"
      " (?, ?, ?, ?, 'open')",
      (team1, team2, odds1, odds2),
  )
  db.commit()
  game_id = cursor.lastrowid

  o1_str = f"+{odds1}" if odds1 > 0 else str(odds1)
  o2_str = f"+{odds2}" if odds2 > 0 else str(odds2)

  await ctx.send(
      f"🎮 **New Game Open!** (Game #{game_id})\n🏟️ **{team1}** ({o1_str}) vs"
      f" **{team2}** ({o2_str})\nUse `!bet {game_id} <team> <amount>` to place"
      " your wager!"
  )


# --- GAMES COMMAND ---
@bot.command(name="games")
async def games(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass

  cursor.execute(
      "SELECT id, team1, team2, odds_team1, odds_team2 FROM games WHERE"
      " status='open'"
  )
  active_games = cursor.fetchall()

  if not active_games:
    await ctx.send("❌ There are no open games right now.")
    return

  msg = "🎮 **Open Games:**\n"
  for g in active_games:
    gid, t1, t2, o1, o2 = g
    o1_str = f"+{o1}" if o1 > 0 else str(o1)
    o2_str = f"+{o2}" if o2 > 0 else str(o2)
    msg += f"**Game #{gid}**: {t1} ({o1_str}) vs {t2} ({o2_str})\n"

  await ctx.send(msg)


# --- RUN BOT & WEB SERVER ---
if __name__ == "__main__":
  server_thread = threading.Thread(target=run_server, daemon=True)
  server_thread.start()

  TOKEN = os.getenv("DISCORD_TOKEN")
  if TOKEN:
    bot.run(TOKEN)
  else:
    print("Error: DISCORD_TOKEN not found in environment variables.")