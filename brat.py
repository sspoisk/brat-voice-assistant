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
import urllib.request
from pathlib import Path
from fuzzywuzzy import fuzz, process

# ============================================
# ГОЛОСОВОЙ ДВИЖОК
# ============================================
engine = pyttsx3.init()
engine.setProperty('rate', 195)   # чуть бодрее обычного — "жизнерадостный" темп
engine.setProperty('volume', 1.0)

def apply_voice(prefer="pavel"):
    """ Выбирает голос: сначала по подстроке prefer (напр. 'pavel'/'irina'),
    затем мужской русский (Pavel), затем любой русский, иначе системный.
    Pavel (мужской) живёт в OneCore; если его нет в SAPI5 — см. README
    (одна команда reg copy открывает его для pyttsx3). """
    prefer = (prefer or "").lower()
    voices = engine.getProperty('voices')
    chosen = None
    if prefer:
        chosen = next((v for v in voices if prefer in v.name.lower()), None)
    if not chosen:
        chosen = next((v for v in voices if 'pavel' in v.name.lower()), None)
    if not chosen:
        chosen = next((v for v in voices if 'russian' in v.name.lower()), None)
    if not chosen:
        return None

    # Надёжная установка напрямую через SAPI: pyttsx3 setProperty('voice')
    # не переключает голос, скопированный из OneCore (напр. Pavel) —
    # остаётся прежний. Поэтому ищем токен по описанию и ставим сами.
    set_ok = False
    try:
        tts = engine.proxy._driver._tts
        all_tokens = tts.GetVoices()
        for i in range(all_tokens.Count):
            tk = all_tokens.Item(i)
            if tk.GetDescription() == chosen.name:
                tts.Voice = tk
                set_ok = True
                break
    except Exception:
        set_ok = False
    if not set_ok:
        engine.setProperty('voice', chosen.id)
    return chosen

apply_voice("pavel")

# ----- Режим озвучки -----
# "offline" -> pyttsx3/Pavel (без интернета)
# "edge"    -> живой нейросетевой голос Edge-TTS (нужен интернет)
TTS_MODE = "offline"
EDGE_VOICE = "ru-RU-DmitryNeural"   # живой мужской русский голос (рус. текст)
EDGE_VOICE_EN = "en-US-GuyNeural"   # живой английский голос (англ. текст)
VOICE_PREF = "pavel"                 # офлайн-голос для рус. текста (для восстановления)

def _text_is_english(text):
    lat = sum(1 for c in text if 'a' <= c.lower() <= 'z')
    cyr = sum(1 for c in text.lower() if 'а' <= c <= 'я' or c == 'ё')
    return lat > cyr

def _offline_say(text):
    en = _text_is_english(text)
    if en:
        try:
            apply_voice("zira")          # английский голос для англ. текста
        except Exception:
            en = False
    try:
        engine.say(text)
        engine.runAndWait()
    finally:
        if en:
            try:
                apply_voice(VOICE_PREF)  # вернуть русский голос
            except Exception:
                pass

def _play_audio_file(path):
    """Проигрывает mp3 через системный MCI (winmm), без доп. зависимостей."""
    import ctypes
    alias = "brat_tts"
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'close {alias}', None, 0, None)
    err = mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    if err != 0:
        mci(f'open "{path}" alias {alias}', None, 0, None)
    mci(f'play {alias} wait', None, 0, None)
    mci(f'close {alias}', None, 0, None)

def _edge_say(text):
    """Синтез через Edge-TTS -> временный mp3 -> проигрывание."""
    import asyncio, sys, tempfile, os as _os, edge_tts
    if sys.platform.startswith("win"):
        # aiohttp/aiodns на Windows требует SelectorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    fd, path = tempfile.mkstemp(suffix=".mp3")
    _os.close(fd)

    voice = EDGE_VOICE_EN if _text_is_english(text) else EDGE_VOICE
    async def _gen():
        await edge_tts.Communicate(text, voice).save(path)

    asyncio.run(_gen())
    try:
        _play_audio_file(path)
    finally:
        try:
            _os.remove(path)
        except Exception:
            pass

