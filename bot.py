import asyncio, json, os, time
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.errors import (SessionPasswordNeededError, PhoneCodeInvalidError,
                             PhoneCodeExpiredError, PasswordHashInvalidError)

API_ID = int(os.environ["API_ID"])          # my.telegram.org se
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]         # @BotFather se
OWNER_ID = int(os.environ["OWNER_ID"])      # tumhara Telegram numeric ID
DATA_FILE = "data.json"

DEFAULT = {"session": "", "enabled": False, "cooldown": 6,
           "message": "👋 Hi {name}!\nMain abhi busy hu, jaldi reply karunga. 🙏",
           "replied": {}}
data = dict(DEFAULT)
if os.path.exists(DATA_FILE):
    data.update(json.load(open(DATA_FILE)))

def save():
    json.dump(data, open(DATA_FILE, "w"))

bot = TelegramClient("bot_session", API_ID, API_HASH)
user = None          # logged-in account client
temp = None          # login ke time ka client
state = {}           # OWNER ka current step

# ---------------- UI ----------------
def main_menu():
    on = data["enabled"]
    return [
        [Button.inline(("🟢 Auto-Reply: ON" if on else "🔴 Auto-Reply: OFF"), b"toggle")],
        [Button.inline("✏️ Message Set Karo", b"setmsg"), Button.inline("👁 Preview", b"preview")],
        [Button.inline("⏱ Cooldown", b"cd"), Button.inline("🗑 Old Msg Delete", b"del")],
        [Button.inline("🔑 Login", b"login"), Button.inline("🚪 Logout", b"logout")],
    ]

def home_text():
    acc = "✅ Logged in" if user else "❌ Login nahi hai"
    on = "🟢 ON" if data["enabled"] else "🔴 OFF"
    return (f"🤖 **Auto-Reply Manager**\n\n👤 Account: {acc}\n"
            f"⚡ Auto-Reply: {on}\n⏱ Cooldown: {data['cooldown']} ghante\n\n"
            f"💬 Message:\n{data['message']}")

BACK = [[Button.inline("⬅️ Back", b"home")]]

async def show_home(event, edit=True):
    if edit:
        try:
            return await event.edit(home_text(), buttons=main_menu())
        except Exception:
            pass
    await bot.send_message(OWNER_ID, home_text(), buttons=main_menu())

# ---------------- Auto reply (user account) ----------------
async def auto_reply(event):
    if not data["enabled"] or not event.is_private or event.out:
        return
    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False) or sender.id == OWNER_ID:
        return
    now = time.time()
    last = data["replied"].get(str(sender.id), 0)
    if now - last < data["cooldown"] * 3600:
        return
    data["replied"][str(sender.id)] = now
    save()
    name = (sender.first_name or "").strip() or "dost"
    text = data["message"].replace("{name}", name)
    await event.reply(text, parse_mode="html")

async def start_user(session_str):
    global user
    c = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        return False
    c.add_event_handler(auto_reply, events.NewMessage(incoming=True))
    user = c
    return True

# ---------------- Delete old messages ----------------
async def delete_old(chat, days):
    ent = await user.get_entity(int(chat) if chat.lstrip("-").isdigit() else chat)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days) if days else None
    ids = []
    async for m in user.iter_messages(ent, from_user="me"):
        if cutoff is None or m.date < cutoff:
            ids.append(m.id)
    for i in range(0, len(ids), 100):
        await user.delete_messages(ent, ids[i:i + 100], revoke=True)
    return len(ids)

# ---------------- Bot handlers ----------------
def owner_only(e):
    return e.sender_id == OWNER_ID

@bot.on(events.NewMessage(pattern="/start", func=owner_only))
async def start(event):
    state.clear()
    await show_home(event, edit=False)

