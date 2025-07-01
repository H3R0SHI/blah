# ---------------------------  main.py  ----------------------------
import os, json, random, string, pkgutil, importlib
from datetime import datetime
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, CallbackContext, CallbackQueryHandler,
    MessageHandler, filters
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_API_TOKEN")
ADMIN_ID  = os.getenv("ADMIN_ID")           # single, numeric string

# ---------- helpers for tiny JSON “DBs” ----------
def _load(path, default):  # tiny wrapper
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

userdata = _load("userdata.json",           {})   # key = str(user_id)
keys     = _load("keys.json", {"credits": {}, "subscriptions": {}})
storage  = _load("storage.json",            {})   # misc bot data

def is_admin(uid: str) -> bool:
    return uid == ADMIN_ID

# ---------- registration / profile ----------
async def start(update: Update, ctx: CallbackContext):
    await update.message.reply_text(
        "👋 Hi! Use /register if you’re new, or /help for commands.")

async def register(update: Update, ctx: CallbackContext):
    uid = str(update.effective_user.id)
    if uid in userdata:
        await update.message.reply_text("✅ You’re already registered.")
        return
    userdata[uid] = {
        "username": update.effective_user.username,
        "full_name": update.effective_user.full_name,
        "date_joined": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "active",
        "balance": 10,
        "subscription": None,           # 1,2,3
        "achievements": [],
        "games_played": 0
    }
    _save("userdata.json", userdata)
    await update.message.reply_text(
        "🎉 Registered! 10 credits added. Use /help to explore features.")

async def profile(update: Update, ctx: CallbackContext):
    uid = str(update.effective_user.id)
    if uid not in userdata:
        await update.message.reply_text("⚠️ Please /register first.")
        return
    u = userdata[uid]
    ach = ", ".join(u["achievements"]) if u["achievements"] else "None"
    msg = (f"👤 **Profile**\n"
           f"ID: {uid}\nName: {u['full_name']}\n"
           f"Joined: {u['date_joined']}\n"
           f"Balance: {u['balance']} cr\n"
           f"Tier: {u['subscription'] or 'None'}\n"
           f"Achievements: {ach}")
    await update.message.reply_text(msg)

# ---------- HELP ----------
async def help_cmd(update: Update, ctx: CallbackContext):
    uid = str(update.effective_user.id)
    base = ("`/start`  – greet\n"
            "`/register` – create account\n"
            "`/profile`  – your stats\n"
            "`/redeem <key>` – add credits / tier\n"
            "`/play_game` – game menu\n")
    admin = ("\n**Admin-only**\n"
             "`/generate_key` – make credit / sub keys\n"
             "`/show_keys`    – list unused keys\n"
             "`/ban <uid>`    – ban user\n"
             "`/broadcast`    – global msg/img")
    await update.message.reply_text(
        base + (admin if is_admin(uid) else ""), parse_mode="Markdown")

# ---------- KEY   GENERATION ----------
def _rand(k=10): return ''.join(random.choices(string.ascii_uppercase+string.digits,k=k))

async def generate_key(update: Update, ctx: CallbackContext):
    if not is_admin(str(update.effective_user.id)):
        return await update.message.reply_text("🚫 Admins only")
    kb = [[InlineKeyboardButton("💰 Credits",  callback_data="key_credit"),
           InlineKeyboardButton("🔒 Tier",      callback_data="key_sub")]]
    await update.message.reply_text("Select key type:", reply_markup=InlineKeyboardMarkup(kb))