speech_queue = queue.Queue()
# Счётчик незавершённой озвучки. Растёт в speak() СРАЗУ (до возврата из команды),
# падает в воркере после реального проигрывания. Гейт против самопрослушивания.
_speech_pending = 0
_speech_lock = threading.Lock()

def speak_worker():
    global _speech_pending
    while True:
        text = speech_queue.get()
        if text is None:
            break
        try:
            if TTS_MODE == "edge":
                try:
                    _edge_say(text)
                except Exception as e:
                    print(f"Edge-TTS недоступен ({e}), включаю офлайн-голос")
                    _offline_say(text)
            else:
                _offline_say(text)
        except Exception as e:
            print(f"Ошибка озвучки: {e}")
        finally:
            with _speech_lock:
                _speech_pending -= 1

def wait_until_quiet(timeout=25):
    """Блокируется, пока ассистент не договорит всю очередь озвучки."""
    start = time.time()
    while _speech_pending > 0 and (time.time() - start) < timeout:
        time.sleep(0.08)
    time.sleep(0.3)   # дать звуку в колонках затихнуть перед записью

worker_thread = threading.Thread(target=speak_worker, daemon=True)
worker_thread.start()

# GUI (dark_gui.py) может подставить колбэк, чтобы озвучка попадала в лог окна
on_speak = None

def speak(text):
    global _speech_pending
    print(f"Брат: {text}")
    if on_speak:
        try:
            on_speak(text)
        except Exception:
            pass
    with _speech_lock:
        _speech_pending += 1
    speech_queue.put(text)

# ============================================
# НАСТРОЙКИ (сохраняются в settings.json)
# ============================================
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "wake_words": ["джарвис", "жарвис", "джарвес"],
    "require_wake": True,    # True -> команды только после кодового слова
    "user_name": "Слава",
    "speech_rate": 195,
    "speech_volume": 1.0,
    "weather_city": "Харьков",
    "voice": "pavel",
    "tts_engine": "offline",
    "edge_voice": "ru-RU-DmitryNeural",
    "languages": ["ru-RU", "en-US"],   # распознавание: русский + английский
    "allowed_folders": ["рабочий стол", "загрузки", "документы", "музыка", "видео", "картинки"],
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
        print(f" 6. Город для погоды : {settings.get('weather_city', 'Харьков')}")
        print(f" 7. Голос (м/ж)       : {settings.get('voice', 'pavel')}")
        print(f" 8. Живой голос Edge  : {settings.get('tts_engine', 'offline')} ({settings.get('edge_voice', 'ru-RU-DmitryNeural')})")
        print(f" 9. Сбросить настройки")
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
            print(f"\nТекущий город: {settings.get('weather_city', 'Харьков')}")
            city = input("Введи город для погоды: ").strip()
            if city:
                settings["weather_city"] = city
                save_settings(settings)
                print(f"Город погоды: {city}")
            else:
                print("Не изменено.")
        elif choice == "7":
            print(f"\nТекущий голос: {settings.get('voice', 'pavel')}")
            print("Доступные русские: pavel (мужской), irina (женский)")
            v = input("Введи голос (pavel/irina или часть имени): ").strip().lower()
            if v:
                chosen = apply_voice(v)
                if chosen:
                    settings["voice"] = v
                    save_settings(settings)
                    print(f"Голос: {chosen.name}")
                    engine.say("Проверка голоса. Теперь говорю так.")
                    engine.runAndWait()
                else:
                    print(f"Голос '{v}' не найден в системе. Не изменено.")
            else:
                print("Не изменено.")
        elif choice == "8":
            global TTS_MODE, EDGE_VOICE
            print(f"\nСейчас: {settings.get('tts_engine', 'offline')}")
            print(" 1 — живой Edge-TTS (онлайн, голос Дмитрия)")
            print(" 2 — обычный офлайн (Pavel)")
            sub = input("Выбери (1/2): ").strip()
            if sub == "1":
                settings["tts_engine"] = "edge"
                TTS_MODE = "edge"
                save_settings(settings)
                print("Включён живой голос Edge-TTS.")
            elif sub == "2":
                settings["tts_engine"] = "offline"
                TTS_MODE = "offline"
                save_settings(settings)
                print("Включён обычный офлайн-голос.")
            else:
                print("Не изменено.")
        elif choice == "9":
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
# РАСПОЗНАВАНИЕ РЕЧИ (русский + английский, авто-выбор)
# ============================================
RECOGNITION_LANGS = ["ru-RU", "en-US"]

