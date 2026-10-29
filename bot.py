import asyncio, html, json, mimetypes, os, re, time
import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import (DocumentAttributeSticker, DocumentAttributeAnimated,
                               InputStickerSetEmpty)
from telethon.errors import (SessionPasswordNeededError, PhoneCodeInvalidError,
                             PhoneCodeExpiredError, PasswordHashInvalidError)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
BRAND = os.getenv("BRAND", "Miss Chutki")

AUTO_DELETE = 300            # auto-reply 5 minute baad delete (UI me option nahi dikhta)
DATA_FILE = "data.json"
START_IMG = "start.jpg"
BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
FILE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"
mimetypes.add_type("application/x-tgsticker", ".tgs")
os.makedirs("media", exist_ok=True)

DEFAULT = {"session": "", "enabled": False, "cooldown": 6.0,
           "message": "👋 Hi {name}!\nMain abhi busy hu, jaldi reply karunga. 🙏",
           "plain": "👋 Hi {name}!\nMain abhi busy hu, jaldi reply karunga. 🙏",
           "media": None, "replied": {}, "pending": [], "menu_id": 0, "start_fid": ""}
data = dict(DEFAULT)
if os.path.exists(DATA_FILE):
    data.update(json.load(open(DATA_FILE)))

def save():
    json.dump(data, open(DATA_FILE, "w"))

# ---------- small caps font ----------
_SC = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ")

def sc(text):
    parts = re.split(r"(<[^>]+>)", text)       # HTML tags ko mat chhedo
    return "".join(p if p.startswith("<") else p.lower().translate(_SC) for p in parts)

# ---------- telegram entities -> html ----------
_TAGS = {"bold": ("<b>", "</b>"), "italic": ("<i>", "</i>"), "underline": ("<u>", "</u>"),
         "strikethrough": ("<s>", "</s>"), "code": ("<code>", "</code>"),
         "pre": ("<pre>", "</pre>"), "spoiler": ("<tg-spoiler>", "</tg-spoiler>"),
         "blockquote": ("<blockquote>", "</blockquote>")}

def to_html(text, ents):
    u = text.encode("utf-16-le")
    n = len(u) // 2
    opens, closes = {}, {}
    for e in ents or []:
        t = e["type"]
        if t == "text_link":
            tag = (f'<a href="{html.escape(e["url"])}">', "</a>")
        elif t in _TAGS:
            tag = _TAGS[t]
        else:
            continue
        s = e["offset"]; en = min(s + e["length"], n)
        opens.setdefault(s, []).append(tag)
        closes.setdefault(en, []).append(tag)
    pts = sorted(set([0, n] + list(opens) + list(closes)))
    out = []
    for i, p in enumerate(pts):
        for tag in reversed(closes.get(p, [])):
            out.append(tag[1])
        for tag in opens.get(p, []):
            out.append(tag[0])
        if i + 1 < len(pts):
            out.append(html.escape(u[2 * p:2 * pts[i + 1]].decode("utf-16-le", "ignore")))
    return "".join(out)

# ---------- bot api ----------
http = httpx.AsyncClient(timeout=60)

async def api(method, **p):
    try:
        r = await http.post(f"{BASE}/{method}", json=p)
        j = r.json()
        if not j.get("ok"):
            print(method, j.get("description"))
            return None
        return j["result"]
    except Exception as e:
        print(method, e)
        return None

def B(label, cb, style=None):
    b = {"text": sc(label), "callback_data": cb}
    if style:
        b["style"] = style          # primary (blue) / success (green) / danger (red)
    return b

BACK = [[B("⬅️ Back", "home", "primary")]]

def home_kb():
    on = data["enabled"]
    return [
        [B("🟢 Auto-Reply : ON" if on else "🔴 Auto-Reply : OFF", "toggle", "success" if on else "danger")],
        [B("✏️ Set Reply", "setmsg", "primary"), B("👁 Preview", "preview", "primary")],
        [B("⏱ Cooldown", "cd", "primary"), B("🔄 Refresh", "home", "primary")],
        [B("🔑 Login", "login", "success"), B("🚪 Logout", "logout", "danger")],
    ]

