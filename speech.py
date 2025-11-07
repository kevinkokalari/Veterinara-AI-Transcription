import tkinter as tk
from tkinter import scrolledtext, messagebox
import queue, json, configparser
import speech_recognition as sr
from datetime import datetime
from openai import OpenAI

cfg = configparser.ConfigParser() 
cfg.read('settings.cfg')

OPENAI_API_KEY = cfg['OPENAI']['API_KEY']

client = OpenAI(api_key=OPENAI_API_KEY)


class SpeechTranscriber:
    """
    Manages background speech transcription using SpeechRecognition.
    - Starts listening on init (if available).
    - Uses recognizer.listen_in_background(...) which returns a stop function.
    - Sends recognized text chunks to a thread-safe Queue for the GUI to consume.
    """
    def __init__(self, output_queue: queue.Queue, status_obj, debug_obj):
        self.output_queue = output_queue
        self.status_var = status_obj
        self.debug_var = debug_obj
        self.recognizer = None
        self.microphone = None
        self.stopper = None
        self._callback = None
        self.active = False
        self._muted = False

        if sr is None:
            self.output_queue.put("[Error] speech_recognition is not installed. Run: pip install SpeechRecognition")
            return

        try:
            self.recognizer = sr.Recognizer()
            self.recognizer.dynamic_energy_threshold = True
            self.microphone = sr.Microphone(sample_rate=32000)
            self._device_index = getattr(self.microphone, "device_index", None) 
            
        except Exception as e:
            self.status_var.set(f"[Audio init error] {e}")
            return

        # Calibrate and start background listening
        try:
            with self.microphone as source:
                self.status_var.set("Calibrating microphone… please be quiet for a moment.")
                self.recognizer.adjust_for_ambient_noise(source, duration=2.0)
                self.debug_var.set(f"Calibration complete. Energy threshold: {self.recognizer.energy_threshold:.0f}")
        except Exception as e:
            self.status_var.set(f"[Calibration error] {e}")
            return

        def callback(recognizer, audio):
            if getattr(self, "_muted", False):
                return
            try:
                # Google Web Speech (needs internet). Swap to recognizer.recognize_sphinx(audio) for offline CMU Sphinx if installed.
                #text = recognizer.recognize_google(audio, language='en-US')  # You can set language='sv-SE' or others if you want.
                text = recognizer.recognize_faster_whisper(audio, model="tiny", language="sv")
                # Example: text = recognizer.recognize_google(audio, language='en-US')
                self.output_queue.put(text)
            except sr.UnknownValueError:
                # Silence/noise—ignore quietly
                pass
            except sr.RequestError as e:
                self.status_var.set(f"[Recognizer error] {e}")

        self._callback = callback
        try:
            self.stopper = self.recognizer.listen_in_background(self.microphone, callback)
            self.active = True
            self.status_var.set("Listening… (press 'Stop Listening' to stop)")
        except Exception as e:
            self.status_var.set(f"[Listen error] {e}")

    def changeStatus(self):
        self._muted = not getattr(self, "_muted", False)
        if self._muted:
            self.status_var.set("Stoped Listening.")
        else:
            self.status_var.set("Listening… (press 'Stop Listening' to stop)")


# --- Your formatter stub (replace this with your real logic later) ---
def transform_text(prompt: str) -> str:
    """
    Placeholder for your future formatting/transformation.
    For now: trim whitespace, collapse multiple spaces, add a simple header.
    Replace this function when you give me the real target format.
    """

    SYST_PROMPT = loadPrompts("./sysprompt.txt")
    resp = client.responses.create(
            model="gpt-5", 
            reasoning={"effort": "low", "summary": "auto"},
            instructions=SYST_PROMPT,
            input=prompt
    )
    
    resp = json.loads(resp.output_text)
    return resp


def loadPrompts(path: str) -> str:
        with open(path, "r", encoding="UTF-8") as f:
            sysPrompt = f.read()
            f.close()
        return sysPrompt


