# -*- coding: utf-8 -*-
"""ControlPC Mini App - серверна частина (Етапи 1-3).

Легкий HTTP-сервер на стандартній бібліотеці Python (без нових залежностей, щоб
не зламати вже налаштовані ноутбуки). Запускається у фоновому потоці з ControlPC.py
і віддає:
    /                     - інтерфейс Mini App (miniapp/index.html)
    /style.css            - стилі Mini App
    /app.js               - логіка Mini App
    /api/health           - перевірка, що сервер живий (без секретів)
    /api/auth             - POST {"initData": "..."} -> перевірка підпису Telegram + сесія
    /api/me               - користувач, для якого видано сесію
    /api/status           - системний знімок ПК (тільки читання, для дашборду)
    /api/actions          - які дії керування доступні на цьому ПК
    /api/processes        - список процесів (PID, RAM, стан, чи можна завершити)
    /api/camera/snapshot  - знімок з веб-камери (JPEG у пам'яті)
    /api/power            - POST живлення: shutdown / reboot / sleep / lock / cancel
    /api/process/kill     - POST завершення процесу за PID (у два кроки)
    /api/media            - POST гучність, мут, медіа-клавіші

Критичні дії (живлення, завершення процесу) виконуються у два кроки: спочатку
сервер видає одноразовий токен підтвердження (живе CONFIRM_TTL секунд і прив'язаний
до дії та користувача), і лише запит із цим токеном реально щось змінює. Так
випадковий тап по кнопці не може вимкнути ПК.

Безпека (обов'язкова для Telegram Mini Apps):
    * initData перевіряється HMAC-SHA256 з ключем HMAC("WebAppData", bot_token)
      (алгоритм з офіційної документації Telegram Web Apps);
    * перевіряється свіжість auth_date (типово 24 години);
    * доступ мають лише дозволені Telegram ID (allowed_ids, типово MY_ID);
    * після перевірки видається короткоживучий підписаний сесійний токен;
    * сервер слухає 127.0.0.1, віддає лише файли з miniapp/, без лістингу каталогів,
      з обмеженням розміру тіла запиту та захистом від перебору підписів.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import mimetypes
import os
import platform
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    import psutil
except ImportError:  # psutil є у боті, але модуль має працювати й без нього
    psutil = None  # type: ignore

API_VERSION = "1.1"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8777
DEFAULT_INIT_DATA_TTL = 24 * 3600      # скільки живе initData з Telegram
DEFAULT_SESSION_TTL = 12 * 3600        # скільки живе сесія Mini App
MAX_BODY_BYTES = 16 * 1024             # максимальний розмір JSON-запиту
AUTH_FAIL_LIMIT = 10                   # скільки невдалих спроб з однієї адреси
AUTH_FAIL_WINDOW = 60                  # ... за стільки секунд блокуємо (429)
CONFIRM_TTL = 45                       # скільки діє підтвердження критичної дії, сек
POWER_DELAY_MIN = 5                    # мінімальна затримка вимкнення, сек
POWER_DELAY_MAX = 300                  # максимальна затримка вимкнення, сек
CAMERA_MIN_INTERVAL = 2.0              # пауза між знімками з камери, сек
CAMERA_QUALITY = 82                    # якість JPEG зі камери
PROCESS_LIST_LIMIT = 60                # скільки процесів максимум віддаємо

# Статичні файли Mini App: тільки ці типи віддаємо назовні
STATIC_EXTENSIONS = {".html", ".css", ".js", ".svg", ".png", ".ico", ".webmanifest"}
STATIC_ROOT_NAMES = {"", "index.html", "style.css", "app.js", "favicon.ico"}

_LOG_LOCK = threading.Lock()
_LOGGER: Optional[Callable[[str], None]] = None


def set_logger(logger: Optional[Callable[[str], None]]) -> None:
    """Дозволяє боту підмінити стандартний print своїм логером."""
    global _LOGGER
    _LOGGER = logger


def log(message: str) -> None:
    """Єдина точка логування модуля (не падає, навіть якщо логер зламався)."""
    line = f"[MiniApp] {message}"
    logger = _LOGGER
    if logger is not None:
        try:
            logger(line)
            return
        except Exception:
            pass
    with _LOG_LOCK:
        try:
            print(line, flush=True)
        except Exception:
            pass


def _now() -> float:
    return time.time()


class MiniAppError(Exception):
    """Базова помилка модуля."""


class MiniAppAuthError(MiniAppError):
    """initData не пройшов перевірку (підпис, термін дії або доступ)."""

    def __init__(self, reason: str, message: str, status: int = 401):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.status = status


class MiniAppConfig:
    """Налаштування Mini App.

    Джерела (у порядку пріоритету): змінні середовища -> miniapp_config.json -> типові
    значення. Файл лежить у папці бота (botDir), щоб його можна було змінювати без
    редагування коду.
    """

    def __init__(self,
                 host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT,
                 public_url: str = "",
                 allowed_ids: Optional[List[int]] = None,
                 enabled: bool = True,
                 init_data_ttl: int = DEFAULT_INIT_DATA_TTL,
                 session_ttl: int = DEFAULT_SESSION_TTL,
                 base_dir: Optional[str] = None,
                 config_path: Optional[str] = None):
        self.host = host
        self.port = int(port)
        self.public_url = (public_url or "").strip().rstrip("/")
        self.allowed_ids = [int(i) for i in (allowed_ids or [])]
        self.enabled = bool(enabled)
        self.init_data_ttl = int(init_data_ttl)
        self.session_ttl = int(session_ttl)
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.config_path = config_path or ""

    # --- допоміжні ---
    @property
    def local_url(self) -> str:
        host = self.host if self.host not in ("0.0.0.0", "::", "") else "127.0.0.1"
        return f"http://{host}:{self.port}"

    @property
    def webapp_url(self) -> Optional[str]:
        """URL для кнопки Telegram WebApp: тільки https, інакше Telegram відмовить."""
        if self.public_url.lower().startswith("https://"):
            return self.public_url
        return None

    @property
    def miniapp_dir(self) -> str:
        return os.path.join(self.base_dir, "miniapp")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "public_url": self.public_url,
            "allowed_ids": self.allowed_ids,
            "enabled": self.enabled,
            "init_data_ttl": self.init_data_ttl,
            "session_ttl": self.session_ttl,
            "config_path": self.config_path,
            "miniapp_dir": self.miniapp_dir,
        }

    def __repr__(self) -> str:
        return f"MiniAppConfig({self.to_dict()})"


def _env(name: str) -> Optional[str]:
    return os.environ.get(name)


def load_config(bot_dir: Optional[str] = None,
                base_dir: Optional[str] = None,
                default_allowed: Optional[List[int]] = None) -> MiniAppConfig:
    """Читає miniapp_config.json (якщо є) і змінні середовища CONTROLPC_MINIAPP_*.

    Файл створюється автоматично з типовими значеннями, щоб користувачу було де
    прописати public_url, коли він підніме HTTPS-тунель.
    """
    base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
    bot_dir = bot_dir or base_dir
    config_path = os.path.join(bot_dir, "miniapp_config.json")
    data: Dict[str, Any] = {}

    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8-sig") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = loaded
        else:
            data = {
                "enabled": True,
                "host": DEFAULT_HOST,
                "port": DEFAULT_PORT,
                "public_url": "",
                "allowed_ids": [int(i) for i in (default_allowed or [])],
                "init_data_ttl": DEFAULT_INIT_DATA_TTL,
                "session_ttl": DEFAULT_SESSION_TTL,
                "_comment": ("public_url - публічна HTTPS-адреса Mini App (тунель/домен), "
                             "наприклад https://controlpc.example.com. Без неї Mini App "
                             "відкривається лише локально у браузері ПК."),
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:  # пошкоджений конфіг не має ламати бота
        data = {}
        log(f"config: не вдалося прочитати {config_path}: {e}")

    allowed = data.get("allowed_ids")
    if not isinstance(allowed, list) or not allowed:
        allowed = list(default_allowed or [])

    def _pick(key: str, env_name: str, caster, fallback):
        value = _env(env_name)
        if value not in (None, ""):
            try:
                return caster(value)
            except Exception:
                log(f"config: некоректна змінна {env_name}={value!r}, беру {key}")
        if key in data and data[key] not in (None, ""):
            try:
                return caster(data[key])
            except Exception:
                log(f"config: некоректне значення {key}={data[key]!r}")
        return fallback

    return MiniAppConfig(
        host=str(_pick("host", "CONTROLPC_MINIAPP_HOST", str, DEFAULT_HOST)),
        port=_pick("port", "CONTROLPC_MINIAPP_PORT", int, DEFAULT_PORT),
        public_url=str(_pick("public_url", "CONTROLPC_MINIAPP_PUBLIC_URL", str, "")),
        allowed_ids=[int(i) for i in allowed],
        enabled=_pick("enabled", "CONTROLPC_MINIAPP_ENABLED",
                      lambda v: str(v).strip().lower() not in ("0", "false", "no", "off"),
                      True),
        init_data_ttl=_pick("init_data_ttl", "CONTROLPC_MINIAPP_INIT_TTL", int,
                            DEFAULT_INIT_DATA_TTL),
        session_ttl=_pick("session_ttl", "CONTROLPC_MINIAPP_SESSION_TTL", int,
                          DEFAULT_SESSION_TTL),
        base_dir=base_dir,
        config_path=config_path,
    )


# ==========================================
# ПЕРЕВІРКА initData (ГОЛОВНИЙ ЗАХИСТ MINI APP)
# ==========================================
def _data_check_string(fields: Dict[str, str]) -> str:
    """Рядок для підпису: відсортовані key=value без hash, з'єднані через \\n."""
    return "\n".join(f"{k}={fields[k]}" for k in sorted(fields))


