# ControlPC

**A Windows PC that answers to Telegram.**

ControlPC is a self-hosted remote-control agent for a single Windows machine. It ships as one Telegram bot
(long polling, no webhook) plus a Telegram Mini App (a small web dashboard served from a standard-library
HTTP server on `127.0.0.1:8777` and published through an HTTPS tunnel). It is designed to be deployed on
several personal laptops, to update itself from `main`, and to keep working when any single feature breaks.

| | |
|---|---|
| **Bot version** | `3.7` |
| **Mini App API version** | `1.2` |
| **Platform** | Windows 10/11 (x64) |
| **Bot runtime** | Python 3.8+ with `pyTelegramBotAPI` |
| **Mini App runtime** | Python standard library only (`http.server`, `hmac`, `hashlib`, `secrets`) |
| **Access model** | Single owner: Telegram user ID allowlist |
| **Repository** | <https://github.com/bsatird/ControlPC> |

---

## Table of contents

1. [What ControlPC does](#1-what-controlpc-does)
2. [Feature matrix](#2-feature-matrix)
3. [Architecture](#3-architecture)
4. [Repository layout](#4-repository-layout)
5. [Requirements](#5-requirements)
6. [Installation](#6-installation)
7. [Configuration](#7-configuration)
8. [Operations](#8-operations)
9. [Mini App HTTP API](#9-mini-app-http-api)
10. [Security model](#10-security-model)
11. [Troubleshooting](#11-troubleshooting)
12. [Development workflow](#12-development-workflow)
13. [Known limitations](#13-known-limitations)
14. [Disclaimer](#14-disclaimer)

---

## 1. What ControlPC does

ControlPC turns a personal Windows machine into a Telegram-controlled endpoint:

- **One owner, one machine.** Every handler checks the incoming Telegram user/chat ID against `MY_ID`.
  There are no groups, no multi-user roles, no invitations.
- **No inbound ports.** The bot uses Telegram long polling, so the PC needs no public IP and no port
  forwarding. The only inbound surface is the Mini App, bound to loopback and exposed through a tunnel.
- **Two clients, one backend.** The same capabilities are reachable from the bot's reply keyboards and
  from the Mini App UI, both backed by the same Python functions in `miniapp_api.py`.
- **Self-updating.** A hidden launcher (`start_hidden.vbs`) re-downloads `ControlPC.py` from `main` whenever
  the process exits; the bot itself refreshes `miniapp_api.py` and `miniapp/*` when their version tag drifts.
- **Fail-soft by design.** Any Mini App failure (missing files, occupied port, broken config) degrades to
  "bot works, Mini App unavailable". `miniapp_api` is imported behind `try/except` and every API function
  returns a dictionary instead of raising.

---

## 2. Feature matrix

### 2.1 Telegram bot (`ControlPC.py`)

| Area | Capabilities |
|---|---|
| Media | Volume ±, mute, play/pause, screenshot (JPEG in memory, size-capped) |
| System | PC info (CPU/RAM), top-5 processes, running applications with details and graceful close, clipboard read, screen lock, shutdown/reboot |
| Camera | Snapshot from the default webcam |
| Input | Type text into the active window (clipboard-preserving), show a message box, open a URL |
| Voice | Text-to-speech on the PC speakers, 10-second microphone recording sent back as a voice message |
| Files | Download a file from the PC by path (≤ 49 MB), upload a file/photo to the PC into a chosen folder |
| Remote desktop | Detects/starts RustDesk, AnyDesk, TeamViewer and reports the session ID |
| RustDesk guard | Watches for incoming RustDesk connection prompts and asks for Accept/Decline in Telegram |
| Software | Silent installation of RustDesk / AnyDesk / TeamViewer / Chrome / Telegram Desktop — installer downloaded from the vendor and run with per-app silent flags (needs an elevated session) |
| Terminal | `/cmd <command>` for arbitrary commands on the PC (owner only) |
| Pranks | Matrix effect, SAPI voice line, fake self-destruct (reversible), rickroll |
| Lifecycle | Restart bot → re-download from GitHub; `/start`; ping/version check |

### 2.2 Telegram Mini App (`miniapp_api.py` + `miniapp/`)

| Screen | Capabilities |
|---|---|
| Dashboard | CPU/RAM/disk/battery/uptime, top processes, live refresh |
| Power | Shutdown (delayed), reboot, sleep, lock, cancel — two-step confirmation |
| Processes | Searchable list, per-process RAM/status, protected-process guardrails, confirmed kill |
| Media | Volume, mute, play/pause, next/prev/stop |
| Camera | JPEG snapshot with rate limiting (≥ 2 s between shots) |
| Files | Browse a single PC folder, download to phone, upload from phone (≤ 25 MB), delete (two-step) |
| Terminal | Run a CMD command with an explicit confirmation step and output capture (20 s timeout) |

---

## 3. Architecture

### 3.1 Components

| Component | File | Process | Responsibility |
|---|---|---|---|
| Telegram bot | `ControlPC.py` | `python.exe` | Menu, commands, callback buttons, Windows actions, downloads/uploads, self-update of Mini App files |
| Mini App backend | `miniapp_api.py` | thread inside the bot | Static files + JSON API, `initData` validation, sessions, confirmation tokens, system actions |
| Mini App frontend | `miniapp/index.html`, `style.css`, `app.js` | Telegram WebView | Dashboard, files, terminal, power/media controls |
| Universal installer | `installer.py` → `installer.exe` | console app | Idempotent provisioning of a new PC |
| Bootstrap script | `run_bot.ps1` | elevated PowerShell | One-shot install + autostart (legacy path, still supported) |
| Hidden supervisor | `start_hidden.vbs` (generated) | `wscript.exe` | Starts `ngrok` and the bot without a console window, keeps the update loop alive |

### 3.2 Data flow

```
                          ┌───────────────────────── Windows PC ─────────────────────────┐
                          │                                                               │
  Telegram app  ──poll──► │  ControlPC.py ──► handlers ──► psutil / ctypes / pyautogui /   │
  (owner only)            │        │                       cv2 / pyttsx3 / pyperclip       │
                          │        │                                                       │
                          │        └──► miniapp_api.py (HTTP 127.0.0.1:8777) ──► miniapp/ │
                          └────────────────────────────▲──────────────────────────────────┘
                                                       │ HTTPS (ngrok static domain)
  Telegram Mini App (WebView) ─────────────────────────┘
```

Both clients call the **same functions** in `miniapp_api.py` (`power_execute`, `kill_prepare`,
`files_save`, `terminal_run`, …), so behaviour cannot drift between the bot and the UI.

### 3.3 Startup and self-update chain

```
Task Scheduler "ControlPC_Bot" (on logon, highest privileges)
        └── wscript.exe start_hidden.vbs
                ├── wscript.exe start_hidden.vbs /ngrok  ──►  ngrok http 8777 --domain=<domain>
                └── loop ──┬── download ControlPC.py from raw/main (atomic, size-checked)
                           ├── python ControlPC.py
                           └── wait 10 s after exit, then repeat
```

- **Bot update:** "🔄 Перезапустити бота" calls `os._exit(0)`; the launcher loop re-downloads `ControlPC.py`
  from `main` and starts it again. Therefore **a push to `main` is a release** for every provisioned PC.
- **Mini App update:** at import time the bot compares the tag in `miniapp/app.js`
  (`ControlPC Mini App vX.Y`) with `MINIAPP_FILES_VERSION`; on mismatch it downloads `miniapp_api.py` and
  `miniapp/*` into memory first and only then writes them, so a partial download can never mix versions.
- **Start-up delay:** `ControlPC.py` sleeps 15 s before doing anything (network/tunnel settling).

### 3.4 Failure isolation

| Failure | Behaviour |
|---|---|
| `miniapp_api.py` or `miniapp/` missing/corrupt | Import guarded; `MINIAPP_AVAILABLE = False`; bot runs and the panel reports "Mini App unavailable" |
| Port `8777` busy | Server tries `8778…8781`; if all fail the bot keeps running |
| Invalid `miniapp_config.json` | Falls back to defaults, one warning in the log |
| Any API action raises | Returns `{"ok": false, ...}`; HTTP server and bot stay alive |
| Telegram network error | Polling loop logs to `bot_errors.txt` and retries after 5 s |

---

## 4. Repository layout

```
ControlPC/
├── ControlPC.py            # Telegram bot: entry point, menus, handlers, self-update (≈2.2k lines)
├── miniapp_api.py          # Mini App HTTP server + auth + system actions (stdlib only)
├── miniapp/
│   ├── index.html          # Mini App markup (Telegram WebApp SDK)
│   ├── style.css           # Telegram-dark themed UI
│   └── app.js              # UI logic: auth, dashboard, files, terminal, camera
├── installer.py            # Universal Windows installer (idempotent, stdlib only)
├── run_bot.ps1             # Legacy one-shot bootstrap: deps + autostart + first run
├── .clinerules             # Project rules for AI-assisted development
└── .gitignore              # Excludes __pycache__, build artefacts, local config, token.txt
```

`installer.spec` is generated by `pyinstaller --onefile …` and is deliberately ignored by `.gitignore`.

Files that exist **only on the target PC** (never committed):

```
%LOCALAPPDATA%\ControlPC\
├── ControlPC.py            # self-updated copy
├── miniapp_api.py          # self-updated copy
├── miniapp\                # self-updated copy
├── token.txt               # bot token (plain text, protected by user-profile ACL)
├── miniapp_config.json     # host/port/public_url/allowed_ids/files_dir
├── start_hidden.vbs        # generated supervisor: ngrok + update loop
├── start_internal.bat      # legacy bat loop, created only by run_bot.ps1
└── bot_errors.txt          # runtime log
```

---

## 5. Requirements

| Requirement | Details |
|---|---|
| OS | Windows 10/11 x64. Several actions need an elevated (administrator) session: scheduled-task creation, silent installers, RustDesk window automation |
| Python | 3.8+ for the bot (3.10+ recommended). The installer itself needs only the standard library |
| Python packages | `pyTelegramBotAPI`, `opencv-python`, `pyautogui`, `psutil`, `pyttsx3`, `sounddevice`, `scipy`, `pyperclip`, `pillow`. The list is duplicated in `installer.py::PIP_PACKAGES` and `run_bot.ps1::$packages` — keep both in sync |
| Telegram | Bot token from [@BotFather](https://t.me/BotFather) and the owner's numeric Telegram ID |
| Tunnel (Mini App only) | `ngrok` with a reserved static domain (free tier is enough). Without a tunnel the Mini App is local-only |
| Hardware | Optional: webcam, microphone/speakers, battery |
| Network | Outbound HTTPS: Telegram API, `raw.githubusercontent.com`, ngrok edge, vendor download hosts |

---

## 6. Installation

All paths below assume the default working directory `%LOCALAPPDATA%\ControlPC`.

### 6.1 Option A — `installer.exe` (recommended)

```powershell
# build once (from the repository root)
pyinstaller --onefile --console --name installer installer.py

# or run the script directly
python installer.py
```

The installer is idempotent and safe to re-run on an already provisioned PC:

1. Verifies Python and prepares `%LOCALAPPDATA%\ControlPC`.
2. Asks for the **Telegram bot token** (validated with `^\d{8,10}:[A-Za-z0-9_-]{35}$`) and stores it in
   `token.txt`; the value is masked in output (`12345678:***`) and never echoed back.
3. Downloads a fresh `ControlPC.py` **atomically** (temporary file + size sanity check before replace).
4. Installs the pip dependencies and verifies that the modules are importable.
5. Optionally registers an **ngrok authtoken** through `ngrok config add-authtoken` (never written into the
   repository or the installer files).
6. Generates `miniapp_config.json` with the static tunnel domain, port `8777` and the owner ID allowlist.
7. Creates the hidden launcher (`start_hidden.vbs`), the `ControlPC_Bot` logon task (highest privileges) and
   removes stale autostart entries.
8. Starts the bot hidden and health-checks `http://127.0.0.1:8777/api/health`.

### 6.2 Option B — `run_bot.ps1` (elevated PowerShell)

```powershell
# PowerShell as Administrator, then:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\run_bot.ps1
```

It prompts for the bot token once, adds a **Defender exclusion** for the bot folder, allows webcam access for
unpackaged desktop apps, installs pip packages, downloads the Mini App files, writes `start_internal.bat` +
`start_hidden.vbs`, registers the `ControlPC_Bot` logon task and starts it hidden.

### 6.3 Option C — manual (development)

```powershell
$dir = "$env:LOCALAPPDATA\ControlPC"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item ControlPC.py, miniapp_api.py -Destination $dir -Force
Copy-Item miniapp -Destination $dir -Recurse -Force
"<BOT_TOKEN>" | Out-File "$dir\token.txt" -Encoding utf8 -NoNewline
python -m pip install pyTelegramBotAPI opencv-python pyautogui psutil pyttsx3 sounddevice scipy pyperclip pillow
python "$dir\ControlPC.py"
```

> The bot sleeps 15 s on import, then sends `🟢 Система [PC] готова!` to the owner. If `token.txt` is missing,
> the script writes a placeholder and exits with `os._exit(0)`.

### 6.4 System changes made by the installer

| Change | Purpose | How to undo |
|---|---|---|
| `%LOCALAPPDATA%\ControlPC\` folder | Working directory, token, config, logs | Delete the folder |
| Scheduled task `ControlPC_Bot` (`onlogon`, `highest`) | Autostart with administrator rights | `schtasks /delete /tn ControlPC_Bot /f` |
| Defender exclusion for the bot folder (`run_bot.ps1`) | Avoids false positives on the self-updating script | `Remove-MpPreference -ExclusionPath "$env:LOCALAPPDATA\ControlPC"` |
| `HKCU\…\CapabilityAccessManager\ConsentStore\webcam\NonPackaged` = `Allow` | Allows camera capture from a non-packaged Python process | Set the value back to `Deny` |
| `ngrok config add-authtoken` | Authenticates the tunnel | Edit `%LOCALAPPDATA%\ngrok\ngrok.yml` |

---

## 7. Configuration

### 7.1 Bot token

| Item | Value |
|---|---|
| Path | `%LOCALAPPDATA%\ControlPC\token.txt` |
| Format | Single line, `123456789:AA…` (35 URL-safe characters after the colon), UTF-8 |
| Reader | `ControlPC.py` with `encoding="utf-8-sig"`, so a BOM or trailing newline is tolerated |
| Ownership | Created by the installer / `run_bot.ps1`, protected by the user-profile ACL only |
| Rotation | Revoke in @BotFather (`/revoke`) and write the new token into `token.txt`, then restart |

The token is **never** stored in the repository, never logged, and is masked whenever the installer prints it.

### 7.2 `miniapp_config.json`

Generated in `%LOCALAPPDATA%\ControlPC\`. Resolution order: **environment variable → JSON → default**.

| Key | Env variable | Default | Meaning |
|---|---|---|---|
| `enabled` | `CONTROLPC_MINIAPP_ENABLED` | `true` | Master switch; `false` = the bot runs without the Mini App |
| `host` | `CONTROLPC_MINIAPP_HOST` | `127.0.0.1` | Bind address. Keep loopback: the tunnel connects to localhost |
| `port` | `CONTROLPC_MINIAPP_PORT` | `8777` | Base port; on conflict the server tries the next four |
| `public_url` | `CONTROLPC_MINIAPP_PUBLIC_URL` | `""` | Public **HTTPS** URL used for the WebApp button. `http://` is ignored by Telegram |
| `allowed_ids` | — | `[<owner id>]` | Telegram user IDs allowed to authenticate. Empty list = no ID filter → rely on HMAC only |
| `init_data_ttl` | `CONTROLPC_MINIAPP_INIT_TTL` | `86400` | Maximum age of `initData` in seconds |
| `session_ttl` | `CONTROLPC_MINIAPP_SESSION_TTL` | `43200` | Session token lifetime (12 h) |
| `files_dir` | `CONTROLPC_MINIAPP_FILES_DIR` | `%USERPROFILE%\Downloads` | The single folder exposed by the "Files" screen |

```json
{
  "enabled": true,
  "host": "127.0.0.1",
  "port": 8777,
  "public_url": "https://example.ngrok-free.dev",
  "allowed_ids": [123456789],
  "init_data_ttl": 86400,
  "session_ttl": 43200,
  "files_dir": ""
}
```

> Hard-coded owner identity lives in `ControlPC.py` (`MY_ID`) and `installer.py` (`ALLOWED_IDS`). When forking
> the project, change **both** — otherwise your bot stays wired to the original owner.

### 7.3 HTTPS tunnel

```powershell
ngrok http 8777 --domain=your-static-domain.ngrok-free.dev
```

Put the same `https://…` value into `public_url`. The frontend renews the `abuse_interstitial` cookie for
`*.ngrok-free.*` hosts so the free-tier warning page does not appear inside the Telegram WebView.

---

## 8. Operations

| Task | How |
|---|---|
| Health check | `Invoke-RestMethod http://127.0.0.1:8777/api/health` → `{ ok: true, api_version: "1.2", bot_version: "3.7 …" }` |
| Is the bot alive? | Send `🏓 Пінг` or `👁 Інфо про ПК`; the version is printed in the answer |
| Logs | `%LOCALAPPDATA%\ControlPC\bot_errors.txt` (exceptions, RustDesk events, `[MiniApp] …` lines) |
| Restart / update | Bot button `🔄 Перезапустити бота` → process exits, `bat` loop pulls `main` and restarts |
| Full restart | `Get-Process python,ngrok,wscript -ErrorAction SilentlyContinue \| Stop-Process -Force`, then `wscript.exe "$env:LOCALAPPDATA\ControlPC\start_hidden.vbs"` |
| Change token | Edit `token.txt`, then restart |
| Change tunnel domain | Edit `public_url` in `miniapp_config.json`, restart `ngrok` with the new `--domain`, restart the bot |
| Stop everything | `schtasks /delete /tn ControlPC_Bot /f` and kill the three processes above |
| Uninstall | Delete the scheduled task, the `%LOCALAPPDATA%\ControlPC` folder, the Defender exclusion and the webcam consent value |

---

## 9. Mini App HTTP API

Base URL `http://127.0.0.1:8777` (public: `https://<tunnel domain>`). Every response is JSON except
`/api/files/download` and `/api/camera/snapshot`, which stream bytes. All `/api/*` routes are served by
`miniapp_api.py`; everything else is a static file from `miniapp/`.

| Method | Path | Auth | Payload | Result |
|---|---|---|---|---|
| `GET` | `/api/health` | none | — | `{ok, api_version, bot_version, time}` |
| `POST` | `/api/auth` | `initData` | `{"initData": "<raw query string>"}` | `{ok, token, user, expires_in}` |
| `POST` | `/api/logout` | session | — | `{ok}` |
| `GET` | `/api/me` | session | — | `{ok, user_id, server_time}` |
| `GET` | `/api/status` | session | — | CPU/RAM/disk/battery/uptime |
| `GET` | `/api/processes` | session | — | top processes (name, pid, RAM, status) |
| `GET` | `/api/actions` | session | — | capability flags used to build the UI |
| `GET` | `/api/files?path=` | session | — | directory listing inside `files_dir` |
| `GET` | `/api/files/download?path=` | session | — | file stream (download) |
| `POST` | `/api/files/upload` | session | multipart | writes into `files_dir`, ≤ 25 MB |
| `POST` | `/api/files/delete` | session + confirm | `{path, confirm}` | deletes one entry |
| `POST` | `/api/power` | session + confirm | `{action, delay}` | `shutdown` / `reboot` / `sleep` / `lock` / `cancel` |
| `POST` | `/api/process/kill` | session + confirm | `{pid, confirm}` | protected-process guardrails apply |
| `POST` | `/api/media` | session | `{action, steps}` | volume/mute/play/next/prev/stop |
| `GET` | `/api/camera/snapshot` | session | — | JPEG, minimum 2 s between frames |
| `POST` | `/api/terminal` | session + confirm | `{command, confirm}` | CMD output, 20 s timeout |

### 9.1 Authentication flow

1. The WebView receives `Telegram.WebApp.initData` (signed by Telegram) and passes it to `POST /api/auth`.
2. `miniapp_api.py` recomputes `HMAC-SHA256(bot_token_key, "WebAppData")` over the sorted key/value pairs,
   compares with `hmac.compare_digest`, checks `auth_date` against `init_data_ttl`, and checks `user.id`
   against `allowed_ids`.
3. On success the server issues an opaque session token (kept in memory, TTL `session_ttl`), which the
   frontend sends as `X-MiniApp-Token` on every subsequent request.
4. Destructive actions are **two-phase**: the client first receives a human-readable confirmation text plus a
   single-use token, and only a second request carrying that token executes the action.

Sessions live in process memory, so restarting the bot invalidates every Mini App session (the UI simply
re-authenticates with `initData`).

### 9.2 Example

```powershell
Invoke-RestMethod http://127.0.0.1:8777/api/health

# authorized call (obtain the token from POST /api/auth inside the WebView)
Invoke-RestMethod http://127.0.0.1:8777/api/status -Headers @{ 'X-MiniApp-Token' = $token }
```

---

## 10. Security model

ControlPC is a **privileged remote-control agent**, not a public service. The design assumes exactly one
trusted operator and treats every other actor as hostile.

### 10.1 Threat model

| Adversary | What they can attempt | Mitigation |
|---|---|---|
| Anyone who learns the bot's @username | Send commands, press inline buttons, upload files | Every message handler compares `message.chat.id` with `MY_ID` and returns silently; callback handlers compare `call.from_user.id` and answer "⛔ Доступ заборонено" |
| Anyone who learns the tunnel URL | Call `/api/*` directly, brute-force endpoints | `/api/*` requires `initData` signed with the bot token (HMAC-SHA256, `allowed_ids`, TTL) |
| Someone who steals `token.txt` | Full control of the bot, forge `initData` | Out of scope for the app: rotate the token in @BotFather, use BitLocker + a dedicated Windows account |
| Another local Windows user | Read `%LOCALAPPDATA%\ControlPC`, tamper with scripts | User-profile ACL; full-disk encryption recommended |
| A compromised web page in the WebView | JavaScript injection into the UI | Mini App loads only its own static files, no third-party scripts, no `eval`, no `innerHTML` sinks for remote data |

### 10.2 Controls in place

| Control | Where | Notes |
|---|---|---|
| Owner-only gating | `ControlPC.py` — every message/callback handler | Fails closed: no answer for messages, a toast for foreign buttons, no log spam |
| Owner-only `/cmd` and uploads | `ControlPC.py::run_command`, `handle_upload` | Added in 3.7; previously these two entry points relied on the menu being hidden |
| Loopback-only HTTP server | `miniapp_api.py` | Binds `127.0.0.1`; the only way in is the outbound tunnel |
| `initData` validation | `miniapp_api.py` | `HMAC-SHA256(key=HMAC_SHA256("WebAppData", bot_token), data_check_string)` compared with `hmac.compare_digest` |
| ID allowlist | `miniapp_config.json → allowed_ids` | Independent of the signature, so a leaked token alone is not enough |
| Freshness window | `init_data_ttl` (24 h) + `session_ttl` (12 h) | Replay of old `initData` is rejected |
| In-memory sessions | `miniapp_api.py` | Restart drops all sessions; nothing persisted to disk |
| Single-use confirmations | `power`, `process/kill`, `files/delete`, `terminal` | Two-phase: preview text + token bound to the user and the action, valid 45 s, consumed on first use |
| Path sandboxing | `files_target()` | `realpath` must stay inside `files_dir`; `..` and absolute paths rejected |
| Filename sanitisation | `ControlPC.py` uploads | `os.path.basename()` + fallback name — no traversal via Telegram file names (3.7) |
| Size limits | Bot: 49 MB download / Mini App: 25 MB upload | Prevents accidental disk exhaustion |
| Camera rate limit | Mini App snapshot | ≥ 2 s between frames |
| Protected processes | Mini App kill | Critical system processes refuse to be killed |
| Secret hygiene | all files | Token read from disk, masked in logs, never committed; `.gitignore` covers `token.txt`, `miniapp_config.json`, `__pycache__/` |
| Explicit command surface | `/cmd` (bot), `/api/terminal` (Mini App) | `shell=True` by design — arbitrary code execution is the feature, therefore owner-only + confirmation token + 20 s timeout |

### 10.3 Fixed in 3.7

Two handlers were reachable by **any** Telegram user who found the bot, because access was enforced only by
the reply-keyboard layout (which is cosmetic):

- `/cmd <text>` — arbitrary command execution on the PC.
- `document` / `photo` messages — arbitrary file write into the configured destination folder, with a
  file name taken from the sender.

Both now start with an explicit owner check, and both sanitise the incoming file name with
`os.path.basename()` plus a generated fallback. Regex only guarantees the shape of a Telegram file name, not
its safety on Windows.

### 10.4 Residual risks you must accept

- **Arbitrary code execution by design.** `/cmd` and the Mini App terminal exist on purpose. Enable them only
  on a machine where an admin-level shell is acceptable, and prefer a non-administrator Windows account.
- **Defender exclusion.** `run_bot.ps1` excludes the bot folder from real-time scanning (self-updating script,
  false positives). That folder should stay under the owner's control.
- **Public tunnel metadata.** `GET /api/health` is unauthenticated and reveals version numbers and server time.
  Treat the tunnel hostname as private and rotate the static domain if it leaks.
- **Free ngrok tier.** The interstitial bypass relies on a browser cookie; it is a convenience, not a security
  boundary.
- **Telegram account is the key.** Anyone with access to the owner's Telegram session has access to the PC —
  enable two-step verification and a device passcode.
- **No audit log of actions**, only exceptions in `bot_errors.txt`. The tunnel provider logs request metadata.

If any of these are unacceptable for your environment, do not enable the Mini App and delete `/cmd`.

---

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot silent after install | `token.txt` missing/empty, or the token was revoked | Check `%LOCALAPPDATA%\ControlPC\token.txt`, re-run the installer |
| Bot ignores messages, buttons answer "⛔ Доступ заборонено" | Your Telegram ID ≠ `MY_ID` | Set your ID in `ControlPC.py` and in `miniapp_config.json → allowed_ids` |
| `ModuleNotFoundError: telebot` | pip step failed or pip installed into another interpreter | `python -m pip install -r` the package list, verify with `python -c "import telebot"` |
| `🎛 Mini App недоступний` button | `miniapp_api.py` / `miniapp/` missing, `enabled: false`, or import error | Check `bot_errors.txt` for `[MiniApp]` lines; re-download the files |
| Mini App loads but auth fails | `public_url` is `http://`, tunnel domain changed, or `initData` expired | Use the exact `https://` URL; restart `ngrok` and the bot |
| `401` on every API call, UI shows "Дані недоступні" | `initData` is older than `init_data_ttl`, PC clock drift, or your ID is missing from `allowed_ids` | Sync the clock (`w32tm /resync`) and reopen the Mini App from the bot button to get fresh `initData` |
| Port `8777` in use | Another instance or a different app | Kill the stale `python.exe`, or set `CONTROLPC_MINIAPP_PORT` |
| Camera snapshot empty | Webcam consent or device in use | Re-apply the `NonPackaged` webcam consent value, close other camera apps |
| Volume keys do nothing | Media keys require an active, unlocked desktop session (disconnected RDP ignores them) | Keep the session unlocked; the bot sends `volumeup` / `volumedown` / `volumemute` key presses |
| Quiet audio recording | No microphone or `sounddevice` device index mismatch | Test with `python -m sounddevice` |
| Upload/download of a big file fails | Size cap (49 MB bot / 25 MB Mini App) | Split the file or use the other channel |
| Screenshot / file takes long | Machine busy or 4K multi-monitor capture | Expected; the bot caps the image size |
| RustDesk prompt not detected | Different window title or UAC session | Check `bot_errors.txt`; the guard is title-based |
| Silent installer fails | No internet, blocked vendor host, or UAC denied | Run the bot from the elevated task; check `bot_errors.txt` for the download step |
| Bot does not start after reboot | Task Scheduler task disabled or removed | `schtasks /query /tn ControlPC_Bot`, recreate it |
| Antivirus removed the script | Defender false positive on a self-updating `.py` | Re-add the exclusion, restore from quarantine |

Log files worth checking first: `%LOCALAPPDATA%\ControlPC\bot_errors.txt`.

---

## 12. Development workflow

### 12.1 Conventions

- Python: standard library first; a new third-party import must also be added to `installer.py::PIP_PACKAGES`
  **and** `run_bot.ps1::$packages`, otherwise existing PCs crash on the next update.
- Comments, UI strings, bot messages and commit messages are in Ukrainian, matching the existing code.
- `ControlPC.py` is a monolith by design (≈2.2k lines). New large subsystems go into their own module, the way
  `miniapp_api.py` did.
- Fail-soft: a broken Mini App must never break the bot (`try/except` import, `MINIAPP_AVAILABLE` flag).

### 12.2 Checks before committing

```powershell
python -m py_compile ControlPC.py miniapp_api.py installer.py
git --no-pager status
git --no-pager diff --stat
```

- Note: `ControlPC.py` sleeps 15 s on import, reads the token and starts threads — do not run it "just to check";
  test logic in a throwaway script under `%TEMP%`.
- Frontend (`miniapp/*.js|css|html`) has no automated tests and Node is not part of the toolchain: changes must
  be verified manually in the Telegram WebView or a desktop browser with a mocked `initData`.
- Never commit `token.txt`, `miniapp_config.json`, `__pycache__/`, `*.pyc`, local logs.

### 12.3 Releasing

`main` is production: pushes reach every provisioned PC on the next restart.

```powershell
git add README.md ControlPC.py
git commit -m "feat(3.7): README англійською + закрито доступ до /cmd і завантажень"
git push origin main
```

After pushing, the running bots pick up the change after their next restart (bot button, or the update loop
on process exit).

---

## 13. Known limitations

- Windows-only; no Linux/macOS port.
- Single owner, single machine per instance — no multi-tenancy, no roles.
- Screen sharing is delegated to RustDesk / AnyDesk / TeamViewer; there is no built-in WebRTC stream.
- The Mini App backend is single-process and memory-bound: 25 MB uploads and 20 s terminal commands.
- Sessions are lost on restart; the WebView re-authenticates transparently.
- RustDesk prompt interception is window-title based and may miss localised or redesigned builds.
- No metrics, no audit trail, no structured logging — troubleshooting relies on `bot_errors.txt`.
- No automated tests. Verification is `py_compile` + manual UI checks.
- Telegram sets the practical ceiling for file transfer (bot API 50 MB, Mini App 25 MB here).

---

## 14. Disclaimer

ControlPC grants remote administrative control over a computer: command execution, file access, camera,
microphone, screen capture, power management and software installation.

Use it **only** on hardware you own or administer with explicit written permission. Deploying it on someone
else's machine, or without their informed consent, is illegal in most jurisdictions and is not a supported use
of this project. The author accepts no liability for damage, data loss or legal consequences resulting from
misuse.

If you fork this repository, replace `MY_ID`, `ALLOWED_IDS` and the tunnel domain with your own values, and
review section [10](#10-security-model) before exposing anything to the internet.


