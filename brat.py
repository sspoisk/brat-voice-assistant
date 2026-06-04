import speech_recognition as sr
import pyttsx3
import subprocess
import threading
import time
import datetime
import re
import os
import queue
import glob
import json
import random
import urllib.parse
from pathlib import Path
from fuzzywuzzy import fuzz, process

# ============================================
# ГОЛОСОВОЙ ДВИЖОК
# ============================================
engine = pyttsx3.init()
engine.setProperty('rate', 180)
engine.setProperty('volume', 1.0)
voices = engine.getProperty('voices')
for voice in voices:
    if 'russian' in voice.name.lower() or 'microsoft irina' in voice.name.lower():
        engine.setProperty('voice', voice.id)
        break

speech_queue = queue.Queue()

def speak_worker():
    while True:
        text = speech_queue.get()
        if text is None:
            break
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print(f"Ошибка озвучки: {e}")

worker_thread = threading.Thread(target=speak_worker, daemon=True)
worker_thread.start()

def speak(text):
    print(f"Брат: {text}")
    speech_queue.put(text)

# ============================================
# НАСТРОЙКИ (сохраняются в settings.json)
# ============================================
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "wake_words": ["брат"],
    "user_name": "Слава",
    "speech_rate": 180,
    "speech_volume": 1.0,
    "custom_aliases": {},
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for key, val in DEFAULT_SETTINGS.items():
                if key not in data:
                    data[key] = val
            return data
        except Exception as e:
            print(f"Ошибка загрузки настроек: {e}")
            save_settings(DEFAULT_SETTINGS)
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        print("Настройки сохранены.")
    except Exception as e:
        print(f"Ошибка сохранения настроек: {e}")

def _aliases_menu(settings):
    while True:
        print("\n" + "-"*50)
        print(" МОИ АЛИАСЫ КОМАНД")
        print(" (своё слово -> что запустить)")
        print("-"*50)
        if settings["custom_aliases"]:
            for i, (alias, target) in enumerate(settings["custom_aliases"].items(), 1):
                print(f" {i}. '{alias}' -> '{target}'")
        else:
            print(" Пусто. Добавь свои.")
        print("-"*50)
        print(" A. Добавить алиас")
        print(" D. Удалить алиас")
        print(" 0. Назад")
        print("-"*50)
        choice = input("Выбери: ").strip().lower()
        if choice == "a":
            print("\nПример: скажешь 'ворк' — откроется 'notepad'")
            alias = input("Что говорить (слово/фраза): ").strip().lower()
            target = input("Что запустить (имя exe или URL): ").strip()
            if alias and target:
                settings["custom_aliases"][alias] = target
                save_settings(settings)
                print(f"Добавлено: '{alias}' -> '{target}'")
            else:
                print("Пустой ввод.")
        elif choice == "d":
            if not settings["custom_aliases"]:
                print("Нечего удалять.")
                continue
            alias = input("Введи слово которое хочешь удалить: ").strip().lower()
            if alias in settings["custom_aliases"]:
                del settings["custom_aliases"][alias]
                save_settings(settings)
                print(f"Удалено: '{alias}'")
            else:
                print(f"'{alias}' не найден.")
        elif choice == "0":
            break

