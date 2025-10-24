"""
VoiceBuddy — Advanced Full Python Frontend + Backend (Full Stack Pro)
Now supports opening websites reliably and improved VS Code launching.
"""

import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import threading
import queue
import speech_recognition as sr
import webbrowser
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
import time
import sys
import random
import re

# ==========================================================
# --- CONFIG / GLOBALS ---
# ==========================================================
NOTES_DIR = Path.home() / "VoiceBuddyNotes"
NOTES_DIR.mkdir(exist_ok=True)

LOCAL_MUSIC_DIR = Path.home() / "Music"
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")

command_queue = queue.Queue()
stop_event = threading.Event()
reminder_lock = threading.Lock()
scheduled_reminders = []

tts_queue = queue.Queue()
tts_stop_event = threading.Event()

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "Why did the function return early? Because it had commitment issues.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why do Java developers wear glasses? Because they don't C sharp.",
]

# ==========================================================
# --- TTS WORKER ---
# ==========================================================
def tts_worker():
    try:
        import pyttsx3
    except Exception as e:
        print("[TTS] pyttsx3 import failed:", e)
        while not tts_stop_event.is_set():
            try:
                item = tts_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is None:
                break
        return

    engine = pyttsx3.init()
    while not tts_stop_event.is_set():
        try:
            text = tts_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if text is None:
            break
        try:
            engine.say(text)
            engine.runAndWait()
        except Exception as e:
            print("[TTS ERROR]", e)
    try:
        engine.stop()
    except Exception:
        pass

def start_tts_thread():
    t = threading.Thread(target=tts_worker, daemon=True)
    t.start()
    return t

def speak(text: str):
    if not text:
        return
    try:
        tts_queue.put(text)
    except Exception as e:
        print("[TTS QUEUE ERROR]", e)

