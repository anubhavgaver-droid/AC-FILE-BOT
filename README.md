# Advanced File Store Bot

MongoDB-backed file store with **Base64 links**, `/single`, `/batch`, `/custombatch`, force-subscribe
(public *and* private-with-join-request), **1/2 token verification with one API per step**,
auto-delete / protect-content, poster-photo messages and an inline admin panel.

```
advanced-filestore-bot/
├── main.py  config.py  render.yaml  requirements.txt  .env.example
├── fsbot/                      # core services
│   ├── db.py  settings.py  encode.py  messages.py  admins.py
│   ├── fsub.py  verify.py  shortener.py  delivery.py  links.py  web.py  utils.py
└── plugins/                    # auto-loaded: any file with register(app)
    ├── start.py   single.py   batch.py   custom_batch.py
    ├── fsub_admin.py  verify_admin.py  messages_admin.py
    └── panel.py   admin.py    broadcast.py   channels.py
```

## Environment variables (Render → Environment)
| Variable | Value |
|---|---|
| `BOT_TOKEN` | from @BotFather |
| `OWNER_IDS` | your Telegram user ID(s), comma separated |
| `DB_CHANNEL_ID` | PRIVATE channel for `/single` and `/custombatch` files (bot = admin) |
| `MONGO_URI` | MongoDB Atlas connection string (allow `0.0.0.0/0` under Network Access) |
| `MONGO_DB_NAME` | optional, default `filestore` |
| `SHORTENER_API_URL` / `SHORTENER_API_KEY` | optional first-run default; manage later with `/setapi` |

`PORT` and `RENDER_EXTERNAL_URL` are set by Render. No API ID / API Hash / session needed.

## Creating links (admins)
All links are `t.me/<bot>?start=<Base64>`. The Base64 hides the structure; the real protection is the
random key stored in MongoDB (links cannot be guessed or enumerated). `/revoke <link>` deletes one.

* **/single** – send any file (forwarded or not). It is copied into the DB channel → link.
* **/batch** – forward the FIRST and LAST post of a range. **Rule:** the bot must be an **admin of the
  channel the files come from** (any such channel works, not just one). First and last must be in the same channel.
  A `t.me/c/...` post link works if forwarding is restricted.
* **/custombatch** – send files one by one; a status message with an inline **⏹ Stop** button stays at the
  bottom while you send. Stop → one link for everything. (`/cancel` or the ❌ button to abort.)

## What a user goes through
link → **force-subscribe** (if configured) → **verification** (if on) → **"⏳ Please wait…"** + files →
auto-delete timer. After deletion the note turns into a **📥 Get Again** button.
Delete timers live in MongoDB, so they survive restarts.

## Force-subscribe
`/addfsub` then forward a post from the channel (bot must be admin, with *Invite users via link*).
* Public channel → normal join button · Private channel → **join-request** link; a pending request counts.
* Force a mode: `/addfsub direct` or `/addfsub request`. `/fsublist`, `/delfsub <id>`, up to 5 channels.
* `/set fsub_auto_approve 1` approves requests automatically.

## 1/2 verification (all live-editable)
Step 1/2 is asked immediately → `verify_gap_hours` of access → step 2/2 → `verify_free_hours` (24 h) free → repeats.
* `/setapi <1|2> <url> <key>` – a different API per step (step 2 falls back to API 1). `/apis`, `/testapi`, `/delapi`.
* `/set verify_steps 1|2`, `verify_gap_hours`, `verify_free_hours`, `link_limit` + `link_window_hours`
  (e.g. 7 links per 24 h / 8 per 12 h), `token_expiry_minutes`, `verify_min_seconds`.
* No API set → links are not shortened and users can skip verification.

## Messages with a poster photo
`/setmsg <welcome|fsub|verify|wait>` as a **reply** to a photo (caption = text) or text. HTML is kept.
Placeholders: welcome `{name}` · fsub `{name} {request_note}` · verify `{name} {step} {total} {flow}` · wait `{count}`.
`/delphoto`, `/resetmsg`, `/previewmsg`. Photo captions are limited to 1024 characters.

## Auto-delete and protection
`/admin` panel toggles: verification, steps, protect content (no forward/save), auto-delete timer
(off / 5m / 10m / 30m / 1h), auto-approve. Exact values: `/set auto_delete_seconds 900`.

## Admins
Owners come from `OWNER_IDS`. Owners add more with `/addadmin <id>`, `/deladmin`, `/admins`.
Everything else: `/adminhelp`, `/settings`, `/stats`, `/broadcast` (reply), `/ban`, `/unban`.

## Deploy on Render
1. Push the folder to GitHub → Render **New → Blueprint** (`render.yaml`) or Web Service
   (Build `pip install -r requirements.txt`, Start `python main.py`).
2. Add the variables above. The bot opens `$PORT` with `/health` and pings itself every 10 min.
   Add a free UptimeRobot monitor on `https://<service>.onrender.com/health` too.
3. Run **one** instance only. Make the bot admin in: the DB channel, every `/batch` source channel,
   force-sub channels.
