# -*- coding: utf-8 -*-
"""
brain.py — «мозг» на базе твоего LLM-пула (gemini-studio, бесплатно).

Подключение НЕ через прямой вызов Google, а через твой пул на сервере:
  Windows → SSH → /root/agents/common/brat_brain_route.py → llm_pool.ask()
Пул сам каскадит: gemini-studio → huggingface → vertex-pro.

Роль: ТОЛЬКО подстраховка. brat.process_command() остаётся первым и
обрабатывает все знакомые команды мгновенно. Сюда фраза попадает лишь
когда быстрый роутер не распознал её (вместо слепого поиска в Windows).

Свободная речь (рус/англ) → пул возвращает строгий JSON
  {"tool":"<name>","args":{...},"say":"<ответ на языке пользователя>"}
→ вызывается ТОТ ЖЕ существующий код brat.

Безопасность:
  • опасные инструменты (taskkill, файлы, сон/выключение) — только после
    подтверждения (голос + кнопка в GUI);
  • файловые операции — только внутри белого списка папок из settings;
  • замена текста — с .bak (как в brat);
  • лог всех вызовов в logs/llm_tools.jsonl.
"""
import os
import sys
import json
import subprocess
import datetime
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))

# ── конфиг из .env (ничего не хардкодим) ──
def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(HERE, ".env"))
    except Exception:
        pass
_load_env()

SSH_HOST   = os.environ.get("BRAIN_SSH_HOST", "vps")
REMOTE_CMD = os.environ.get("BRAIN_REMOTE_CMD", "python3 /root/agents/common/brat_brain_route.py")
SSH_TIMEOUT = int(os.environ.get("BRAIN_SSH_TIMEOUT", "25"))
BRAIN_ENABLED = os.environ.get("BRAIN_ENABLED", "1").strip() not in ("0", "false", "False", "")
LOG_PATH = os.path.join(HERE, "logs", "llm_tools.jsonl")

# Колбэк подтверждения опасных действий. GUI ставит свой (кнопки+голос).
# Сигнатура: confirm_fn(description:str, recognizer) -> bool
CONFIRM_FN = None

# ══════════════════════════════════════════════════════════════
#  РЕЕСТР ИНСТРУМЕНТОВ
# ══════════════════════════════════════════════════════════════
# Описание для модели (строки в промпт). Имена должны совпадать с DISPATCH.
TOOLS_DOC = """- open_application(name): launch an installed app or open a website by name
- open_browser(): open the default/preferred web browser
- youtube_search(query): open a YouTube search for query
- youtube_open(): open YouTube home page
- set_volume(level): set system volume, level 0-100
- change_volume(direction): direction = "up" or "down" (step ~10%)
- mute_audio(state): state = "on" to mute, "off" to unmute
- take_screenshot(): capture the whole screen to Pictures
- media_control(action): action = "play_pause" | "next" | "previous"
- get_weather(city): current weather; city optional
- get_time_date(kind): kind = "time" or "date"
- set_timer(seconds, label): start a countdown timer
- set_alarm(hour, minute): set an alarm at hour:minute
- lock_screen(): lock the Windows session
- clipboard_set(text): put text into the clipboard
- clipboard_paste(): paste clipboard into the active window (Ctrl+V)
- set_voice_mode(mode): mode = "live" (neural) or "offline"
- close_application(name): force-close a running app  [DANGEROUS]
- move_file(filename, dest_folder): move a file to a folder  [DANGEROUS]
- replace_in_file(filename, old_text, new_text): replace text in a file  [DANGEROUS]
- sleep_pc(): put the PC to sleep  [DANGEROUS]
- shutdown_pc(mode, delay): mode = "shutdown" | "restart" | "cancel"; delay seconds  [DANGEROUS]
- none(): nothing matched — just answer in "say" """

DANGEROUS = {"close_application", "move_file", "replace_in_file", "sleep_pc", "shutdown_pc"}

SYSTEM_PROMPT = (
    "You are the intent router of a Windows voice assistant named Jarvis.\n"
    "Map the user's phrase to EXACTLY ONE tool with arguments.\n"
    "Respond with ONLY a raw JSON object (no markdown, no code fences), schema:\n"
    '{"tool":"<name>","args":{...},"say":"<short reply in the SAME language as the user>"}\n'
    "Rules: pick the single most relevant tool; put real values in args; keep 'say' short.\n"
    "If nothing fits, use tool \"none\" and answer the user in 'say'.\n\n"
    "AVAILABLE TOOLS:\n" + TOOLS_DOC + "\n"
)


