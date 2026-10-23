"""The /settings control panel: builds every menu (text + inline buttons).

Callback-data map (all handled in plugins/settings_panel.py):
  m:<menu>        open a menu            n:<key>          open a numeric editor
  np:<key>:<val>  set a preset value     t:<key>          toggle an on/off setting
  in:<action>     ask the admin to type  ic:cancel        cancel typing
  f/fm/fl/fd/fdy  force-sub channel      a/at/ad          verification API
  g/gp/gr/gx      messages               bc:go / bc:no    broadcast confirm
"""
from __future__ import annotations

import re
from typing import Optional

from telegram import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup

from fsbot import admins, messages, settings
from fsbot.db import get_db
from fsbot.utils import chunked, h, human_duration

ON, OFF = "✅ ON", "❌ OFF"

# Numeric settings: how they are labelled, which preset buttons they get, where "Back" goes.
NUMERIC: dict[str, dict] = {
    "verify_free_hours": {
        "label": "⏱ Free access time", "unit": "h", "presets": [6, 12, 24, 48, 72], "back": "verify",
        "desc": "How long a user keeps free access after the LAST verification step."},
    "verify_gap_hours": {
        "label": "⏳ Gap between verifications", "unit": "h", "presets": [1, 3, 6, 12, 24], "back": "verify",
        "desc": "2-step mode: how long access lasts after step 1, before step 2 is asked."},
    "link_limit": {
        "label": "🔗 Links per window", "unit": "", "presets": [3, 5, 7, 10, 15, 20], "back": "verify",
        "desc": "How many verification links one user may generate inside the window below."},
    "link_window_hours": {
        "label": "🕐 Link-limit window", "unit": "h", "presets": [6, 12, 24, 48], "back": "verify",
        "desc": "The time window used by the link limit above."},
    "token_expiry_minutes": {
        "label": "⌛ Verification link expiry", "unit": "m", "presets": [5, 10, 15, 30, 60], "back": "verify",
        "desc": "An unused verification link stops working after this long."},
    "verify_min_seconds": {
        "label": "🛡 Anti-bypass minimum time", "unit": "s", "presets": [0, 5, 8, 15, 30], "back": "verify",
        "desc": "A verification link opened faster than this is rejected (blocks bypass bots)."},
    "auto_delete_seconds": {
        "label": "🗑 Auto-delete timer", "unit": "s", "zero": "Off", "back": "main",
        "presets": [0, 300, 600, 1800, 3600, 21600, 86400],
        "desc": "Delivered files are deleted from the user's chat after this long."},
    "link_expiry_hours": {
        "label": "⌛ File-link expiry", "unit": "h", "zero": "Never", "back": "links",
        "presets": [0, 24, 72, 168, 720],
        "desc": "Links you create stop working this long after creation."},
}

TOGGLE_BACK = {
    "verify_enabled": "verify", "verify_steps": "verify", "protect_content": "protect",
    "fsub_auto_approve": "fsub", "maintenance": "main",
}
MSG_LABELS = {
    "welcome": "👋 Welcome message", "fsub": "📢 Join prompt",
    "verify": "🔐 Verification prompt", "wait": "⏳ Please-wait message",
}
INPUT_ACTIONS = {"num", "api", "msgtext", "msgphoto", "fsubadd", "ban", "unban", "addadmin", "deladmin", "broadcast"}


# ------------------------------------------------------------------ helpers
def on_off(value: bool) -> str:
    return ON if value else OFF


def fmt_value(key: str, value: Optional[float] = None) -> str:
    spec = NUMERIC[key]
    value = settings.get(key) if value is None else value
    if value == 0 and spec.get("zero"):
        return spec["zero"]
    unit = spec["unit"]
    if unit == "h":
        return human_duration(value * 3600)
    if unit == "m":
        return human_duration(value * 60)
    if unit == "s":
        return human_duration(value)
    return f"{value:g}"


_AMOUNT = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$", re.I)
_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def parse_amount(text: str, unit: str) -> Optional[float]:
    """'12' / '90m' / '2h' / '1d' -> a number in the setting's own unit (None if invalid)."""
    match = _AMOUNT.match(text or "")
    if not match:
        return None
    number, suffix = float(match.group(1)), match.group(2).lower()
    if not suffix:
        return number
    if unit not in _UNIT_SECONDS:  # plain counts take no time suffix
        return None
    return number * _TO_SECONDS[suffix] / _UNIT_SECONDS[unit]