def validate_init_data(init_data: str,
                       bot_token: str,
                       allowed_ids: Optional[List[int]] = None,
                       max_age: int = DEFAULT_INIT_DATA_TTL,
                       now: Optional[float] = None) -> Dict[str, Any]:
    """Перевіряє підпис initData і повертає дані користувача.

    Алгоритм (документація Telegram "Validating data received via the Mini App"):
        secret_key = HMAC_SHA256("WebAppData", bot_token)
        hash       = HMAC_SHA256(secret_key, data_check_string)
    Плюс перевірка auth_date (свіжість) і білого списку Telegram ID.

    Кидає MiniAppAuthError з людським текстом, якщо перевірка не пройдена.
    """
    if not isinstance(init_data, str) or not init_data.strip():
        raise MiniAppAuthError("empty", "Порожні дані Telegram (initData)")
    if not bot_token or ":" not in bot_token:
        raise MiniAppAuthError("server", "Некоректний токен бота на сервері", status=500)

    try:
        fields = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    except Exception:
        raise MiniAppAuthError("parse", "Не вдалося розібрати initData")

    received_hash = fields.pop("hash", "")
    if not received_hash:
        raise MiniAppAuthError("no_hash", "У initData відсутній підпис (hash)")

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()

    def _make_hash(data: Dict[str, str]) -> str:
        return hmac.new(secret_key,
                        _data_check_string(data).encode("utf-8"),
                        hashlib.sha256).hexdigest()

    # Нові клієнти Telegram додають поле "signature" (ed25519). Офіційний приклад
    # перевірки HMAC виключає лише "hash", тому signature лишається в рядку. Але
    # частина клієнтів/бібліотек формує hash без нього - перевіряємо обидва варіанти.
    candidates = [dict(fields)]
    if "signature" in fields:
        candidates.append({k: v for k, v in fields.items() if k != "signature"})
    if not any(hmac.compare_digest(_make_hash(candidate), received_hash)
               for candidate in candidates):
        raise MiniAppAuthError("bad_hash", "Підпис Telegram не збігається")


    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        raise MiniAppAuthError("bad_date", "Некоректна дата авторизації")

    moment = _now() if now is None else now
    if max_age and auth_date:
        if moment - auth_date > max_age:
            raise MiniAppAuthError("expired", "Дані авторизації застаріли", status=403)
        if auth_date - moment > 300:      # допускаємо невеликий розбіг часу
            raise MiniAppAuthError("future", "Дата авторизації з майбутнього", status=403)

    user: Dict[str, Any] = {}
    raw_user = fields.get("user")
    if raw_user:
        try:
            parsed = json.loads(raw_user)
            if isinstance(parsed, dict):
                user = parsed
        except Exception:
            raise MiniAppAuthError("bad_user", "Не вдалося розібрати дані користувача")

    try:
        user_id = int(user.get("id", 0))
    except (TypeError, ValueError):
        user_id = 0
    if not user_id:
        raise MiniAppAuthError("no_user", "У даних Telegram немає користувача")

    if allowed_ids and user_id not in [int(i) for i in allowed_ids]:
        raise MiniAppAuthError("forbidden", "Цей Telegram ID не має доступу до Mini App",
                               status=403)

    return {
        "user": user,
        "user_id": user_id,
        "auth_date": auth_date,
        "age": int(moment - auth_date) if auth_date else 0,
        "query_id": fields.get("query_id", ""),
        "start_param": fields.get("start_param", ""),
    }


