"""Універсальний інсталятор ControlPC (Telegram-бот + Telegram Mini App).

Що робить скрипт (кожен крок ідемпотентний - повторний запуск не ламає
вже налаштований ПК):
  1. Запитує Ngrok Authtoken (Enter - пропустити).
  2. Готує робочу папку %LOCALAPPDATA%\\ControlPC (та сама, що в ControlPC.py).
  3. Атомарно завантажує свіжий ControlPC.py з GitHub raw і перевіряє його.
  4. Доставляє pip-залежності бота.
  5. Реєструє authtoken у ngrok.
  6. Генерує miniapp_config.json із постійним доменом тунелю.
  7. Створює прихований фоновий запуск (ngrok + цикл оновлення бота) і додає
     його в автозапуск Windows.

Запуск: python installer.py
Компіляція в один exe без зовнішніх залежностей:
    pyinstaller --onefile --console --name installer installer.py
Скрипт використовує лише стандартну бібліотеку, тому додаткові pip-пакети
самому інсталятору не потрібні.
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


# --- Параметри встановлення -------------------------------------------------
APP_NAME = "ControlPC"
RAW_BASE = "https://raw.githubusercontent.com/bsatird/ControlPC/refs/heads/main"
BOT_SCRIPT_URL = f"{RAW_BASE}/ControlPC.py"
NGROK_DOMAIN = "ouch-modulator-gleeful.ngrok-free.dev"
MINIAPP_PORT = 8777
ALLOWED_IDS = (7678008217,)
MIN_PYTHON = (3, 8)
MIN_BOT_SCRIPT_SIZE = 10_000        # менший файл - точно не ControlPC.py
# Файли Mini App (той самий перелік, що MINIAPP_REMOTE_FILES у ControlPC.py).
MINIAPP_FILES = ("miniapp_api.py", "miniapp/index.html", "miniapp/style.css",
                 "miniapp/app.js")
MINIAPP_MIN_SIZE = 200               # захист від HTML-сторінки помилки замість файла

# Усе, що імпортує ControlPC.py. Список синхронізований з $packages у run_bot.ps1,
# інакше на новому ПК бот падає вже на першому import.
PIP_PACKAGES = (
    "pyTelegramBotAPI", "opencv-python", "pyautogui", "psutil", "pyttsx3",
    "sounddevice", "scipy", "pyperclip", "pillow",
)
# Імена модулів для перевірки після pip install (назва pip-пакета != імпорт).
REQUIRED_MODULES = ("telebot", "cv2", "numpy", "PIL", "pyautogui", "psutil",
                    "pyttsx3", "sounddevice", "scipy", "pyperclip")

NET_TIMEOUT = 30                     # секунд на одну спробу завантаження
NET_ATTEMPTS = 3                     # скільки разів пробуємо мережу
PIP_TIMEOUT = 1200                   # opencv-python на повільному інтернеті
TASK_NAME = "ControlPC_Bot"          # завдання, яке створює run_bot.ps1
STARTUP_LAUNCHER = "ControlPC_Startup.vbs"
PLACEHOLDER_TOKEN = "ВСТАВ_СВІЙ_ТОКЕН_СЮДИ"
BOT_TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{25,}$")
# authtoken ngrok: довгий рядок із латинських літер, цифр, '_' та '-'.
NGROK_TOKEN_RE = re.compile(r"^[A-Za-z0-9_\-]{30,}$")
# Імена файлів/ярликів старих інсталяцій: другий автозапуск підняв би другого бота.
AUTOSTART_MARKERS = ("controlpc", "start_background", "start_hidden", "start_internal")


class InstallerError(RuntimeError):
    """Помилка, яку треба показати користувачу без traceback."""


# --- Вивід у консоль --------------------------------------------------------

def _setup_console() -> None:
    """Вмикає UTF-8 у консолі Windows, щоб кирилиця не падала на cp866."""
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        if stream is None:
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(text: str = "", *, error: bool = False) -> None:
    """Друкує рядок; мовчки ігнорує вивід, якщо консолі немає (pythonw)."""
    stream = sys.stderr if error else sys.stdout
    if stream is None:
        return
    try:
        print(text, file=stream, flush=True)
    except Exception:
        pass


def step(title: str) -> None:
    say("")
    say(f"[*] {title}")


def ok(text: str) -> None:
    say(f"    [+] {text}")


def warn(text: str) -> None:
    say(f"    [!] {text}", error=True)


def fail(text: str) -> None:
    say(f"    [x] {text}", error=True)


def _interactive() -> bool:
    """Чи можна питати користувача (у pipe/без консолі - ні)."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except Exception:
        return False


def ask(prompt: str) -> Optional[str]:
    """Читає відповідь користувача. None - ввід недоступний (EOF)."""
    if sys.stdin is None:
        return None
    try:
        return input(prompt).strip()
    except EOFError:
        say("")
        return None