def normalize(key: str, value: float) -> str:
    """Whole numbers for integer settings (minutes, seconds, counts)."""
    return str(round(value)) if settings.SPEC[key].kind == "int" else f"{value:g}"


_DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/[A-Za-z0-9._~/-]*)?$", re.I)


def parse_domain(text: str) -> Optional[str]:
    """'gplinks.com' (with or without http) -> 'https://gplinks.com/api'."""
    value = re.sub(r"^https?://", "", (text or "").strip(), flags=re.I).rstrip("/")
    if not _DOMAIN.match(value):
        return None
    host, _, path = value.partition("/")
    return f"https://{host.lower()}/{path or 'api'}"


def mask(key: str) -> str:
    return "—" if not key else (key[:4] + "…" + key[-3:] if len(key) > 8 else "••••")


def _back(target: str = "main") -> list:
    return [Button("⬅️ Back", callback_data=f"m:{target}")]


def _api_is_set(step: int) -> bool:
    return bool(settings.raw(f"api{step}_url")) or (step == 1 and bool(settings.get_api(1)[0]))


# ------------------------------------------------------------------ prompts
def input_hint(key: str) -> str:
    unit = NUMERIC[key]["unit"]
    if unit == "":
        return "Send a whole number, e.g. <code>7</code>."
    word = {"h": "hours", "m": "minutes", "s": "seconds"}[unit]
    return (f"Send a number of {word}, e.g. <code>12</code> — or a time like "
            f"<code>90m</code>, <code>2h</code>, <code>1d</code>. Send <code>0</code> to switch it off where that applies.")


def api_key_prompt(step: int, url: str) -> str:
    return (f"🔑 <b>Verification API {step}</b>\n\n✅ URL: <code>{h(url)}</code>\n\n"
            "Now send the <b>API key</b> (just the key, nothing else).")


def input_prompt(action: str, arg: str) -> str:
    if action == "num":
        spec = NUMERIC[arg]
        return (f"✏️ <b>{spec['label']}</b>\nCurrent: <b>{fmt_value(arg)}</b>\n\n{input_hint(arg)}")
    if action == "api":
        return (f"🔑 <b>Verification API {arg}</b>\n\nSend the shortener's domain <b>without http</b>, "
                "e.g. <code>gplinks.com</code>.\n(If its API path is not /api, send it with the path: "
                "<code>api.example.com/shorten</code>.)")
    if action == "msgtext":
        return (f"✏️ <b>{MSG_LABELS[arg]}</b>\n\nSend the new text. HTML formatting is kept.\n"
                f"Placeholders: <code>{messages.PLACEHOLDERS[arg]}</code>")
    if action == "msgphoto":
        return (f"🖼 <b>{MSG_LABELS[arg]}</b>\n\nSend the poster <b>photo</b>. "
                "If you add a caption, it becomes the new text as well.")
    if action == "fsubadd":
        return ("📢 <b>Add force-subscribe channel</b>\n\nForward <b>any post</b> from the channel (the bot must be admin "
                "there), or send its channel ID.\nPublic channels get a join button, private ones a join-request link.")
    if action in {"ban", "unban"}:
        return f"{'🚫 <b>Ban' if action == 'ban' else '✅ <b>Unban'} a user</b>\n\nSend the user's numeric ID."
    if action in {"addadmin", "deladmin"}:
        return f"👑 <b>{'Add' if action == 'addadmin' else 'Remove'} an admin</b>\n\nSend the user's numeric ID."
    return "📣 <b>Broadcast</b>\n\nSend the message you want to deliver to every user (text, photo, file — anything)."


# ------------------------------------------------------------------- stats
async def stats_text() -> str:
    s = await get_db().stats()
    return (
        "📊 <b>Statistics</b>\n\n"
        f"Users: <b>{s['users']}</b> (active {s['active']}, banned {s['banned']})\n"
        f"Links: <b>{s['single'] + s['batch'] + s['custom']}</b> "
        f"(single {s['single']}, batch {s['batch']}, custom {s['custom']})\n"
        f"Force-sub channels: <b>{s['fsub']}</b>\n"
        f"Files waiting for auto-delete: <b>{s['scheduled']}</b>"
    )


