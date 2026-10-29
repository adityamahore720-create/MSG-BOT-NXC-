import asyncio, html, json, mimetypes, os, re, time
import httpx
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon import utils
from telethon.tl import types as tl
from telethon.tl.types import (DocumentAttributeSticker, DocumentAttributeAnimated,
                               InputStickerSetEmpty)
from telethon.errors import (SessionPasswordNeededError, PhoneCodeInvalidError,
                             PhoneCodeExpiredError, PasswordHashInvalidError, FloodWaitError)

API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
BRAND = os.getenv("BRAND", "Miss Chutki")
OWNER_CONTACT = "https://t.me/NXC_OWNERJI"

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
           "media": None, "replied": {}, "pending": [], "menus": {}, "start_fid": "",
           "admins": []}
data = dict(DEFAULT)
if os.path.exists(DATA_FILE):
    data.update(json.load(open(DATA_FILE)))

def save():
    json.dump(data, open(DATA_FILE, "w"))

def is_owner(uid):
    return uid == OWNER_ID

def is_admin(uid):
    return uid == OWNER_ID or uid in data["admins"]

# ---------- small caps font ----------
_SC = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ")

def sc(text):
    parts = re.split(r"(<[^>]+>)", text)
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
            if "not modified" not in str(j.get("description")):
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

def home_kb(uid):
    on = data["enabled"]
    kb = [
        [B("🟢 Auto-Reply : ON" if on else "🔴 Auto-Reply : OFF", "toggle", "success" if on else "danger")],
        [B("✏️ Set Reply", "setmsg", "primary"), B("👁 Preview", "preview", "primary")],
        [B("⏱ Cooldown", "cd", "primary"), B("🔄 Refresh", "home", "primary")],
    ]
    if is_owner(uid):
        kb.append([B("🔑 Login", "login", "success"), B("🚪 Logout", "logout", "danger")])
        kb.append([B("👑 Admins", "admins", "primary")])
    return kb

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

def prompt(text):
    return f"✦ <b>{sc(BRAND)}</b> ✦\n\n{text}"

async def send_card(uid, caption, kb):
    """Start photo (spoiler) + caption + buttons."""
    r = None
    markup = {"inline_keyboard": kb}
    if data.get("start_fid"):
        r = await api("sendPhoto", chat_id=uid, photo=data["start_fid"], caption=caption,
                      parse_mode="HTML", has_spoiler=True, reply_markup=markup)
    if not r:
        with open(START_IMG, "rb") as f:
            resp = await http.post(f"{BASE}/sendPhoto",
                                   data={"chat_id": uid, "caption": caption, "parse_mode": "HTML",
                                         "has_spoiler": "true", "reply_markup": json.dumps(markup)},
                                   files={"photo": f})
        j = resp.json()
        r = j.get("result") if j.get("ok") else None
        if r:
            data["start_fid"] = r["photo"][-1]["file_id"]
            save()
    return r

async def send_menu(uid):
    old = data["menus"].get(str(uid))
    if old:
        await api("deleteMessage", chat_id=uid, message_id=old)
    r = await send_card(uid, home_text(), home_kb(uid))
    if r:
        data["menus"][str(uid)] = r["message_id"]
        save()

async def send_unauth(uid):
    cap = (f"✦ <b>{sc(BRAND)}</b> ✦\n\n🔒 {sc('access denied')}\n"
           f"{sc('is bot ko use karne ke liye admin hona zaroori hai.')}\n"
           f"{sc('access ke liye owner se connect karo')} 👇")
    kb = [[{"text": sc("👑 contact owner"), "url": OWNER_CONTACT, "style": "primary"}]]
    await send_card(uid, cap, kb)

async def edit_menu(uid, caption, kb):
    return await api("editMessageCaption", chat_id=uid, message_id=data["menus"].get(str(uid)),
                     caption=caption, parse_mode="HTML", reply_markup={"inline_keyboard": kb})