def settings_menu(settings):
    while True:
        print("\n" + "="*50)
        print(" НАСТРОЙКИ ПОМОЩНИКА")
        print("="*50)
        wake = ", ".join(settings["wake_words"])
        print(f" 1. Слова активации : {wake}")
        print(f" 2. Имя пользователя : {settings['user_name']}")
        print(f" 3. Скорость речи : {settings['speech_rate']} (100-300)")
        print(f" 4. Громкость : {settings['speech_volume']} (0.0-1.0)")
        print(f" 5. Мои алиасы команд : {len(settings['custom_aliases'])} шт.")
        print(f" 6. Сбросить настройки")
        print(f" 0. Выйти из настроек")
        print("="*50)
        choice = input("Выбери пункт: ").strip()
        if choice == "1":
            print(f"\nТекущие слова активации: {', '.join(settings['wake_words'])}")
            print("Введи новые слова через запятую (например: брат,эй,слушай)")
            raw = input(">>> ").strip().lower()
            if raw:
                words = [w.strip() for w in raw.split(",") if w.strip()]
                if words:
                    settings["wake_words"] = words
                    save_settings(settings)
                    print(f"Слова активации: {', '.join(words)}")
                else:
                    print("Пустой ввод, не изменено.")
            else:
                print("Не изменено.")
        elif choice == "2":
            print(f"\nТекущее имя: {settings['user_name']}")
            name = input("Введи новое имя: ").strip()
            if name:
                settings["user_name"] = name
                save_settings(settings)
                print(f"Имя изменено на: {name}")
            else:
                print("Не изменено.")
        elif choice == "3":
            print(f"\nТекущая скорость: {settings['speech_rate']}")
            val = input("Введи скорость (100-300): ").strip()
            try:
                rate = int(val)
                if 100 <= rate <= 300:
                    settings["speech_rate"] = rate
                    engine.setProperty('rate', rate)
                    save_settings(settings)
                    print(f"Скорость: {rate}")
                else:
                    print("Число должно быть от 100 до 300.")
            except ValueError:
                print("Введи число.")
        elif choice == "4":
            print(f"\nТекущая громкость: {settings['speech_volume']}")
            val = input("Введи громкость (0.0 - 1.0): ").strip()
            try:
                vol = float(val)
                if 0.0 <= vol <= 1.0:
                    settings["speech_volume"] = vol
                    engine.setProperty('volume', vol)
                    save_settings(settings)
                    print(f"Громкость: {vol}")
                else:
                    print("Число должно быть от 0.0 до 1.0.")
            except ValueError:
                print("Введи число.")
        elif choice == "5":
            _aliases_menu(settings)
        elif choice == "6":
            confirm = input("Сбросить ВСЕ настройки? (да/нет): ").strip().lower()
            if confirm == "да":
                settings.update(DEFAULT_SETTINGS.copy())
                save_settings(settings)
                engine.setProperty('rate', settings["speech_rate"])
                engine.setProperty('volume', settings["speech_volume"])
                print("Настройки сброшены.")
            else:
                print("Отмена.")
        elif choice == "0":
            print("Выходим из настроек.")
            break
        else:
            print("Неверный пункт.")
    return settings

# ============================================
# СКАНЕР ПРИЛОЖЕНИЙ
# ============================================
APPS_CACHE_FILE = "apps_cache.json"

