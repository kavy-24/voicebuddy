"""
VoiceBuddy — Full Python Frontend + Backend
-------------------------------------------
Frontend: Tkinter GUI
Backend: Voice recognition + command execution (runs in background thread)
Auto starts listening when app launches.
"""

import tkinter as tk
from tkinter.scrolledtext import ScrolledText
import threading
import queue
import speech_recognition as sr
import pyttsx3
import webbrowser
import os
import subprocess
from datetime import datetime
from pathlib import Path
import time
import sys

# ==========================================================
# --- BACKEND SETUP ---
# ==========================================================
NOTES_DIR = Path.home() / "VoiceBuddyNotes"
NOTES_DIR.mkdir(exist_ok=True)

LOCAL_MUSIC_DIR = Path.home() / "Music"

command_queue = queue.Queue()
stop_event = threading.Event()

engine = pyttsx3.init()

def speak(text: str):
    """Offline text-to-speech."""
    try:
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print("[TTS ERROR]", e)


def handle_command(cmd: str, gui_log):
    """Process a recognized or typed command."""
    cmd = cmd.strip().lower()
    if not cmd:
        return

    gui_log(f"🗣️ Command: {cmd}")

    # === STOP LISTENING COMMAND ===
    if cmd in ["stop", "stop listening", "exit listening"]:
        stop_event.set()
        speak("Stopping listener. VoiceBuddy is now silent.")
        gui_log("🛑 Listening stopped by user command.")
        return

    # open websites
    if cmd.startswith("open "):
        target = cmd.replace("open ", "").strip()
        shortcuts = {
            "youtube": "https://www.youtube.com",
            "google": "https://www.google.com",
            "github": "https://github.com",
            "gmail": "https://mail.google.com",
            "stackoverflow": "https://stackoverflow.com",
        }
        url = shortcuts.get(target, f"https://www.google.com/search?q={target}")
        webbrowser.open(url)
        speak(f"Opening {target}")
        gui_log(f"🌐 Opened {url}")
        return

    # search something
    if cmd.startswith("search "):
        query = cmd.replace("search ", "")
        url = f"https://www.google.com/search?q={query}"
        webbrowser.open(url)
        speak(f"Searching for {query}")
        gui_log(f"🔍 Search: {query}")
        return

    # time/date
    if "time" in cmd:
        now = datetime.now().strftime("%I:%M %p")
        speak(f"The time is {now}")
        gui_log(f"🕒 Time: {now}")
        return
    if "date" in cmd:
        today = datetime.now().strftime("%B %d, %Y")
        speak(f"Today is {today}")
        gui_log(f"📅 Date: {today}")
        return

    # write notes
    if cmd.startswith("note ") or cmd.startswith("write note "):
        content = cmd.replace("write note ", "").replace("note ", "")
        filename = NOTES_DIR / f"note_{datetime.now().strftime('%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        speak("Note saved.")
        gui_log(f"📝 Note saved: {filename.name}")
        return

    # play music
    if cmd.startswith("play "):
        name = cmd.replace("play ", "").strip()
        if not LOCAL_MUSIC_DIR.exists():
            gui_log("🎵 Music folder not found.")
            return
        matches = [p for p in LOCAL_MUSIC_DIR.glob("**/*") if p.is_file() and name.lower() in p.stem.lower()]
        if matches:
            target = matches[0]
            gui_log(f"🎧 Playing {target.name}")
            speak(f"Playing {target.stem}")
            try:
                if sys.platform.startswith("win"):
                    os.startfile(target)
                elif sys.platform.startswith("darwin"):
                    subprocess.Popen(["open", str(target)])
                else:
                    subprocess.Popen(["xdg-open", str(target)])
            except Exception as e:
                gui_log(f"Error playing music: {e}")
        else:
            speak("No matching music found.")
            gui_log("No music found.")
        return

    # run shell command
    if cmd.startswith("run "):
        command = cmd.replace("run ", "")
        gui_log(f"⚙️ Running: {command}")
        try:
            subprocess.Popen(command, shell=True)
            speak("Command executed.")
        except Exception as e:
            gui_log(f"Command error: {e}")
        return

    # fallback
    gui_log("🤖 I didn't understand that.")
    speak("Sorry, I didn't understand that command.")


def background_listener(gui_log):
    """Background thread to continuously listen for voice input."""
    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except Exception as e:
        gui_log(f"🎙️ Microphone not available: {e}")
        return

    with mic as source:
        gui_log("Calibrating mic for ambient noise...")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        gui_log("Listening in background...")
        speak("VoiceBuddy is now listening")

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

    stop_listen = recognizer.listen_in_background(mic, callback, phrase_time_limit=5)

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
        self.root.title("🎙️ VoiceBuddy — Full Python Edition")
        self.root.geometry("700x500")

        tk.Label(
            root,
            text="VoiceBuddy (Auto Voice Assistant)",
            font=("Segoe UI", 12, "bold"),
            fg="#00d0ff",
        ).pack(pady=8)

        self.log = ScrolledText(root, state="disabled", bg="#111", fg="#0f0", height=20, wrap="word")
        self.log.pack(fill="both", padx=10, pady=10, expand=True)

        # typed command box
        frame = tk.Frame(root)
        frame.pack(fill="x", padx=10, pady=5)
        self.entry = tk.Entry(frame)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self.on_enter)
        tk.Button(frame, text="Send", command=self.on_enter).pack(side="left", padx=6)

        # periodic queue check
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
# --- MAIN ENTRY POINT ---
# ==========================================================
def main():
    root = tk.Tk()
    app = VoiceBuddyApp(root)

    # start listener thread
    listener_thread = threading.Thread(target=background_listener, args=(app.gui_log,), daemon=True)
    listener_thread.start()

    def on_close():
        stop_event.set()
        root.after(300, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