async def edit_home(uid):
    await edit_menu(uid, home_text(), home_kb(uid))

def admins_view():
    lines = "\n".join(f"• <a href=\"tg://user?id={a}\">{a}</a>" for a in data["admins"]) or f"• {sc('koi admin nahi')}"
    text = prompt(f"👑 {sc('admins')}\n\n{sc('owner')} : <a href=\"tg://user?id={OWNER_ID}\">{OWNER_ID}</a>\n\n{lines}\n\n"
                  f"{sc('admin ko login/logout/admin-control nahi milta.')}")
    kb = [[B("➕ Add Admin", "addadm", "success")]]
    for a in data["admins"]:
        kb.append([B(f"❌ Remove {a}", f"rm:{a}", "danger")])
    kb.append(BACK[0])
    return text, kb

# ---------- user account (auto reply) ----------
user = None
temp = None
me_id = 0
state = {}          # uid -> {"step": ...}

media_cache = None            # media ek baar upload hoke yahan cache hota hai (rate-limit se bachne ke liye)
send_lock = asyncio.Lock()    # replies ek ek karke jayenge
SPOILER_KINDS = ("photo", "video", "animation")

def media_args(m):
    kind = m["kind"]
    kw, attrs = {}, None
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
    return kw, attrs

async def build_media_cache(m):
    """Media ko Saved Messages me ek baar upload karo, phir sirf reference reuse hota hai."""
    kw, attrs = media_args(m)
    msg = await user.send_file("me", m["path"], attributes=attrs, **kw)
    sp = m["kind"] in SPOILER_KINDS
    med = msg.media
    if getattr(med, "photo", None):
        return tl.InputMediaPhoto(id=utils.get_input_photo(med.photo), spoiler=sp)
    return tl.InputMediaDocument(id=utils.get_input_document(med.document), spoiler=sp)

async def send_reply(event, name):
    global media_cache
    text = data["message"].replace("{name}", html.escape(name))
    m = data.get("media")
    sent = []
    if m and os.path.exists(m["path"]):
        no_caption = m["kind"] in ("sticker", "video_note")
        cap = None if no_caption or not text.strip() else text
        args = dict(reply_to=event.id, caption=cap, parse_mode="html")
        if media_cache is None:
            media_cache = await build_media_cache(m)
        try:
            msg = await user.send_file(event.chat_id, media_cache, **args)
        except FloodWaitError:
            raise
        except Exception as e:
            if "too many" in str(e).lower():
                raise
            print("media cache rebuild:", e)           # file reference expire hua to dobara banao
            media_cache = await build_media_cache(m)
            msg = await user.send_file(event.chat_id, media_cache, **args)
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
    sid = event.sender_id
    if not sid or sid in (me_id, 777000):
        return
    name = "dost"
    try:
        sender = await event.get_sender()
        if sender is not None:
            if getattr(sender, "bot", False):
                return
            name = (getattr(sender, "first_name", "") or "").strip() or "dost"
    except Exception:
        pass
    now = time.time()
    if now - data["replied"].get(str(sid), 0) < data["cooldown"] * 3600:
        return
    try:
        async with send_lock:
            await send_reply(event, name)
            await asyncio.sleep(1.5)         # thoda gap, taaki Telegram rate-limit na kare
        data["replied"][str(sid)] = now      # sirf success hone par cooldown lagta hai
        save()
    except FloodWaitError as e:
        print(f"flood wait {e.seconds}s - is user ko baad me reply milega:", sid)
    except Exception as e:
        print("reply error:", sid, e)

async def cleaner():
    """5 minute purane auto-replies automatic delete."""
    while True:
        await asyncio.sleep(15)
        if not user or not data["pending"]:
            continue
        try:
            if not user.is_connected():
                await user.connect()
        except Exception as e:
            print("reconnect error:", e)
            continue
        now = time.time()
        keep = []
        for chat, mid, due in data["pending"]:
            if due > now:
                keep.append([chat, mid, due])
                continue
            try:
                await user.delete_messages(chat, [mid], revoke=True)
            except Exception as e:
                print("delete error:", e)
                if now - due < 3600:             # 1 ghante tak dobara try
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
OWNER_ONLY = {"login", "logout", "admins", "addadm"}