# ==========================================================
# --- NOTES (WRITE / LIST / OPEN) ---
# ==========================================================
def _sanitize_filename(s: str) -> str:
    s = re.sub(r'[\\/:"*?<>|]+', "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]

def write_note(content: str, title: str | None, gui_log):
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if title:
            safe_title = _sanitize_filename(title)
        else:
            preview = content.strip().splitlines()[0][:30] if content else "note"
            safe_title = _sanitize_filename(preview) or "note"
        filename = f"{safe_title} - {timestamp}.txt"
        file_path = NOTES_DIR / filename
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        gui_log(f"📝 Note saved: {file_path}")
        speak(f"Saved note {safe_title}. Opening in Notepad.")
        try:
            subprocess.Popen(["notepad.exe", str(file_path)])
        except Exception:
            try:
                os.startfile(str(file_path))
            except Exception as e:
                gui_log(f"❌ Could not open note automatically: {e}")
                speak("Saved the note but couldn't open it automatically.")
    except Exception as e:
        gui_log(f"❌ Error saving note: {e}")
        speak("There was an error saving the note.")

def list_notes(gui_log):
    files = sorted(NOTES_DIR.glob("*.txt"), reverse=True)
    files = list(files)
    if not files:
        gui_log("📂 No notes found in VoiceBuddyNotes.")
        speak("You have no notes.")
        return
    gui_log("📂 Notes:")
    for f in files:
        gui_log(f" - {f.name}")
    speak(f"You have {len(files)} note(s).")

def open_note_by_name(query: str, gui_log):
    query = query.strip().lower()
    matches = [p for p in NOTES_DIR.glob("*.txt") if query in p.name.lower()]
    if not matches:
        gui_log(f"🔎 No note matching '{query}' was found.")
        speak("I couldn't find a matching note.")
        return
    target = matches[0]
    gui_log(f"📂 Opening note: {target.name}")
    speak(f"Opening note {target.name}")
    try:
        subprocess.Popen(["notepad.exe", str(target)])
    except Exception:
        try:
            os.startfile(str(target))
        except Exception as e:
            gui_log(f"❌ Could not open note: {e}")
            speak("I couldn't open the note.")

# ==========================================================
# --- REMINDERS ---
# ==========================================================
def _reminder_action(message: str, gui_log):
    speak(f"Reminder: {message}")
    gui_log(f"⏰ Reminder triggered: {message}")

def schedule_reminder_at(dt: datetime, message: str, gui_log):
    now = datetime.now()
    delay = (dt - now).total_seconds()
    if delay <= 0:
        gui_log("⚠️ Reminder time is in the past.")
        speak("I can't set a reminder in the past.")
        return None
    timer = threading.Timer(delay, _reminder_action, args=(message, gui_log))
    timer.daemon = True
    timer.start()
    with reminder_lock:
        scheduled_reminders.append({"time": dt, "message": message, "timer": timer})
    gui_log(f"🗓️ Reminder scheduled at {dt.strftime('%Y-%m-%d %H:%M')}: {message}")
    speak(f"Reminder set for {dt.strftime('%I:%M %p on %B %d')}.")
    return timer

def schedule_reminder_in(minutes: int, message: str, gui_log):
    dt = datetime.now() + timedelta(minutes=minutes)
    return schedule_reminder_at(dt, message, gui_log)

def list_reminders(gui_log):
    with reminder_lock:
        if not scheduled_reminders:
            gui_log("🔔 No reminders scheduled.")
            speak("You have no reminders.")
            return
        gui_log("🔔 Scheduled reminders:")
        for r in scheduled_reminders:
            gui_log(f" - {r['time'].strftime('%Y-%m-%d %H:%M')} : {r['message']}")
        speak(f"You have {len(scheduled_reminders)} reminder(s).")

def cancel_all_reminders(gui_log):
    with reminder_lock:
        for r in scheduled_reminders:
            try:
                r["timer"].cancel()
            except Exception:
                pass
        scheduled_reminders.clear()
    gui_log("🗑️ All reminders canceled.")
    speak("All reminders have been canceled.")

# ==========================================================
# --- UTIL: URL / APP START HELPERS ---
# ==========================================================
def looks_like_url(text: str) -> bool:
    text = text.strip().lower()
    if text.startswith("http://") or text.startswith("https://"):
        return True
    # contains a dot and no spaces -> likely a domain
    if "." in text and " " not in text:
        return True
    return False

def normalize_website(target: str) -> str:
    t = target.strip()
    if t.startswith("http://") or t.startswith("https://"):
        return t
    # if user said 'google' -> try www.google.com
    if "." not in t:
        return "https://www." + t + ".com"
    # if contains dot but no scheme
    return "https://" + t if not t.startswith("http") else t

def try_open_website(target: str, gui_log) -> bool:
    try:
        url = normalize_website(target)
        gui_log(f"🌐 Opening website: {url}")
        webbrowser.open(url, new=2)  # open in new tab if possible
        speak(f"Opening {target}")
        return True
    except Exception as e:
        gui_log(f"❌ Failed to open website {target}: {e}")
        return False

def try_launch_executable(path_or_cmd: str, gui_log) -> bool:
    """Try to launch an exe/command. Return True on success, False otherwise."""
    try:
        # if it's an absolute path to file, use Popen with list
        if os.path.isabs(path_or_cmd) and os.path.exists(path_or_cmd):
            subprocess.Popen([path_or_cmd])
            return True
        # try running as command (works if on PATH)
        subprocess.Popen([path_or_cmd], shell=False)
        return True
    except Exception as e:
        gui_log(f"attempt to run '{path_or_cmd}' failed: {e}")
    # try shell start fallback
    try:
        subprocess.Popen(f'start "" "{path_or_cmd}"', shell=True)
        return True
    except Exception as e:
        gui_log(f"shell start fallback for '{path_or_cmd}' failed: {e}")
    return False

# ==========================================================
# --- UNIVERSAL APP LAUNCHER (FIXED FOR WEBSITES & VSCODE) ---
# ==========================================================
def open_any_app(target: str, gui_log):
    target_raw = target.strip()
    target = target_raw.lower()
    gui_log(f"⚡ Trying to open: {target_raw}")

    # Known app name -> command or exe path
    known_apps = {
        "notepad": "notepad.exe",
        "paint": "mspaint.exe",
        "file explorer": "explorer.exe",
        "file explorer": "explorer.exe",
        "explorer": "explorer.exe",
        "calculator": "calc.exe",
        "word": "winword.exe",
        "excel": "excel.exe",
        "powerpoint": "powerpnt.exe",
        "onenote": "onenote.exe",
        "outlook": "outlook.exe",
        "edge": "msedge.exe",
        "chrome": "chrome.exe",
        "control panel": "control.exe",
        "cmd": "cmd.exe",
        "terminal": "wt.exe",
        "store": "ms-windows-store:",
        "settings": "ms-settings:",
        "camera": "microsoft.windows.camera:",
        "photos": "ms-photos:",
        # user-friendly keys for VS Code
        "vs code": "vscode",
        "visual studio code": "vscode",
        "visualstudio code": "vscode",
    }

    # If target looks like URL / domain -> open website
    if looks_like_url(target_raw):
        success = try_open_website(target_raw, gui_log)
        if not success:
            gui_log(f"❌ Could not open website: {target_raw}")
            speak(f"Sorry, I couldn't open the website {target_raw}.")
        return

    # If explicit "open website <something>" or "open site <something>"
    if target.startswith("website ") or target.startswith("site "):
        # strip keyword
        stripped = re.sub(r'^(website|site)\s+', '', target_raw, flags=re.IGNORECASE)
        if stripped:
            if try_open_website(stripped, gui_log):
                return
        gui_log("❌ Could not parse website target.")
        speak("Sorry, I couldn't parse that website.")
        return

    # If we have a known mapping
    if target in known_apps:
        app = known_apps[target]
        # Special-case vscode handling
        if app == "vscode":
            # 1) try 'code' on PATH
            gui_log("🔎 Trying VS Code via 'code' command.")
            if try_launch_executable("code", gui_log):
                speak("Opening Visual Studio Code.")
                return
            if try_launch_executable("code.exe", gui_log):
                speak("Opening Visual Studio Code.")
                return
            # 2) try common install locations
            local_appdata = os.environ.get("LOCALAPPDATA", r"C:\Users\Default\AppData\Local")
            candidates = [
                os.path.join(local_appdata, "Programs", "Microsoft VS Code", "Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
                r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
            ]
            for c in candidates:
                gui_log(f"🔎 Trying VS Code path: {c}")
                if os.path.exists(c):
                    try:
                        subprocess.Popen([c])
                        speak("Opening Visual Studio Code.")
                        return
                    except Exception as e:
                        gui_log(f"Failed to launch {c}: {e}")
            # 3) fallback: try os.startfile with 'code' (may work)
            try:
                os.startfile("code")
                speak("Opening Visual Studio Code.")
                return
            except Exception as e:
                gui_log(f"VS Code startfile fallback failed: {e}")
            gui_log("❌ Could not open Visual Studio Code.")
            speak("Sorry, I couldn't open Visual Studio Code.")
            return
        # For other mapped apps, use os.startfile (works for exe names and URI schemes)
        try:
            os.startfile(app)
            speak(f"Opening {target_raw}")
            return
        except Exception as e:
            gui_log(f"startfile for {app} failed: {e}")
            # try launching the literal app string
            if try_launch_executable(app, gui_log):
                speak(f"Opening {target_raw}")
                return
            gui_log(f"❌ Could not open mapped app {target_raw}.")
            speak(f"Sorry, I couldn't open {target_raw}.")
            return

    # Not a known mapping and not a URL: try several fallbacks
    # 1) Try treating it as a website by adding www and .com
    gui_log("🔁 Not a known app — trying website fallback (www.<target>.com)")
    website_try = "www." + re.sub(r'\s+', '', target) + ".com"
    if try_open_website(website_try, gui_log):
        return

    # 2) Try as an executable/command
    gui_log(f"🔁 Trying to run as command/exe: {target_raw}")
    if try_launch_executable(target_raw, gui_log):
        speak(f"Opening {target_raw}")
        return

    # 3) Try shell start fallback
    try:
        subprocess.Popen(f'start "" "{target_raw}"', shell=True)
        speak(f"Opening {target_raw}")
        return
    except Exception as e:
        gui_log(f"shell fallback failed for {target_raw}: {e}")

    gui_log(f"❌ Could not open: {target_raw}")
    speak(f"Sorry, I couldn't open {target_raw}.")

# ==========================================================
# --- COMMAND HANDLER ---
# ==========================================================
def handle_single_command(cmd: str, gui_log):
    cmd = cmd.strip()
    if not cmd:
        return
    lower = cmd.lower()
    gui_log(f"🗣️ Command: {cmd}")

    # --- Notes: write / list / open ---
    if lower.startswith("write note"):
        rest = cmd[len("write note"):].strip()
        if ":" in rest:
            parts = rest.split(":", 1)
            title = parts[0].strip()
            content = parts[1].strip()
        else:
            title = None
            content = rest
        if not content:
            gui_log("⚠️ No note content provided.")
            speak("You didn't provide any content for the note.")
            return
        write_note(content, title, gui_log)
        return

    if lower.startswith("save note"):
        rest = cmd[len("save note"):].strip()
        if ":" in rest:
            parts = rest.split(":", 1)
            title = parts[0].strip()
            content = parts[1].strip()
        else:
            title = None
            content = rest
        if not content:
            gui_log("⚠️ No note content provided.")
            speak("You didn't provide any content for the note.")
            return
        write_note(content, title, gui_log)
        return

    if lower.startswith("list notes"):
        list_notes(gui_log)
        return

    if lower.startswith("open note"):
        query = cmd[len("open note"):].strip()
        if not query:
            gui_log("⚠️ No note name provided to open.")
            speak("Please tell me the name of the note to open.")
            return
        open_note_by_name(query, gui_log)
        return

    # --- Open any app / website ---
    if lower.startswith("open "):
        target = cmd[len("open "):].strip()
        open_any_app(target, gui_log)
        return

    # other built-ins
    if "joke" in lower:
        joke = random.choice(JOKES)
        gui_log(f"😂 Joke: {joke}")
        speak(joke)
        return

    if lower == "time":
        now = datetime.now().strftime("%I:%M %p")
        speak(f"The time is {now}.")
        gui_log(f"🕒 Time: {now}")
        return

    if lower == "date":
        today = datetime.now().strftime("%B %d, %Y")
        speak(f"Today's date is {today}.")
        gui_log(f"📅 Date: {today}")
        return

    m = re.match(r"remind me in (\d+)\s*minutes? to (.+)", lower)
    if m:
        minutes = int(m.group(1))
        message = m.group(2).strip()
        schedule_reminder_in(minutes, message, gui_log)
        return

    m2 = re.match(r"remind me at (\d{1,2}:\d{2}) to (.+)", lower)
    if m2:
        time_str = m2.group(1)
        message = m2.group(2).strip()
        try:
            t = datetime.strptime(time_str, "%H:%M").time()
        except Exception:
            try:
                t = datetime.strptime(time_str, "%I:%M").time()
            except Exception:
                gui_log("⚠️ Could not parse reminder time.")
                speak("I couldn't parse the time you gave me.")
                return
        now = datetime.now()
        dt = datetime.combine(now.date(), t)
        if dt <= now:
            dt = dt + timedelta(days=1)
        schedule_reminder_at(dt, message, gui_log)
        return

    if lower == "list reminders":
        list_reminders(gui_log)
        return

    if lower == "cancel all reminders":
        cancel_all_reminders(gui_log)
        return

    gui_log("🤖 I didn't understand that.")
    speak("Sorry, I didn't understand that command.")

def handle_command(cmd: str, gui_log):
    parts = re.split(r"\b(?:and|then)\b", cmd, flags=re.IGNORECASE)
    for part in parts:
        if part.strip():
            handle_single_command(part.strip(), gui_log)

# ==========================================================
# --- BACKGROUND LISTENER ---
# ==========================================================
def background_listener(gui_log):
    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except Exception as e:
        gui_log(f"🎙️ Microphone not available: {e}")
        speak("Microphone not available.")
        return

    with mic as source:
        gui_log("Calibrating mic for ambient noise...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        gui_log("Listening in background...")
        speak("VoiceBuddy is now listening.")

    def callback(recognizer, audio):
        if stop_event.is_set():
            return
        try:
            text = recognizer.recognize_google(audio)
            gui_log(f"🎧 Heard: {text}")
            command_queue.put(text)
        except sr.UnknownValueError:
            gui_log("Could not understand audio.")
        except sr.RequestError as e:
            gui_log(f"Recognition service error: {e}")
            speak("Speech recognition service error.")

    stop_listen = recognizer.listen_in_background(mic, callback, phrase_time_limit=6)

    while not stop_event.is_set():
        time.sleep(0.5)
    stop_listen(wait_for_stop=False)
    gui_log("Listener stopped.")

# ==========================================================
# --- FRONTEND GUI ---
# ==========================================================
class VoiceBuddyApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🎙️ VoiceBuddy — Pro (Full Stack)")
        self.root.geometry("800x560")

        tk.Label(
            root,
            text="VoiceBuddy (Pro — Universal Assistant)",
            font=("Segoe UI", 13, "bold"),
            fg="#00d0ff",
        ).pack(pady=8)

        self.log = ScrolledText(root, state="disabled", bg="#111", fg="#0f0", height=22, wrap="word")
        self.log.pack(fill="both", padx=10, pady=10, expand=True)

        frame = tk.Frame(root)
        frame.pack(fill="x", padx=10, pady=5)
        self.entry = tk.Entry(frame)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        tk.Button(frame, text="Send", command=self.on_enter).pack(side="left", padx=6)

        self.root.after(300, self.process_queue)

    def gui_log(self, msg: str):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def on_enter(self, event=None):
        cmd = self.entry.get().strip()
        self.entry.delete(0, "end")
        if cmd:
            handle_command(cmd, self.gui_log)

    def process_queue(self):
        try:
            while True:
                cmd = command_queue.get_nowait()
                handle_command(cmd, self.gui_log)
        except queue.Empty:
            pass
        self.root.after(300, self.process_queue)

# ==========================================================
# --- MAIN ---
# ==========================================================
def main():
    tts_thread = start_tts_thread()

    root = tk.Tk()
    app = VoiceBuddyApp(root)

    listener_thread = threading.Thread(target=background_listener, args=(app.gui_log,), daemon=True)
    listener_thread.start()

    def on_close():
        stop_event.set()
        cancel_all_reminders(app.gui_log)
        tts_stop_event.set()
        try:
            tts_queue.put(None)
        except Exception:
            pass
        root.after(300, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()

if __name__ == "__main__":
    main()