async def key_cb(update: Update, ctx: CallbackContext):
    q = update.callback_query; uid = str(q.from_user.id)
    await q.answer()
    if not is_admin(uid): return
    if q.data == "key_credit":
        kb = [[InlineKeyboardButton(str(a), callback_data=f"camt_{a}")]
              for a in (25,50,100,200,350,500,800,1000)]
        kb.append([InlineKeyboardButton("Custom amount", callback_data="camt_custom")])
        await q.edit_message_text("Pick credit amount:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data.startswith("camt_"):
        amt = q.data.split("_")[1]
        if amt == "custom":
            ctx.user_data["await_custom_amount"] = True
            return await q.edit_message_text("Send custom credit amount (number):")
        ctx.user_data["pending_amount"] = int(amt)
        ctx.user_data["await_key_count"] = True
        await q.edit_message_text("How many keys to generate?")
    elif q.data == "key_sub":
        kb = [[InlineKeyboardButton("Bronze 1", callback_data="tier_1")],
              [InlineKeyboardButton("Silver 2", callback_data="tier_2")],
              [InlineKeyboardButton("Gold 3",   callback_data="tier_3")]]
        await q.edit_message_text("Select subscription tier:", reply_markup=InlineKeyboardMarkup(kb))
    elif q.data.startswith("tier_"):
        tier = int(q.data.split("_")[1])
        ctx.user_data["pending_tier"] = tier
        ctx.user_data["await_key_count"] = True
        await q.edit_message_text("How many keys to generate?")
    elif q.data == "post_keys":
        # build post-ready message
        klist = ctx.user_data.get("last_keys", [])
        if not klist:
            return await q.answer("No keys.")
        lines = "\n".join(klist)
        msg = (f"🎁 **Free Keys!** 🎁\n\n"
               f"Count: {len(klist)}\n\n{lines}\n\n"
               "Redeem in bot → `/redeem <key>`")
        await q.edit_message_text(msg, parse_mode="Markdown")

async def text_admin_input(update: Update, ctx: CallbackContext):
    uid = str(update.effective_user.id)
    if not is_admin(uid): return
    if ctx.user_data.get("await_custom_amount"):
        try:
            amt = int(update.message.text)
            ctx.user_data["pending_amount"] = amt
            ctx.user_data["await_custom_amount"] = False
            ctx.user_data["await_key_count"] = True
            return await update.message.reply_text("How many keys to generate?")
        except ValueError:
            return await update.message.reply_text("Enter a number.")
    if ctx.user_data.get("await_key_count"):
        try:
            cnt = int(update.message.text)
            ctx.user_data["await_key_count"] = False
        except ValueError:
            return await update.message.reply_text("Enter a number.")
        klist = []
        if "pending_amount" in ctx.user_data:      # credit keys
            amt = ctx.user_data.pop("pending_amount")
            for _ in range(cnt):
                k = f"MIKU-CR{amt}-{_rand(8)}"
                keys["credits"][k] = amt
                klist.append(k)
        elif "pending_tier" in ctx.user_data:      # sub keys
            tier = ctx.user_data.pop("pending_tier")
            for _ in range(cnt):
                k = f"MIKU-SUB{tier}-{_rand(8)}"
                keys["subscriptions"][k] = tier
                klist.append(k)
        _save("keys.json", keys)
        ctx.user_data["last_keys"] = klist
        kb = [[InlineKeyboardButton("📢 Make post message", callback_data="post_keys")]]
        await update.message.reply_text("\n".join(klist), reply_markup=InlineKeyboardMarkup(kb))

# ---------- /show_keys ----------
async def show_keys(update: Update, ctx: CallbackContext):
    if not is_admin(str(update.effective_user.id)):
        return
    cr  = "\n".join(keys["credits"].keys()) or "No credit keys."
    sub = "\n".join(keys["subscriptions"].keys()) or "No subscription keys."
    await update.message.reply_text(f"💰 **Credits**\n{cr}\n\n🔒 **Subs**\n{sub}", parse_mode="Markdown")

# ---------- REDEEM ----------
async def redeem(update: Update, ctx: CallbackContext):
    uid = str(update.effective_user.id)
    if len(ctx.args)!=1: return await update.message.reply_text("Usage /redeem <key>")
    key = ctx.args[0]
    if key in keys["credits"]:
        amt = keys["credits"].pop(key)
        userdata[uid]["balance"] += amt
        await update.message.reply_text(f"✅ {amt} credits added!")
    elif key in keys["subscriptions"]:
        tier = keys["subscriptions"].pop(key)
        userdata[uid]["subscription"] = tier
        await update.message.reply_text(f"✅ Tier {tier} subscription activated!")
    else:
        return await update.message.reply_text("❌ Invalid or used key.")
    _save("userdata.json", userdata); _save("keys.json", keys)

# ---------- BAN ----------
async def ban(update: Update, ctx: CallbackContext):
    if not is_admin(str(update.effective_user.id)): return
    if len(ctx.args)!=1: return await update.message.reply_text("Usage /ban <uid>")
    target=ctx.args[0]
    if target in userdata:
        userdata[target]["status"]="banned"; _save("userdata.json", userdata)
        await update.message.reply_text("User banned.")
    else:
        await update.message.reply_text("Not found.")

# ---------- BROADCAST ----------
async def broadcast(update: Update, ctx: CallbackContext):
    if not is_admin(str(update.effective_user.id)): return
    ctx.user_data["await_broadcast"]=True
    await update.message.reply_text("Send broadcast text or photo (with caption).")

async def handle_broadcast(update: Update, ctx: CallbackContext):
    if not ctx.user_data.get("await_broadcast"): return
    ctx.user_data["await_broadcast"]=False
    sent=0
    if update.message.photo:
        photo=update.message.photo[-1].file_id
        cap = update.message.caption or ""
        for uid in userdata:
            try:
                await ctx.bot.send_photo(uid, photo, caption=cap)
                sent+=1
            except: pass
    else:
        msg=update.message.text
        for uid in userdata:
            try:
                await ctx.bot.send_message(uid, msg)
                sent+=1
            except: pass
    await update.message.reply_text(f"Broadcast delivered to {sent} users.")

# ---------- AUTO-LOAD game modules ----------
def load_modules(app: Application):
    for _, modname, _ in pkgutil.iter_modules():
        if modname == "main": continue
        mod = importlib.import_module(modname)
        if hasattr(mod,"register_handlers"):
            mod.register_handlers(app)

# ---------- APP ----------
def main():
    app=Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("register", register))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("generate_key", generate_key))
    app.add_handler(CommandHandler("show_keys", show_keys))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("broadcast", broadcast))

    app.add_handler(CallbackQueryHandler(handle_key_selection, pattern="^(key_|select_|camt_|tier_|post_keys)"))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(int(ADMIN_ID)), text_admin_input))
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & filters.User(int(ADMIN_ID)), handle_broadcast))

    load_modules(app)
    app.run_polling()

if __name__=="__main__":
    main()