@bot.on(events.CallbackQuery(func=owner_only))
async def cb(event):
    global user
    d = event.data
    if d == b"home":
        state.clear()
        return await show_home(event)
    if d == b"toggle":
        if not user:
            return await event.answer("Pehle login karo!", alert=True)
        data["enabled"] = not data["enabled"]; save()
        return await show_home(event)
    if d == b"setmsg":
        state["step"] = "msg"
        return await event.edit("✏️ Naya auto-reply message bhejo.\n\n"
                                "• `{name}` = sender ka naam\n"
                                "• HTML chalega: <b>bold</b> <i>italic</i> <code>code</code> "
                                "<a href=\"https://t.me/x\">link</a>\n• Emoji kuch bhi lagao 🎉",
                                buttons=BACK)
    if d == b"preview":
        await event.answer()
        return await bot.send_message(OWNER_ID, "👁 Preview:\n\n" + data["message"].replace("{name}", "Rahul"),
                                      parse_mode="html")
    if d == b"cd":
        state["step"] = "cd"
        return await event.edit("⏱ Cooldown ghanto me bhejo (ek bande ko dobara reply kitne ghante baad).\n"
                                "Example: `6` ya `0.5`", buttons=BACK)
    if d == b"del":
        if not user:
            return await event.answer("Pehle login karo!", alert=True)
        state["step"] = "del_chat"
        return await event.edit("🗑 Kis chat ke tumhare bheje hue messages delete karne hain?\n"
                                "Username (@name) ya numeric ID bhejo.", buttons=BACK)
    if d == b"login":
        if user:
            return await event.answer("Already logged in ✅", alert=True)
        state["step"] = "phone"
        return await event.edit("📱 Apna phone number bhejo country code ke saath.\nExample: `+919876543210`\n\n"
                                "⚠️ Sirf apna khud ka account use karo.", buttons=BACK)
    if d == b"logout":
        if user:
            await user.log_out(); user = None
        data["session"] = ""; data["enabled"] = False; save()
        await event.answer("Logout ho gaya ✅", alert=True)
        return await show_home(event)

@bot.on(events.NewMessage(func=lambda e: owner_only(e) and not (e.raw_text or "").startswith("/")))
async def text_in(event):
    global user, temp
    step = state.get("step")
    t = (event.raw_text or "").strip()
    if not step:
        return
    try:
        if step == "msg":
            data["message"] = event.message.text if False else t
            save(); state.clear()
            await event.respond("✅ Message set ho gaya!")
            return await show_home(event, edit=False)

        if step == "cd":
            data["cooldown"] = float(t); save(); state.clear()
            await event.respond("✅ Cooldown set!")
            return await show_home(event, edit=False)

        if step == "del_chat":
            state.update(step="del_days", chat=t)
            return await event.respond("📅 Kitne din se purane messages delete karne hain?\n"
                                       "`0` = saare messages, `7` = 7 din se purane.", buttons=BACK)
        if step == "del_days":
            msg = await event.respond("⏳ Delete ho raha hai...")
            n = await delete_old(state["chat"], int(t)); state.clear()
            await msg.edit(f"✅ {n} messages delete ho gaye.", buttons=BACK)
            return

        if step == "phone":
            temp = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp.connect()
            sent = await temp.send_code_request(t)
            state.update(step="code", phone=t, hash=sent.phone_code_hash)
            return await event.respond(
                "📩 Telegram ne OTP bheja hai.\n\n⚠️ OTP **spaces ke saath** bhejo, jaise `1 2 3 4 5` "
                "(warna Telegram code block kar deta hai).", buttons=BACK)

        if step == "code":
            await event.delete()
            code = "".join(ch for ch in t if ch.isdigit())
            try:
                await temp.sign_in(state["phone"], code, phone_code_hash=state["hash"])
            except SessionPasswordNeededError:
                state["step"] = "2fa"
                return await event.respond("🔐 2-Step password bhejo.", buttons=BACK)
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                return await event.respond("❌ OTP galat/expired. Dobara bhejo ya Back dabake restart karo.")
            return await finish_login(event)

        if step == "2fa":
            await event.delete()
            try:
                await temp.sign_in(password=t)
            except PasswordHashInvalidError:
                return await event.respond("❌ Password galat. Dobara bhejo.")
            return await finish_login(event)

    except Exception as e:
        state.clear()
        await event.respond(f"⚠️ Error: `{e}`", buttons=BACK)

async def finish_login(event):
    global temp
    data["session"] = temp.session.save(); save()
    await temp.disconnect(); temp = None
    ok = await start_user(data["session"])
    state.clear()
    await event.respond("✅ Login ho gaya!" if ok else "❌ Login fail.")
    await show_home(event, edit=False)

async def main():
    await bot.start(bot_token=BOT_TOKEN)
    if data["session"]:
        await start_user(data["session"])
    print("Bot chalu hai...")
    await bot.run_until_disconnected()

asyncio.run(main())