def ask_yes_no(question: str, default: bool = True) -> bool:
    """Питання так/ні; Enter - значення за замовчуванням."""
    hint = "[Y/n]" if default else "[y/N]"
    answer = ask(f"    {question} {hint} ")
    if answer is None:
        return False
    if not answer:
        return default
    return answer.lower() in ("y", "yes", "т", "так", "д", "да")


def pause(message: str = "Натисни Enter, щоб вийти...") -> None:
    """Тримає вікно відкритим після завершення (важливо для installer.exe)."""
    if not _interactive():
        return
    try:
        input(message)
    except (EOFError, KeyboardInterrupt):
        pass


# --- Шляхи та файли ---------------------------------------------------------

def _env_path(name: str) -> Optional[Path]:
    value = os.environ.get(name)
    return Path(value) if value else None


def bot_dir() -> Optional[Path]:
    """%LOCALAPPDATA%\\ControlPC - та сама папка, яку використовує ControlPC.py."""
    local = _env_path("LOCALAPPDATA")
    return local / APP_NAME if local else None


def startup_dir() -> Optional[Path]:
    """Папка «Автозавантаження» поточного користувача."""
    appdata = _env_path("APPDATA")
    if not appdata:
        return None
    return (appdata / "Microsoft" / "Windows" / "Start Menu"
            / "Programs" / "Startup")


def _write_text_atomic(path: Path, text: str, encoding: str = "utf-8") -> None:
    """Пише текст через тимчасовий файл + os.replace.

    Так на диску ніколи не залишається напівзаписаний json/bat/vbs, навіть якщо
    інсталятор перервано або файл зараз читає інший процес.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as handle:
            handle.write(text)
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    """Те саме для бінарних даних (завантажений .py пишемо байт-у-байт)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def _read_json_object(path: Path) -> Optional[Dict[str, object]]:
    """Читає JSON-об'єкт; None - файла немає, він пошкоджений або це не об'єкт."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# --- Підпроцеси -------------------------------------------------------------

def _creation_flags() -> int:
    """CREATE_NO_WINDOW: дочірні консолі не блимають поверх вікна інсталятора."""
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return 0


def _decode_output(data: Optional[bytes]) -> str:
    """Декодує вивід підпроцесу: pip/ngrok на Windows бувають у різних кодуваннях."""
    if not data:
        return ""
    for encoding in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _output(process: subprocess.CompletedProcess) -> str:
    """stdout + stderr підпроцесу одним рядком (для повідомлень про помилки)."""
    parts = [_decode_output(process.stdout).strip(),
             _decode_output(process.stderr).strip()]
    return "\n".join(part for part in parts if part)


def _tail(text: str, limit: int = 1500) -> str:
    """Обрізає довгий вивід, лишаючи кінець - там зазвичай причина помилки."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def run_capture(cmd: Sequence[str], timeout: int) -> subprocess.CompletedProcess:
    """Запускає процес без вікна і збирає сирий stdout/stderr."""
    return subprocess.run(
        [str(part) for part in cmd],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        creationflags=_creation_flags(),
    )


# --- Пошук Python -----------------------------------------------------------

def _python_version(exe: Path) -> Optional[Tuple[int, int, int]]:
    """Повертає версію Python або None (не Python, заглушка Store, помилка)."""
    code = "import sys; print('%d.%d.%d' % sys.version_info[:3])"
    try:
        process = run_capture([exe, "-c", code], timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    raw = _decode_output(process.stdout).strip()
    if process.returncode != 0 or not re.fullmatch(r"\d+\.\d+\.\d+", raw):
        return None
    major, minor, patch = (int(part) for part in raw.split("."))
    return major, minor, patch


def _existing_python(value: object) -> Optional[Path]:
    """Повертає реальний python.exe; pythonw.exe для консолі не годиться."""
    if not value:
        return None
    try:
        path = Path(str(value))
    except (TypeError, ValueError):
        return None
    if path.name.lower() == "pythonw.exe":
        console = path.with_name("python.exe")
        if console.is_file():
            path = console
    return path if path.is_file() else None


def _python_candidates() -> List[Path]:
    """Усі ймовірні інтерпретатори: PATH, py-лаунчер, типові папки встановлення."""
    found: List[Path] = []

    def add(value: object) -> None:
        path = _existing_python(value)
        if path is not None and path not in found:
            found.append(path)

    # Запуск через `python installer.py`: sys.executable - справжній Python.
    # У зібраному installer.exe sys.executable - це сам exe, його не чіпаємо,
    # інакше `installer.exe -m pip ...` рекурсивно запустив би інсталятор.
    if not getattr(sys, "frozen", False):
        add(sys.executable)
    add(shutil.which("python"))
    add(shutil.which("python3"))

    py_launcher = shutil.which("py")
    if py_launcher:
        try:
            process = run_capture(
                [py_launcher, "-3", "-c", "import sys; print(sys.executable)"],
                timeout=30,
            )
            if process.returncode == 0:
                add(_decode_output(process.stdout).strip())
        except (OSError, subprocess.SubprocessError):
            pass

    local = _env_path("LOCALAPPDATA")
    if local:
        programs = local / "Programs" / "Python"
        if programs.is_dir():
            for candidate in sorted(programs.glob("Python3*/python.exe"), reverse=True):
                add(candidate)
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            for candidate in sorted(Path(base).glob("Python3*/python.exe"), reverse=True):
                add(candidate)
    return found


def resolve_python() -> Optional[Tuple[Path, str]]:
    """Перший робочий Python >= 3.8; Windows Store-заглушки відсіюються перевіркою."""
    for exe in _python_candidates():
        version = _python_version(exe)
        if version is None:
            continue
        if version[:2] < MIN_PYTHON:
            warn(f"{exe} - Python {version[0]}.{version[1]}, "
                 f"потрібен {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+, пропускаю.")
            continue
        return exe, ".".join(str(part) for part in version)
    return None


# --- Завантаження з GitHub --------------------------------------------------

def fetch_url(url: str, attempts: int = NET_ATTEMPTS,
              timeout: int = NET_TIMEOUT) -> bytes:
    """Завантажує URL із повторами; кидає InstallerError з людським текстом."""
    last_error = "невідома помилка"
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": f"{APP_NAME}-Installer/1.0",
                "Cache-Control": "no-cache",
                "Accept": "text/plain, */*",
            })
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise InstallerError(f"сервер відповів HTTP {status}")
                data = response.read()
            if not data:
                raise InstallerError("сервер повернув порожній файл")
            return data
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code} {exc.reason or ''}".strip()
            if exc.code in (403, 404, 410):
                break                         # повторювати такі помилки марно
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"{type(exc).__name__}: {getattr(exc, 'reason', exc)}"
        except InstallerError as exc:
            last_error = str(exc)
        if attempt < attempts:
            warn(f"спроба {attempt}/{attempts} не вдалася ({last_error}), повторюю...")
            time.sleep(attempt * 2)
    raise InstallerError(last_error)