def _recognize_multilang(recognizer, audio):
    """Распознаёт по нескольким языкам, выбирает вариант с большей уверенностью."""
    best_text, best_conf, net_error = None, -1.0, False
    for lang in RECOGNITION_LANGS:
        try:
            res = recognizer.recognize_google(audio, language=lang, show_all=True)
        except sr.RequestError:
            net_error = True
            continue
        except Exception:
            continue
        if not res or not isinstance(res, dict):
            continue
        alts = res.get("alternative") or []
        if not alts:
            continue
        transcript = alts[0].get("transcript", "")
        conf = alts[0].get("confidence", 0.0) or 0.0
        if transcript and conf > best_conf:
            best_conf, best_text = conf, transcript
        if transcript and conf >= 0.85:   # уверенно -> второй язык не нужен
            break
    if best_text is None and net_error:
        raise sr.RequestError("network")
    return best_text

def _listen_once(recognizer, timeout=5, phrase_limit=8):
    # Не слушаем, пока ассистент говорит — иначе микрофон ловит его же голос.
    wait_until_quiet()
    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.2)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
        text = _recognize_multilang(recognizer, audio)
        if not text:
            return None
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
# Намерение "найти/включить произведение" ведём в поиск YouTube даже без слова "ютуб"
SONG_INTENT = ["найди песню", "найди трек", "найди клип", "найди композицию",
               "найди видео", "найди ролик", "включи песню", "включи трек",
               "включи клип", "включи композицию", "включи видео",
               "поставь песню", "поставь трек", "поставь клип", "спой песню",
               "хочу послушать", "хочу песню", "хочу трек"]

def _extract_youtube_query(text_lower):
    """Вырезает триггеры/слово 'ютуб', НЕ ломая предлоги внутри названия."""
    q = text_lower
    # сначала убираем 'на/в/по ютубе' как цельные фразы (предлог тут служебный)
    for ph in ["на ютубе", "в ютубе", "по ютубе", "на ютуб", "в ютуб",
               "на youtube", "в youtube", "на ютьюбе", "в ютьюбе"]:
        q = q.replace(ph, " ")
    # одиночные слова 'ютуб'
    for w in YOUTUBE_WORDS:
        q = re.sub(r'\b' + re.escape(w) + r'\b', ' ', q)
    # триггеры и категории как отдельные слова (предлоги в/на/по НЕ трогаем —
    # они могут быть частью названия, напр. "в лесу родилась ёлочка")
    for w in ["открой", "открыть", "запусти", "запустить", "включи", "включить",
              "поставь", "найди", "поищи", "покажи", "спой", "мне", "пожалуйста",
              "хочу", "послушать", "песню", "песня", "трек", "клип",
              "композицию", "композиция", "видео", "ролик"]:
        q = re.sub(r'\b' + re.escape(w) + r'\b', ' ', q)
    return re.sub(r'\s+', ' ', q).strip()

