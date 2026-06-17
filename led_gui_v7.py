# =============================================================================
# led_gui_v7.py  —  HAL LED + Temperature control GUI
#
# Controls Arduino LED and displays DS18B20 temperature via Modbus TCP.
#
# INSTALL DEPENDENCIES:
#   uv pip install pymodbus
#
# USAGE:
#   uv run led_gui_v7.py
# =============================================================================

import tkinter as tk
from tkinter import font as tkfont
import threading
import time
import logging
from pymodbus.client import ModbusTcpClient

# =============================================================================
# CONFIG
# =============================================================================

ARDUINO_IP     = "192.168.1.100"
ARDUINO_PORT   = 502

REG_LED_ENABLE  = 0
REG_BLINK_RATE  = 1
REG_LED_STATE   = 0
REG_HEARTBEAT   = 1
REG_TEMPERATURE = 2
REG_TEMP_STATUS = 3

POLL_INTERVAL  = 0.5

# =============================================================================
# Colors
# =============================================================================

BG         = "#0D0D0D"
PANEL      = "#141414"
BORDER     = "#2A2A2A"
TEXT       = "#E8E6DF"
TEXT_DIM   = "#555550"
ACCENT     = "#E8A020"
ACCENT_DIM = "#7A5010"
GREEN      = "#1D9E75"
RED        = "#C0392B"
BLUE       = "#2980B9"

logging.basicConfig(level=logging.WARNING)

class HALApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HAL — LED + Temperature")
        self.configure(bg=BG)
        self.resizable(False, False)

        self.client     = None
        self.connected  = False
        self.led_state  = 0
        self.heartbeat  = 0
        self.temp_c     = None
        self.temp_fault = False
        self.blink_rate = tk.DoubleVar(value=1.0)
        self.running    = True
        self.lock       = threading.Lock()

        self._build_ui()
        self._connect()

        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # -------------------------------------------------------------------------
    def _build_ui(self):
        mono   = tkfont.Font(family="Courier New", size=11)
        mono_s = tkfont.Font(family="Courier New", size=9)
        label  = tkfont.Font(family="Courier New", size=9, weight="bold")
        big    = tkfont.Font(family="Courier New", size=28, weight="bold")
        temp_f = tkfont.Font(family="Courier New", size=32, weight="bold")

        # Header
        hdr = tk.Frame(self, bg=BG, pady=16, padx=24)
        hdr.pack(fill="x")
        tk.Label(hdr, text="HAL",
                 font=tkfont.Font(family="Courier New", size=22, weight="bold"),
                 bg=BG, fg=ACCENT).pack(side="left")
        tk.Label(hdr, text=" / LED + TEMPERATURE",
                 font=tkfont.Font(family="Courier New", size=14),
                 bg=BG, fg=TEXT_DIM).pack(side="left", pady=4)
        self.conn_dot = tk.Label(hdr, text="● OFFLINE", font=label, bg=BG, fg=RED)
        self.conn_dot.pack(side="right")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # Main content
        content = tk.Frame(self, bg=BG, padx=24, pady=20)
        content.pack(fill="both")

        # ---- Column 1: LED status ----
        col1 = tk.Frame(content, bg=PANEL, padx=20, pady=20,
                        highlightbackground=BORDER, highlightthickness=1)
        col1.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        tk.Label(col1, text="LED STATUS", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        tk.Frame(col1, bg=BORDER, height=1).pack(fill="x", pady=(4, 16))

        tk.Label(col1, text="LED", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        self.led_canvas = tk.Canvas(col1, width=48, height=48, bg=PANEL,
                                    highlightthickness=0)
        self.led_canvas.pack(anchor="w", pady=(6, 16))
        self.led_oval = self.led_canvas.create_oval(4, 4, 44, 44,
                                                     fill="#2A2A2A", outline=BORDER, width=1)

        tk.Label(col1, text="HEARTBEAT", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        self.hb_label = tk.Label(col1, text="—", font=big, bg=PANEL, fg=TEXT)
        self.hb_label.pack(anchor="w")

        tk.Frame(col1, bg=BORDER, height=1).pack(fill="x", pady=(16, 8))
        tk.Label(col1, text=f"DEVICE  {ARDUINO_IP}:{ARDUINO_PORT}",
                 font=mono_s, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")

        # ---- Column 2: Temperature ----
        col2 = tk.Frame(content, bg=PANEL, padx=20, pady=20,
                        highlightbackground=BORDER, highlightthickness=1)
        col2.grid(row=0, column=1, sticky="nsew", padx=(0, 10))

        tk.Label(col2, text="TEMPERATURE", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        tk.Frame(col2, bg=BORDER, height=1).pack(fill="x", pady=(4, 16))

        self.temp_c_label = tk.Label(col2, text="—", font=temp_f, bg=PANEL, fg=BLUE)
        self.temp_c_label.pack(anchor="w")
        tk.Label(col2, text="°C", font=mono, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        tk.Frame(col2, bg=BORDER, height=1).pack(fill="x", pady=(12, 12))
        self.temp_f_label = tk.Label(col2, text="—", font=temp_f, bg=PANEL, fg=ACCENT)
        self.temp_f_label.pack(anchor="w")
        tk.Label(col2, text="°F", font=mono, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")

        tk.Frame(col2, bg=BORDER, height=1).pack(fill="x", pady=(16, 8))
        self.temp_status = tk.Label(col2, text="● WAITING",
                                     font=label, bg=PANEL, fg=TEXT_DIM)
        self.temp_status.pack(anchor="w")
        tk.Label(col2, text="DS18B20  Pin 2",
                 font=mono_s, bg=PANEL, fg=TEXT_DIM).pack(anchor="w", pady=(8, 0))

        # ---- Column 3: Controls ----
        col3 = tk.Frame(content, bg=PANEL, padx=20, pady=20,
                        highlightbackground=BORDER, highlightthickness=1)
        col3.grid(row=0, column=2, sticky="nsew")

        tk.Label(col3, text="CONTROLS", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        tk.Frame(col3, bg=BORDER, height=1).pack(fill="x", pady=(4, 16))

        tk.Label(col3, text="MODE", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        btn_frame = tk.Frame(col3, bg=PANEL)
        btn_frame.pack(fill="x", pady=(6, 16))

        self.btn_off   = self._mode_btn(btn_frame, "OFF",      0)
        self.btn_blink = self._mode_btn(btn_frame, "BLINK",    1)
        self.btn_solid = self._mode_btn(btn_frame, "SOLID ON", 2)
        self.btn_off.pack(side="left", padx=(0, 6))
        self.btn_blink.pack(side="left", padx=(0, 6))
        self.btn_solid.pack(side="left")

        tk.Label(col3, text="BLINK RATE", font=label, bg=PANEL, fg=TEXT_DIM).pack(anchor="w")
        rate_row = tk.Frame(col3, bg=PANEL)
        rate_row.pack(fill="x", pady=(6, 16))

        self.rate_slider = tk.Scale(
            rate_row, from_=0.1, to=10.0, resolution=0.1,
            orient="horizontal", variable=self.blink_rate,
            command=self._on_rate_change,
            bg=PANEL, fg=TEXT, troughcolor=BORDER,
            activebackground=ACCENT, highlightthickness=0,
            sliderrelief="flat", bd=0, length=180
        )
        self.rate_slider.pack(side="left")
        self.rate_val = tk.Label(rate_row, text="1.0 Hz", font=mono,
                                  bg=PANEL, fg=ACCENT, width=7)
        self.rate_val.pack(side="left", padx=(10, 0))

        tk.Frame(col3, bg=BORDER, height=1).pack(fill="x", pady=(0, 16))
        self.demo_btn = tk.Button(
            col3, text="▶  RUN DEMO SEQUENCE",
            font=label, bg=ACCENT_DIM, fg=ACCENT,
            activebackground=ACCENT, activeforeground=BG,
            bd=0, padx=16, pady=10, cursor="hand2",
            command=self._run_demo
        )
        self.demo_btn.pack(fill="x")

        # Log
        log_frame = tk.Frame(self, bg=BG, padx=24, pady=20)
        log_frame.pack(fill="both")
        tk.Label(log_frame, text="LOG", font=label, bg=BG, fg=TEXT_DIM).pack(anchor="w")
        tk.Frame(log_frame, bg=BORDER, height=1).pack(fill="x", pady=(4, 8))
        self.log_box = tk.Text(log_frame, height=5, bg=PANEL, fg=TEXT_DIM,
                               font=mono_s, bd=0, insertbackground=TEXT,
                               state="disabled", wrap="word",
                               highlightbackground=BORDER, highlightthickness=1)
        self.log_box.pack(fill="x")
        self.log_box.tag_config("tx",  foreground=GREEN)
        self.log_box.tag_config("rx",  foreground=BLUE)
        self.log_box.tag_config("sys", foreground=TEXT_DIM)
        self.log_box.tag_config("err", foreground=RED)

    def _mode_btn(self, parent, text, value):
        return tk.Button(
            parent, text=text,
            font=tkfont.Font(family="Courier New", size=9, weight="bold"),
            bg=BORDER, fg=TEXT_DIM,
            activebackground=ACCENT, activeforeground=BG,
            bd=0, padx=14, pady=8, cursor="hand2",
            command=lambda: self._set_mode(value)
        )

    # -------------------------------------------------------------------------
    def _log(self, msg, tag="sys"):
        def _do():
            ts = time.strftime("%H:%M:%S")
            self.log_box.configure(state="normal")
            self.log_box.insert("end", f"[{ts}] {msg}\n", tag)
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _do)

    def _connect(self):
        self.client = ModbusTcpClient(ARDUINO_IP, port=ARDUINO_PORT)
        if self.client.connect():
            self.connected = True
            self._log(f"Connected to Arduino at {ARDUINO_IP}:{ARDUINO_PORT}")
            self.after(0, lambda: self.conn_dot.config(text="● ONLINE", fg=GREEN))
        else:
            self._log(f"Could not connect to {ARDUINO_IP}:{ARDUINO_PORT}", "err")

    def _modbus_write(self, enable, rate_tenth):
        with self.lock:
            self.client.write_register(REG_LED_ENABLE, enable)
            self.client.write_register(REG_BLINK_RATE, rate_tenth)

    def _set_mode(self, mode):
        if not self.connected:
            self._log("Not connected", "err")
            return
        rate_tenth = max(1, min(100, int(self.blink_rate.get() * 10)))
        threading.Thread(target=self._modbus_write, args=(mode, rate_tenth), daemon=True).start()
        modes = {0: "OFF", 1: "BLINK", 2: "SOLID ON"}
        self._log(f"Set mode → {modes[mode]}  {self.blink_rate.get():.1f} Hz", "tx")
        self._update_btn_states(mode)

    def _update_btn_states(self, active):
        btns = {0: self.btn_off, 1: self.btn_blink, 2: self.btn_solid}
        for v, btn in btns.items():
            btn.config(bg=ACCENT if v == active else BORDER,
                       fg=BG     if v == active else TEXT_DIM)

    def _on_rate_change(self, val):
        hz = float(val)
        self.rate_val.config(text=f"{hz:.1f} Hz")

    def _poll_loop(self):
        while self.running:
            if self.connected:
                try:
                    with self.lock:
                        # Read all input registers in one call
                        result = self.client.read_input_registers(
                            address=0, count=4
                        )
                    if not result.isError():
                        self.led_state  = result.registers[REG_LED_STATE]
                        self.heartbeat  = result.registers[REG_HEARTBEAT]
                        temp_raw        = result.registers[REG_TEMPERATURE]
                        temp_status     = result.registers[REG_TEMP_STATUS]
                        self.temp_c     = temp_raw / 10.0
                        self.temp_fault = temp_status == 1
                        self.after(0, self._update_status)
                except Exception:
                    pass
            time.sleep(POLL_INTERVAL)

    def _update_status(self):
        # LED indicator
        color = ACCENT if self.led_state else "#2A2A2A"
        self.led_canvas.itemconfig(self.led_oval, fill=color)
        self.hb_label.config(text=str(self.heartbeat))

        # Temperature
        if self.temp_fault:
            self.temp_c_label.config(text="ERR", fg=RED)
            self.temp_f_label.config(text="ERR", fg=RED)
            self.temp_status.config(text="● FAULT", fg=RED)
        else:
            temp_f = self.temp_c * 9/5 + 32
            self.temp_c_label.config(text=f"{self.temp_c:.1f}", fg=BLUE)
            self.temp_f_label.config(text=f"{temp_f:.1f}", fg=ACCENT)
            self.temp_status.config(text="● OK", fg=GREEN)

    def _run_demo(self):
        if not self.connected:
            self._log("Not connected", "err")
            return
        self.demo_btn.config(state="disabled", text="  RUNNING...")
        threading.Thread(target=self._demo_sequence, daemon=True).start()

    def _demo_sequence(self):
        steps = [
            (2,  0,  "Solid on",      3),
            (1, 10,  "Blink 1.0 Hz",  4),
            (1, 25,  "Blink 2.5 Hz",  4),
            (1, 50,  "Blink 5.0 Hz",  4),
            (0,  0,  "Off",            2),
            (1, 10,  "Default blink",  1),
        ]
        for enable, rate, lbl, duration in steps:
            self._log(f"Demo → {lbl}", "tx")
            self._modbus_write(enable, rate if rate > 0 else 10)
            self.after(0, lambda e=enable: self._update_btn_states(e))
            time.sleep(duration)
        self.after(0, lambda: self.demo_btn.config(
            state="normal", text="▶  RUN DEMO SEQUENCE"))
        self._log("Demo sequence complete", "sys")

    def _on_close(self):
        self.running = False
        if self.client:
            self.client.close()
        self.destroy()

# =============================================================================
if __name__ == "__main__":
    app = HALApp()
    app.mainloop()