def home_text():
    acc = "✅ ʟᴏɢɢᴇᴅ ɪɴ" if user else "❌ ɴᴏᴛ ʟᴏɢɢᴇᴅ ɪɴ"
    on = "🟢 ᴏɴ" if data["enabled"] else "🔴 ᴏꜰꜰ"
    m = data.get("media")
    media = sc(m["kind"]) if m else sc("none")
    plain = (data.get("plain") or "").strip()
    short = html.escape(plain[:140] + ("…" if len(plain) > 140 else "")) or "—"
    return (f"✦ <b>{sc(BRAND)}</b> ✦\n"
            f"<i>{sc('auto reply manager')}</i>\n\n"
            f"👤 {sc('account')} : {acc}\n"
            f"⚡ {sc('auto reply')} : {on}\n"
            f"⏱ {sc('cooldown')} : {data['cooldown']:g}{sc('h')}\n"
            f"🎞 {sc('media')} : {media}\n\n"
            f"💬 {sc('message')} :\n<blockquote>{short}</blockquote>")

async def send_menu():
    if data.get("menu_id"):
        await api("deleteMessage", chat_id=OWNER_ID, message_id=data["menu_id"])
    kb = json.dumps({"inline_keyboard": home_kb()})
    r = None
    if data.get("start_fid"):
        r = await api("sendPhoto", chat_id=OWNER_ID, photo=data["start_fid"], caption=home_text(),
                      parse_mode="HTML", has_spoiler=True, reply_markup={"inline_keyboard": home_kb()})
    if not r:
        with open(START_IMG, "rb") as f:
            resp = await http.post(f"{BASE}/sendPhoto",
                                   data={"chat_id": OWNER_ID, "caption": home_text(), "parse_mode": "HTML",
                                         "has_spoiler": "true", "reply_markup": kb},
                                   files={"photo": f})
        j = resp.json()
        r = j.get("result") if j.get("ok") else None
        if r:
            data["start_fid"] = r["photo"][-1]["file_id"]
    if r:
        data["menu_id"] = r["message_id"]
        save()

async def edit_menu(caption, kb):
    r = await api("editMessageCaption", chat_id=OWNER_ID, message_id=data["menu_id"],
                  caption=caption, parse_mode="HTML", reply_markup={"inline_keyboard": kb})
    return r

async def edit_home():
    await edit_menu(home_text(), home_kb())

def prompt(text):
    return f"✦ <b>{sc(BRAND)}</b> ✦\n\n{text}"

# ---------- user account (auto reply) ----------
user = None
temp = None
me_id = 0
state = {}

async def send_reply(event, name):
    text = data["message"].replace("{name}", html.escape(name))
    m = data.get("media")
    sent = []
    if m and os.path.exists(m["path"]):
        kind = m["kind"]
        kw = {}
        attrs = None
        if kind == "voice":
            kw["voice_note"] = True
        elif kind == "video_note":
            kw["video_note"] = True
        elif kind == "document":
            kw["force_document"] = True
        elif kind == "sticker":
            attrs = [DocumentAttributeSticker(alt=m.get("emoji") or "🙂",
                                              stickerset=InputStickerSetEmpty())]
        elif kind == "animation":
            attrs = [DocumentAttributeAnimated()]
        elif kind == "video":
            kw["supports_streaming"] = True
        no_caption = kind in ("sticker", "video_note")
        msg = await user.send_file(event.chat_id, m["path"], reply_to=event.id,
                                   caption=None if no_caption or not text.strip() else text,
                                   parse_mode="html", attributes=attrs, **kw)
        sent.append(msg)
        if no_caption and text.strip():
            sent.append(await user.send_message(event.chat_id, text, parse_mode="html"))
    elif text.strip():
        sent.append(await event.reply(text, parse_mode="html"))
    due = time.time() + AUTO_DELETE
    for s in sent:
        data["pending"].append([event.chat_id, s.id, due])
    save()

async def auto_reply(event):
    if not data["enabled"] or not event.is_private or event.out:
        return
    sender = await event.get_sender()
    if not sender or getattr(sender, "bot", False) or sender.id in (me_id, 777000):
        return
    now = time.time()
    if now - data["replied"].get(str(sender.id), 0) < data["cooldown"] * 3600:
        return
    data["replied"][str(sender.id)] = now
    save()
    try:
        await send_reply(event, (sender.first_name or "").strip() or "dost")
    except Exception as e:
        print("reply error:", e)

async def cleaner():
    """5 minute purane auto-replies automatic delete."""
    while True:
        await asyncio.sleep(15)
        if not user or not data["pending"]:
            continue
        now = time.time()
        keep = []
        for chat, mid, due in data["pending"]:
            if due <= now:
                try:
                    await user.delete_messages(chat, [mid], revoke=True)
                except Exception as e:
                    print("delete error:", e)
            else:
                keep.append([chat, mid, due])
        data["pending"] = keep
        save()