# ------------------------------------------------------------------- menus
async def _main(_arg):
    channels = len(await get_db().list_fsub())
    steps = int(settings.get("verify_steps"))
    text = (
        "⚙️ <b>Settings</b>\n\n"
        f"🔐 Verification: <b>{on_off(settings.get('verify_enabled'))}</b> · {steps} step{'s' if steps != 1 else ''}"
        f" · free {fmt_value('verify_free_hours')} · gap {fmt_value('verify_gap_hours')}\n"
        f"📢 Force-subscribe: <b>{channels}</b> channel{'s' if channels != 1 else ''}\n"
        f"🛡 Protect content: <b>{on_off(settings.get('protect_content'))}</b>\n"
        f"🗑 Auto-delete: <b>{fmt_value('auto_delete_seconds')}</b>\n"
        f"🔗 File-link expiry: <b>{fmt_value('link_expiry_hours')}</b>\n"
        f"🚧 Maintenance: <b>{on_off(settings.get('maintenance'))}</b>\n\n"
        "Tap a button to open it. Every change applies instantly."
    )
    rows = [
        [Button("🔐 Verification", callback_data="m:verify"), Button("📢 Force-Subscribe", callback_data="m:fsub")],
        [Button("🛡 Protection", callback_data="m:protect"), Button("🗑 Auto-Delete", callback_data="n:auto_delete_seconds")],
        [Button("💬 Messages", callback_data="m:msgs"), Button("🔗 Links", callback_data="m:links")],
        [Button("👥 Users", callback_data="m:users"), Button(f"🚧 Maintenance: {on_off(settings.get('maintenance'))}", callback_data="t:maintenance")],
        [Button("📊 Stats", callback_data="m:stats"), Button("❌ Close", callback_data="x:close")],
    ]
    return text, Markup(rows)


async def _verify(_arg):
    steps = int(settings.get("verify_steps"))
    api = lambda step: ("✅ set" if _api_is_set(step) else ("⚠️ not set" + (" (uses API 1)" if step == 2 and _api_is_set(1) else "")))
    text = (
        "🔐 <b>Verification</b>\n\n"
        f"Status: <b>{on_off(settings.get('verify_enabled'))}</b> · Steps: <b>{steps}</b>\n"
        f"⏱ Free access after the last step: <b>{fmt_value('verify_free_hours')}</b>\n"
        f"⏳ Gap between step 1 and step 2: <b>{fmt_value('verify_gap_hours')}</b>"
        f"{'' if steps == 2 else ' <i>(only used in 2-step mode)</i>'}\n"
        f"🔗 Link limit: <b>{fmt_value('link_limit')}</b> per <b>{fmt_value('link_window_hours')}</b>\n"
        f"⌛ Link expiry: <b>{fmt_value('token_expiry_minutes')}</b> · 🛡 Min time: <b>{fmt_value('verify_min_seconds')}</b>\n"
        f"🔑 API 1: {api(1)} · API 2: {api(2)}\n\n"
        "<i>Flow: step 1 is asked immediately → gap of access → step 2 → free access → repeat.</i>"
    )
    button = lambda label, cb: Button(label, callback_data=cb)
    rows = [
        [button(f"🔐 Verification: {on_off(settings.get('verify_enabled'))}", "t:verify_enabled"),
         button(f"🔢 Steps: {steps}", "t:verify_steps")],
        [button(f"⏱ Free access: {fmt_value('verify_free_hours')}", "n:verify_free_hours")],
        [button(f"⏳ Gap time: {fmt_value('verify_gap_hours')}", "n:verify_gap_hours")],
        [button(f"🔗 Link limit: {fmt_value('link_limit')}", "n:link_limit"),
         button(f"🕐 Window: {fmt_value('link_window_hours')}", "n:link_window_hours")],
        [button(f"⌛ Expiry: {fmt_value('token_expiry_minutes')}", "n:token_expiry_minutes"),
         button(f"🛡 Min time: {fmt_value('verify_min_seconds')}", "n:verify_min_seconds")],
        [button(f"🔑 API 1 {'✅' if _api_is_set(1) else '⚠️'}", "a:1"), button(f"🔑 API 2 {'✅' if _api_is_set(2) else '⚠️'}", "a:2")],
        _back(),
    ]
    return text, Markup(rows)