def parse_youtube_command(text, recognizer=None):
    """ YouTube: открыть главную или поиск по запросу.
    Триггерится на 'ютуб' ИЛИ на 'найди/включи песню/трек/клип/видео'.
    Если название не расслышали — переспрашивает голосом (ловит конкретное
    произведение отдельной фразой с увеличенным окном записи). """
    text_lower = text.lower()
    has_yt = any(w in text_lower for w in YOUTUBE_WORDS)
    has_song = any(w in text_lower for w in SONG_INTENT)
    if not (has_yt or has_song):
        return False

    query = _extract_youtube_query(text_lower)

    # Запрос пуст. Переспрашиваем ТОЛЬКО при намерении поиска
    # ("найди/поставь/хочу..."), а не на простое "открой ютуб".
    find_intent = has_song or any(w in text_lower for w in
                                  ["найди", "поищи", "покажи", "поставь", "спой", "хочу"])
    if not query and find_intent and recognizer is not None:
        speak("Что найти на Ютубе? Назови песню или видео.")
        ans = _listen_once(recognizer, timeout=8, phrase_limit=9)
        if ans:
            query = ans.strip()

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
# ЗАКРЫТИЕ ПРИЛОЖЕНИЯ
# Команды:
#   "закрой телеграм"  /  "заверши хром"  /  "закрой браузер"
# ============================================
CLOSE_TRIGGERS = ["закрой", "закрыть", "заверши", "завершить", "прикрой", "убей"]
# системные значения из app_aliases, которые нельзя/не нужно "закрывать"
_NON_KILLABLE = ("lock", "screenshot")

def _resolve_kill_targets(query, installed_apps):
    """ По произнесённому имени возвращает список .exe для taskkill (или None). """
    query = query.lower().strip()
    # 1. конкретный браузер по имени (хром/опера/edge/яндекс/brave/фаерфокс)
    bq = query
    for alias, canonical in BROWSER_ALIASES.items():
        if alias in bq:
            bq = bq.replace(alias, canonical)
    for bname, paths in KNOWN_BROWSERS.items():
        if bname == bq or fuzz.token_sort_ratio(bq, bname) > 85:
            return [os.path.basename(paths[0])]
    # 2. словарь алиасов (точно или фаззи)
    cmd = None
    if query in app_aliases:
        cmd = app_aliases[query]
    elif app_aliases:
        best, score = process.extractOne(query, app_aliases.keys(), scorer=fuzz.token_sort_ratio)
        if score > 80:
            cmd = app_aliases[best]
    if cmd == "__browser__":
        names = [os.path.basename(p) for p in get_installed_browsers().values()]
        return names or None
    if cmd and not (cmd.startswith("http") or cmd.startswith("shutdown")
                    or cmd.startswith("ms-settings") or cmd in _NON_KILLABLE):
        return [cmd if cmd.lower().endswith(".exe") else cmd + ".exe"]
    # 3. кэш установленных приложений
    if installed_apps:
        best, score = process.extractOne(query, installed_apps.keys(), scorer=fuzz.token_sort_ratio)
        if score > 75:
            return [os.path.basename(installed_apps[best])]
    return None

def parse_close_command(text, installed_apps):
    """ Обрабатывает "закрой/заверши X". Возвращает True если команда была про закрытие. """
    text_lower = text.lower()
    if not any(w in text_lower for w in CLOSE_TRIGGERS):
        return False
    # убираем триггеры и слова-наполнители ПО ГРАНИЦАМ СЛОВ
    # (иначе "окно" вырезается из "блокнот" -> "бл т")
    query = text_lower
    for w in CLOSE_TRIGGERS + ["приложение", "программу", "программа",
                               "окно", "окна", "процесс", "мне", "это"]:
        query = re.sub(r'\b' + re.escape(w) + r'\b', ' ', query)
    query = re.sub(r'\s+', ' ', query).strip()
    if not query:
        speak("Что закрыть? Назови приложение.")
        return True
    targets = _resolve_kill_targets(query, installed_apps)
    if not targets:
        speak(f"Не знаю что закрывать по слову '{query}'.")
        return True
    closed = []
    for img in targets:
        try:
            r = subprocess.run(["taskkill", "/F", "/IM", img],
                               capture_output=True, text=True)
            if r.returncode == 0:
                closed.append(img)
        except Exception:
            continue
    if closed:
        speak(f"Закрыл: {', '.join(closed)}")
    else:
        speak(f"Не нашёл запущенное приложение '{query}'.")
    return True