def download_bot_script(dest: Path) -> int:
    """Качає ControlPC.py і не дає записати обрізаний файл або HTML-сторінку помилки."""
    data = fetch_url(BOT_SCRIPT_URL)
    try:
        source = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise InstallerError("файл бота не є UTF-8 текстом "
                             "(можливо, GitHub повернув сторінку помилки)") from exc
    if len(data) < MIN_BOT_SCRIPT_SIZE:
        raise InstallerError(f"файл замалий ({len(data)} байт) - це не ControlPC.py")
    if "MY_ID" not in source or "BOT_VERSION" not in source:
        raise InstallerError("у завантаженому файлі немає ознак ControlPC.py")
    try:
        compile(source, dest.name, "exec")
    except SyntaxError as exc:
        raise InstallerError(
            f"у завантаженому ControlPC.py синтаксична помилка: {exc}") from exc
    _write_bytes_atomic(dest, data)
    return len(data)


# --- Залежності Python ------------------------------------------------------

def _pip_available(python_exe: Path) -> bool:
    try:
        process = run_capture([python_exe, "-m", "pip", "--version"], timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return process.returncode == 0


def _ensure_pip(python_exe: Path) -> bool:
    """pip є не в кожній інсталяції Python - за потреби відновлюємо ensurepip."""
    if _pip_available(python_exe):
        return True
    warn("pip не знайдено - пробую відновити через ensurepip...")
    try:
        process = run_capture([python_exe, "-m", "ensurepip", "--upgrade"],
                              timeout=PIP_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        fail(f"ensurepip не запустився: {exc}")
        return False
    if process.returncode != 0:
        fail("ensurepip не зміг відновити pip:")
        say("      " + _tail(_output(process), 800))
        return False
    return _pip_available(python_exe)


def install_packages(python_exe: Path) -> bool:
    """Тихо ставить усі pip-залежності; за потреби повторює з --user."""
    if not _ensure_pip(python_exe):
        return False
    say(f"    pip install {' '.join(PIP_PACKAGES)}")
    say("    (opencv-python великий, на повільному інтернеті це кілька хвилин)")
    base = [python_exe, "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input"]
    last_output = ""
    for extra in ([], ["--user"]):
        if extra:
            warn("системний Python захищений - повторюю встановлення з --user...")
        try:
            process = run_capture(base + extra + list(PIP_PACKAGES),
                                  timeout=PIP_TIMEOUT)
        except subprocess.TimeoutExpired:
            last_output = f"pip не встиг завершитися за {PIP_TIMEOUT} с"
            continue
        except OSError as exc:
            last_output = f"не вдалося запустити pip: {exc}"
            continue
        if process.returncode == 0:
            return True
        last_output = _output(process)
    fail("pip не зміг встановити залежності.")
    if last_output:
        say("    Останні рядки виводу pip:")
        say(_tail(last_output))
    return False


def find_missing_modules(python_exe: Path) -> Optional[List[str]]:
    """Перевіряє, що бот зможе імпортувати свої бібліотеки.

    None - перевірити не вдалося (тоді просто пробуємо pip install).
    """
    code = (
        "import importlib.util as u\n"
        f"names = {list(REQUIRED_MODULES)!r}\n"
        "print(','.join(n for n in names if u.find_spec(n) is None))\n"
    )
    try:
        process = run_capture([python_exe, "-c", code], timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if process.returncode != 0:
        warn("перевірка бібліотек завершилася помилкою:")
        say("      " + _tail(_output(process), 600))
        return None
    raw = _decode_output(process.stdout).strip()
    return [name for name in raw.split(",") if name]


# --- ngrok ------------------------------------------------------------------

def find_ngrok() -> Optional[Path]:
    """Шукає ngrok.exe у PATH, winget-пакеті та типових папках."""
    candidates: List[Path] = []
    from_path = shutil.which("ngrok")
    if from_path:
        candidates.append(Path(from_path))
    local = _env_path("LOCALAPPDATA")
    if local:
        candidates.append(local / "ngrok" / "ngrok.exe")
        winget = local / "Microsoft" / "WinGet" / "Packages"
        if winget.is_dir():
            try:
                candidates.extend(sorted(winget.glob("Ngrok.Ngrok_*/ngrok.exe"),
                                         reverse=True))
            except OSError:
                pass
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                 os.environ.get("USERPROFILE")):
        if base:
            candidates.append(Path(base) / "ngrok" / "ngrok.exe")
    candidates.append(Path("C:/ngrok/ngrok.exe"))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _mask_secret(text: str, secret: str) -> str:
    """Прибирає токен із виводу, щоб він не потрапив у логи чи скріншоти."""
    if secret:
        text = text.replace(secret, "<authtoken>")
    return text


def register_ngrok_token(ngrok_exe: Path, authtoken: str) -> bool:
    """Реєструє authtoken через `ngrok config add-authtoken`."""
    try:
        process = run_capture([ngrok_exe, "config", "add-authtoken", authtoken],
                              timeout=120)
    except subprocess.TimeoutExpired:
        fail("ngrok не відповів за 120 с - authtoken не збережено.")
        return False
    except OSError as exc:
        fail(f"не вдалося запустити ngrok: {exc}")
        return False
    if process.returncode == 0:
        return True
    fail("ngrok відмовився зберегти authtoken:")
    say("      " + _tail(_mask_secret(_output(process), authtoken), 800))
    return False


# --- Конфіг Mini App --------------------------------------------------------

def default_miniapp_config() -> Dict[str, object]:
    """Поля ті самі, що генерує miniapp_api.load_config(), плюс статичний домен."""
    return {
        "enabled": True,
        "host": "127.0.0.1",
        "port": MINIAPP_PORT,
        "public_url": f"https://{NGROK_DOMAIN}",
        "allowed_ids": list(ALLOWED_IDS),
        "init_data_ttl": 86400,
        "session_ttl": 43200,
        "files_dir": "",
        "_comment": ("public_url - постійна HTTPS-адреса Mini App (статичний домен "
                     "ngrok). Без неї Telegram не покаже WebApp-кнопку."),
        "_comment_files": ("files_dir - папка ПК для розділу «Файли»; порожньо = "
                           "папка завантажень користувача."),
    }


def merge_miniapp_config(existing: Optional[Dict[str, object]]) -> Dict[str, object]:
    """Бере свіжі параметри інсталятора, але не втрачає ручних правок користувача."""
    config = default_miniapp_config()
    if not isinstance(existing, dict):
        return config
    files_dir = existing.get("files_dir")
    if isinstance(files_dir, str) and files_dir.strip():
        config["files_dir"] = files_dir
    ids = list(ALLOWED_IDS)
    known = existing.get("allowed_ids")
    if isinstance(known, list):
        for value in known:
            try:
                value = int(value)
            except (TypeError, ValueError):
                continue
            if value not in ids:
                ids.append(value)
    config["allowed_ids"] = ids
    return config


def write_miniapp_config(path: Path) -> bool:
    """Генерує miniapp_config.json атомарно і перечитує його для контролю."""
    existing = _read_json_object(path)
    if path.exists() and existing is None:
        warn("поточний miniapp_config.json пошкоджений - перезаписую.")
    config = merge_miniapp_config(existing)
    payload = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    try:
        if existing is not None:
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        _write_text_atomic(path, payload, "utf-8")
    except OSError as exc:
        fail(f"не вдалося записати {path}: {exc}")
        return False
    if _read_json_object(path) != config:
        fail("записаний miniapp_config.json не читається назад - перевір права.")
        return False
    return True


# --- Токен Telegram-бота ----------------------------------------------------

def read_bot_token(path: Path) -> str:
    """Читає token.txt тим самим способом, що й ControlPC.py (utf-8-sig)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _mask_token(token: str) -> str:
    """Показує лише id бота, щоб сам токен не світився у консолі."""
    return f"{token.split(':', 1)[0]}:***"


def ensure_bot_token(work_dir: Path) -> bool:
    """Перевіряє token.txt; за потреби один раз питає токен у користувача.

    Без токена ControlPC.py не може працювати, тому автозапуск у такому разі
    не створюється - інакше бат-цикл вічно перезапускав би бота, що падає.
    """
    token_file = work_dir / "token.txt"
    current = read_bot_token(token_file)
    if BOT_TOKEN_RE.match(current):
        ok(f"токен бота вже є ({_mask_token(current)})")
        return True
    if current and current != PLACEHOLDER_TOKEN:
        warn("token.txt містить токен неочікуваного формату - перевір його.")
    say("    Токен бота береться у @BotFather (команда /newbot або /token).")
    entered = ask("    Токен Telegram-бота (Enter - пропустити): ")
    if not entered:
        warn("без токена бот не стартує, тому автозапуск не створюю.")
        return False
    if not BOT_TOKEN_RE.match(entered):
        fail("токен не схожий на справжній (формат 123456789:AA...): не зберігаю.")
        return False
    try:
        _write_text_atomic(token_file, entered + "\n", "utf-8")
    except OSError as exc:
        fail(f"не вдалося зберегти {token_file}: {exc}")
        return False
    ok(f"токен збережено у {token_file} ({_mask_token(entered)})")
    return True


# --- Прихований запуск (VBS) ------------------------------------------------
# Файл генерується як UTF-16 (wscript читає такий .vbs і коректно розуміє
# кирилицю в шляхах), тому в шаблоні нижче - звичайні VBS-рядки.

START_HIDDEN_VBS = r"""' ControlPC: прихований запуск бота і тунелю ngrok.
' Файл генерує installer.py - ручні правки зникнуть після перевстановлення.
Option Explicit

Dim gShell, gFso, gBotDir, gBotScript, gPython, gNgrok, gLog, gPort, gDomain
Dim gUpdateUrl, gTmpScript

Set gShell = CreateObject("WScript.Shell")
Set gFso = CreateObject("Scripting.FileSystemObject")

gBotDir = "__BOT_DIR__"
gBotScript = gBotDir & "\ControlPC.py"
gTmpScript = gBotDir & "\ControlPC.download"
gPython = "__PYTHON__"
gNgrok = "__NGROK__"
gLog = gBotDir & "\bot_errors.txt"
gPort = "__PORT__"
gDomain = "__DOMAIN__"
gUpdateUrl = "__UPDATE_URL__"

If WScript.Arguments.Named.Exists("ngrok") Then
    If CountProcesses("wscript.exe", "/ngrok") > 1 Then WScript.Quit 0
    RunNgrokLoop
    WScript.Quit 0
End If

' Другий екземпляр (Автозавантаження + Планувальник) не потрібен: двоє ботів
' з одним токеном Telegram блокує.
If CountProcesses("wscript.exe", WScript.ScriptName) > 1 Then WScript.Quit 0

' Тунель піднімаємо окремим прихованим процесом, щоб він пережив перезапуск бота.
If gNgrok <> "" Then
    If CountProcesses("ngrok.exe", "") = 0 Then
        gShell.Run "wscript.exe " & Quote(WScript.ScriptFullName) & " /ngrok", 0, False
    End If
End If

' Цикл оновлення: ControlPC.py при "Перезапуску" робить os._exit(0), і саме цей
' цикл перезапускає його, попередньо перекачавши свіжий файл з GitHub.
Do
    DownloadUpdate
    If Not gFso.FileExists(gBotScript) Then
        WScript.Sleep 20000          ' немає файла - чекаємо мережу, не спамимо лог
    Else
        RotateLog
        gShell.Run "cmd.exe /c " & Quote(Quote(gPython) & " " & Quote(gBotScript) & _
            " >> " & Quote(gLog) & " 2>&1"), 0, True
        WScript.Sleep 10000
    End If
Loop

' --- допоміжні процедури -----------------------------------------------------

Function Quote(text)
    Quote = Chr(34) & text & Chr(34)
End Function

' Скільки процесів із такою назвою запущено (needle - підрядок у командному рядку).
Function CountProcesses(procName, needle)
    Dim wmi, items, item, total
    total = 0
    On Error Resume Next
    Set wmi = GetObject("winmgmts:\\.\root\cimv2")
    If Not wmi Is Nothing Then
        Set items = wmi.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name='" & procName & "'")
        For Each item In items
            If Len(needle) = 0 Then
                total = total + 1
            ElseIf InStr(1, item.CommandLine & "", needle, vbTextCompare) > 0 Then
                total = total + 1
            End If
        Next
    End If
    On Error GoTo 0
    CountProcesses = total
End Function

' Перекачує ControlPC.py з GitHub: спочатку в .download, підміна - лише коли
' завантаження ціле, щоб обірваний інтернет не залишив бота без файла.
Sub DownloadUpdate()
    Dim http, stream, size
    On Error Resume Next
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    http.setTimeouts 5000, 5000, 10000, 30000
    http.Open "GET", gUpdateUrl, False
    http.setRequestHeader "Cache-Control", "no-cache"
    http.Send
    If Err.Number = 0 And http.Status = 200 Then
        Set stream = CreateObject("ADODB.Stream")
        stream.Type = 1
        stream.Open
        stream.Write http.ResponseBody
        size = stream.Size
        If Err.Number = 0 And size > 10000 Then
            If gFso.FileExists(gTmpScript) Then gFso.DeleteFile gTmpScript, True
            stream.SaveToFile gTmpScript, 2
            stream.Close
            If Err.Number = 0 Then gFso.CopyFile gTmpScript, gBotScript, True
            If Err.Number = 0 Then gFso.DeleteFile gTmpScript, True
        Else
            stream.Close
        End If
    End If
    Err.Clear
    On Error GoTo 0
End Sub

' Лог бота не має рости безкінечно (бот пише туди весь свій вивід).
Sub RotateLog()
    On Error Resume Next
    If gFso.FileExists(gLog) Then
        If gFso.GetFile(gLog).Size > 5000000 Then gFso.DeleteFile gLog, True
    End If
    Err.Clear
    On Error GoTo 0
End Sub

' ngrok зі статичним доменом: тримаємо тунель живим після обривів мережі.
Sub RunNgrokLoop()
    Dim cmd
    cmd = "cmd.exe /c " & Quote(Quote(gNgrok) & " http " & gPort & " --domain=" & _
        gDomain & " --log=stdout")
    Do
        gShell.Run cmd, 0, True
        WScript.Sleep 20000
    Loop
End Sub
"""

STARTUP_VBS = r"""' ControlPC: запуск прихованого супервізора з Автозавантаження.
' Файл генерує installer.py.
Set shell = CreateObject("WScript.Shell")
shell.Run "wscript.exe " & Chr(34) & "__HIDDEN_VBS__" & Chr(34), 0, False
"""


def _vbs_text(template: str, values: Dict[str, str]) -> str:
    """Підставляє шляхи у VBS-шаблон (VBS не екранує зворотні слеші)."""
    text = template
    for key, value in values.items():
        text = text.replace(f"__{key}__", value)
    return text.replace("\n", "\r\n")


def write_hidden_launcher(work_dir: Path, python_exe: Path,
                          ngrok_exe: Optional[Path]) -> Optional[Path]:
    """Створює start_hidden.vbs - супервізор бота і тунелю ngrok."""
    target = work_dir / "start_hidden.vbs"
    text = _vbs_text(START_HIDDEN_VBS, {
        "BOT_DIR": str(work_dir),
        "PYTHON": str(python_exe),
        "NGROK": str(ngrok_exe) if ngrok_exe else "",
        "PORT": str(MINIAPP_PORT),
        "DOMAIN": NGROK_DOMAIN,
        "UPDATE_URL": BOT_SCRIPT_URL,
    })
    try:
        _write_text_atomic(target, text, "utf-16")
    except OSError as exc:
        fail(f"не вдалося записати {target}: {exc}")
        return None
    return target


def write_startup_launcher(startup: Path, hidden_vbs: Path) -> Optional[Path]:
    """Кладе в «Автозавантаження» маленький vbs, що стартує супервізор.

    Автозавантаження працює без прав адміністратора, тому воно - основний спосіб
    підняти бота після входу в систему.
    """
    target = startup / STARTUP_LAUNCHER
    text = _vbs_text(STARTUP_VBS, {"HIDDEN_VBS": str(hidden_vbs)})
    try:
        _write_text_atomic(target, text, "utf-16")
    except OSError as exc:
        fail(f"не вдалося записати {target}: {exc}")
        return None
    return target


# --- Автозапуск -------------------------------------------------------------

def _schtasks(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return run_capture(["schtasks", *args], timeout=timeout)


def list_task_names() -> List[str]:
    """Усі імена завдань планувальника (порожній список, якщо недоступно)."""
    try:
        process = _schtasks("/query", "/fo", "csv", "/nh")
    except (OSError, subprocess.SubprocessError):
        return []
    if process.returncode != 0:
        return []
    names: List[str] = []
    for line in _decode_output(process.stdout).splitlines():
        line = line.strip()
        if not line.startswith('"'):
            continue
        name = line.split('","', 1)[0].strip('"')
        if name:
            names.append(name)
    return names


def task_command(name: str) -> str:
    """Командний рядок завдання (Command + Arguments), порожній - якщо не читається."""
    try:
        process = _schtasks("/query", "/tn", name, "/xml", "ONE")
    except (OSError, subprocess.SubprocessError):
        return ""
    if process.returncode != 0:
        return ""
    xml = _decode_output(process.stdout)
    parts = []
    for tag in ("Command", "Arguments"):
        found = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
        if found:
            parts.append(found.group(1).replace("&amp;", "&").strip())
    return " ".join(part for part in parts if part)


def find_conflicting_tasks(hidden_vbs: Path) -> List[Tuple[str, str]]:
    """Завдання/ярлики старих інсталяцій, які підняли б другого бота."""
    ours = str(hidden_vbs).lower()
    conflicts: List[Tuple[str, str]] = []
    for name in list_task_names():
        if not any(marker in name.lower() for marker in AUTOSTART_MARKERS):
            continue
        command = task_command(name)
        if not command:
            continue                     # закрите завдання іншого користувача
        if ours in command.lower():
            continue                     # це наше завдання
        conflicts.append((name, command))
    return conflicts


def ensure_scheduled_task(hidden_vbs: Path) -> bool:
    """Створює (або перестворює) завдання ControlPC_Bot з прихованим запуском."""
    trigger = f'wscript.exe "{hidden_vbs}"'
    for extra in (["/rl", "highest"], []):
        try:
            process = _schtasks("/create", "/tn", TASK_NAME, "/tr", trigger,
                                "/sc", "onlogon", "/f", *extra, timeout=120)
        except (OSError, subprocess.SubprocessError) as exc:
            warn(f"schtasks недоступний: {exc}")
            return False
        if process.returncode == 0:
            return True
        last = _output(process)
    warn("не вдалося створити завдання планувальника (потрібні права адміністратора):")
    say("      " + _tail(last, 600))
    return False


def remove_task(name: str) -> bool:
    try:
        process = _schtasks("/delete", "/tn", name, "/f", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    return process.returncode == 0


def download_miniapp_files(work_dir: Path) -> int:
    """Докачує файли Mini App; збій не критичний - бот докачає їх сам при старті."""
    saved = 0
    for rel in MINIAPP_FILES:
        target = work_dir / Path(*rel.split("/"))
        try:
            data = fetch_url(f"{RAW_BASE}/{rel}", attempts=2)
            if len(data) < MINIAPP_MIN_SIZE:
                raise InstallerError(f"файл замалий ({len(data)} байт)")
            _write_bytes_atomic(target, data)
            saved += 1
        except (InstallerError, OSError) as exc:
            warn(f"{rel}: {exc} - бот докачає цей файл сам.")
    return saved


# --- Запит Ngrok Authtoken --------------------------------------------------

def prompt_ngrok_authtoken() -> str:
    """Питає authtoken (можна пропустити Enter). Ніколи не показує його назад."""
    say("    Authtoken: dashboard.ngrok.com -> Your Authtoken.")
    say("    Потрібен для постійної HTTPS-адреси Mini App.")
    while True:
        value = ask("    Ngrok Authtoken (Enter - пропустити): ")
        if not value:
            return ""
        if NGROK_TOKEN_RE.match(value):
            return value
        warn("authtoken виглядає некоректно (очікуються латинські літери, "
             "цифри, '_' або '-'). Спробуй ще раз або натисни Enter.")


# --- Перевірка Mini App -----------------------------------------------------

def check_miniapp_health(timeout: int = 45) -> bool:
    """Чекає на /api/health локального сервера Mini App. True - відповів."""
    url = f"http://127.0.0.1:{MINIAPP_PORT}/api/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", MINIAPP_PORT), timeout=2):
                pass
        except OSError:
            time.sleep(2)
            continue
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if getattr(response, "status", 200) == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(2)
    return False


# --- Запуск бота ------------------------------------------------------------

def start_in_background(hidden_vbs: Path) -> bool:
    """Піднімає прихований супервізор одразу, не чекаючи наступного входу."""
    try:
        subprocess.Popen(["wscript.exe", str(hidden_vbs)],
                         creationflags=_creation_flags(), close_fds=True)
    except OSError as exc:
        fail(f"не вдалося запустити {hidden_vbs.name}: {exc}")
        return False
    return True


def print_banner() -> None:
    say("=" * 62)
    say(f"  {APP_NAME} - інсталятор для Windows (бот + Mini App)")
    say("=" * 62)
    say("  Повторний запуск безпечний: налаштування не дублюються.")


# --- Головний сценарій ------------------------------------------------------

def main() -> int:
    _setup_console()
    print_banner()

    if os.name != "nt":
        fail("інсталятор розрахований на Windows.")
        return 1

    work_dir = bot_dir()
    startup = startup_dir()
    if work_dir is None:
        fail("не знайдено %LOCALAPPDATA% - запусти від імені свого користувача.")
        pause()
        return 1
    if startup is None:
        warn("не знайдено папку «Автозавантаження»: автозапуск буде лише через "
             "планувальник завдань.")

    problems: List[str] = []

    step("1/8 Робоча папка")
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        fail(f"не вдалося створити {work_dir}: {exc}")
        pause()
        return 1
    ok(str(work_dir))

    step("2/8 Python")
    resolved = resolve_python()
    if resolved is None:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ не знайдено.")
        say("    Встанови з https://www.python.org/downloads (галочка "
            "«Add python.exe to PATH»)")
        say("    або виконай: winget install Python.Python.3.12")
        pause()
        return 1
    python_exe, python_ver = resolved
    ok(f"Python {python_ver}: {python_exe}")

    step("3/8 Ngrok Authtoken")
    authtoken = prompt_ngrok_authtoken()
    if authtoken:
        ok("authtoken отримано (у файли інсталятора не пишеться)")
    else:
        warn("пропущено: без нього ngrok не підніме тунель для Mini App.")

    step("4/8 Файли бота")
    try:
        size = download_bot_script(work_dir / "ControlPC.py")
    except InstallerError as exc:
        fail(f"не вдалося завантажити ControlPC.py: {exc}")
        say("    Перевір інтернет або проксі і запусти інсталятор ще раз.")
        pause()
        return 1
    ok(f"ControlPC.py ({size // 1024} КБ)")
    saved = download_miniapp_files(work_dir)
    if saved:
        ok(f"файли Mini App: {saved}/{len(MINIAPP_FILES)}")
    else:
        problems.append("файли Mini App не завантажено (бот докачає сам)")

    step("5/8 Токен Telegram-бота")
    has_token = ensure_bot_token(work_dir)
    if not has_token:
        problems.append("немає токена бота: автозапуск не створено")

    step("6/8 Бібліотеки Python")
    missing = find_missing_modules(python_exe)
    if missing == []:
        ok("усі бібліотеки вже встановлені")
    else:
        if missing:
            say(f"    не вистачає: {', '.join(missing)}")
        if install_packages(python_exe):
            still = find_missing_modules(python_exe)
            if still:
                fail(f"після pip install не імпортуються: {', '.join(still)}")
                problems.append("частина бібліотек не встановилася - частина "
                                "функцій бота не працюватиме")
            else:
                ok("бібліотеки встановлено")
        else:
            problems.append("pip не встановив бібліотеки - бот не запуститься")

    step("7/8 ngrok і Mini App")
    ngrok_exe = find_ngrok()
    if ngrok_exe:
        ok(f"ngrok: {ngrok_exe}")
    else:
        warn("ngrok.exe не знайдено: Mini App працюватиме лише локально.")
        say("    Встанови: winget install Ngrok.Ngrok (або https://ngrok.com/download)")
        problems.append("ngrok не встановлено: немає HTTPS-тунелю для Mini App")
    if authtoken and ngrok_exe:
        if register_ngrok_token(ngrok_exe, authtoken):
            ok("authtoken збережено в конфізі ngrok")
        else:
            problems.append("authtoken ngrok не збережено")
    elif authtoken:
        warn("authtoken не записано: спочатку встанови ngrok, потім повтори запуск.")
    if write_miniapp_config(work_dir / "miniapp_config.json"):
        ok(f"miniapp_config.json: https://{NGROK_DOMAIN}, порт {MINIAPP_PORT}")
    else:
        problems.append("miniapp_config.json не записано")

    step("8/8 Автозапуск")
    hidden_vbs = write_hidden_launcher(work_dir, python_exe, ngrok_exe)
    if hidden_vbs is None:
        problems.append("start_hidden.vbs не створено - фоновий запуск недоступний")
    else:
        ok("start_hidden.vbs: прихований запуск ngrok + цикл оновлення бота")

    if hidden_vbs is not None and has_token:
        for name, command in find_conflicting_tasks(hidden_vbs):
            warn(f"сторонній автозапуск: {name} -> {command}")
            if ask_yes_no(f"Видалити завдання {name}?", default=False):
                if remove_task(name):
                    ok(f"завдання {name} видалено")
                else:
                    warn(f"{name} не видалено (потрібні права адміністратора)")
        if startup is not None:
            launcher = write_startup_launcher(startup, hidden_vbs)
            if launcher is not None:
                ok(f"Автозавантаження: {launcher}")
            else:
                problems.append("не вдалося додати запуск в Автозавантаження")
        if ensure_scheduled_task(hidden_vbs):
            ok(f"завдання планувальника: {TASK_NAME}")
        else:
            warn("залишиться автозапуск через папку «Автозавантаження».")

    say("")
    say("-" * 62)
    if problems:
        warn("Завершено із зауваженнями:")
        for item in problems:
            say(f"      - {item}")
    else:
        ok("Усе налаштовано.")

    if hidden_vbs is not None and has_token:
        if ask_yes_no("Запустити бота зараз у фоні?", default=True):
            if start_in_background(hidden_vbs):
                say("    бот стартує (ControlPC.py спить 15 с після запуску)...")
                health = check_miniapp_health()
                if health:
                    ok(f"Mini App відповідає на http://127.0.0.1:{MINIAPP_PORT}")
                else:
                    warn("Mini App поки не відповів: дивись "
                         f"{work_dir / 'bot_errors.txt'}")
    say("")
    say(f"  Лог бота:  {work_dir / 'bot_errors.txt'}")
    say(f"  Токен:     {work_dir / 'token.txt'}")
    say(f"  Конфіг:    {work_dir / 'miniapp_config.json'}")
    say("=" * 62)
    pause()
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("")
        say("Скасовано користувачем.")
        sys.exit(130)
    except Exception:
        say("")
        fail("Непередбачена помилка інсталятора:")
        say(traceback.format_exc())
        pause()
        sys.exit(1)
