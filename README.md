# Brat — Russian Voice Assistant for Windows

**Brat** (Russian: *Брат*, "Bro") is a lightweight, offline-friendly voice assistant for Windows.
It listens for a wake word, understands Russian voice commands, and launches apps, opens
websites, manages files, sets timers/alarms, and chats with simple small-talk — all from the
command line.

> The assistant speaks and understands **Russian**. The UI text and voice prompts are in Russian
> by design. This README is in English so the project is easy to browse on GitHub.

---

## Features

- 🎙️ **Wake-word activation** — say `брат` (configurable) followed by a command.
- 🚀 **App launcher** — opens apps by spoken name with fuzzy matching (`открой телеграм`,
  `запусти калькулятор`). Scans `Program Files`, Start Menu and user app folders, then caches them.
- 🌐 **Browser control** — detects Chrome, Firefox, Opera, Yandex, Edge, Brave; asks which one
  to open if several are installed.
- ⏱️ **Timers & alarms** — `таймер на 5 минут`, `будильник на 7 утра`, with audible beeps.
- 🗂️ **File operations** — move files (`перемести файл отчёт в загрузки`) and replace text inside
  text files (with an automatic `.bak` backup before writing).
- 💬 **Small talk** — greetings, time, date, and casual replies.
- ⚙️ **Settings menu** — change wake words, your name, speech rate/volume, and custom command
  aliases. Everything is saved to `settings.json`.
- 🔊 **Offline text-to-speech** via `pyttsx3` (Windows SAPI5 voices). Speech **recognition** uses
  Google's free API and needs an internet connection.

---

## Requirements

- **Windows** (uses `winsound`, `ms-settings:`, `explorer.exe`, etc.)
- **Python 3.8+**
- A working **microphone**
- **Internet connection** for speech recognition (Google Speech API)

Python packages (see `requirements.txt`):

```
SpeechRecognition
pyttsx3
fuzzywuzzy
PyAudio
pyautogui
python-Levenshtein   # optional, removes a fuzzywuzzy warning
```

---

## Installation

```bash
git clone https://github.com/sspoisk/brat-voice-assistant.git
cd brat-voice-assistant
pip install -r requirements.txt
```

> **Note on PyAudio:** if `pip install pyaudio` fails on Windows, install a prebuilt wheel:
> `pip install pipwin && pipwin install pyaudio`, or grab a wheel matching your Python version.

For a Russian text-to-speech voice, install a Russian SAPI5 voice in Windows
(*Settings → Time & Language → Speech*). The script auto-selects a Russian / "Irina" voice if one
is present; otherwise it falls back to the default system voice.

---

## Usage

```bash
python brat.py
```

On start:

- Press **Enter** to launch the assistant, or type **`s` + Enter** to open the settings menu first.
- Wait for *"Готов"* ("Ready"), then speak: **`брат, открой телеграм`**.

### Example commands (Russian)

| You say                              | What happens                          |
| ------------------------------------ | ------------------------------------- |
| `брат, открой телеграм`              | Launches Telegram                     |
| `брат, браузер`                      | Opens your browser (asks which one)   |
| `брат, таймер на 10 минут`           | Starts a 10-minute timer              |
| `брат, будильник на 7 утра`          | Sets an alarm for 7:00                |
| `брат, который час`                  | Tells the current time                |
| `брат, перемести файл отчёт в загрузки` | Moves a file to Downloads          |
| `брат, замени текст в файле заметки` | Replaces text in a file (with backup) |
| `брат, настройки`                    | Opens the settings menu               |
| `брат, выключение`                   | Shuts down the PC in 60s (`shutdown /a` cancels) |
| `брат, пока`                         | Exits the assistant                   |

### Custom aliases

In the settings menu (`5. Мои алиасы команд`) you can map any spoken phrase to an executable or
URL — e.g. say `ворк` to open `notepad`. Aliases have the highest matching priority.

---

## How it works

1. **Listen** — `_listen_once()` records from the mic and transcribes via Google Speech (`ru-RU`).
2. **Wake check** — the main loop fires only when the transcript contains a wake word.
3. **Route** — `process_command()` dispatches the command in order: settings → small talk →
   file ops → timers/alarms → app launch.
4. **Match** — `find_app()` resolves the target through custom aliases → built-in aliases →
   the scanned app cache, using `fuzzywuzzy` for fuzzy matching, and finally falls back to the
   Windows search box via `pyautogui`.
5. **Speak** — replies are queued and spoken on a background worker thread (`pyttsx3`), so the
   main loop never blocks.

Generated runtime files (`settings.json`, `apps_cache.json`, `*.bak`) are git-ignored.

---

## Configuration files

| File              | Purpose                                                  |
| ----------------- | -------------------------------------------------------- |
| `settings.json`   | Wake words, user name, speech rate/volume, custom aliases |
| `apps_cache.json` | Cached scan of installed apps (delete it to rescan)       |

---

## Notes & limitations

- Speech **recognition** requires internet (Google's free endpoint); TTS works offline.
- Designed and tested for **Russian** voice input on **Windows** only.
- The "replace text in file" command works on UTF-8 text files and always writes a `.bak` backup.

---

## License

[MIT](LICENSE) © sspoisk