async def _numeric(key):
    spec, current = NUMERIC[key], settings.get(key)
    text = f"{spec['label']}\n\n{spec['desc']}\n\nCurrent: <b>{fmt_value(key)}</b>\nPick a preset or tap <b>Custom</b>."
    presets = [
        Button(("✅ " if abs(p - current) < 1e-9 else "") + fmt_value(key, p), callback_data=f"np:{key}:{p:g}")
        for p in spec["presets"]
    ]
    rows = list(chunked(presets, 3)) + [[Button("✏️ Custom", callback_data=f"in:num:{key}")], _back(spec["back"])]
    return text, Markup(rows)


async def _api(arg):
    step = int(arg)
    url, key = settings.get_api(step)
    own = _api_is_set(step) and (bool(settings.raw(f"api{step}_url")) or step == 1)
    note = "" if own or step == 1 else "\n<i>Not set — this step uses API 1.</i>"
    text = (
        f"🔑 <b>Verification API {step}</b>{note}\n\n"
        f"URL: <code>{h(url or '—')}</code>\nKey: <code>{h(mask(key))}</code>\n\n"
        "Use <b>Set / Change</b>: first the domain (without http), then the API key."
    )
    rows = [
        [Button("✏️ Set / Change", callback_data=f"in:api:{step}"), Button("🧪 Test", callback_data=f"at:{step}")],
        [Button("🗑 Remove", callback_data=f"ad:{step}")],
        _back("verify"),
    ]
    return text, Markup(rows)


async def _fsub(_arg):
    channels = await get_db().list_fsub()
    lines = ["📢 <b>Force-Subscribe</b>", ""]
    if channels:
        for ch in channels:
            lines.append(f"• <b>{h(ch['title'])}</b> — {'🔐 request' if ch['mode'] == 'request' else '📢 direct'}")
    else:
        lines.append("No channels yet. Users can open links freely.")
    lines += ["", f"Auto-approve join requests: <b>{on_off(settings.get('fsub_auto_approve'))}</b>"]
    rows = [[Button(f"{'🔐' if ch['mode'] == 'request' else '📢'} {ch['title']}", callback_data=f"f:{ch['chat_id']}")] for ch in channels]
    rows += [
        [Button("➕ Add channel", callback_data="in:fsubadd")],
        [Button(f"✅ Auto-approve: {on_off(settings.get('fsub_auto_approve'))}", callback_data="t:fsub_auto_approve")],
        _back(),
    ]
    return "\n".join(lines), Markup(rows)


async def _find_channel(arg):
    return next((c for c in await get_db().list_fsub() if str(c["chat_id"]) == str(arg)), None)


async def _channel(arg):
    ch = await _find_channel(arg)
    if ch is None:
        return await _fsub(None)
    is_request = ch["mode"] == "request"
    text = (
        f"📢 <b>{h(ch['title'])}</b>\n<code>{ch['chat_id']}</code>\n\n"
        f"Mode: <b>{'🔐 Request (private channel — a join request is enough)' if is_request else '📢 Direct (users must join)'}</b>"
    )
    rows = [
        [Button("🔁 Switch to Direct" if is_request else "🔁 Switch to Request", callback_data=f"fm:{ch['chat_id']}")],
        [Button("🔗 New invite link", callback_data=f"fl:{ch['chat_id']}"), Button("🗑 Remove", callback_data=f"fd:{ch['chat_id']}")],
        _back("fsub"),
    ]
    return text, Markup(rows)


async def _confirm_remove(arg):
    ch = await _find_channel(arg)
    if ch is None:
        return await _fsub(None)
    rows = [[Button("✅ Yes, remove", callback_data=f"fdy:{ch['chat_id']}"), Button("❌ No", callback_data=f"f:{ch['chat_id']}")]]
    return f"🗑 Remove <b>{h(ch['title'])}</b> from force-subscribe?", Markup(rows)


async def _protect(_arg):
    text = (
        "🛡 <b>Protection</b>\n\n"
        f"Protect content: <b>{on_off(settings.get('protect_content'))}</b>\n"
        "When ON, delivered files cannot be forwarded, saved or screenshot-shared from Telegram.\n\n"
        f"🗑 Auto-delete timer: <b>{fmt_value('auto_delete_seconds')}</b>"
    )
    rows = [
        [Button(f"🛡 Protect content: {on_off(settings.get('protect_content'))}", callback_data="t:protect_content")],
        [Button(f"🗑 Auto-delete: {fmt_value('auto_delete_seconds')}", callback_data="n:auto_delete_seconds")],
        _back(),
    ]
    return text, Markup(rows)