# ══════════════════════════════════════════════════════════════
#  ВЫЗОВ ПУЛА (через SSH)
# ══════════════════════════════════════════════════════════════
def _ask_pool(phrase):
    """Отправляет промпт в пул на сервере, возвращает сырой ответ (str) или None."""
    prompt = SYSTEM_PROMPT + '\nUSER PHRASE: "' + phrase.replace('"', "'") + '"\nJSON:'
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", SSH_HOST] + REMOTE_CMD.split(),
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=SSH_TIMEOUT,
        )
        out = r.stdout.decode("utf-8", "replace").strip()
        if not out or out.startswith("__EMPTY__") or out.startswith("__ERROR__"):
            return None
        return out
    except Exception:
        return None


def _parse_json(raw):
    """Достаёт JSON-объект из ответа модели (на случай мусора вокруг)."""
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        return json.loads(raw)
    except Exception:
        pass
    # вырезаем первый {...}
    i, j = raw.find("{"), raw.rfind("}")
    if i != -1 and j != -1 and j > i:
        try:
            return json.loads(raw[i:j + 1])
        except Exception:
            return None
    return None


# ══════════════════════════════════════════════════════════════
#  ЛОГ
# ══════════════════════════════════════════════════════════════
def _log(phrase, tool, args, danger, confirmed, result):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        rec = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "phrase": phrase, "tool": tool, "args": args,
            "dangerous": danger, "confirmed": confirmed, "result": result,
        }
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  БЕЛЫЙ СПИСОК ПАПОК (для файловых операций)
# ══════════════════════════════════════════════════════════════
def _allowed_folders(settings):
    import brat
    raw = settings.get("allowed_folders")
    if raw:
        paths = []
        for p in raw:
            paths.append(os.path.abspath(os.path.expandvars(brat.FOLDER_ALIASES.get(p.lower(), p))))
        return paths
    # по умолчанию — все папки-алиасы brat
    return [os.path.abspath(p) for p in set(brat.FOLDER_ALIASES.values())]


def _within_whitelist(path, settings):
    ap = os.path.abspath(path)
    for base in _allowed_folders(settings):
        try:
            if os.path.commonpath([ap, base]) == base:
                return True
        except Exception:
            continue
    return False


# ══════════════════════════════════════════════════════════════
#  ПОДТВЕРЖДЕНИЕ ОПАСНЫХ ДЕЙСТВИЙ (голос + кнопка)
# ══════════════════════════════════════════════════════════════
def _confirm(description, recognizer):
    import brat
    if CONFIRM_FN:
        try:
            return bool(CONFIRM_FN(description, recognizer))
        except Exception:
            pass
    # дефолт (CLI): голос
    brat.speak(description + ". Подтверди: да или нет")
    ans = (brat._listen_once(recognizer, timeout=7) or "").lower()
    yes = any(w in ans for w in ["да", "подтвержд", "давай", "согла", "yes", "confirm", "ок", "окей"])
    no = any(w in ans for w in ["нет", "отмен", "не надо", "no", "cancel", "стоп"])
    return yes and not no


# ══════════════════════════════════════════════════════════════
#  ИСПОЛНИТЕЛИ ИНСТРУМЕНТОВ  (вызывают существующий код brat)
# ══════════════════════════════════════════════════════════════
def _h_open_application(args, ctx):
    import brat
    name = (args.get("name") or "").strip()
    if not name:
        return False
    res = brat.find_app(name, ctx["apps"], ctx["settings"].get("custom_aliases", {}))
    if res == "__browser__":
        brat.handle_browser_command(ctx["browsers"], ctx["recognizer"]); return True
    if res.startswith("__winsearch__"):
        brat._win_search(name); return True
    brat.open_app(res); return True

def _h_open_browser(args, ctx):
    import brat
    brat.handle_browser_command(ctx["browsers"], ctx["recognizer"]); return True

def _h_youtube_search(args, ctx):
    import brat
    q = (args.get("query") or "").strip()
    if not q:
        brat.os.startfile("https://youtube.com"); return True
    brat.os.startfile("https://www.youtube.com/results?search_query=" + urllib.parse.quote(q)); return True

def _h_youtube_open(args, ctx):
    import brat
    brat.os.startfile("https://youtube.com"); return True

def _h_set_volume(args, ctx):
    import brat
    try:
        lvl = float(args.get("level"))
    except (TypeError, ValueError):
        return False
    return brat._try_set_volume(max(0.0, min(1.0, lvl / 100.0)))

def _h_change_volume(args, ctx):
    import brat
    cur = brat._get_volume_scalar()
    if cur is None:
        cur = 0.5
    d = (args.get("direction") or "up").lower()
    step = 0.1
    target = cur + step if d.startswith("up") or "громч" in d else cur - step
    return brat._try_set_volume(max(0.0, min(1.0, target)))

