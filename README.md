# Advanced File Store Bot

MongoDB-backed file store with **Base64 links**, `/single`, `/batch`, `/custombatch`, force-subscribe
(public *and* private-with-join-request), **1/2 token verification with one API per step**,
auto-delete / protect-content, poster-photo messages — and a **full inline settings panel: every setting is a button**.

```
advanced-filestore-bot/
├── main.py  config.py  render.yaml  requirements.txt  .env.example
├── fsbot/                      # core services
│   ├── db.py  settings.py  encode.py  messages.py  admins.py  ui.py (panel menus)
│   ├── fsub.py  verify.py  shortener.py  delivery.py  broadcast.py  links.py  web.py  utils.py
└── plugins/                    # auto-loaded: any file with register(app)
    ├── start.py   single.py   batch.py   custom_batch.py
    ├── settings_panel.py       # /settings button panel
    ├── fsub_admin.py  verify_admin.py  messages_admin.py   # classic commands, same features
    └── admin.py   broadcast.py   channels.py
```

## Environment variables (Render → Environment)
| Variable | Value |
|---|---|
| `BOT_TOKEN` | from @BotFather |
| `OWNER_IDS` | your Telegram user ID(s), comma separated |
| `DB_CHANNEL_ID` | PRIVATE channel for `/single` and `/custombatch` files (bot = admin) |
| `MONGO_URI` | MongoDB Atlas connection string (allow `0.0.0.0/0` under Network Access) |
| `MONGO_DB_NAME` | optional, default `advanced_filestore` — use a NEW name, not a database another bot uses |

Everything else (APIs, timers, channels, messages) is set from the bot itself. `PORT` / `RENDER_EXTERNAL_URL` come from Render.
No API ID / API Hash / session needed.

## ⚙️ /settings — the control panel (all buttons)
Open it with `/settings` (or `/admin`). Every change applies instantly and the menu refreshes in place.

| Menu | What you can do with buttons |
|---|---|
| 🔐 **Verification** | on/off · 1 or 2 steps · **free-access time** (after the last step) · **gap time** (between step 1 and 2) · link limit + window · link expiry · anti-bypass minimum time · **API 1 / API 2** |
| 🔑 **API 1 / API 2** | **Set**: first the domain *without http* (e.g. `gplinks.com`), then the API key · **Test** · Remove. Step 2 falls back to API 1 if unset |
| 📢 **Force-Subscribe** | **Add** channel (forward a post) · open a channel to **switch Request ↔ Direct**, make a new invite link, **remove** (with confirm) · auto-approve join requests |
| 🛡 **Protection** | protect content (no forward/save) · auto-delete timer |
| 🗑 **Auto-Delete** | Off / 5m / 10m / 30m / 1h / 6h / 24h / **Custom** |
| 💬 **Messages** | for Welcome, Join prompt, Verification prompt, Please-wait: **Set text · Set photo · Remove photo · Reset · Preview** |
| 🔗 **Links** | link counts · **link expiry** (links stop working after N hours) |
| 👥 **Users** | ban / unban · **Broadcast** (send the message, confirm) · admins (owners can add/remove) |
| 🚧 **Maintenance** | one tap: only admins can use the bot |
| 📊 **Stats** | users, links, channels |

**Custom values:** every number has preset buttons *and* a **✏️ Custom** button. Type `12`, `90m`, `2h` or `1d` —
the bot converts it to the right unit (counts take plain numbers). Mistakes are shown inside the prompt; the secret
API-key message is deleted right after you send it.

## Creating links (admins)
All links are `t.me/<bot>?start=<Base64>`. The Base64 hides the structure; the real protection is the random key
stored in MongoDB (links cannot be guessed or enumerated). `/revoke <link>` deletes one.

* **/single** – send any file (forwarded or not) → copied into the DB channel → link.
* **/batch** – forward the FIRST and LAST post of a range. **Rule:** the bot must be an **admin of the channel the files
  come from** (any such channel works). First and last must be in the same channel. A `t.me/c/...` post link works if forwarding is restricted.
* **/custombatch** – send files one by one; a status message with an inline **⏹ Stop** button stays at the bottom.
  Stop → one link for everything.

## What a user goes through
link → **force-subscribe** → **verification** → **"⏳ Please wait…"** + files → auto-delete timer. After deletion the note
becomes a **📥 Get Again** button. Timers live in MongoDB, so they survive restarts.
Two-step flow: step 1/2 asked immediately → *gap* of access → step 2/2 → *free access* (e.g. 24 h) → repeats.

## Messages with a poster photo
Placeholders: welcome `{name}` · join prompt `{name} {request_note}` · verification `{name} {step} {total} {flow}` · wait `{count}`.
A photo makes the message a poster with the text as caption (max 1024 characters).

## Classic commands (optional — the panel does all of this)
`/set <key> <value>` · `/setapi <1|2> <url> <key>` · `/addfsub` · `/delfsub` · `/fsublist` · `/setmsg` (reply) ·
`/broadcast` (reply) · `/ban` · `/unban` · `/addadmin` · `/deladmin` · `/stats` · `/adminhelp`

## Deploy on Render
1. Push the folder to GitHub → Render **New → Blueprint** (`render.yaml`) or Web Service
   (Build `pip install -r requirements.txt`, Start `python main.py`). If you create it manually, add `PYTHON_VERSION=3.12.3`.
2. Add the variables above. The bot opens `$PORT` with `/health` and pings itself every 10 min.
   Add a free UptimeRobot monitor on `https://<service>.onrender.com/health` as well.
3. Run **one** instance only. Make the bot admin in: the DB channel, every `/batch` source channel, force-sub channels
   (private ones need "Invite users via link").