# --- GUI App ---
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Veterinära Transcriber")
        self.geometry("900x400")
        self.showFormated = False

        self.status_var = tk.StringVar()
        self.debug_var = tk.StringVar()

        # Queues for thread-safe message passing
        self.transcript_queue = queue.Queue()

        # Layout
        self._build_widgets()

        # Speech
        self.transcriber = SpeechTranscriber(self.transcript_queue, self.status_var, self.debug_var)

        # Poll the queue to update the transcript box
        self.after(100, self._drain_transcript_queue)

    def _build_widgets(self):
        # Labels
        lbl1 = tk.Label(self, text="Live Transcription")
        lbl1.pack(anchor="w", padx=10, pady=(10, 2))

        # First textbox (transcribed text)
        self.txt_transcript = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=12)
        self.txt_transcript.pack(fill="both", expand=False, padx=10, pady=(0, 5))

        lbl2 = tk.Label(self, text="Key Words")
        lbl2.pack(anchor="w", padx=10, pady=(10, 2))

        self.txt_keywords = scrolledtext.ScrolledText(self, wrap=tk.WORD, height=3)
        self.txt_keywords.pack(fill="both", expand=False, padx=10, pady=(0, 10))
        
        debug = tk.Label(self, textvariable=self.debug_var, anchor="w")
        debug.pack(fill="x", padx=10, pady=(0, 8))
        # Status bar
        status = tk.Label(self, textvariable=self.status_var, anchor="w")
        status.pack(fill="x", padx=10, pady=(0, 8))

        # Buttons frame
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", padx=10)

        self.btn_stop = tk.Button(btn_frame, text="Stop Listening", command=self._changeListenStatus)
        self.btn_stop.pack(side="left", padx=(0, 10))

        self.btn_format = tk.Button(btn_frame, text="Format", command=self._format_text)
        self.btn_format.pack(side="left")

        # NEW: formatting panel is hidden initially
        self.format_panel = None   # created on first Format click
        self.fmt_boxes = []        # will hold 5 ScrolledText widgets


    def _changeListenStatus(self):
        if not hasattr(self, "transcriber") or not self.transcriber:
            return

        self.transcriber.changeStatus()

        if self.transcriber._muted:
            self.btn_stop.config(text="Resume Listening")
        else:
            self.btn_stop.config(text="Stop Listening")


    def _ensure_format_panel_vertical(self):
        if getattr(self, "format_panel", None) is not None:
            if not self.format_panel.winfo_ismapped():
                self.format_panel.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            return

        # Create a panel and stack 5 labeled ScrolledText boxes vertically
        self.format_panel = tk.Frame(self)
        self.format_panel.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.fmt_boxes = []

        # Single-column grid so each row expands evenly

        labels = ["Date and Author", "Journal Entry"]
        heights = [1,30]



        for r in range(len(labels)):
            row_frame = tk.Frame(self.format_panel)
            row_frame.grid(row=r, column=0, sticky="nsew", padx=6, pady=6)

            lbl = tk.Label(row_frame, text=labels[r])
            lbl.pack(anchor="w")

       

            box = scrolledtext.ScrolledText(row_frame, wrap=tk.WORD, height=heights[r])
            box.pack(fill="both", expand=True)

            self.fmt_boxes.append(box)

        # Make the grid responsive
        for r in range(len(labels)):
            self.format_panel.rowconfigure(r, weight=1)
        self.format_panel.columnconfigure(0, weight=1)

        # Expand the window when panel appears (taller for 5 boxes)
        try:
            if not hasattr(self, "_original_geometry"):
                self._original_geometry = self.geometry()
            self.geometry("900x850")
        except Exception:
            pass


    def _format_text(self):
        original = self.txt_transcript.get("1.0", tk.END)
        keywords = self.txt_keywords.get("1.0", tk.END)
        self._ensure_format_panel_vertical()  # create/show panel on first use
        try:
            # Fill the first box with transformed text; others stay empty for edits/variants
            firstRow = str(datetime.now().strftime("%Y-%m-%d %H:%M")) + " | KOKALARI"
            to_transform = original + "\n\nKeywords:\n" + keywords
            result = transform_text(to_transform)

            out = ""
            out += "///////////////////// REASON FOR VISIT ///////////////////////////////////\n"
            out += result["Reason"] + "\n\n"
            out += "///////////////////// CONDITIONS AND SYMPTOMS ////////////////////////////\n"
            out += result["Condition"] + "\n\n"
            out += "///////////////////// EXAMINATION AND DIAGNOSIS //////////////////////////\n"
            out += result["Examination"] + "\n\n"
            out += "///////////////////// MEDICATION /////////////////////////////////////////\n"
            out += result["Medication"] + "\n\n"
            out += "///////////////////// TREATMENT SCHEDULE AND PROGNOSIS ///////////////////\n"
            out += result["Prognosis"] + "\n\n"



            self.fmt_boxes[0].delete("1.0", tk.END)
            self.fmt_boxes[0].insert(tk.END, firstRow)
            self.fmt_boxes[1].delete("1.0", tk.END)
            self.fmt_boxes[1].insert(tk.END, out)


            self.status_var.set("Text formatted.")
        except Exception as e:
            messagebox.showerror("Formatting Error", str(e))


    def _drain_transcript_queue(self):
        try:
            while True:
                chunk = self.transcript_queue.get_nowait()
                # If the chunk looks like a status line, prefix; otherwise append as text
                if chunk.startswith("[") and "]" in chunk.splitlines()[0]:
                    self._append_status(chunk)
                else:
                    self._append_transcript(chunk)
        except queue.Empty:
            pass
        # Re-schedule polling
        self.after(100, self._drain_transcript_queue)

    def _append_transcript(self, text):
        # Append recognized text + space
        self.txt_transcript.insert(tk.END, (text.strip() + " "))
        self.txt_transcript.see(tk.END)
        #self.status_var.set("Transcribing…")

    def _append_status(self, line):
        # Also show status lines in the transcript box to keep everything in one place
        self.txt_transcript.insert(tk.END, f"\n{line}\n")
        self.txt_transcript.see(tk.END)
        self.status_var.set(line.strip("[]"))

    def on_closing(self):
        try:
            if hasattr(self, "transcriber") and self.transcriber:
                self.transcriber.changeStatus()
        finally:
            self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()