# -*- coding: utf-8 -*-
"""
DARK / БРАТ — графическая оболочка поверх движка brat.py.

Объединяет:
  • GUI и систему защиты/лицензии (изначально из версии "DARK")
  • ВСЕ голосовые команды и голоса из brat.py (YouTube-поиск, закрытие
    приложений, громкость, скриншот, медиа, погода, буфер, блокировка/сон,
    мужской голос Pavel + живой Edge-TTS)

Распознавание речи — Google (онлайн), как в brat.py.
Запуск:  python dark_gui.py
Если customtkinter не установлен — откатывается на консольный brat.main().
"""
import os
import sys
import re
import json
import datetime
import threading
import time
import hashlib
import hmac
import uuid
import platform

import speech_recognition as sr
import brat  # весь движок: команды, голоса, настройки, TTS

# ╔══════════════════════════════════════════════╗
# ║         ЗАЩИТА / ЛИЦЕНЗИЯ (3 уровня)         ║
# ╚══════════════════════════════════════════════╝
DEV_MODE = True                       # True — проверки отключены (личное использование)
_SECRET = b"BR4T_S3CR3T_K3Y_2024_CHANGE_ME"
_LICENSE_FILE = "license.key"
_INTEGRITY_FILE = "integrity.hash"


def _get_hwid():
    try:
        raw = f"{uuid.getnode()}-{platform.node()}-{platform.processor()}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]
    except Exception:
        return "UNKNOWN_HWID"


def _generate_key(hwid):
    sig = hmac.new(_SECRET, hwid.encode(), hashlib.sha256).hexdigest()[:16].upper()
    return "-".join(sig[i:i + 4] for i in range(0, 16, 4))


def _check_license():
    if DEV_MODE:
        return True
    if not os.path.exists(_LICENSE_FILE):
        return False
    try:
        with open(_LICENSE_FILE, "r") as f:
            data = json.load(f)
        cur = _get_hwid()
        return data.get("hwid") == cur and data.get("key") == _generate_key(cur)
    except Exception:
        return False


def _compute_file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _check_integrity():
    if DEV_MODE or not os.path.exists(_INTEGRITY_FILE):
        return True
    try:
        with open(_INTEGRITY_FILE, "r") as f:
            saved = f.read().strip()
        return hmac.compare_digest(saved, _compute_file_hash(os.path.abspath(__file__)))
    except Exception:
        return False


def _save_integrity():
    try:
        with open(_INTEGRITY_FILE, "w") as f:
            f.write(_compute_file_hash(os.path.abspath(__file__)))
    except Exception:
        pass


def create_license_for(hwid):
    """Утилита для продавца: сгенерировать license.key под конкретный HWID."""
    key = _generate_key(hwid)
    with open(_LICENSE_FILE, "w") as f:
        json.dump({"hwid": hwid, "key": key, "issued": str(datetime.date.today())}, f, indent=2)
    print(f"Лицензия создана:\n  HWID: {hwid}\n  KEY:  {key}")
    return key