# ============================================
# ГРОМКОСТЬ ЗВУКА
# Команды:
#   "громче" / "тише"                  -> +/- 10%
#   "громче на 20 процентов"           -> +/- N%
#   "громкость на 50 процентов"        -> установить 50%
#   "громкость на максимум" / "минимум"
#   "выключи звук" / "включи звук"     -> mute / unmute
#   "какая громкость"                  -> сказать текущий уровень
# Основной способ — pycaw (точная установка). Запасной — медиаклавиши.
# ============================================
def _volume_iface():
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    speakers = AudioUtilities.GetSpeakers()
    # Новый pycaw (>=2023): GetSpeakers() возвращает обёртку AudioDevice
    # с готовым .EndpointVolume. Старый — IMMDevice с методом .Activate.
    endpoint = getattr(speakers, "EndpointVolume", None)
    if endpoint is not None:
        return endpoint
    iface = speakers.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(iface, POINTER(IAudioEndpointVolume))

def _get_volume_scalar():
    """Текущий уровень 0.0..1.0 или None если pycaw недоступен."""
    try:
        return _volume_iface().GetMasterVolumeLevelScalar()
    except Exception:
        return None

def _try_set_volume(value):
    try:
        _volume_iface().SetMasterVolumeLevelScalar(max(0.0, min(1.0, value)), None)
        return True
    except Exception:
        return False

def _try_set_mute(state):
    try:
        _volume_iface().SetMute(1 if state else 0, None)
        return True
    except Exception:
        return False

def _media_key(key, n=1):
    try:
        import pyautogui
        for _ in range(n):
            pyautogui.press(key)
        return True
    except Exception:
        return False