async def _msgs(_arg):
    lines = ["💬 <b>Messages</b>", "", "Pick a message to edit its text or poster photo.", ""]
    for name, label in MSG_LABELS.items():
        stored = settings.raw(f"msg_{name}") or {}
        lines.append(f"{label}: {'✏️ custom' if stored.get('text') else 'default'}"
                     f"{' · 🖼 photo' if stored.get('photo') else ''}")
    names = list(MSG_LABELS)
    rows = list(chunked([Button(MSG_LABELS[n], callback_data=f"g:{n}") for n in names], 2)) + [_back()]
    return "\n".join(lines), Markup(rows)


async def _message(name):
    stored = settings.raw(f"msg_{name}") or {}
    text = (
        f"{MSG_LABELS[name]}\n\n"
        f"Text: <b>{'✏️ custom' if stored.get('text') else 'default'}</b>\n"
        f"Poster photo: <b>{'🖼 set' if stored.get('photo') else 'none'}</b>"
        f"{'' if name in messages.PHOTO_NAMES else ' <i>(this message is text only)</i>'}\n"
        f"Placeholders: <code>{messages.PLACEHOLDERS[name]}</code>"
    )
    first = [Button("✏️ Set text", callback_data=f"in:msgtext:{name}")]
    if name in messages.PHOTO_NAMES:
        first.append(Button("🖼 Set photo", callback_data=f"in:msgphoto:{name}"))
    second = [Button("🔄 Reset", callback_data=f"gr:{name}")]
    if name in messages.PHOTO_NAMES:
        second.insert(0, Button("🗑 Remove photo", callback_data=f"gx:{name}"))
    rows = [first, second, [Button("👁 Preview", callback_data=f"gp:{name}")], _back("msgs")]
    return text, Markup(rows)


async def _links(_arg):
    s = await get_db().stats()
    text = (
        "🔗 <b>Links</b>\n\n"
        f"Created: <b>{s['single'] + s['batch'] + s['custom']}</b> "
        f"(single {s['single']}, batch {s['batch']}, custom {s['custom']})\n"
        f"⌛ File-link expiry: <b>{fmt_value('link_expiry_hours')}</b>\n\n"
        "Create links with /single, /batch and /custombatch. Delete one with /revoke &lt;link&gt;."
    )
    rows = [[Button(f"⌛ Link expiry: {fmt_value('link_expiry_hours')}", callback_data="n:link_expiry_hours")], _back()]
    return text, Markup(rows)


async def _users(_arg):
    s = await get_db().stats()
    text = f"👥 <b>Users</b>\n\nTotal <b>{s['users']}</b> · active <b>{s['active']}</b> · banned <b>{s['banned']}</b>"
    rows = [
        [Button("🚫 Ban user", callback_data="in:ban"), Button("✅ Unban user", callback_data="in:unban")],
        [Button("📣 Broadcast", callback_data="in:broadcast"), Button("👑 Admins", callback_data="m:admins")],
        _back(),
    ]
    return text, Markup(rows)


async def _admins_menu(_arg):
    lines = ["👑 <b>Admins</b>", ""]
    lines += [f"• <code>{uid}</code>{' (owner)' if admins.is_owner(uid) else ''}" for uid in admins.all_admins()]
    lines += ["", "Only owners can add or remove admins."]
    rows = [
        [Button("➕ Add admin", callback_data="in:addadmin"), Button("➖ Remove admin", callback_data="in:deladmin")],
        _back("users"),
    ]
    return "\n".join(lines), Markup(rows)


async def _stats(_arg):
    return await stats_text(), Markup([_back()])


_BUILDERS = {
    "main": _main, "verify": _verify, "numeric": _numeric, "api": _api, "fsub": _fsub, "channel": _channel,
    "confirm_remove": _confirm_remove, "protect": _protect, "msgs": _msgs, "message": _message,
    "links": _links, "users": _users, "admins": _admins_menu, "stats": _stats,
}


async def render(menu: str, arg: Optional[str] = None, note: str = ""):
    """Return (text, markup) for a menu; `note` is shown on top (e.g. '✅ Saved')."""
    text, markup = await _BUILDERS.get(menu, _main)(arg)
    return (f"{note}\n\n{text}" if note else text), markup