def _h_mute_audio(args, ctx):
    import brat
    st = str(args.get("state", "on")).lower()
    return brat._try_set_mute(st in ("on", "true", "1", "yes", "вкл", "да"))

def _h_take_screenshot(args, ctx):
    import brat
    return brat.parse_screenshot_command("сделай скриншот")

def _h_media_control(args, ctx):
    import brat
    a = (args.get("action") or "play_pause").lower()
    key = {"play_pause": "playpause", "pause": "playpause", "play": "playpause",
           "next": "nexttrack", "previous": "prevtrack", "prev": "prevtrack"}.get(a, "playpause")
    return brat._media_key(key)

def _h_get_weather(args, ctx):
    import brat
    city = (args.get("city") or "").strip()
    phrase = ("погода в " + city) if city else "погода"
    return brat.parse_weather_command(phrase, ctx["settings"])

def _h_get_time_date(args, ctx):
    import brat
    kind = (args.get("kind") or "time").lower()
    reply = brat.get_chat_response("какой день" if kind == "date" else "который час",
                                   ctx["settings"].get("user_name", "Слава"))
    if reply:
        brat.speak(reply)
    return True

def _h_set_timer(args, ctx):
    import brat
    try:
        secs = int(args.get("seconds"))
    except (TypeError, ValueError):
        return False
    brat.set_timer(secs, args.get("label") or f"Таймер на {secs} секунд"); return True

def _h_set_alarm(args, ctx):
    import brat
    try:
        h = int(args.get("hour")); m = int(args.get("minute", 0))
    except (TypeError, ValueError):
        return False
    brat.set_alarm(h % 24, m % 60); return True

def _h_lock_screen(args, ctx):
    import brat
    brat.subprocess.Popen("rundll32.exe user32.dll,LockWorkStation"); return True

def _h_clipboard_set(args, ctx):
    import brat
    txt = args.get("text") or ""
    return brat._set_clipboard(txt)

def _h_clipboard_paste(args, ctx):
    try:
        import pyautogui, time
        time.sleep(0.4)
        pyautogui.hotkey("ctrl", "v")
        return True
    except Exception:
        return False

def _h_set_voice_mode(args, ctx):
    import brat
    mode = (args.get("mode") or "offline").lower()
    return brat.parse_tts_command("включи живой голос" if mode == "live" else "обычный голос")

# ---- опасные ----
def _h_close_application(args, ctx):
    import brat
    name = (args.get("name") or "").strip()
    targets = brat._resolve_kill_targets(name, ctx["apps"])
    if not targets:
        brat.speak(f"Не знаю что закрывать: {name}"); return False
    closed = []
    for img in targets:
        try:
            r = brat.subprocess.run(["taskkill", "/F", "/IM", img], capture_output=True, text=True)
            if r.returncode == 0:
                closed.append(img)
        except Exception:
            continue
    brat.speak("Закрыл: " + ", ".join(closed) if closed else f"Не нашёл запущенное: {name}")
    return bool(closed)

def _h_move_file(args, ctx):
    import brat, shutil
    fn = (args.get("filename") or "").strip()
    dest = (args.get("dest_folder") or "").strip()
    src = brat.find_file_on_desktop_and_downloads(fn)
    if not src:
        brat.speak(f"Не нашёл файл {fn}"); return False
    dst_folder = brat.resolve_folder(dest)
    if not dst_folder:
        brat.speak(f"Не знаю папку {dest}"); return False
    if not (_within_whitelist(src, ctx["settings"]) and _within_whitelist(dst_folder, ctx["settings"])):
        brat.speak("Путь вне разрешённых папок — отказываю в перемещении"); return False
    try:
        dst = os.path.join(dst_folder, os.path.basename(src))
        if os.path.exists(dst):
            base, ext = os.path.splitext(dst); n = 1
            while os.path.exists(f"{base} ({n}){ext}"):
                n += 1
            dst = f"{base} ({n}){ext}"
        shutil.move(src, dst)
        brat.speak(f"Переместил {os.path.basename(src)} в {dest}"); return True
    except Exception as e:
        brat.speak(f"Ошибка перемещения: {e}"); return False