def _show_protection_error(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("DARK — Ошибка активации", message)
        root.destroy()
    except Exception:
        print(f"[ЗАЩИТА] {message}")
    sys.exit(1)


def run_protection():
    if DEV_MODE:
        print("[ЗАЩИТА] DEV_MODE — проверки отключены")
        return
    if not _check_integrity():
        _show_protection_error("Файл программы был изменён. Обратитесь к продавцу.")
    if not os.path.exists(_INTEGRITY_FILE):
        _save_integrity()
    if not _check_license():
        hwid = _get_hwid()
        _show_protection_error(
            f"Лицензия не найдена или недействительна.\n\n"
            f"Ваш HWID для получения лицензии:\n{hwid}\n\nОбратитесь к продавцу."
        )


# ╔══════════════════════════════════════════════╗
# ║                  GUI                         ║
# ╚══════════════════════════════════════════════╝
import customtkinter as ctk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#6C63FF"
ACCENT2 = "#FF6584"
BG_DARK = "#0F0F1A"
BG_CARD = "#1A1A2E"
BG_INPUT = "#16213E"
TEXT_PRI = "#FFFFFF"
TEXT_SEC = "#A0A0C0"

EXIT_WORDS = ["пока", "выйди", "стоп", "выключись", "завершение"]


class BratApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("БРАТ — голосовой ассистент")
        self.geometry("520x720")
        self.configure(fg_color=BG_DARK)

        # --- движок brat ---
        self.settings = brat.load_settings()
        brat.engine.setProperty('rate', self.settings.get("speech_rate", 195))
        brat.engine.setProperty('volume', self.settings.get("speech_volume", 1.0))
        brat.apply_voice(self.settings.get("voice", "pavel"))
        brat.TTS_MODE = self.settings.get("tts_engine", "offline")
        brat.EDGE_VOICE = self.settings.get("edge_voice", "ru-RU-DmitryNeural")
        brat.on_speak = self.log            # озвучка попадает в лог окна

        self.apps_cache = brat.load_apps_cache()
        self.browsers = brat.get_installed_browsers()
        self.recognizer = sr.Recognizer()
        self.wake_words = self.settings.get("wake_words", ["брат"])
        self.listening = False

        self._build_ui()

        self.log(f"🚀 БРАТ запущен (HWID: {_get_hwid()})")
        self.log(f"👤 Пользователь: {self.settings.get('user_name', 'Слава')}")
        self.log(f"🎯 Слово активации: {', '.join(self.wake_words)}")
        self.log(f"📦 Приложений в кэше: {len(self.apps_cache)} | Браузеры: {', '.join(self.browsers) or '—'}")
        voice_kind = "живой Edge-TTS" if brat.TTS_MODE == "edge" else "офлайн (Pavel)"
        self.log(f"🔊 Голос: {voice_kind}")
        self.after(800, lambda: brat.speak(
            f"Привет, {self.settings.get('user_name', 'Слава')}! Брат готов."))

    def _find_wake(self, text):
        """Ищет кодовое слово целым словом (по границам), не как подстроку."""
        for w in self.wake_words:
            if re.search(r'\b' + re.escape(w) + r'\b', text):
                return w
        return None

    def _wake_hint(self):
        words = ", ".join(self.wake_words)
        if self.settings.get("require_wake", True):
            return f"Скажи «{words}», затем команду"
        return "Можно говорить без кодового слова"

    # ---------- UI ----------
    def _build_ui(self):
        ctk.CTkLabel(self, text="БРАТ", font=("Arial", 36, "bold"),
                     text_color=ACCENT).pack(pady=(18, 2))
        ctk.CTkLabel(self, text="Голосовой ассистент", font=("Arial", 14),
                     text_color=TEXT_SEC).pack(pady=(0, 4))
        self.wake_label = ctk.CTkLabel(
            self, text=self._wake_hint(),
            font=("Arial", 12), text_color=ACCENT2)
        self.wake_label.pack(pady=(0, 8))

        log_frame = ctk.CTkFrame(self, fg_color=BG_CARD)
        log_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self.log_text = ctk.CTkTextbox(log_frame, fg_color=BG_CARD, text_color=TEXT_PRI,
                                       font=("Consolas", 12), wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.log_text.configure(state="disabled")

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=5)
        self.listen_btn = ctk.CTkButton(btns, text="🎤 СЛУШАТЬ", font=("Arial", 16, "bold"),
                                        fg_color=ACCENT, hover_color="#5A52E0", height=50,
                                        command=self.toggle_listening)
        self.listen_btn.pack(fill="x", pady=2)
        ctk.CTkButton(btns, text="⚙ Настройки", font=("Arial", 12), fg_color=BG_CARD,
                      hover_color=BG_INPUT, height=35, command=self._open_settings).pack(fill="x", pady=2)
        ctk.CTkButton(btns, text="🔄 Пересканировать приложения", font=("Arial", 12),
                      fg_color=BG_CARD, hover_color=BG_INPUT, height=35,
                      command=self.refresh_apps).pack(fill="x", pady=2)
        ctk.CTkButton(btns, text="🗑 Очистить лог", font=("Arial", 12), fg_color=BG_CARD,
                      hover_color=BG_INPUT, height=35, command=self._clear_log).pack(fill="x", pady=2)

        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=(5, 10))
        self.text_input = ctk.CTkEntry(row, placeholder_text="Введи команду вручную...",
                                       font=("Arial", 13), fg_color=BG_CARD, border_color=ACCENT,
                                       corner_radius=10, height=38)
        self.text_input.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.text_input.bind("<Return>", self._on_manual_send)
        ctk.CTkButton(row, text="➤", width=44, height=38, fg_color=ACCENT,
                      hover_color="#5A52E0", corner_radius=10,
                      command=self._on_manual_send).pack(side="right")

        self.status_label = ctk.CTkLabel(self, text="● Ожидание", font=("Arial", 12),
                                         text_color=TEXT_SEC)
        self.status_label.pack(pady=(0, 10))

    # ---------- лог / статус (потокобезопасно через after) ----------
    def log(self, message):
        self.after(0, self._log_safe, message)

    def _log_safe(self, message):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] {message}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _set_status(self, text, color):
        self.after(0, lambda: self.status_label.configure(text=text, text_color=color))

    # ---------- ручной ввод ----------
    def _on_manual_send(self, event=None):
        text = self.text_input.get().strip()
        if not text:
            return
        self.text_input.delete(0, "end")
        self.log(f"⌨ Ты: {text}")
        threading.Thread(target=self._run_command, args=(text.lower(),), daemon=True).start()

    def _run_command(self, command):
        try:
            brat.process_command(command, self.apps_cache, self.browsers,
                                 self.recognizer, self.settings)
        except Exception as e:
            self.log(f"⚠ Ошибка: {e}")

    # ---------- прослушивание ----------
    def toggle_listening(self):
        if self.listening:
            self.listening = False
            self.listen_btn.configure(text="🎤 СЛУШАТЬ", fg_color=ACCENT)
            self._set_status("● Ожидание", TEXT_SEC)
            self.log("🛑 Прослушивание остановлено")
        else:
            self.listening = True
            self.listen_btn.configure(text="⏹ СТОП", fg_color=ACCENT2)
            self._set_status("● Слушаю...", ACCENT2)
            self.log(f"🎤 Жду слово «{self.wake_words[0]}»...")
            threading.Thread(target=self._listen_loop, daemon=True).start()

    def _listen_loop(self):
        while self.listening:
            text = brat._listen_once(self.recognizer, timeout=8)
            if not text or not self.listening:
                continue
            self.log(f"🗣 Услышал: {text}")

            require_wake = self.settings.get("require_wake", True)
            # Кодовое слово ищем ЦЕЛЫМ словом (\b), чтобы "бот" не срабатывал
            # внутри "работа", "суббота" и т.п.
            matched = self._find_wake(text)

            if require_wake and not matched:
                self.log("💤 Нет кодового слова — пропускаю")
                continue

            if matched:
                command = re.sub(r'\b' + re.escape(matched) + r'\b', ' ', text, count=1).strip()
                command = re.sub(r'\s+', ' ', command)
            else:
                command = text.strip()
            if not command:
                command = "__wake_only__"

            if any(w in command for w in EXIT_WORDS):
                self.log("👋 Команда выхода — останавливаю прослушивание")
                brat.speak(f"До связи, {self.settings.get('user_name', 'Слава')}!")
                self.listening = False
                self.after(0, lambda: self.listen_btn.configure(text="🎤 СЛУШАТЬ", fg_color=ACCENT))
                self._set_status("● Ожидание", TEXT_SEC)
                break

            self._set_status("● Обрабатываю...", ACCENT)
            self._run_command(command)
            self._set_status("● Слушаю...", ACCENT2)
            time.sleep(0.2)

    # ---------- пересканировать приложения ----------
    def refresh_apps(self):
        def _scan():
            self.log("🔄 Сканирую приложения...")
            self.apps_cache = brat.scan_installed_apps()
            self.log(f"✅ Найдено: {len(self.apps_cache)} приложений")
        threading.Thread(target=_scan, daemon=True).start()

    # ---------- настройки ----------
    def _open_settings(self):
        win = ctk.CTkToplevel(self)
        win.title("Настройки")
        win.geometry("480x620")
        win.configure(fg_color=BG_DARK)
        win.grab_set()

        ctk.CTkLabel(win, text="Настройки", font=("Arial", 20, "bold"),
                     text_color=ACCENT).pack(pady=(18, 10))

        def row(label, var, placeholder=""):
            fr = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10)
            fr.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(fr, text=label, font=("Arial", 12), text_color=TEXT_SEC,
                         width=150, anchor="w").pack(side="left", padx=12, pady=10)
            ctk.CTkEntry(fr, textvariable=var, width=210, fg_color=BG_INPUT,
                         border_color=ACCENT, corner_radius=8,
                         placeholder_text=placeholder).pack(side="right", padx=12, pady=8)

        name_var = ctk.StringVar(value=self.settings.get("user_name", "Слава"))
        wake_var = ctk.StringVar(value=", ".join(self.settings.get("wake_words", ["брат"])))
        city_var = ctk.StringVar(value=self.settings.get("weather_city", "Харьков"))
        voice_var = ctk.StringVar(value=self.settings.get("voice", "pavel"))

        row("Имя пользователя", name_var)
        row("Слова активации", wake_var, "брат, эй, слушай")
        row("Город для погоды", city_var)
        row("Голос (pavel/irina)", voice_var, "pavel")

        # Скорость речи
        fr_rate = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10)
        fr_rate.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(fr_rate, text="Скорость речи", font=("Arial", 12), text_color=TEXT_SEC,
                     width=150, anchor="w").pack(side="left", padx=12)
        rate_var = ctk.IntVar(value=self.settings.get("speech_rate", 195))
        ctk.CTkSlider(fr_rate, from_=100, to=300, variable=rate_var, width=200,
                      button_color=ACCENT, progress_color=ACCENT).pack(side="right", padx=12, pady=12)

        # Живой голос Edge-TTS
        fr_edge = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10)
        fr_edge.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(fr_edge, text="Живой голос Edge-TTS", font=("Arial", 12), text_color=TEXT_SEC,
                     width=150, anchor="w").pack(side="left", padx=12, pady=10)
        edge_var = ctk.BooleanVar(value=(self.settings.get("tts_engine", "offline") == "edge"))
        ctk.CTkSwitch(fr_edge, text="", variable=edge_var, progress_color=ACCENT2).pack(
            side="right", padx=12, pady=10)

        # Требовать слово активации
        fr_wake = ctk.CTkFrame(win, fg_color=BG_CARD, corner_radius=10)
        fr_wake.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(fr_wake, text="Требовать кодовое слово", font=("Arial", 12), text_color=TEXT_SEC,
                     width=150, anchor="w").pack(side="left", padx=12, pady=10)
        reqwake_var = ctk.BooleanVar(value=self.settings.get("require_wake", True))
        ctk.CTkSwitch(fr_wake, text="", variable=reqwake_var, progress_color=ACCENT2).pack(
            side="right", padx=12, pady=10)

        def _save():
            self.settings["user_name"] = name_var.get().strip() or "Слава"
            words = [w.strip() for w in wake_var.get().split(",") if w.strip()]
            self.settings["wake_words"] = words or ["брат"]
            self.settings["weather_city"] = city_var.get().strip() or "Харьков"
            self.settings["voice"] = voice_var.get().strip().lower() or "pavel"
            self.settings["speech_rate"] = rate_var.get()
            self.settings["tts_engine"] = "edge" if edge_var.get() else "offline"
            self.settings["require_wake"] = bool(reqwake_var.get())

            brat.engine.setProperty('rate', self.settings["speech_rate"])
            brat.apply_voice(self.settings["voice"])
            brat.TTS_MODE = self.settings["tts_engine"]
            self.wake_words = self.settings["wake_words"]
            self.wake_label.configure(text=self._wake_hint())
            brat.save_settings(self.settings)
            self.log("✅ Настройки сохранены")
            win.destroy()

        ctk.CTkButton(win, text="💾 Сохранить", font=("Arial", 14, "bold"), fg_color=ACCENT,
                      hover_color="#5A52E0", height=44, corner_radius=12,
                      command=_save).pack(padx=20, pady=20, fill="x")


def main():
    run_protection()
    try:
        app = BratApp()
        app.mainloop()
    except Exception as e:
        # Если GUI недоступен (нет дисплея/customtkinter) — консольный режим
        print(f"GUI недоступен ({e}). Запускаю консольный режим brat.main()...")
        brat.main()


if __name__ == "__main__":
    main()