async def start_user(session_str):
    global user, me_id
    c = TelegramClient(StringSession(session_str), API_ID, API_HASH)
    await c.connect()
    if not await c.is_user_authorized():
        await c.disconnect()
        return False
    me_id = (await c.get_me()).id
    c.add_event_handler(auto_reply, events.NewMessage(incoming=True))
    user = c
    return True

# ---------- handlers ----------
async def on_cb(q):
    global user, temp
    if q["from"]["id"] != OWNER_ID:
        return await api("answerCallbackQuery", callback_query_id=q["id"])
    d = q["data"]
    cid = q["id"]
    if d == "home":
        state.clear()
        if temp:
            await temp.disconnect(); temp = None
        await api("answerCallbackQuery", callback_query_id=cid)
        return await edit_home()
    if d == "toggle":
        if not user:
            return await api("answerCallbackQuery", callback_query_id=cid,
                             text=sc("pehle login karo!"), show_alert=True)
        data["enabled"] = not data["enabled"]; save()
        await api("answerCallbackQuery", callback_query_id=cid)
        return await edit_home()
    if d == "setmsg":
        state["step"] = "msg"
        await api("answerCallbackQuery", callback_query_id=cid)
        return await edit_menu(prompt(
            f"✏️ {sc('naya auto-reply bhejo')}\n\n"
            f"• {sc('text, photo, video, sticker, gif, voice, file - sab chalega')}\n"
            f"• {sc('bold/italic/link/spoiler formatting telegram se hi lagao')}\n"
            f"• <code>{{name}}</code> = {sc('sender ka naam')}\n"
            f"• {sc('media ke saath caption bhi likh sakte ho')}"), BACK)
    if d == "preview":
        await api("answerCallbackQuery", callback_query_id=cid)
        return await send_preview()
    if d == "cd":
        state["step"] = "cd"
        await api("answerCallbackQuery", callback_query_id=cid)
        return await edit_menu(prompt(f"⏱ {sc('ek bande ko dobara reply kitne ghante baad?')}\n"
                                      f"{sc('example')} : <code>6</code> / <code>0.5</code>"), BACK)
    if d == "login":
        if user:
            return await api("answerCallbackQuery", callback_query_id=cid,
                             text=sc("already logged in"), show_alert=True)
        state["step"] = "phone"
        await api("answerCallbackQuery", callback_query_id=cid)
        return await edit_menu(prompt(
            f"📱 {sc('apna phone number bhejo (country code ke saath)')}\n"
            f"{sc('example')} : <code>+919876543210</code>\n\n"
            f"⚠️ {sc('sirf apna khud ka account use karo')}"), BACK)
    if d == "logout":
        if user:
            try:
                await user.log_out()
            except Exception:
                pass
            user = None
        data["session"] = ""; data["enabled"] = False; data["pending"] = []; save()
        await api("answerCallbackQuery", callback_query_id=cid, text=sc("logout ho gaya"), show_alert=True)
        return await edit_home()

async def send_preview():
    text = data["message"].replace("{name}", "Rahul")
    m = data.get("media")
    ids = []
    if m:
        method = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation",
                  "sticker": "sendSticker", "voice": "sendVoice", "audio": "sendAudio",
                  "video_note": "sendVideoNote", "document": "sendDocument"}[m["kind"]]
        field = method[4:].lower() if m["kind"] != "video_note" else "video_note"
        p = {"chat_id": OWNER_ID, field: m["fid"]}
        if m["kind"] not in ("sticker", "video_note") and text.strip():
            p.update(caption=text, parse_mode="HTML")
        r = await api(method, **p)
        if r: ids.append(r["message_id"])
        if m["kind"] in ("sticker", "video_note") and text.strip():
            r = await api("sendMessage", chat_id=OWNER_ID, text=text, parse_mode="HTML")
            if r: ids.append(r["message_id"])
    else:
        r = await api("sendMessage", chat_id=OWNER_ID, text=text or "—", parse_mode="HTML")
        if r: ids.append(r["message_id"])
    async def later():
        await asyncio.sleep(20)
        for i in ids:
            await api("deleteMessage", chat_id=OWNER_ID, message_id=i)
    asyncio.create_task(later())

