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
- 🔉 **System volume control** — `громче`, `тише`, `громкость на 50 процентов`, `выключи звук`.
  Precise level via `pycaw`, with a media-key fallback.
- 📸 **Screenshots** — `сделай скриншот` captures the screen, saves a timestamped PNG to
  `Pictures\Screenshots`, and opens Explorer with the new file selected.
- 🎵 **Media control** — `пауза`, `плей`, `следующий трек`, `предыдущий трек` via system media
  keys (works with Spotify, browser players, etc.).
- 🌤️ **Weather** — `погода` / `погода в Москве` reads the current weather aloud (via free
  `wttr.in`, no API key). Default city is configurable in settings.
- 📋 **Clipboard** — `запиши в буфер` dictates text into the clipboard; `вставь` pastes it
  (Ctrl+V) into the active window.
- 🔒 **Lock & sleep** — `заблокируй` locks the screen, `спящий режим` puts the PC to sleep.
- ⏱️ **Timers & alarms** — `таймер на 5 минут`, `будильник на 7 утра`, with audible beeps.
- 🗂️ **File operations** — move files (`перемести файл отчёт в загрузки`) and replace text inside
  text files (with an automatic `.bak` backup before writing).
- 💬 **Small talk** — greetings, time, date, and casual replies.
- ⚙️ **Settings menu** — change wake words, your name, speech rate/volume, and custom command
  aliases. Everything is saved to `settings.json`.
- 🔊 **Offline text-to-speech** via `pyttsx3` (Windows SAPI5 voices). Speech **recognition** uses
  Google's free API and needs an internet connection.
- 🗣️ **Optional live neural voice** via **Edge-TTS** (free, online) — a much more natural Russian
  male voice (`ru-RU-DmitryNeural`). Toggle by voice (`включи живой голос` / `обычный голос`) or in
  settings; falls back to the offline voice automatically when offline.

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
(*Settings → Time & Language → Speech*). The script prefers a **male Russian voice (Pavel)**, then
any Russian voice (Irina), then the default system voice. You can switch the voice in the settings
menu (`7. Голос`).

### Male voice (Pavel)

Windows ships the male Russian voice **"Microsoft Pavel"** as a *OneCore* voice, which `pyttsx3`
(SAPI5) does not see by default — so only the female *Irina* shows up. Expose Pavel to SAPI5 with
one command in an **elevated** PowerShell/Command Prompt:

```cmd
reg copy "HKLM\SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens\MSTTS_V110_ruRU_PavelM" "HKLM\SOFTWARE\Microsoft\Speech\Voices\Tokens\MSTTS_V110_ruRU_PavelM" /s /f
```

This only *copies* an existing voice token (additive, reversible — delete the destination key to
undo). After that the assistant speaks with the cheerful male voice automatically. If Pavel is not
installed at all, add the Russian language speech pack first.

### Live neural voice (Edge-TTS, optional)

For a far more natural voice, the assistant can use **Microsoft Edge's online neural TTS** (free,
no API key) via the `edge-tts` package. Default voice: `ru-RU-DmitryNeural` (lively male).

- Enable it by voice: say **`брат, включи живой голос`** (and `брат, обычный голос` to switch back),
  or set it in the settings menu (`8. Живой голос Edge`).
- It requires an internet connection. If Edge-TTS fails (offline), the assistant automatically
  falls back to the offline `pyttsx3`/Pavel voice.
- Audio is synthesized to a temporary MP3 and played through the system MCI player (no extra
  binaries needed).

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
| `брат, закрой телеграм`              | Closes Telegram (via `taskkill`)      |
| `брат, заверши хром`                 | Closes the browser process            |
| `брат, браузер`                      | Opens your browser (asks which one)   |
| `брат, громче` / `брат, тише`        | Volume up / down by 10%               |
| `брат, громкость на 50 процентов`    | Sets system volume to 50%             |
| `брат, выключи звук` / `включи звук`  | Mute / unmute                         |
| `брат, сделай скриншот`              | Saves a screenshot to Pictures\Screenshots |
| `брат, пауза` / `брат, плей`         | Pause / resume playback               |
| `брат, следующий трек`               | Next track                            |
| `брат, погода` / `погода в киеве`    | Reads current weather aloud           |
| `брат, запиши в буфер`               | Dictate text → clipboard              |
| `брат, заблокируй`                   | Locks the screen                      |
| `брат, спящий режим`                 | Puts the PC to sleep                  |
| `брат, открой ютуб`                  | Opens YouTube                         |
| `брат, найди на ютубе котики`        | Opens a YouTube search for "котики"   |
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