def parse_volume_command(text):
    """ Управление системной громкостью. Возвращает True если команда была про звук. """
    t = text.lower()
    vol_words = ["громкост", "громче", "погромче", "тише", "потише",
                 "звук", "громко", "тихо", "мьют", "mute"]
    if not any(w in t for w in vol_words):
        return False

    num_match = re.search(r'(\d{1,3})', t)
    num = int(num_match.group(1)) if num_match else None

    # MUTE / UNMUTE
    if any(w in t for w in ["включи звук", "верни звук", "со звуком", "верни громкость"]):
        if not _try_set_mute(False):
            _media_key("volumemute")
        speak("Звук включён")
        return True
    if any(w in t for w in ["выключи звук", "отключи звук", "без звука",
                            "убери звук", "заглуши", "мьют", "mute", "тишина"]):
        if not _try_set_mute(True):
            _media_key("volumemute")
        speak("Звук выключен")
        return True

    up = any(w in t for w in ["громче", "погромче", "прибавь", "добавь",
                              "увеличь", "повыси", "подними"])
    down = any(w in t for w in ["тише", "потише", "убавь", "сбавь",
                                "уменьши", "понизь", "опусти"])
    mx = any(w in t for w in ["максимум", "максимальн", "на полную", "полную", "на всю"])
    mn = any(w in t for w in ["минимум", "минимальн"])

    cur = _get_volume_scalar()

    if mx:
        target = 1.0
    elif mn:
        target = 0.0
    elif up:
        step = (num if num else 10) / 100.0
        target = (cur if cur is not None else 0.5) + step
    elif down:
        step = (num if num else 10) / 100.0
        target = (cur if cur is not None else 0.5) - step
    elif num is not None:
        target = num / 100.0
    else:
        # просто спросили уровень
        if cur is not None:
            speak(f"Громкость {int(round(cur * 100))} процентов")
        else:
            speak("Не могу определить уровень громкости")
        return True

    target = max(0.0, min(1.0, target))
    if _try_set_volume(target):
        speak(f"Громкость {int(round(target * 100))} процентов")
    else:
        # запасной путь — медиаклавиши (только относительно)
        if mx:
            _media_key("volumeup", 50)
        elif mn:
            _media_key("volumedown", 50)
        elif up:
            _media_key("volumeup", max(1, (num if num else 10) // 2))
        elif down:
            _media_key("volumedown", max(1, (num if num else 10) // 2))
        speak("Готово")
    return True

# ============================================
# СКРИНШОТ
# Команды:
#   "сделай скриншот" / "снимок экрана" / "заскринь"
# Сохраняет PNG в %USERPROFILE%\Pictures\Screenshots с датой в имени
# и открывает папку с выделенным файлом.
# ============================================
SCREENSHOT_TRIGGERS = ["скриншот", "снимок экрана", "сфотографируй экран",
                       "сфоткай экран", "сделай скрин", "скрин экрана",
                       "заскринь", "печать экрана", "скрин"]

def parse_screenshot_command(text):
    """ Делает скриншот всего экрана. Возвращает True если команда была про скриншот. """
    t = text.lower()
    if not any(w in t for w in SCREENSHOT_TRIGGERS):
        return False

    folder = os.path.expandvars(r"%USERPROFILE%\Pictures\Screenshots")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        folder = os.path.expandvars(r"%USERPROFILE%\Pictures")

    fname = "screenshot_" + datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".png"
    path = os.path.join(folder, fname)

    img = None
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
    except Exception:
        try:
            import pyautogui
            img = pyautogui.screenshot()
        except Exception as e:
            speak(f"Не смог сделать скриншот: {e}")
            return True

    try:
        img.save(path)
    except Exception as e:
        speak(f"Не смог сохранить скриншот: {e}")
        return True

    speak("Скриншот готов, сохранил в папку скриншоты")
    # Открываем проводник с выделенным файлом
    try:
        subprocess.Popen(f'explorer /select,"{path}"')
    except Exception:
        pass
    return True

# ============================================
# УПРАВЛЕНИЕ МУЗЫКОЙ / МЕДИА
# Команды (работают с активным плеером: Spotify, браузер, и т.д.):
#   "пауза" / "плей" / "продолжи"      -> play/pause (одна кнопка-переключатель)
#   "следующий трек" / "переключи песню"
#   "предыдущий трек" / "прошлая песня"
# Через системные медиаклавиши. ВАЖНО: слово "стоп" не используем —
# в главном цикле оно завершает помощника.
# ============================================
def parse_media_command(text):
    """ Управление воспроизведением. Возвращает True если команда была медийной. """
    t = text.lower()

    # Следующий трек
    if any(w in t for w in ["следующ", "переключи песн", "переключи трек",
                            "дальше песн", "дальше трек", "next track", "вперёд песн"]):
        _media_key("nexttrack")
        speak("Следующий трек")
        return True

    # Предыдущий трек
    if any(w in t for w in ["предыдущ", "прошл", "назад песн", "назад трек",
                            "previous track", "верни песн"]):
        _media_key("prevtrack")
        speak("Предыдущий трек")
        return True

    # Play / Pause (одна системная кнопка-переключатель)
    # ВНИМАНИЕ: "стоп" нельзя — главный цикл по нему завершает помощника
    pause_words = ["пауз", "останови музык", "останови трек", "pause"]
    play_words = ["плей", "play", "продолж", "возобнов", "играй музык", "включи воспроизвед"]
    if any(w in t for w in pause_words):
        _media_key("playpause")
        speak("Ставлю на паузу")
        return True
    if any(w in t for w in play_words):
        _media_key("playpause")
        speak("Продолжаю")
        return True

    return False

# ============================================
# ПОГОДА (wttr.in, без ключа)
# Команды:
#   "погода"  /  "какая погода"  /  "погода в Москве"
# ============================================
# wttr.in/WWO не локализует описание -> своя таблица кодов погоды на русском
WEATHER_CODES_RU = {
    "113": "ясно", "116": "переменная облачность", "119": "облачно",
    "122": "пасмурно", "143": "дымка", "176": "местами дождь",
    "179": "местами снег", "182": "местами дождь со снегом",
    "185": "местами ледяная морось", "200": "возможна гроза",
    "227": "метель", "230": "сильная метель", "248": "туман",
    "260": "ледяной туман", "263": "местами лёгкая морось",
    "266": "лёгкая морось", "281": "ледяная морось",
    "284": "сильная ледяная морось", "293": "местами небольшой дождь",
    "296": "небольшой дождь", "299": "временами умеренный дождь",
    "302": "умеренный дождь", "305": "временами сильный дождь",
    "308": "сильный дождь", "311": "лёгкий ледяной дождь",
    "314": "умеренный или сильный ледяной дождь", "317": "лёгкий дождь со снегом",
    "320": "умеренный или сильный дождь со снегом", "323": "местами лёгкий снег",
    "326": "лёгкий снег", "329": "местами умеренный снег", "332": "умеренный снег",
    "335": "местами сильный снег", "338": "сильный снег", "350": "ледяная крупа",
    "353": "небольшой ливень", "356": "умеренный или сильный ливень",
    "359": "проливной ливень", "362": "лёгкий ливневый дождь со снегом",
    "365": "умеренный или сильный дождь со снегом", "368": "лёгкий снегопад",
    "371": "умеренный или сильный снегопад", "374": "лёгкая ледяная крупа",
    "377": "умеренная или сильная ледяная крупа", "386": "местами дождь с грозой",
    "389": "сильный дождь с грозой", "392": "местами снег с грозой",
    "395": "сильный снег с грозой",
}

def parse_weather_command(text, settings):
    """ Текущая погода через wttr.in. Возвращает True если команда была про погоду. """
    t = text.lower()
    if not any(w in t for w in ["погод", "сколько градус", "температура на улице", "на улице тепло"]):
        return False

    city = None
    m = re.search(r'(?:в|во)\s+([а-яё\-]+(?:\s+[а-яё\-]+)?)', t)
    if m:
        city = re.sub(r'\b(сейчас|сегодня|завтра|на|улице|градусов?)\b', ' ', m.group(1)).strip()
    if not city:
        city = settings.get("weather_city", "Харьков")

    try:
        url = "https://wttr.in/" + urllib.parse.quote(city) + "?format=j1&lang=ru"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        cur = data["current_condition"][0]
        temp = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        desc = WEATHER_CODES_RU.get(str(cur.get("weatherCode", "")),
                                    cur["weatherDesc"][0]["value"]).capitalize()
        city_say = city[:1].upper() + city[1:]
        speak(f"В городе {city_say}: {temp} градусов, ощущается как {feels}. {desc}.")
    except Exception as e:
        speak(f"Не смог получить погоду: {e}")
    return True

# ============================================
# БУФЕР ОБМЕНА
# Команды:
#   "запиши в буфер" / "скопируй в буфер" -> диктуешь текст -> в буфер
#   "вставь" / "вставь текст"             -> Ctrl+V в активное окно
# ============================================
def _set_clipboard(text):
    """Кладёт текст в буфер. True/False."""
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        pass
    # запасной путь — системная утилита clip (UTF-16LE)
    try:
        p = subprocess.Popen("clip", stdin=subprocess.PIPE)
        p.communicate(text.encode("utf-16-le"))
        return p.returncode == 0
    except Exception:
        return False

def parse_clipboard_command(text, recognizer):
    """ Работа с буфером обмена. Возвращает True если команда была про буфер. """
    t = text.lower()

    # Вставка в активное окно
    if any(w in t for w in ["вставь", "вставка", "вставить текст", "вставить из буфера"]):
        try:
            import pyautogui
            speak("Вставляю через три секунды, переключись на нужное окно")
            time.sleep(3)
            pyautogui.hotkey('ctrl', 'v')
        except Exception as e:
            speak(f"Не смог вставить: {e}")
        return True

    # Диктовка текста в буфер
    if any(w in t for w in ["буфер", "скопир", "продиктую", "надиктую",
                            "запиши текст", "сохрани текст"]):
        speak("Говори текст, я скопирую в буфер")
        dictated = _listen_once(recognizer, timeout=12)
        if not dictated:
            speak("Не услышал текст")
            return True
        if _set_clipboard(dictated):
            speak("Скопировал в буфер. Вставляй через Ctrl+V или скажи: вставь")
        else:
            speak("Не получилось скопировать в буфер")
        return True

    return False

# ============================================
# БЛОКИРОВКА / СОН ПК
# Команды:
#   "заблокируй" / "блокировка"   -> экран блокировки
#   "спящий режим" / "усыпи"      -> сон
# ============================================
def parse_power_command(text):
    """ Блокировка экрана или сон. Возвращает True если команда была про питание. """
    t = text.lower()

    if any(w in t for w in ["заблокируй", "блокировк", "запри комп", "запри экран", "залочь"]):
        speak("Блокирую")
        try:
            subprocess.Popen("rundll32.exe user32.dll,LockWorkStation")
        except Exception as e:
            speak(f"Не смог заблокировать: {e}")
        return True

    if any(w in t for w in ["спящий режим", "режим сна", "усыпи", "уйти в сон",
                            "сон компьютер", "засни компьютер"]):
        speak("Ухожу в спящий режим")
        try:
            os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
        except Exception as e:
            speak(f"Не смог уйти в сон: {e}")
        return True

    return False

# ============================================
# ПЕРЕКЛЮЧЕНИЕ ГОЛОСА (живой Edge-TTS / обычный офлайн)
# Команды:
#   "включи живой голос" / "красивый голос"  -> Edge-TTS (онлайн)
#   "обычный голос" / "офлайн голос"          -> pyttsx3 / Pavel
# ============================================
def parse_tts_command(text):
    global TTS_MODE
    t = text.lower()
    if any(w in t for w in ["живой голос", "онлайн голос", "нейросетевой голос",
                            "красивый голос", "голос дмитрия", "включи живой"]):
        TTS_MODE = "edge"
        speak("Переключаюсь на живой голос")
        return True
    if any(w in t for w in ["обычный голос", "офлайн голос", "оффлайн голос",
                            "простой голос", "верни обычный голос", "выключи живой"]):
        TTS_MODE = "offline"
        speak("Возвращаю обычный голос")
        return True
    return False

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
    if parse_youtube_command(text, recognizer):
        return
    # 4.6 Закрытие приложения
    if parse_close_command(text, installed_apps):
        return
    # 4.7 Громкость звука
    if parse_volume_command(text):
        return
    # 4.8 Скриншот
    if parse_screenshot_command(text):
        return
    # 4.9 Музыка / медиа (play, pause, next, prev)
    if parse_media_command(text):
        return
    # 4.10 Погода
    if parse_weather_command(text, settings):
        return
    # 4.11 Буфер обмена (диктовка / вставка)
    if parse_clipboard_command(text, recognizer):
        return
    # 4.12 Блокировка / сон ПК
    if parse_power_command(text):
        return
    # 4.13 Переключение голоса (живой / обычный)
    if parse_tts_command(text):
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
        # «Мозг»: нераспознанную свободную речь отдаём в LLM-пул, который
        # подбирает существующий инструмент. Если мозг не справился/недоступен —
        # обычный Win-поиск, как раньше (ничего не ломается).
        try:
            import brain
            if brain.handle_freeform(text, recognizer, settings, installed_apps, installed_browsers):
                return
        except Exception as e:
            print(f"brain недоступен: {e}")
        speak(f"Не нашёл '{clean_text}', ищу через Windows")
        _win_search(query)
        return
    speak(f"Открываю {clean_text}")
    open_app(result)

# ============================================
# ГЛАВНЫЙ ЦИКЛ
# ============================================
def main():
    global TTS_MODE, EDGE_VOICE, VOICE_PREF, RECOGNITION_LANGS
    settings = load_settings()
    engine.setProperty('rate', settings["speech_rate"])
    engine.setProperty('volume', settings["speech_volume"])
    VOICE_PREF = settings.get("voice", "pavel")
    apply_voice(VOICE_PREF)
    TTS_MODE = settings.get("tts_engine", "offline")
    EDGE_VOICE = settings.get("edge_voice", "ru-RU-DmitryNeural")
    RECOGNITION_LANGS = settings.get("languages", ["ru-RU", "en-US"])
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