def scan_installed_apps():
    print("Сканирую приложения на компе...")
    apps = {}
    scan_dirs = [
        r"C:\Program Files",
        r"C:\Program Files (x86)",
        os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
        os.path.expandvars(r"%LOCALAPPDATA%\Programs"),
    ]
    skip_words = ["uninstall", "setup", "install", "update", "helper", "crash", "report", "uninst", "repair", "configure"]
    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir):
            continue
        for pattern in ["**/*.exe", "**/*.lnk"]:
            try:
                for filepath in glob.glob(os.path.join(scan_dir, pattern), recursive=True):
                    name = Path(filepath).stem.lower()
                    if any(w in name for w in skip_words):
                        continue
                    apps[name] = filepath
            except PermissionError:
                continue
    try:
        with open(APPS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(apps, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Не смог сохранить кэш: {e}")
    print(f"Найдено приложений: {len(apps)}")
    return apps

def load_apps_cache():
    if os.path.exists(APPS_CACHE_FILE):
        try:
            with open(APPS_CACHE_FILE, "r", encoding="utf-8") as f:
                apps = json.load(f)
            print(f"Загружен кэш: {len(apps)} приложений")
            return apps
        except:
            pass
    return scan_installed_apps()

# ============================================
# БРАУЗЕРЫ
# ============================================
KNOWN_BROWSERS = {
    "хром": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "фаерфокс": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
    ],
    "опера": [
        r"C:\Program Files\Opera\opera.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera\opera.exe"),
    ],
    "яндекс браузер": [
        os.path.expandvars(r"%LOCALAPPDATA%\Yandex\YandexBrowser\Application\browser.exe"),
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "brave": [
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
    ],
}

BROWSER_ALIASES = {
    "гугл": "хром",
    "google": "хром",
    "chrome": "хром",
    "mozilla": "фаерфокс",
    "firefox": "фаерфокс",
    "яндекс": "яндекс браузер",
    "yandex": "яндекс браузер",
}

def get_installed_browsers():
    installed = {}
    for name, paths in KNOWN_BROWSERS.items():
        for path in paths:
            if os.path.exists(path):
                installed[name] = path
                break
    return installed

# ============================================
# СЛОВАРИ КОМАНД
# ============================================
app_aliases = {
    "браузер": "__browser__",
    "интернет": "__browser__",
    "телеграм": "telegram",
    "телега": "telegram",
    "дискорд": "discord",
    "вк": "vk",
    "вконтакте": "vk",
    "ютуб": "https://youtube.com",
    "спотифай": "spotify",
    "музыка": "spotify",
    "влц": "vlc",
    "видео": "vlc",
    "блокнот": "notepad",
    "заметки": "notepad",
    "калькулятор": "calc",
    "проводник": "explorer",
    "папки": "explorer",
    "мой компьютер": "explorer",
    "терминал": "cmd",
    "командная строка": "cmd",
    "пауэршел": "powershell",
    "ворд": "winword",
    "эксель": "excel",
    "повер поинт": "powerpnt",
    "стим": "steam",
    "настройки": "ms-settings:",
    "блокировка": "lock",
    "скриншот": "screenshot",
    "выключение": "shutdown /s /t 60",
    "отмена выключения": "shutdown /a",
    "перезагрузка": "shutdown /r /t 10",
}

trigger_words = [
    "открой",
    "запусти",
    "включи",
    "покажи",
    "найди",
    "зайди в",
    "иди в",
    "открыть",
    "запустить",
    "включить"
]

# ============================================
# ОТВЕТЧИК НА ПРОСТЫЕ ФРАЗЫ
# ============================================
chat_responses = {
    "привет": ["Привет, {name}! Чем помочь?", "Здарова, {name}! Что надо?"],
    "здарова": ["Здарова, {name}!", "О, {name}! Чем помочь?"],
    "дарова": ["Дарова, {name}! Слушаю.", "Привет, {name}! Что надо?"],
    "как дела": ["Нормально, {name}. Работаю, жду команд.", "Всё чётко, {name}. У тебя как?"],
    "как ты": ["Работаю в штатном режиме, {name}.", "Всё нормально, жду твоих команд."],
    "ты живой": ["Живой, {name}. Слушаю тебя.", "Да, здесь. Говори."],
    "что умеешь": ["Открываю приложения, браузеры, ставлю таймеры и будильники. Говори и я сделаю, {name}."],
    "что можешь": ["Запускаю программы, открываю сайты, слежу за временем. Всё для тебя, {name}."],
    "что ты умеешь": ["Открываю приложения, ставлю таймеры и будильники. Говори, {name}."],
    "помощь": ["Скажи: открой телеграм, или: таймер на 5 минут, или: будильник на 7 утра. Всё просто, {name}."],
    "который час": "__time__",
    "сколько времени": "__time__",
    "какое время": "__time__",
    "какой день": "__date__",
    "какая дата": "__date__",
    "какой сегодня день": "__date__",
    "спасибо": ["Всегда пожалуйста, {name}.", "Не за что, {name}.", "Обращайся, {name}."],
    "благодарю": ["Всегда рад помочь, {name}.", "Не за что, {name}."],
    "пока": ["Пока, {name}! До следующего раза.", "Давай, {name}. Буду здесь."],
    "до свидания": ["До свидания, {name}!", "Пока, {name}!"],
    "ты кто": ["Твой голосовой помощник, {name}. Без имени пока, но работаю.", "Помощник на твоём компе, {name}."],
    "как тебя зовут": ["Имени нет, {name}. Зови просто Брат.", "Я Брат. Твой помощник, {name}."],
    "ты умный": ["Стараюсь, {name}.", "Ну, для своих задач — да, {name}."],
    "ты лучший": ["Спасибо, {name}! Стараюсь.", "Работаю на тебя, {name}."],
    "скучно": ["Дай команду, {name}. Займёмся делом.", "Открой ютуб тогда, {name}."],
    "окей": ["Слушаю, {name}.", "Говори, {name}."],
    "ладно": ["Окей, {name}.", "Хорошо, {name}."],
}

def get_chat_response(text, user_name="Слава"):
    text_lower = text.lower().strip()
    for wake in ["брат", "эй", "слушай"]:
        text_lower = text_lower.replace(wake, "").strip()
    # Точное совпадение
    if text_lower in chat_responses:
        response = chat_responses[text_lower]
        if response == "__time__":
            now = datetime.datetime.now()
            return f"Сейчас {now.strftime('%H:%M')}, {user_name}."
        if response == "__date__":
            now = datetime.datetime.now()
            days = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
            months = ["января","февраля","марта","апреля","мая","июня", "июля","августа","сентября","октября","ноября","декабря"]
            return f"Сегодня {days[now.weekday()]}, {now.day} {months[now.month-1]}, {user_name}."
        return random.choice(response).format(name=user_name)
    # Нечёткий поиск
    if chat_responses:
        best_key, score = process.extractOne(text_lower, chat_responses.keys(), scorer=fuzz.token_sort_ratio)
        if score > 85:
            response = chat_responses[best_key]
            if response == "__time__":
                now = datetime.datetime.now()
                return f"Сейчас {now.strftime('%H:%M')}, {user_name}."
            if response == "__date__":
                now = datetime.datetime.now()
                days = ["понедельник","вторник","среда","четверг","пятница","суббота","воскресенье"]
                months = ["января","февраля","марта","апреля","мая","июня", "июля","августа","сентября","октября","ноября","декабря"]
                return f"Сегодня {days[now.weekday()]}, {now.day} {months[now.month-1]}, {user_name}."
            return random.choice(response).format(name=user_name)
    return None

# ============================================
# ТАЙМЕРЫ И БУДИЛЬНИКИ
# ============================================
active_timers = []

def beep_sound():
    try:
        import winsound
        winsound.Beep(1000, 300)
    except:
        print('\a')

def set_timer(duration_seconds, label="Таймер"):
    def timer_thread():
        speak(f"Запустил {label}")
        time.sleep(duration_seconds)
        speak(f"Брат! {label} сработал! Время вышло!")
        for _ in range(5):
            beep_sound()
            time.sleep(0.5)
    thread = threading.Thread(target=timer_thread, daemon=True)
    thread.start()
    active_timers.append(thread)

def set_alarm(hour, minute, label="Будильник"):
    def alarm_thread():
        now = datetime.datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        diff = (target - now).total_seconds()
        speak(f"Будильник поставлен на {target.strftime('%H:%M')}")
        time.sleep(diff)
        speak(f"Подъём! {label} сработал!")
        for _ in range(10):
            beep_sound()
            time.sleep(0.3)
    thread = threading.Thread(target=alarm_thread, daemon=True)
    thread.start()
    active_timers.append(thread)

def parse_time_command(text):
    text_lower = text.lower()
    if any(w in text_lower for w in ["таймер", "засеки", "отсчёт"]):
        match = re.search(r'(\d+)\s*(секунд|минут|час|часов|мин|сек)', text_lower)
        if match:
            value = int(match.group(1))
            unit = match.group(2)
            if "час" in unit:
                seconds = value * 3600
            elif "минут" in unit or "мин" in unit:
                seconds = value * 60
            else:
                seconds = value
            set_timer(seconds, f"Таймер на {value} {unit}")
            return True
    if any(w in text_lower for w in ["будильник", "разбуди", "подъём"]):
        hour = None
        minute = 0
        time_match = re.search(r'(\d{1,2})[.:\s](\d{2})', text_lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
        else:
            hour_match = re.search(r'(\d{1,2})\s*(утра|вечера|часов|час|часа|ночи|дня)', text_lower)
            if hour_match:
                hour = int(hour_match.group(1))
                period = hour_match.group(2)
                if period in ["вечера", "дня"] and hour != 12:
                    hour += 12
                elif period in ["ночи"] and hour == 12:
                    hour = 0
                minute = 0
        if hour is not None:
            set_alarm(hour % 24, minute)
            return True
        else:
            speak("Не понял время. Скажи например: будильник на 7 утра")
            return True
    return False

# ============================================
# ПОИСК ПРИЛОЖЕНИЯ
# ============================================
def find_app(query, installed_apps, custom_aliases=None):
    query = query.lower().strip()
    if custom_aliases is None:
        custom_aliases = {}
    # 0. Пользовательские алиасы (высший приоритет)
    if query in custom_aliases:
        return custom_aliases[query]
    if custom_aliases:
        best_key, score = process.extractOne(query, custom_aliases.keys(), scorer=fuzz.token_sort_ratio)
        if score > 85:
            return custom_aliases[best_key]
    # 1. Точное совпадение в словаре
    if query in app_aliases:
        return app_aliases[query]
    # 2. Нечёткий поиск по словарю
    if app_aliases:
        best_key, score = process.extractOne(query, app_aliases.keys(), scorer=fuzz.token_sort_ratio)
        if score > 80:
            return app_aliases[best_key]
    # 3. Поиск в кэше системы
    if installed_apps:
        best_app, score = process.extractOne(query, installed_apps.keys(), scorer=fuzz.token_sort_ratio)
        if score > 75:
            return installed_apps[best_app]
    # 4. Фолбэк — Win поиск
    return f"__winsearch__{query}"

# ============================================
# ОТКРЫТИЕ ПРИЛОЖЕНИЯ
# ============================================
def open_app(command):
    try:
        cmd = command.lower().strip()
        if cmd.startswith("http"):
            os.startfile(command)
            return
        if cmd.startswith("shutdown") or cmd.startswith("ms-settings"):
            os.system(command)
            return
        if cmd == "lock":
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation")
            return
        if cmd == "screenshot":
            subprocess.Popen("snippingtool.exe")
            return
        system_apps = {
            "calc": "calc.exe",
            "calculator": "calc.exe",
            "notepad": "notepad.exe",
            "explorer": "explorer.exe",
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "mspaint": "mspaint.exe",
        }
        if cmd in system_apps:
            subprocess.Popen(system_apps[cmd])
            return
        # Полный путь из кэша
        if os.path.exists(command):
            os.startfile(command)
            return
        # Попытка запустить напрямую
        try:
            subprocess.Popen(f"{command}.exe")
            return
        except FileNotFoundError:
            pass
        # Win поиск
        _win_search(command)
    except Exception as e:
        speak(f"Ошибка открытия: {e}")

def _win_search(query):
    try:
        import pyautogui
        pyautogui.hotkey('win')
        time.sleep(0.3)
        pyautogui.write(query, interval=0.05)
        time.sleep(0.4)
        pyautogui.press('enter')
    except Exception as e:
        speak(f"Не смог открыть через поиск: {e}")

# ============================================
# ЛОГИКА БРАУЗЕРОВ
# ============================================
def handle_browser_command(installed_browsers, recognizer):
    if not installed_browsers:
        speak("Не нашёл ни одного браузера на компе")
        return
    if len(installed_browsers) == 1:
        name = list(installed_browsers.keys())[0]
        path = list(installed_browsers.values())[0]
        speak(f"Открываю {name}")
        os.startfile(path)
        return
    names = list(installed_browsers.keys())
    names_str = ", ".join(names)
    speak(f"У тебя {len(names)} браузера: {names_str}. Какой открыть?")
    answer = _listen_once(recognizer, timeout=6)
    if not answer:
        speak("Не расслышал. Открываю первый.")
        os.startfile(list(installed_browsers.values())[0])
        return
    answer_lower = answer.lower()
    for alias, canonical in BROWSER_ALIASES.items():
        if alias in answer_lower:
            answer_lower = answer_lower.replace(alias, canonical)
    for name in names:
        if name in answer_lower or fuzz.partial_ratio(answer_lower, name) > 80:
            speak(f"Открываю {name}")
            os.startfile(installed_browsers[name])
            return
    speak("Не понял какой. Открываю первый.")
    os.startfile(list(installed_browsers.values())[0])

# ============================================
# РАСПОЗНАВАНИЕ РЕЧИ
# ============================================
def _listen_once(recognizer, timeout=5):
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=5)
            text = recognizer.recognize_google(audio, language="ru-RU")
            print(f"Услышал: {text}")
            return text.lower()
    except sr.WaitTimeoutError:
        return None
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        speak("Нет интернета для распознавания")
        return None
    except Exception as e:
        print(f"Ошибка микрофона: {e}")
        return None

# ============================================
# РАБОТА С ФАЙЛАМИ
# Команды:
#   "перемести файл X в папку Y"
#   "переименуй файл X в Y"
#   "замени текст в файле X" -> вводишь новый текст голосом или файлом
# ============================================
import shutil

# Папки-алиасы чтобы говорить "рабочий стол" вместо полного пути
FOLDER_ALIASES = {
    "рабочий стол": os.path.expandvars(r"%USERPROFILE%\Desktop"),
    "десктоп": os.path.expandvars(r"%USERPROFILE%\Desktop"),
    "загрузки": os.path.expandvars(r"%USERPROFILE%\Downloads"),
    "документы": os.path.expandvars(r"%USERPROFILE%\Documents"),
    "музыка": os.path.expandvars(r"%USERPROFILE%\Music"),
    "видео": os.path.expandvars(r"%USERPROFILE%\Videos"),
    "картинки": os.path.expandvars(r"%USERPROFILE%\Pictures"),
    "фото": os.path.expandvars(r"%USERPROFILE%\Pictures"),
    "temp": os.path.expandvars(r"%TEMP%"),
    "временные": os.path.expandvars(r"%TEMP%"),
}

def resolve_folder(name):
    """Переводит алиас папки в полный путь. Если уже путь — возвращает как есть."""
    name = name.strip().lower()
    if name in FOLDER_ALIASES:
        return FOLDER_ALIASES[name]
    # Может уже полный путь
    if os.path.isdir(name):
        return name
    return None

def find_file_on_desktop_and_downloads(filename):
    """Ищет файл на рабочем столе и в загрузках — самые частые места."""
    search_dirs = [
        os.path.expandvars(r"%USERPROFILE%\Desktop"),
        os.path.expandvars(r"%USERPROFILE%\Downloads"),
        os.path.expandvars(r"%USERPROFILE%\Documents"),
    ]
    filename_lower = filename.lower()
    for folder in search_dirs:
        if not os.path.exists(folder):
            continue
        for f in os.listdir(folder):
            if filename_lower in f.lower():
                return os.path.join(folder, f)
    return None

def move_file_command(text, recognizer):
    """ Обрабатывает: "перемести файл X в папку Y"
    Если X или Y не понял — уточняет голосом. """
    text = text.lower()
    # Пробуем вытащить имя файла и папку назначения из фразы
    # Шаблон: "перемести [файл] X в [папку] Y"
    match = re.search(
        r'(?:файл\s+)?(.+?)\s+(?:в|в папку|в папке)\s+(.+)',
        text.replace("перемести", "").replace("переместить", "").strip()
    )
    if match:
        file_part = match.group(1).strip()
        folder_part = match.group(2).strip()
    else:
        # Не смогли распарсить — спрашиваем по очереди
        speak("Какой файл переместить? Назови имя.")
        file_part = _listen_once(recognizer, timeout=7)
        if not file_part:
            speak("Не услышал имя файла.")
            return
        speak("Куда переместить? Назови папку.")
        folder_part = _listen_once(recognizer, timeout=7)
        if not folder_part:
            speak("Не услышал папку назначения.")
            return
    # Ищем файл
    src = find_file_on_desktop_and_downloads(file_part)
    if not src:
        speak(f"Не нашёл файл '{file_part}' на рабочем столе, в загрузках и документах.")
        return
    # Резолвим папку
    dst_folder = resolve_folder(folder_part)
    if not dst_folder:
        speak(f"Не знаю папку '{folder_part}'. Скажи например: рабочий стол, загрузки, документы.")
        return
    try:
        dst = os.path.join(dst_folder, os.path.basename(src))
        shutil.move(src, dst)
        speak(f"Переместил '{os.path.basename(src)}' в {folder_part}.")
    except Exception as e:
        speak(f"Ошибка при перемещении: {e}")

def edit_file_command(text, recognizer):
    """ Обрабатывает: "замени текст в файле X"
    Потом спрашивает: 1. Что заменить (голосом или файлом) 2. На что заменить (голосом или файлом) """
    text_lower = text.lower()
    # Вытаскиваем имя файла
    match = re.search(r'(?:в файле|файл|файле)\s+(.+)', text_lower)
    if match:
        file_part = match.group(1).strip()
    else:
        speak("В каком файле заменить текст? Назови имя.")
        file_part = _listen_once(recognizer, timeout=7)
        if not file_part:
            speak("Не услышал.")
            return
    # Ищем файл
    src = find_file_on_desktop_and_downloads(file_part)
    if not src:
        speak(f"Не нашёл файл '{file_part}'.")
        return
    # Читаем файл
    try:
        with open(src, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        speak(f"Не могу прочитать файл: {e}")
        return
    speak(f"Нашёл файл. Что заменить? Скажи текст или назови файл с текстом.")
    old_text = _ask_text_or_file(recognizer)
    if old_text is None:
        speak("Не получил текст для замены.")
        return
    speak("На что заменить? Скажи новый текст или назови файл с новым текстом.")
    new_text = _ask_text_or_file(recognizer)
    if new_text is None:
        speak("Не получил новый текст.")
        return
    if old_text not in content:
        speak(f"Текст '{old_text}' не найден в файле.")
        return
    count = content.count(old_text)
    new_content = content.replace(old_text, new_text)
    try:
        # Делаем бэкап
        backup = src + ".bak"
        shutil.copy2(src, backup)
        with open(src, "w", encoding="utf-8") as f:
            f.write(new_content)
        speak(f"Заменил {count} вхождений. Бэкап сохранён рядом.")
    except Exception as e:
        speak(f"Ошибка при записи файла: {e}")

def _ask_text_or_file(recognizer):
    """ Спрашивает текст голосом ИЛИ предлагает указать файл с текстом.
    Возвращает строку или None. """
    speak("Говори текст голосом — или скажи 'файл' чтобы указать файл с текстом.")
    answer = _listen_once(recognizer, timeout=8)
    if not answer:
        return None
    if "файл" in answer.lower():
        # Пользователь хочет указать файл
        speak("Назови имя файла с текстом.")
        file_name = _listen_once(recognizer, timeout=7)
        if not file_name:
            return None
        path = find_file_on_desktop_and_downloads(file_name)
        if not path:
            speak(f"Файл '{file_name}' не найден.")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            speak(f"Не могу прочитать: {e}")
            return None
    else:
        # Голосовой текст
        return answer

def parse_file_command(text, recognizer):
    """ Определяет тип файловой команды и вызывает нужную функцию.
    Возвращает True если команда была файловой. """
    text_lower = text.lower()
    move_triggers = ["перемести", "переместить", "перенеси", "перенести", "перетащи"]
    edit_triggers = ["замени текст", "заменить текст", "отредактируй", "редактировать", "измени файл"]
    if any(w in text_lower for w in move_triggers):
        move_file_command(text_lower, recognizer)
        return True
    if any(w in text_lower for w in edit_triggers):
        edit_file_command(text_lower, recognizer)
        return True
    return False

# ============================================
# YOUTUBE
# Команды:
#   "открой ютуб"            -> главная страница
#   "найди на ютубе котики"  -> поиск по запросу
#   "включи на ютубе джаз"   -> поиск по запросу
# ============================================
YOUTUBE_WORDS = ["ютубе", "ютуб", "ютьюб", "ютюб", "youtube", "ютьюбе"]

def parse_youtube_command(text):
    """ Если в команде есть 'ютуб' — открывает YouTube.
    С хвостом после слова 'ютуб' — открывает поиск по этому запросу.
    Возвращает True если команда была про YouTube. """
    text_lower = text.lower()
    if not any(w in text_lower for w in YOUTUBE_WORDS):
        return False

    # Чистим триггеры, предлоги и само слово 'ютуб' — остаётся поисковый запрос
    junk = ["открой", "открыть", "запусти", "запустить", "включи", "включить",
            "найди", "поищи", "покажи", "на", "в", "мне"] + YOUTUBE_WORDS
    query = text_lower
    for w in junk:
        query = re.sub(r'\b' + re.escape(w) + r'\b', ' ', query)
    query = re.sub(r'\s+', ' ', query).strip()

    if query:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
        speak(f"Ищу на Ютубе: {query}")
    else:
        url = "https://youtube.com"
        speak("Открываю Ютуб")
    try:
        os.startfile(url)
    except Exception as e:
        speak(f"Не смог открыть Ютуб: {e}")
    return True

# ============================================
# ОБРАБОТЧИК КОМАНД
# ============================================
def process_command(text, installed_apps, installed_browsers, recognizer, settings):
    user_name = settings.get("user_name", "Слава")
    # 0. Пустая активация
    if text == "__wake_only__":
        speak(f"Слушаю тебя, {user_name}")
        command = _listen_once(recognizer, timeout=6)
        if command:
            process_command(command, installed_apps, installed_browsers, recognizer, settings)
        else:
            speak("Не услышал команду")
        return
    # 1. Голосовой вызов настроек
    if any(w in text for w in ["настройки", "параметры", "конфиг"]):
        speak("Открываю настройки в консоли")
        settings_menu(settings)
        return
    # 2. Простые фразы
    chat_reply = get_chat_response(text, user_name)
    if chat_reply:
        speak(chat_reply)
        return
    # 3. Файловые команды
    if parse_file_command(text, recognizer):
        return
    # 4. Таймеры и будильники
    if parse_time_command(text):
        return
    # 4.5 YouTube (открыть / поиск голосом)
    if parse_youtube_command(text):
        return
    # 5. Убираем триггерные слова
    clean_text = text
    for word in sorted(trigger_words, key=len, reverse=True):
        if clean_text.startswith(word):
            clean_text = clean_text[len(word):].strip()
            break
    for prep in ["в ", "на ", "мой ", "мою "]:
        if clean_text.startswith(prep):
            clean_text = clean_text[len(prep):].strip()
    if not clean_text:
        speak("Что именно открыть?")
        return
    # 6. Ищем и открываем приложение
    result = find_app(clean_text, installed_apps, settings.get("custom_aliases", {}))
    if result == "__browser__":
        handle_browser_command(installed_browsers, recognizer)
        return
    if result.startswith("__winsearch__"):
        query = result[len("__winsearch__"):]
        speak(f"Не нашёл '{clean_text}', ищу через Windows")
        _win_search(query)
        return
    speak(f"Открываю {clean_text}")
    open_app(result)

# ============================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================
def main():
    settings = load_settings()
    engine.setProperty('rate', settings["speech_rate"])
    engine.setProperty('volume', settings["speech_volume"])
    print("\n" + "="*50)
    print(" Нажми S + Enter чтобы зайти в настройки")
    print(" Нажми Enter чтобы запустить помощника")
    print("="*50)
    user_input = input(">>> ").strip().lower()
    if user_input == "s":
        settings = settings_menu(settings)
    speak("Запускаюсь, подожди немного")
    installed_apps = load_apps_cache()
    installed_browsers = get_installed_browsers()
    browser_names = list(installed_browsers.keys()) if installed_browsers else []
    speak(f"Готов. Нашёл {len(installed_apps)} приложений.")
    if browser_names:
        speak(f"Браузеры: {', '.join(browser_names)}")
    wake = settings["wake_words"][0]
    speak(f"Говори '{wake}' и команду. Например: {wake}, открой телеграм")
    recognizer = sr.Recognizer()
    while True:
        try:
            print(f"Жду: {', '.join(settings['wake_words'])}...")
            text = _listen_once(recognizer, timeout=10)
            if not text:
                continue
            triggered = False
            matched_wake = None
            for wake_word in settings["wake_words"]:
                if wake_word in text:
                    triggered = True
                    matched_wake = wake_word
                    break
            if not triggered:
                continue
            command = text.replace(matched_wake, "").strip()
            if not command:
                command = "__wake_only__"
            if any(w in command for w in ["пока", "выйди", "стоп", "выключись", "завершение"]):
                speak(f"До связи, {settings['user_name']}!")
                speech_queue.put(None)
                break
            process_command(command, installed_apps, installed_browsers, recognizer, settings)
        except KeyboardInterrupt:
            speak("Выключаюсь")
            speech_queue.put(None)
            break
        except Exception as e:
            print(f"Ошибка главного цикла: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