async def set_reply(m):
    kind = None
    obj = None
    for k in ("photo", "animation", "video", "sticker", "voice", "audio", "video_note", "document"):
        if k in m:
            kind, obj = k, m[k]
            break
    if kind:
        plain, ents = m.get("caption", ""), m.get("caption_entities")
    else:
        plain, ents = m.get("text", ""), m.get("entities")
    if data.get("media"):
        try: os.remove(data["media"]["path"])
        except Exception: pass
        data["media"] = None
    if kind:
        fobj = obj[-1] if kind == "photo" else obj
        info = await api("getFile", file_id=fobj["file_id"])
        if not info:
            raise Exception("file download nahi hui (limit 20MB)")
        ext = os.path.splitext(info["file_path"])[1]
        if kind == "sticker":
            ext = ".tgs" if obj.get("is_animated") else ".webm" if obj.get("is_video") else ".webp"
        path = f"media/reply{ext}"
        resp = await http.get(f"{FILE}/{info['file_path']}")
        open(path, "wb").write(resp.content)
        data["media"] = {"kind": kind, "path": path, "fid": fobj["file_id"],
                         "emoji": obj.get("emoji") if kind == "sticker" else None}
    data["message"] = to_html(plain, ents)
    data["plain"] = plain
    save()

async def finish_login():
    global temp
    data["session"] = temp.session.save(); save()
    await temp.disconnect(); temp = None
    ok = await start_user(data["session"])
    state.clear()
    await edit_home() if ok else await edit_menu(prompt("❌ " + sc("login fail")), BACK)

async def on_msg(m):
    global temp
    if m["chat"]["id"] != OWNER_ID or m["from"]["id"] != OWNER_ID or m["chat"]["type"] != "private":
        return
    txt = (m.get("text") or "").strip()
    mid = m["message_id"]
    if txt.startswith("/start"):
        state.clear()
        await api("deleteMessage", chat_id=OWNER_ID, message_id=mid)
        return await send_menu()
    step = state.get("step")
    await_delete = True
    try:
        if step == "msg":
            await set_reply(m)
            state.clear()
            await edit_home()
        elif step == "cd":
            data["cooldown"] = float(txt); save(); state.clear()
            await edit_home()
        elif step == "phone":
            temp = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp.connect()
            sent = await temp.send_code_request(txt)
            state.update(step="code", phone=txt, hash=sent.phone_code_hash)
            await edit_menu(prompt(
                f"📩 {sc('telegram ne otp bheja hai')}\n\n"
                f"⚠️ {sc('otp spaces ke saath bhejo')} : <code>1 2 3 4 5</code>\n"
                f"{sc('(warna telegram code expire kar deta hai)')}"), BACK)
        elif step == "code":
            code = "".join(ch for ch in txt if ch.isdigit())
            try:
                await temp.sign_in(state["phone"], code, phone_code_hash=state["hash"])
            except SessionPasswordNeededError:
                state["step"] = "2fa"
                await edit_menu(prompt(f"🔐 {sc('2-step password bhejo')}"), BACK)
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                await edit_menu(prompt("❌ " + sc("otp galat ya expire. dobara bhejo")), BACK)
            else:
                await finish_login()
        elif step == "2fa":
            try:
                await temp.sign_in(password=txt)
            except PasswordHashInvalidError:
                await edit_menu(prompt("❌ " + sc("password galat. dobara bhejo")), BACK)
            else:
                await finish_login()
    except Exception as e:
        state.clear()
        await edit_menu(prompt(f"⚠️ {sc('error')} : <code>{html.escape(str(e))[:300]}</code>"), BACK)
    if await_delete:       # chat clean rakho (OTP/password turant delete)
        await api("deleteMessage", chat_id=OWNER_ID, message_id=mid)

async def handle(u):
    try:
        if "callback_query" in u:
            await on_cb(u["callback_query"])
        elif "message" in u:
            await on_msg(u["message"])
    except Exception as e:
        print("handler error:", e)

async def main():
    await api("deleteWebhook")
    if data["session"]:
        await start_user(data["session"])
    asyncio.create_task(cleaner())
    print("Bot chalu hai...")
    offset = None
    while True:
        try:
            r = await http.post(f"{BASE}/getUpdates", timeout=45,
                                json={"timeout": 30, "offset": offset,
                                      "allowed_updates": ["message", "callback_query"]})
            for u in r.json().get("result", []):
                offset = u["update_id"] + 1
                await handle(u)
        except Exception as e:
            print("poll error:", e)
            await asyncio.sleep(3)

asyncio.run(main())