async def on_cb(q):
    global user, temp
    uid = q["from"]["id"]
    cid = q["id"]
    d = q["data"]
    if not is_admin(uid):
        return await api("answerCallbackQuery", callback_query_id=cid,
                         text=sc("access denied - owner se connect karo"), show_alert=True)
    if (d in OWNER_ONLY or d.startswith("rm:")) and not is_owner(uid):
        return await api("answerCallbackQuery", callback_query_id=cid,
                         text=sc("sirf owner ke liye"), show_alert=True)
    data["menus"][str(uid)] = q["message"]["message_id"]
    ans = lambda **k: api("answerCallbackQuery", callback_query_id=cid, **k)

    if d == "home":
        state.pop(uid, None)
        if temp and is_owner(uid):
            await temp.disconnect(); temp = None
        await ans()
        return await edit_home(uid)
    if d == "toggle":
        if not user:
            return await ans(text=sc("pehle owner login kare!"), show_alert=True)
        data["enabled"] = not data["enabled"]; save()
        await ans()
        return await edit_home(uid)
    if d == "setmsg":
        state[uid] = {"step": "msg"}
        await ans()
        return await edit_menu(uid, prompt(
            f"✏️ {sc('naya auto-reply bhejo')}\n\n"
            f"• {sc('text, photo, video, sticker, gif, voice, file - sab chalega')}\n"
            f"• {sc('photo/video user ko spoiler (hide) me jayegi')}\n"
            f"• {sc('bold/italic/link formatting telegram se hi lagao')}\n"
            f"• <code>{{name}}</code> = {sc('sender ka naam')}"), BACK)
    if d == "preview":
        await ans()
        return await send_preview(uid)
    if d == "cd":
        state[uid] = {"step": "cd"}
        await ans()
        return await edit_menu(uid, prompt(
            f"⏱ {sc('ek bande ko dobara reply kitne ghante baad?')}\n"
            f"{sc('example')} : <code>6</code> / <code>0.5</code>\n"
            f"<code>0</code> = {sc('har message par reply')}"), BACK)
    if d == "login":
        if user:
            return await ans(text=sc("already logged in"), show_alert=True)
        state[uid] = {"step": "phone"}
        await ans()
        return await edit_menu(uid, prompt(
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
        await ans(text=sc("logout ho gaya"), show_alert=True)
        return await edit_home(uid)
    if d == "admins":
        await ans()
        t, kb = admins_view()
        return await edit_menu(uid, t, kb)
    if d == "addadm":
        state[uid] = {"step": "addadm"}
        await ans()
        return await edit_menu(uid, prompt(
            f"➕ {sc('naye admin ki numeric telegram id bhejo')}\n"
            f"{sc('(id @userinfobot se milti hai)')}\n\n"
            f"{sc('us bande ko bot me /start karna hoga')}"), [[B("⬅️ Back", "admins", "primary")]])
    if d.startswith("rm:"):
        a = int(d[3:])
        if a in data["admins"]:
            data["admins"].remove(a); save()
        await ans(text=sc("admin hata diya"))
        t, kb = admins_view()
        return await edit_menu(uid, t, kb)

async def send_preview(uid):
    text = data["message"].replace("{name}", "Rahul")
    m = data.get("media")
    ids = []
    if m:
        k = m["kind"]
        method = {"photo": "sendPhoto", "video": "sendVideo", "animation": "sendAnimation",
                  "sticker": "sendSticker", "voice": "sendVoice", "audio": "sendAudio",
                  "video_note": "sendVideoNote", "document": "sendDocument"}[k]
        p = {"chat_id": uid, k: m["fid"]}
        if k in ("photo", "video", "animation"):
            p["has_spoiler"] = True
        if k not in ("sticker", "video_note") and text.strip():
            p.update(caption=text, parse_mode="HTML")
        r = await api(method, **p)
        if r: ids.append(r["message_id"])
        if k in ("sticker", "video_note") and text.strip():
            r = await api("sendMessage", chat_id=uid, text=text, parse_mode="HTML")
            if r: ids.append(r["message_id"])
    else:
        r = await api("sendMessage", chat_id=uid, text=text or "—", parse_mode="HTML")
        if r: ids.append(r["message_id"])
    async def later():
        await asyncio.sleep(20)
        for i in ids:
            await api("deleteMessage", chat_id=uid, message_id=i)
    asyncio.create_task(later())

async def set_reply(m):
    global media_cache
    media_cache = None
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

async def finish_login(uid):
    global temp
    data["session"] = temp.session.save(); save()
    await temp.disconnect(); temp = None
    ok = await start_user(data["session"])
    state.pop(uid, None)
    if ok:
        await edit_home(uid)
    else:
        await edit_menu(uid, prompt("❌ " + sc("login fail")), BACK)

async def on_msg(m):
    global temp
    if m["chat"]["type"] != "private":
        return
    uid = m["from"]["id"]
    if not is_admin(uid):
        return await send_unauth(uid)          # bina admin ke -> owner contact button
    txt = (m.get("text") or "").strip()
    mid = m["message_id"]
    if txt.startswith("/start"):
        state.pop(uid, None)
        await api("deleteMessage", chat_id=uid, message_id=mid)
        return await send_menu(uid)
    step = state.get(uid, {}).get("step")
    if not step:
        return await api("deleteMessage", chat_id=uid, message_id=mid)
    st = state[uid]
    try:
        if step == "msg":
            await set_reply(m)
            state.pop(uid, None)
            await edit_home(uid)
        elif step == "cd":
            data["cooldown"] = float(txt); save(); state.pop(uid, None)
            await edit_home(uid)
        elif step == "addadm" and is_owner(uid):
            a = int(txt)
            if a != OWNER_ID and a not in data["admins"]:
                data["admins"].append(a); save()
            state.pop(uid, None)
            t, kb = admins_view()
            await edit_menu(uid, t, kb)
        elif step == "phone" and is_owner(uid):
            temp = TelegramClient(StringSession(), API_ID, API_HASH)
            await temp.connect()
            sent = await temp.send_code_request(txt)
            st.update(step="code", phone=txt, hash=sent.phone_code_hash)
            await edit_menu(uid, prompt(
                f"📩 {sc('telegram ne otp bheja hai')}\n\n"
                f"⚠️ {sc('otp spaces ke saath bhejo')} : <code>1 2 3 4 5</code>\n"
                f"{sc('(warna telegram code expire kar deta hai)')}"), BACK)
        elif step == "code" and is_owner(uid):
            code = "".join(ch for ch in txt if ch.isdigit())
            try:
                await temp.sign_in(st["phone"], code, phone_code_hash=st["hash"])
            except SessionPasswordNeededError:
                st["step"] = "2fa"
                await edit_menu(uid, prompt(f"🔐 {sc('2-step password bhejo')}"), BACK)
            except (PhoneCodeInvalidError, PhoneCodeExpiredError):
                await edit_menu(uid, prompt("❌ " + sc("otp galat ya expire. dobara bhejo")), BACK)
            else:
                await finish_login(uid)
        elif step == "2fa" and is_owner(uid):
            try:
                await temp.sign_in(password=txt)
            except PasswordHashInvalidError:
                await edit_menu(uid, prompt("❌ " + sc("password galat. dobara bhejo")), BACK)
            else:
                await finish_login(uid)
    except Exception as e:
        state.pop(uid, None)
        await edit_menu(uid, prompt(f"⚠️ {sc('error')} : <code>{html.escape(str(e))[:300]}</code>"), BACK)
    await api("deleteMessage", chat_id=uid, message_id=mid)    # OTP/password turant delete

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