def _h_replace_in_file(args, ctx):
    import brat, shutil
    fn = (args.get("filename") or "").strip()
    old = args.get("old_text"); new = args.get("new_text")
    if old is None or new is None:
        return False
    src = brat.find_file_on_desktop_and_downloads(fn)
    if not src:
        brat.speak(f"Не нашёл файл {fn}"); return False
    if not _within_whitelist(src, ctx["settings"]):
        brat.speak("Файл вне разрешённых папок — отказываю в правке"); return False
    try:
        with open(src, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        brat.speak(f"Не могу прочитать файл: {e}"); return False
    if old not in content:
        brat.speak("Такой текст в файле не найден"); return False
    try:
        shutil.copy2(src, src + ".bak")
        with open(src, "w", encoding="utf-8") as f:
            f.write(content.replace(old, new))
        brat.speak(f"Заменил {content.count(old)} вхождений. Бэкап рядом"); return True
    except Exception as e:
        brat.speak(f"Ошибка записи: {e}"); return False

def _h_sleep_pc(args, ctx):
    import brat
    brat.os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0"); return True

def _h_shutdown_pc(args, ctx):
    import brat
    mode = (args.get("mode") or "shutdown").lower()
    delay = int(args.get("delay", 60)) if str(args.get("delay", "60")).isdigit() else 60
    if mode == "cancel":
        brat.os.system("shutdown /a"); return True
    flag = "/r" if mode == "restart" else "/s"
    brat.os.system(f"shutdown {flag} /t {delay}"); return True


DISPATCH = {
    "open_application": _h_open_application, "open_browser": _h_open_browser,
    "youtube_search": _h_youtube_search, "youtube_open": _h_youtube_open,
    "set_volume": _h_set_volume, "change_volume": _h_change_volume, "mute_audio": _h_mute_audio,
    "take_screenshot": _h_take_screenshot, "media_control": _h_media_control,
    "get_weather": _h_get_weather, "get_time_date": _h_get_time_date,
    "set_timer": _h_set_timer, "set_alarm": _h_set_alarm, "lock_screen": _h_lock_screen,
    "clipboard_set": _h_clipboard_set, "clipboard_paste": _h_clipboard_paste,
    "set_voice_mode": _h_set_voice_mode,
    "close_application": _h_close_application, "move_file": _h_move_file,
    "replace_in_file": _h_replace_in_file, "sleep_pc": _h_sleep_pc, "shutdown_pc": _h_shutdown_pc,
}

# человекочитаемое описание для подтверждения
def _danger_phrase(tool, args):
    a = args or {}
    if tool == "close_application":
        return f"Закрыть приложение {a.get('name','?')}"
    if tool == "move_file":
        return f"Переместить файл {a.get('filename','?')} в {a.get('dest_folder','?')}"
    if tool == "replace_in_file":
        return f"Заменить текст в файле {a.get('filename','?')}"
    if tool == "sleep_pc":
        return "Отправить компьютер в сон"
    if tool == "shutdown_pc":
        m = a.get("mode", "shutdown")
        return {"restart": "Перезагрузить компьютер", "cancel": "Отменить выключение"}.get(m, "Выключить компьютер")
    return f"Выполнить {tool}"


# ══════════════════════════════════════════════════════════════
#  ГЛАВНАЯ ТОЧКА ВХОДА
# ══════════════════════════════════════════════════════════════
def handle_freeform(phrase, recognizer, settings, installed_apps, installed_browsers):
    """
    Пытается обработать нераспознанную фразу через LLM-пул.
    Возвращает True, если что-то сделал/ответил; False — пусть brat делает Win-поиск.
    """
    import brat
    if not BRAIN_ENABLED:
        return False
    raw = _ask_pool(phrase)
    data = _parse_json(raw)
    if not data:
        return False  # пул недоступен/мусор → brat сделает обычный Win-поиск
    tool = (data.get("tool") or "none").strip()
    args = data.get("args") or {}
    say = (data.get("say") or "").strip()

    if tool == "none" or tool not in DISPATCH:
        if say:
            brat.speak(say)
            _log(phrase, tool, args, False, None, "answered")
            return True
        return False  # нечего сказать → Win-поиск

    ctx = {"recognizer": recognizer, "settings": settings,
           "apps": installed_apps, "browsers": installed_browsers}

    danger = tool in DANGEROUS
    confirmed = None
    if danger:
        desc = _danger_phrase(tool, args)
        confirmed = _confirm(desc, recognizer)
        if not confirmed:
            brat.speak("Отменено")
            _log(phrase, tool, args, True, False, "cancelled")
            return True

    if say and not danger:
        brat.speak(say)
    try:
        result = DISPATCH[tool](args, ctx)
        _log(phrase, tool, args, danger, confirmed, "ok" if result else "failed")
        return True
    except Exception as e:
        brat.speak(f"Ошибка выполнения: {e}")
        _log(phrase, tool, args, danger, confirmed, f"error: {e}")
        return True