class SessionStore:
    """Видає та перевіряє сесійні токени Mini App.

    Токен stateless: "<uid>.<expires>.<підпис>", де підпис - HMAC від випадкового
    секрету процесу. Після перезапуску бота секрет новий, тому всі старі токени
    автоматично стають недійсними (це саме те, що потрібно).
    """

    def __init__(self, ttl: int = DEFAULT_SESSION_TTL, secret: Optional[bytes] = None):
        self.ttl = int(ttl)
        self._secret = secret or secrets.token_bytes(32)
        self._lock = threading.Lock()
        self._issued = 0

    def _sign(self, payload: str) -> str:
        return hmac.new(self._secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    def issue(self, user_id: int) -> Tuple[str, int]:
        expires = int(_now() + self.ttl)
        payload = f"{int(user_id)}.{expires}"
        with self._lock:
            self._issued += 1
        return f"{payload}.{self._sign(payload)}", self.ttl

    def verify(self, token: Optional[str]) -> Optional[int]:
        if not token or not isinstance(token, str):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        user_id, expires, signature = parts
        payload = f"{user_id}.{expires}"
        if not hmac.compare_digest(self._sign(payload), signature):
            return None
        try:
            if int(expires) < int(_now()):
                return None
            return int(user_id)
        except (TypeError, ValueError):
            return None

    def revoke_all(self) -> None:
        """Розриває всі сесії (новий секрет -> усі старі токени недійсні)."""
        with self._lock:
            self._secret = secrets.token_bytes(32)

    @property
    def issued_total(self) -> int:
        return self._issued


class AuthGuard:
    """Простий захист від перебору підписів: ліміт невдач з однієї адреси."""

    def __init__(self, limit: int = AUTH_FAIL_LIMIT, window: int = AUTH_FAIL_WINDOW):
        self.limit = limit
        self.window = window
        self._fails: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def is_blocked(self, ip: str) -> bool:
        moment = _now()
        with self._lock:
            stamps = [t for t in self._fails.get(ip, []) if moment - t < self.window]
            self._fails[ip] = stamps
            return len(stamps) >= self.limit

    def register_fail(self, ip: str) -> None:
        with self._lock:
            self._fails.setdefault(ip, []).append(_now())

    def reset(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)

    @staticmethod
    def client_ip(handler: BaseHTTPRequestHandler) -> str:
        forwarded = handler.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return handler.client_address[0] if handler.client_address else "?"


# ==========================================
# СИСТЕМНИЙ ЗНІМОК ДЛЯ ДАШБОРДУ (ТІЛЬКИ ЧИТАННЯ)
# ==========================================
def _human_uptime(seconds: float) -> str:
    seconds = int(max(0, seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} д {hours} год"
    if hours:
        return f"{hours} год {minutes} хв"
    return f"{minutes} хв"


def system_snapshot(bot_version: str = "", pc_name: str = "") -> Dict[str, Any]:
    """Знімок стану ПК для Mini App. Нічого не змінює - лише читає дані."""
    import datetime as _dt

    snapshot: Dict[str, Any] = {
        "api_version": API_VERSION,
        "bot_version": bot_version,
        "pc_name": pc_name or platform.node(),
        "platform": f"{platform.system()} {platform.release()}",
        "python": platform.python_version(),
        "timestamp": _dt.datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "time": int(_now()),
    }
    if psutil is None:
        snapshot["psutil"] = False
        return snapshot

    snapshot["psutil"] = True
    try:
        snapshot["cpu"] = {
            "percent": psutil.cpu_percent(interval=0.15),
            "cores_physical": psutil.cpu_count(logical=False) or 0,
            "cores_logical": psutil.cpu_count(logical=True) or 0,
            "freq_mhz": int(psutil.cpu_freq().current) if psutil.cpu_freq() else 0,
        }
    except Exception as e:
        log(f"snapshot cpu: {e}")

    try:
        mem = psutil.virtual_memory()
        snapshot["memory"] = {
            "percent": mem.percent,
            "total_mb": round(mem.total / 1048576),
            "used_mb": round((mem.total - mem.available) / 1048576),
        }
        swap = psutil.swap_memory()
        snapshot["swap"] = {"percent": swap.percent, "total_mb": round(swap.total / 1048576)}
    except Exception as e:
        log(f"snapshot memory: {e}")

    try:
        disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
        snapshot["disk"] = {
            "percent": disk.percent,
            "total_gb": round(disk.total / 1073741824, 1),
            "free_gb": round(disk.free / 1073741824, 1),
        }
    except Exception as e:
        log(f"snapshot disk: {e}")

    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            snapshot["battery"] = {
                "percent": round(battery.percent),
                "plugged": bool(battery.power_plugged),
            }
    except Exception:
        pass

    try:
        snapshot["uptime"] = _human_uptime(_now() - psutil.boot_time())
    except Exception:
        pass

    try:
        procs = sorted(psutil.process_iter(["name", "memory_percent"]),
                       key=lambda p: p.info.get("memory_percent") or 0, reverse=True)[:5]
        snapshot["top_processes"] = [
            {"name": p.info.get("name") or "?",
             "memory_percent": round(p.info.get("memory_percent") or 0, 1)}
            for p in procs
        ]
    except Exception as e:
        log(f"snapshot processes: {e}")

    return snapshot


# ==========================================
# ДІЇ КЕРУВАННЯ ПК (ЕТАП 3)
# ==========================================
# Усе, що змінює стан ПК, зібрано тут. Кожна функція повертає словник формату
# {"ok": bool, ...} і ніколи не кидає виняток назовні - помилка дії не повинна
# ламати ні HTTP-сервер, ні бота.
POWER_ACTIONS = ("shutdown", "reboot", "sleep", "lock")
POWER_LABELS = {
    "shutdown": "Вимкнення ПК",
    "reboot": "Перезавантаження",
    "sleep": "Режим сну",
    "lock": "Блокування екрана",
}

MEDIA_KEYS = {
    "volume_up": 0xAF,      # VK_VOLUME_UP
    "volume_down": 0xAE,    # VK_VOLUME_DOWN
    "mute": 0xAD,           # VK_VOLUME_MUTE
    "play_pause": 0xB3,     # VK_MEDIA_PLAY_PAUSE
    "next": 0xB0,           # VK_MEDIA_NEXT_TRACK
    "prev": 0xB1,           # VK_MEDIA_PREV_TRACK
    "stop": 0xB2,           # VK_MEDIA_STOP
}

MEDIA_LABELS = {
    "volume_up": "Гучність збільшено",
    "volume_down": "Гучність зменшено",
    "mute": "Звук перемкнуто",
    "play_pause": "Плей / пауза",
    "next": "Наступний трек",
    "prev": "Попередній трек",
    "stop": "Стоп",
}

# Процеси, які не можна завершувати навіть із підтвердженням: без них Windows
# падає або перезавантажується (bsod / втрата сесії).
PROTECTED_PROCESSES = {
    "system", "system idle process", "registry", "memory compression", "memcompression",
    "secure system", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe", "services.exe",
    "lsass.exe", "svchost.exe", "fontdrvhost.exe", "dwm.exe", "audiodg.exe", "sihost.exe",
}

# Батьківські процеси, через які запущений бот: їх завершення = вбити бота.
BOT_HOST_PROCESSES = {
    "python.exe", "pythonw.exe", "py.exe", "pyw.exe",
    "cmd.exe", "conhost.exe", "wscript.exe", "cscript.exe", "powershell.exe", "pwsh.exe",
}

_CAMERA_LOCK = threading.Lock()
_CAMERA_LAST = [0.0]


class ConfirmStore:
    """Одноразові токени підтвердження критичних дій.

    Токен прив'язаний до дії ("power:shutdown", "kill:4242") і до Telegram ID.
    Живе CONFIRM_TTL секунд і знімається при першому використанні, тому повторний
    запит із тим самим токеном уже не пройде.
    """

    def __init__(self, ttl: int = CONFIRM_TTL):
        self.ttl = int(ttl)
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def issue(self, action: str, user_id: int) -> Dict[str, Any]:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._prune()
            self._items[token] = {"action": action,
                                  "user_id": int(user_id),
                                  "expires": _now() + self.ttl}
        return {"token": token, "expires_in": self.ttl}

    def consume(self, token: str, action: str, user_id: int) -> bool:
        if not token:
            return False
        with self._lock:
            item = self._items.pop(token, None)
        if not item or item["expires"] < _now():
            return False
        return item["action"] == action and item["user_id"] == int(user_id)

    def _prune(self) -> None:
        """Прибирає прострочені токени (викликається під замком)."""
        moment = _now()
        for key in [k for k, v in self._items.items() if v["expires"] < moment]:
            self._items.pop(key, None)


def _is_windows() -> bool:
    return os.name == "nt"


def clamp_delay(value: Any, default: int = 15) -> int:
    """Затримка вимкнення: ціле число в межах POWER_DELAY_MIN..POWER_DELAY_MAX."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(POWER_DELAY_MIN, min(POWER_DELAY_MAX, number))


def power_confirm_text(action: str, delay: int = 0) -> str:
    """Текст попередження для підтвердження дії живлення."""
    if action == "shutdown":
        return f"ПК вимкнеться через {delay} с. Незбережені дані можуть втратитися."
    if action == "reboot":
        return f"ПК перезавантажиться через {delay} с. Бот підніметься сам після старту."
    if action == "sleep":
        return "ПК перейде в режим сну. Розбудити його віддалено не вийде."
    return POWER_LABELS.get(action, "Дія з живленням")


def power_cancel() -> Dict[str, Any]:
    """Скасовує заплановане вимкнення/перезавантаження (shutdown /a)."""
    if not _is_windows():
        return {"ok": False, "error": "Керування живленням доступне лише на Windows",
                "reason": "platform"}
    try:
        proc = subprocess.run(["shutdown", "/a"], capture_output=True, text=True, timeout=15)
    except Exception as e:
        return {"ok": False, "error": f"Не вдалося скасувати: {e}", "reason": "exec"}
    if proc.returncode != 0:
        return {"ok": False, "error": "Немає запланованого вимкнення",
                "details": (proc.stderr or proc.stdout or "").strip(), "reason": "nothing"}
    return {"ok": True, "action": "cancel", "text": "Заплановане вимкнення скасовано"}


def power_execute(action: str, delay: int = 15) -> Dict[str, Any]:
    """Виконує дію живлення. Windows-only, без винятків назовні."""
    action = str(action or "").strip().lower()
    if action not in POWER_ACTIONS:
        return {"ok": False, "error": "Невідома дія живлення", "reason": "bad_action"}
    if not _is_windows():
        return {"ok": False, "error": "Керування живленням доступне лише на Windows",
                "reason": "platform"}

    if action == "lock":
        try:
            import ctypes
            if not ctypes.windll.user32.LockWorkStation():
                return {"ok": False, "error": "Windows відмовився блокувати екран",
                        "reason": "exec"}
        except Exception as e:
            return {"ok": False, "error": f"Не вдалося заблокувати екран: {e}",
                    "reason": "exec"}
        return {"ok": True, "action": "lock", "delay": 0, "text": "Екран заблоковано"}

    if action == "sleep":
        try:
            import ctypes
            # SetSuspendState(Hibernate=0, ForceCritical=1, DisableWakeEvent=0).
            # Якщо в системі вимкнена гібернація - це звичайний сон.
            ctypes.windll.powrprof.SetSuspendState(0, 1, 0)
        except Exception as e:
            return {"ok": False, "error": f"Не вдалося перевести ПК в сон: {e}",
                    "reason": "exec"}
        return {"ok": True, "action": "sleep", "delay": 0, "text": "ПК переходить у сон"}

    delay = clamp_delay(delay)
    comment = f"ControlPC Mini App: {POWER_LABELS.get(action, action)}"
    args = ["shutdown", "/s" if action == "shutdown" else "/r", "/t", str(delay), "/c", comment]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=20)
    except Exception as e:
        return {"ok": False, "error": f"Команда не запустилася: {e}", "reason": "exec"}
    if proc.returncode != 0:
        details = (proc.stderr or proc.stdout or "").strip()
        return {"ok": False, "error": details or "Windows відмовився виконувати команду",
                "reason": "exec"}

    text = (f"ПК вимкнеться через {delay} с" if action == "shutdown"
            else f"ПК перезавантажиться через {delay} с")
    return {"ok": True, "action": action, "delay": delay, "text": text}


def _bot_tree_pids() -> set:
    """PID бота та батьківських python/cmd/wscript - завершувати їх не можна."""
    pids = {os.getpid()}
    if psutil is None:
        return pids
    try:
        current = psutil.Process()
        for _ in range(8):
            parent = current.parent()
            if parent is None:
                break
            if (parent.name() or "").lower() not in BOT_HOST_PROCESSES:
                break
            pids.add(parent.pid)
            current = parent
    except Exception:
        pass
    return pids


def _protected_reason(pid: int, name: str, bot_pids: set) -> str:
    """Чому процес не можна завершувати (порожній рядок = можна)."""
    lowered = (name or "").lower()
    if pid in (0, 4) or lowered in PROTECTED_PROCESSES:
        return "Критичний процес Windows"
    if pid in bot_pids:
        return "Процес бота ControlPC"
    return ""


def list_processes(limit: int = 40, query: str = "") -> List[Dict[str, Any]]:
    """Активні процеси для панелі «Додатки»: ім'я, PID, RAM, стан, захист."""
    if psutil is None:
        return []
    needle = (query or "").strip().lower()
    bot_pids = _bot_tree_pids()
    items: List[Dict[str, Any]] = []
    try:
        iterator = psutil.process_iter(["pid", "name", "username", "memory_percent", "status"])
    except Exception as e:
        log(f"processes: {e}")
        return []
    for proc in iterator:
        try:
            info = proc.info
            pid = int(info.get("pid") or 0)
            name = info.get("name") or "?"
            if needle and needle not in name.lower():
                continue
            reason = _protected_reason(pid, name, bot_pids)
            items.append({
                "pid": pid,
                "name": name,
                "memory_percent": round(float(info.get("memory_percent") or 0), 1),
                "user": (info.get("username") or "").split("\\")[-1],
                "status": (info.get("status") or "").lower(),
                "protected": bool(reason),
                "protected_reason": reason,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, ValueError):
            continue
    items.sort(key=lambda item: item["memory_percent"], reverse=True)
    return items[:max(1, int(limit or 40))]


def kill_prepare(pid: Any) -> Dict[str, Any]:
    """Перевіряє, чи можна завершити процес, і віддає дані для підтвердження."""
    if psutil is None:
        return {"ok": False, "error": "psutil недоступний на цьому ПК", "reason": "psutil"}
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Некоректний PID", "reason": "bad_pid"}
    if pid <= 0:
        return {"ok": False, "error": "Некоректний PID", "reason": "bad_pid"}
    try:
        proc = psutil.Process(pid)
        name = proc.name() or "?"
    except psutil.NoSuchProcess:
        return {"ok": False, "error": "Процес уже не працює", "reason": "gone"}
    except psutil.AccessDenied:
        return {"ok": False, "error": "Немає доступу до цього процесу", "reason": "access"}
    except Exception as e:
        return {"ok": False, "error": f"Не вдалося прочитати процес: {e}", "reason": "error"}

    reason = _protected_reason(pid, name, _bot_tree_pids())
    if reason:
        return {"ok": False, "pid": pid, "name": name, "reason": "protected",
                "error": f"{reason} — завершення заблоковано"}
    try:
        memory = round(float(proc.memory_percent() or 0), 1)
    except Exception:
        memory = 0.0
    return {"ok": True, "pid": pid, "name": name, "memory_percent": memory,
            "text": f"Завершити «{name}» (PID {pid})?"}


def kill_process(pid: Any) -> Dict[str, Any]:
    """Завершує процес: terminate(), а якщо не відповів - kill()."""
    check = kill_prepare(pid)
    if not check.get("ok"):
        return check
    pid, name = check["pid"], check["name"]
    started = _now()
    try:
        proc = psutil.Process(pid)
        proc.terminate()
    except psutil.NoSuchProcess:
        return {"ok": False, "pid": pid, "name": name, "reason": "gone",
                "error": "Процес уже завершився"}
    except psutil.AccessDenied:
        return {"ok": False, "pid": pid, "name": name, "reason": "access",
                "error": "Немає прав — запусти бота від адміністратора"}
    except Exception as e:
        return {"ok": False, "pid": pid, "name": name, "reason": "error",
                "error": f"Не вдалося завершити: {e}"}

    forced = False
    try:
        proc.wait(timeout=2.0)
    except psutil.TimeoutExpired:
        try:
            proc.kill()
            forced = True
            proc.wait(timeout=1.5)
        except psutil.NoSuchProcess:
            forced = True
        except Exception as e:
            return {"ok": False, "pid": pid, "name": name, "reason": "stuck",
                    "error": f"Процес не завершився: {e}"}
    except Exception:
        pass

    log(f"kill {name} (PID {pid}) -> {'forced' if forced else 'terminate'}")
    return {"ok": True, "pid": pid, "name": name, "forced": forced,
            "elapsed_ms": int((_now() - started) * 1000),
            "text": f"«{name}» завершено" + (" (примусово)" if forced else "")}


def camera_available() -> bool:
    """Чи є на ПК модуль opencv (перевірка без важкого імпорту)."""
    try:
        return importlib.util.find_spec("cv2") is not None
    except Exception:
        return False


def camera_snapshot(quality: int = CAMERA_QUALITY) -> Tuple[bytes, int, int]:
    """Знімок з веб-камери у JPEG у пам'яті (файли не створюються).

    Повертає (jpeg, ширина, висота) або кидає MiniAppError з людським текстом.
    """
    if not _CAMERA_LOCK.acquire(blocking=False):
        raise MiniAppError("Камера вже зайнята іншим знімком — спробуй за мить")
    try:
        if _now() - _CAMERA_LAST[0] < CAMERA_MIN_INTERVAL:
            raise MiniAppError("Зачекай кілька секунд перед наступним знімком")
        try:
            import cv2
        except ImportError:
            raise MiniAppError("Модуль opencv на ПК не встановлено")

        cap = None
        try:
            try:
                cap = cv2.VideoCapture(0, cv2.CAP_DSHOW if _is_windows() else 0)
            except Exception:
                cap = cv2.VideoCapture(0)
            if cap is None or not cap.isOpened():
                raise MiniAppError("Камера не знайдена або зайнята іншою програмою")
            try:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            except Exception:
                pass
            frame = None
            for _ in range(4):          # перші кадри камери часто темні
                ok, candidate = cap.read()
                if ok and candidate is not None:
                    frame = candidate
                time.sleep(0.08)
            if frame is None:
                raise MiniAppError("Камера не віддала кадр")
            ok_encode, buffer = cv2.imencode(".jpg", frame,
                                             [cv2.IMWRITE_JPEG_QUALITY, int(quality)])
            if not ok_encode:
                raise MiniAppError("Не вдалося стиснути кадр у JPEG")
            data = buffer.tobytes()
            height, width = int(frame.shape[0]), int(frame.shape[1])
            _CAMERA_LAST[0] = _now()
            return data, width, height
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass
    finally:
        _CAMERA_LOCK.release()


def media_action(action: str, steps: int = 5) -> Dict[str, Any]:
    """Гучність / мут / медіа-клавіші через keybd_event (без сторонніх бібліотек)."""
    action = str(action or "").strip().lower()
    if action not in MEDIA_KEYS:
        return {"ok": False, "error": "Невідома медіа-дія", "reason": "bad_action"}
    if not _is_windows():
        return {"ok": False, "error": "Медіа-клавіші доступні лише на Windows",
                "reason": "platform"}
    try:
        count = int(steps)
    except (TypeError, ValueError):
        count = 5
    if action in ("volume_up", "volume_down"):
        count = max(1, min(20, count))
    else:
        count = 1
    try:
        import ctypes
        user32 = ctypes.windll.user32
        vk = MEDIA_KEYS[action]
        for _ in range(count):
            user32.keybd_event(vk, 0, 0, 0)     # натиснути
            user32.keybd_event(vk, 0, 2, 0)     # відпустити (KEYEVENTF_KEYUP)
            if count > 1:
                time.sleep(0.03)
    except Exception as e:
        return {"ok": False, "error": f"Не вдалося надіслати клавішу: {e}", "reason": "exec"}
    return {"ok": True, "action": action, "steps": count,
            "text": MEDIA_LABELS.get(action, "Виконано")}


def capabilities() -> Dict[str, Any]:
    """Що реально доступне на цьому ПК (Mini App вимикає зайві кнопки)."""
    windows = _is_windows()
    return {
        "platform": f"{platform.system()} {platform.release()}",
        "windows": windows,
        "power": windows,
        "media": windows,
        "camera": camera_available(),
        "processes": psutil is not None,
        "power_delay": {"min": POWER_DELAY_MIN, "max": POWER_DELAY_MAX, "default": 15},
        "limits": {"processes": PROCESS_LIST_LIMIT, "camera_interval": CAMERA_MIN_INTERVAL},
    }


_FALLBACK_HTML = """<!doctype html>
<html lang="uk"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ControlPC Mini App</title>
<style>body{background:#17212b;color:#e9eef3;font:16px/1.5 -apple-system,Segoe UI,sans-serif;
padding:24px;max-width:520px;margin:0 auto}h1{font-size:20px;color:#4ea1ff}
code{background:#0e1621;padding:2px 6px;border-radius:6px}</style></head>
<body><h1>🖥 ControlPC Mini App</h1>
<p>Сервер працює, але файли інтерфейсу не знайдено.</p>
<p>Поклади у папку бота каталог <code>miniapp/</code> з файлами
<code>index.html</code>, <code>style.css</code>, <code>app.js</code> і перезапусти бота.</p>
<p>Перевірка API: <code>/api/health</code></p></body></html>"""


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer, який не засмічує лог бота мережевими обривами.

    Mini App часто закривають посеред запиту (згорнули Telegram, зникло
    з'єднання) - це нормальний ConnectionReset, а не помилка сервера.
    """

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        log(f"HTTP: {exc}")


# ==========================================
# HTTP-ОБРОБНИК MINI APP
# ==========================================
_CSP = ("default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://telegram.org; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "base-uri 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org")


class MiniAppHandler(BaseHTTPRequestHandler):
    """Обробник запитів Mini App: статика + JSON API з перевіркою сесії."""

    server_version = f"ControlPC-MiniApp/{API_VERSION}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # Заповнюється у MiniAppServer.start() через динамічний підклас
    config: MiniAppConfig
    bot_token: str = ""
    bot_version: str = ""
    pc_name: str = ""
    allowed_origins: Tuple[str, ...] = ()
    sessions: SessionStore
    guard: AuthGuard
    confirms: ConfirmStore

    # --- базове ---
    def log_message(self, fmt: str, *args: Any) -> None:
        log(f"{self.address_string()} {fmt % args}")

    def log_error(self, fmt: str, *args: Any) -> None:
        log(f"ERROR {fmt % args}")

    def _send(self, body: bytes, status: int = 200,
              content_type: str = "application/json; charset=utf-8",
              extra: Optional[Dict[str, str]] = None) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            log(f"send: {e}")

    def _json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(body, status)

    def _error(self, status: int, message: str, reason: str = "") -> None:
        self._json({"ok": False, "error": message, "reason": reason}, status)

    def _read_json(self) -> Optional[Dict[str, Any]]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self._error(400, "Некоректний Content-Length", "bad_length")
            return None
        if length <= 0:
            self._error(400, "Порожній запит", "empty_body")
            return None
        if length > MAX_BODY_BYTES:
            self._error(413, "Запит завеликий", "too_large")
            return None
        try:
            raw = self.rfile.read(length)
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            self._error(400, "Очікується JSON", "bad_json")
            return None
        if not isinstance(data, dict):
            self._error(400, "Очікується JSON-об'єкт", "bad_json_type")
            return None
        return data

    # --- безпека ---
    def _origin_allowed(self) -> bool:
        """Захист від сторонніх сторінок: Origin має бути свій або дозволений."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in self.allowed_origins:
            return True
        host = urllib.parse.urlsplit("//" + (self.headers.get("Host") or "")).netloc
        return bool(host) and urllib.parse.urlsplit(origin).netloc == host

    def _session_token(self) -> str:
        token = (self.headers.get("X-MiniApp-Token") or "").strip()
        if not token:
            auth = (self.headers.get("Authorization") or "").strip()
            if auth.lower().startswith("bearer "):
                token = auth[7:].strip()
        return token

    def _require_session(self) -> Optional[int]:
        user_id = self.sessions.verify(self._session_token())
        if not user_id:
            self._error(401, "Потрібна авторизація Mini App", "session")
            return None
        return user_id

    # --- статика ---
    def _serve_static(self, path: str) -> None:
        rel = urllib.parse.unquote(path).lstrip("/") or "index.html"
        root = os.path.abspath(self.config.miniapp_dir)
        candidate = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
        inside = candidate == root or candidate.startswith(root + os.sep)
        if not inside:
            self._error(404, "Не знайдено", "not_found")   # не розкриваємо структуру каталогів
            return
        if not os.path.isfile(candidate):
            if rel in ("index.html", "/"):
                self._send(_FALLBACK_HTML.encode("utf-8"), 200,
                           "text/html; charset=utf-8",
                           {"Content-Security-Policy": _CSP})
            else:
                self._error(404, "Файл не знайдено", "not_found")
            return
        ext = os.path.splitext(candidate)[1].lower()
        if ext not in STATIC_EXTENSIONS:
            self._error(404, "Файл не знайдено", "not_found")
            return
        try:
            with open(candidate, "rb") as f:
                body = f.read()
        except OSError as e:
            log(f"static {rel}: {e}")
            self._error(500, "Не вдалося прочитати файл", "read_error")
            return
        content_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
        if ext in (".html", ".css", ".js", ".webmanifest"):
            content_type += "; charset=utf-8"
        extra = {"Content-Security-Policy": _CSP} if ext == ".html" else {}
        self._send(body, 200, content_type, extra)

    # --- маршрути ---
    def do_GET(self) -> None:  # noqa: N802 (ім'я вимагає http.server)
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/health":
            self._json({
                "ok": True,
                "api_version": API_VERSION,
                "bot_version": self.bot_version,
                "time": int(_now()),
            })
            return

        if path == "/api/status":
            if not self._require_session():
                return
            self._json({"ok": True, "status": system_snapshot(self.bot_version, self.pc_name)})
            return

        if path == "/api/me":
            user_id = self._require_session()
            if not user_id:
                return
            self._json({"ok": True, "user_id": user_id, "server_time": int(_now())})
            return

        if path == "/api/actions":
            if not self._require_session():
                return
            self._json({"ok": True, "actions": capabilities(), "server_time": int(_now())})
            return

        if path == "/api/processes":
            if not self._require_session():
                return
            if psutil is None:
                self._error(503, "psutil недоступний на цьому ПК", "psutil")
                return
            query = urllib.parse.parse_qs(parsed.query)
            try:
                limit = int((query.get("limit") or [PROCESS_LIST_LIMIT])[0])
            except (TypeError, ValueError):
                limit = PROCESS_LIST_LIMIT
            limit = max(1, min(PROCESS_LIST_LIMIT, limit))
            needle = (query.get("q") or [""])[0][:60]
            processes = list_processes(limit, needle)
            self._json({"ok": True, "processes": processes, "count": len(processes),
                        "server_time": int(_now())})
            return

        if path == "/api/camera/snapshot":
            if not self._require_session():
                return
            try:
                data, width, height = camera_snapshot()
            except MiniAppError as e:
                self._error(503, str(e), "camera")
                return
            except Exception as e:
                log(f"camera: {e}")
                self._error(500, "Не вдалося зробити знімок", "camera")
                return
            log(f"camera snapshot {width}x{height}, {len(data)} байт")
            self._send(data, 200, "image/jpeg")
            return

        if path.startswith("/api/"):
            self._error(404, "Невідомий метод API", "no_route")
            return

        if parsed.path == "/favicon.ico":
            self._send(b"", 204, "image/x-icon")
            return

        self._serve_static(parsed.path)

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"

        if not self._origin_allowed():
            self._error(403, "Запит зі стороннього джерела", "origin")
            return

        if path == "/api/auth":
            ip = AuthGuard.client_ip(self)
            if self.guard.is_blocked(ip):
                self._error(429, "Забагато невдалих спроб. Спробуй за хвилину.", "rate_limited")
                return
            payload = self._read_json()
            if payload is None:
                return
            init_data = payload.get("initData") or payload.get("init_data") or ""
            try:
                info = validate_init_data(init_data, self.bot_token,
                                          self.config.allowed_ids,
                                          self.config.init_data_ttl)
            except MiniAppAuthError as e:
                self.guard.register_fail(ip)
                log(f"auth fail ({e.reason}) from {ip}")
                self._error(e.status, e.message, e.reason)
                return
            self.guard.reset(ip)
            token, ttl = self.sessions.issue(info["user_id"])
            log(f"auth ok for {info['user_id']}")
            self._json({
                "ok": True,
                "token": token,
                "expires_in": ttl,
                "user": _public_user(info["user"]),
                "server_time": int(_now()),
            })
            return

        if path == "/api/logout":
            if not self._require_session():
                return
            self.sessions.revoke_all()
            self._json({"ok": True})
            return

        if path == "/api/power":
            user_id = self._require_session()
            if not user_id:
                return
            payload = self._read_json()
            if payload is None:
                return
            action = str(payload.get("action") or "").strip().lower()
            if action == "cancel":
                result = power_cancel()
                log(f"power cancel -> {result.get('ok')}")
                self._json(result, 200 if result.get("ok") else 409)
                return
            if action not in POWER_ACTIONS:
                self._error(400, "Невідома дія живлення", "bad_action")
                return
            delay = clamp_delay(payload.get("delay"))
            token = str(payload.get("confirm") or "")
            needs_confirm = action in ("shutdown", "reboot", "sleep")
            if needs_confirm and not token:
                response: Dict[str, Any] = {
                    "ok": True,
                    "needs_confirm": True,
                    "action": action,
                    "delay": delay,
                    "text": power_confirm_text(action, delay),
                }
                response.update(self.confirms.issue(f"power:{action}", user_id))
                log(f"power {action}: чекає підтвердження від {user_id}")
                self._json(response)
                return
            if needs_confirm and not self.confirms.consume(token, f"power:{action}", user_id):
                self._error(409, "Підтвердження прострочене — повтори дію", "confirm")
                return
            result = power_execute(action, delay)
            log(f"power {action} -> {result.get('ok')} {result.get('reason') or ''}".rstrip())
            self._json(result, 200 if result.get("ok") else 500)
            return

        if path == "/api/process/kill":
            user_id = self._require_session()
            if not user_id:
                return
            payload = self._read_json()
            if payload is None:
                return
            check = kill_prepare(payload.get("pid"))
            if not check.get("ok"):
                self._json(check, 403 if check.get("reason") == "access" else 400)
                return
            token = str(payload.get("confirm") or "")
            if not token:
                response = {
                    "ok": True,
                    "needs_confirm": True,
                    "pid": check["pid"],
                    "name": check["name"],
                    "memory_percent": check.get("memory_percent", 0),
                    "text": check.get("text", ""),
                }
                response.update(self.confirms.issue(f"kill:{check['pid']}", user_id))
                self._json(response)
                return
            if not self.confirms.consume(token, f"kill:{check['pid']}", user_id):
                self._error(409, "Підтвердження прострочене — онови список", "confirm")
                return
            result = kill_process(check["pid"])
            self._json(result, 200 if result.get("ok") else 409)
            return

        if path == "/api/media":
            if not self._require_session():
                return
            payload = self._read_json()
            if payload is None:
                return
            result = media_action(str(payload.get("action") or ""), payload.get("steps", 5))
            log(f"media {payload.get('action')} -> {result.get('ok')}")
            self._json(result, 200 if result.get("ok") else 500)
            return

        if path.startswith("/api/"):
            self._error(404, "Невідомий метод API", "no_route")
            return

        self._error(405, "Метод не підтримується", "method")


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Тільки безпечні поля користувача Telegram (без зайвих даних назовні)."""
    keys = ("id", "first_name", "last_name", "username", "language_code", "is_premium")
    return {k: user.get(k) for k in keys if user.get(k) is not None}


# ==========================================
# СЕРВЕР MINI APP (ФОНОВИЙ ПОТІК)
# ==========================================
class MiniAppServer:
    """Життєвий цикл HTTP-сервера Mini App у daemon-потоці."""

    def __init__(self, config: MiniAppConfig, bot_token: str,
                 bot_version: str = "", pc_name: str = "",
                 logger: Optional[Callable[[str], None]] = None):
        if logger is not None:
            set_logger(logger)
        self.config = config
        self.bot_token = bot_token
        self.bot_version = bot_version
        self.pc_name = pc_name
        self.sessions = SessionStore(config.session_ttl)
        self.guard = AuthGuard()
        self.confirms = ConfirmStore()
        self.error = ""
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._started_at = 0.0

    # --- стан ---
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def local_url(self) -> str:
        return self.config.local_url

    @property
    def webapp_url(self) -> Optional[str]:
        return self.config.webapp_url

    @property
    def uptime(self) -> int:
        return int(_now() - self._started_at) if self._started_at else 0

    def status_dict(self) -> Dict[str, Any]:
        return {
            "running": self.running,
            "local_url": self.config.local_url,
            "public_url": self.config.public_url,
            "webapp_url": self.config.webapp_url,
            "allowed_ids": self.config.allowed_ids,
            "uptime": self.uptime,
            "sessions_issued": self.sessions.issued_total,
            "error": self.error,
        }

    def _handler_class(self, port: int):
        cfg = self.config
        origins = {
            f"http://127.0.0.1:{port}",
            f"http://localhost:{port}",
            f"http://{cfg.host}:{port}",
        }
        if cfg.public_url:
            parts = urllib.parse.urlsplit(cfg.public_url)
            if parts.scheme and parts.netloc:
                origins.add(f"{parts.scheme}://{parts.netloc}")
        return type("ControlPCMiniAppHandler", (MiniAppHandler,), {
            "config": cfg,
            "bot_token": self.bot_token,
            "bot_version": self.bot_version,
            "pc_name": self.pc_name,
            "allowed_origins": tuple(sorted(origins)),
            "sessions": self.sessions,
            "guard": self.guard,
            "confirms": self.confirms,
        })

    # --- запуск / зупинка ---
    def start(self) -> bool:
        if self._httpd is not None:
            return True
        if not self.config.enabled:
            self.error = "Mini App вимкнено в miniapp_config.json (enabled=false)"
            log(self.error)
            return False
        if not os.path.isfile(os.path.join(self.config.miniapp_dir, "index.html")):
            log("увага: miniapp\\index.html не знайдено - буде віддано сторінку-заглушку")

        last_error: Optional[Exception] = None
        for port in range(self.config.port, self.config.port + 5):
            try:
                httpd = _QuietThreadingHTTPServer((self.config.host, port),
                                                  self._handler_class(port))
            except OSError as e:
                last_error = e
                log(f"порт {port} недоступний: {e}")
                continue
            httpd.daemon_threads = True
            httpd.allow_reuse_address = True
            self.config.port = port
            self._httpd = httpd
            self._thread = threading.Thread(target=self._serve, name="MiniAppHTTP", daemon=True)
            self._thread.start()
            self._started_at = _now()
            log(f"Mini App запущено: {self.local_url}")
            if self.webapp_url:
                log(f"публічна адреса: {self.webapp_url}")
            else:
                log("public_url не задано: кнопка WebApp з'явиться після вказівки "
                    "HTTPS-адреси в miniapp_config.json")
            return True

        self.error = f"не вдалося зайняти порт {self.config.port}: {last_error}"
        log(self.error)
        return False

    def _serve(self) -> None:
        httpd = self._httpd
        if httpd is None:
            return
        try:
            httpd.serve_forever(poll_interval=0.5)
        except Exception as e:      # потік не має падати мовчки
            log(f"serve_forever зупинився: {e}")

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        self._thread = None
        if httpd is None:
            return
        try:
            httpd.shutdown()
        except Exception:
            pass
        try:
            httpd.server_close()
        except Exception:
            pass
        log("Mini App зупинено")


def get_public_url(bot_dir: str, base_dir: Optional[str] = None) -> Optional[str]:
    """HTTPS-адреса Mini App для кнопки Telegram (None, якщо не налаштована)."""
    try:
        cfg = load_config(bot_dir=bot_dir, base_dir=base_dir)
        return cfg.webapp_url
    except Exception:
        return None


def start_webapp_server(bot_dir: str,
                        bot_token: str,
                        bot_version: str = "",
                        pc_name: str = "",
                        default_allowed: Optional[List[int]] = None,
                        base_dir: Optional[str] = None,
                        logger: Optional[Callable[[str], None]] = None) -> Optional[MiniAppServer]:
    """Зручний старт для ControlPC.py: конфіг -> сервер -> потік.

    Ніколи не кидає виняток: якщо щось пішло не так, бот продовжує працювати
    (Mini App просто буде недоступним).
    """
    try:
        base = base_dir or os.path.dirname(os.path.abspath(__file__))
        cfg = load_config(bot_dir=bot_dir, base_dir=base, default_allowed=default_allowed)
        server = MiniAppServer(cfg, bot_token, bot_version=bot_version, pc_name=pc_name,
                               logger=logger)
        return server if server.start() else None
    except Exception as e:
        log(f"не вдалося запустити Mini App: {e}")
        return None








