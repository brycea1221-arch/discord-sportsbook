import os
import sqlite3
import threading
from datetime import datetime
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

# Games Table
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

# Users / Balances Table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        balance REAL DEFAULT 1000.0,
        last_claim TEXT
    )
""")

# Bets Table
cursor.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        game_id INTEGER,
        team_picked TEXT,
        amount REAL,
        odds INTEGER,
        status TEXT DEFAULT 'pending'
    )
""")
db.commit()

# --- DISCORD BOT SETUP ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


def get_or_create_user(user_id):
  cursor.execute(
      "SELECT balance, last_claim FROM users WHERE user_id = ?", (str(user_id),)
  )
  user = cursor.fetchone()
  if not user:
    cursor.execute(
        "INSERT INTO users (user_id, balance, last_claim) VALUES (?, 1000.0,"
        " NULL)",
        (str(user_id),),
    )
    db.commit()
    return 1000.0, None
  return user[0], user[1]


@bot.event
async def on_ready():
  print(f"Logged in as {bot.user.name} (ID: {bot.user.id})")
  print("Bot is online and listening.")


# --- PING ---
@bot.command(name="ping")
async def ping(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass
  await ctx.send(f"Pong! 🏓 Bot latency: {round(bot.latency * 1000)}ms")


# --- BALANCE ---
@bot.command(name="balance", aliases=["bal"])
async def balance(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass
  bal, _ = get_or_create_user(ctx.author.id)
  await ctx.send(
      f"💰 **{ctx.author.display_name}**, your current balance is:"
      f" **${bal:,.2f}**"
  )


# --- DAILY CLAIM ---
@bot.command(name="claim")
async def claim(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass
  uid = str(ctx.author.id)
  bal, last_claim = get_or_create_user(uid)

  today = datetime.now().strftime("%Y-%m-%d")
  if last_claim == today:
    await ctx.send(
        "❌ You have already claimed your daily bonus today! Come back tomorrow.",
        delete_after=10,
    )
    return

  bonus = 250.0
  new_bal = bal + bonus
  cursor.execute(
      "UPDATE users SET balance = ?, last_claim = ? WHERE user_id = ?",
      (new_bal, today, uid),
  )
  db.commit()

  await ctx.send(
      f"🎁 **{ctx.author.display_name}**, you successfully claimed your daily"
      f" **${bonus:,.2f}** bonus! New balance: **${new_bal:,.2f}**"
  )


# --- LEADERBOARD (!lb) ---
@bot.command(name="lb")
async def lb(ctx):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass
  cursor.execute(
      "SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10"
  )
  top_users = cursor.fetchall()

  if not top_users:
    await ctx.send("❌ No users on the leaderboard yet.")
    return

  msg = "🏆 **Sportsbook Leaderboard - Top Bettors** 🏆\n"
  for idx, (uid, bal) in enumerate(top_users, start=1):
    member = ctx.guild.get_member(int(uid))
    name = member.display_name if member else f"User {uid}"
    msg += f"**{idx}.** {name} — **${bal:,.2f}**\n"

  await ctx.send(msg)


# --- CREATE GAME (Admin Only) ---
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


# --- LIST GAMES ---
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


# --- PLACE BET ---
@bot.command(name="bet")
async def bet(ctx, game_id: int, team_name: str, amount: float):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass

  if amount <= 0:
    await ctx.send(
        "❌ Bet amount must be greater than zero.", delete_after=10
    )
    return

  uid = str(ctx.author.id)
  bal, _ = get_or_create_user(uid)

  if bal < amount:
    await ctx.send(
        f"❌ You don't have enough funds! Your balance is ${bal:,.2f}.",
        delete_after=10,
    )
    return

  # Check if game is open
  cursor.execute(
      "SELECT team1, team2, odds_team1, odds_team2, status FROM games WHERE id"
      " = ?",
      (game_id,),
  )
  game = cursor.fetchone()

  if not game or game[4] != "open":
    await ctx.send("❌ That game is not open for betting.", delete_after=10)
    return

  t1, t2, o1, o2, _ = game

  # Match team name loosely
  chosen_team = None
  odds = 0
  if team_name.lower() in t1.lower():
    chosen_team = t1
    odds = o1
  elif team_name.lower() in t2.lower():
    chosen_team = t2
    odds = o2
  else:
    await ctx.send(
        f"❌ Team '{team_name}' not found in Game #{game_id}.", delete_after=10
    )
    return

  # Deduct balance and record bet
  new_bal = bal - amount
  cursor.execute(
      "UPDATE users SET balance = ? WHERE user_id = ?", (new_bal, uid)
  )
  cursor.execute(
      "INSERT INTO bets (user_id, game_id, team_picked, amount, odds, status)"
      " VALUES (?, ?, ?, ?, ?, 'pending')",
      (uid, game_id, chosen_team, amount, odds),
  )
  db.commit()

  o_str = f"+{odds}" if odds > 0 else str(odds)
  await ctx.send(
      f"✅ **{ctx.author.display_name}** successfully wagered **${amount:,.2f}**"
      f" on **{chosen_team}** ({o_str}) for Game #{game_id}!"
  )


# --- RESOLVE GAME (Admin Only) ---
@bot.command(name="resolve")
@commands.has_permissions(administrator=True)
async def resolve(ctx, game_id: int, *, winning_team: str):
  try:
    await ctx.message.delete()
  except discord.Forbidden:
    pass

  cursor.execute(
      "SELECT team1, team2, status FROM games WHERE id = ?", (game_id,)
  )
  game = cursor.fetchone()

  if not game:
    await ctx.send(f"❌ Game #{game_id} not found.", delete_after=10)
    return

  if game[2] != "open":
    await ctx.send(
        f"❌ Game #{game_id} is already resolved or closed.", delete_after=10
    )
    return

  t1, t2, _ = game
  winner = None
  if winning_team.lower() in t1.lower():
    winner = t1
  elif winning_team.lower() in t2.lower():
    winner = t2
  else:
    await ctx.send(
        f"❌ '{winning_team}' does not match either team in Game #{game_id}."
        f" ({t1} vs {t2})",
        delete_after=10,
    )
    return

  # Mark game as closed
  cursor.execute(
      "UPDATE games SET status = 'closed' WHERE id = ?", (game_id,)
  )

  # Fetch all pending bets for this game
  cursor.execute(
      "SELECT id, user_id, team_picked, amount, odds FROM bets WHERE game_id ="
      " ? AND status = 'pending'",
      (game_id,),
  )
  pending_bets = cursor.fetchall()

  payout_summary = f"🏁 **Game #{game_id} Resolved! Winner: {winner}**\n"

  for bet_id, uid, picked, amount, odds in pending_bets:
    cursor.execute(
        "SELECT balance FROM users WHERE user_id = ?", (str(uid),)
    )
    user_row = cursor.fetchone()
    if not user_row:
      continue
    user_bal = user_row[0]

    if picked.lower() == winner.lower():
      # Calculate American Odds payout
      if odds > 0:
        profit = amount * (odds / 100.0)
      else:
        profit = amount * (100.0 / abs(odds))

      total_payout = amount + profit
      new_bal = user_bal + total_payout
      cursor.execute(
          "UPDATE users SET balance = ? WHERE user_id = ?",
          (new_bal, str(uid)),
      )
      cursor.execute(
          "UPDATE bets SET status = 'won' WHERE id = ?", (bet_id,)
      )
    else:
      cursor.execute(
          "UPDATE bets SET status = 'lost' WHERE id = ?", (bet_id,)
      )

  db.commit()
  await ctx.send(
      f"🏁 **Game #{game_id} has been resolved!** Winning Team: **{winner}**."
      " Payouts have been distributed to the winners!"
  )


# --- RUN BOT & WEB SERVER ---
if __name__ == "__main__":
  server_thread = threading.Thread(target=run_server, daemon=True)
  server_thread.start()

  TOKEN = os.getenv("DISCORD_TOKEN")
  if TOKEN:
    bot.run(TOKEN)
  else:
    print("Error: DISCORD_TOKEN not found in environment variables.")