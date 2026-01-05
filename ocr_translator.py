# ==============================
# DPI 인식 강제
# ==============================
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)

import tkinter as tk
import pytesseract
import pyautogui
import time
from googletrans import Translator
import threading
import win32con
import win32gui

# ==============================
# Tesseract 경로
# ==============================
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ==============================
# 전역 상태
# ==============================
root = None

mode_select_translate = None
mode_auto_translate = None

auto_running = False
auto_region = None
auto_session_id = 0

current_overlay = None
overlay_label = None
last_text = ""


# ==============================
# 영역 선택 클래스
# ==============================
class AreaSelector:
    def __init__(self, master):
        self.root = tk.Toplevel(master)
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.config(cursor="cross")

        self.canvas = tk.Canvas(self.root, bg="gray")
        self.canvas.pack(fill="both", expand=True)

        self.start_x = self.start_y = 0
        self.rect = None
        self.selection = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", self.cancel)

    def cancel(self, event=None):
        self.root.destroy()

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y,
            self.start_x, self.start_y,
            outline="red", width=2
        )

    def on_drag(self, event):
        self.canvas.coords(
            self.rect,
            self.start_x, self.start_y,
            event.x, event.y
        )

    def on_release(self, event):
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(self.start_x - event.x)
        height = abs(self.start_y - event.y)
        self.selection = (left, top, width, height)
        self.root.destroy()


# ==============================
# 오버레이 처리
# ==============================
def remove_overlay():
    global current_overlay, overlay_label, last_text
    if current_overlay:
        current_overlay.destroy()
    current_overlay = None
    overlay_label = None
    last_text = ""


def show_or_update_overlay(text, region, auto=False):
    global current_overlay, overlay_label, last_text

    if text == last_text:
        return

    last_text = text
    left, top, width, height = region

    if auto and current_overlay:
        overlay_label.config(text=text)
        return

    remove_overlay()

    overlay = tk.Toplevel(root)
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True)
    overlay.attributes("-alpha", 0.85)
    overlay.configure(bg="black")
    overlay.geometry(f"+{left}+{top + height + 5}")

    label = tk.Label(
        overlay,
        text=text,
        bg="black",
        fg="white",
        font=("Malgun Gothic", 11),
        wraplength=600,
        justify="left"
    )
    label.pack(padx=10, pady=6)

    def start_move(e):
        overlay._x = e.x
        overlay._y = e.y

    def on_move(e):
        x = overlay.winfo_x() + e.x - overlay._x
        y = overlay.winfo_y() + e.y - overlay._y
        overlay.geometry(f"+{x}+{y}")

    overlay.bind("<ButtonPress-1>", start_move)
    overlay.bind("<B1-Motion>", on_move)

    current_overlay = overlay
    overlay_label = label

    if not auto:
        overlay.after(5000, remove_overlay)


# ==============================
# OCR + 번역
# ==============================
def ocr_translate(region, auto=False):
    screenshot = pyautogui.screenshot(region=region)

    text = pytesseract.image_to_string(
        screenshot, lang="eng", config="--psm 6"
    ).strip()

    if not text:
        return

    result = Translator().translate(text, src="en", dest="ko")
    show_or_update_overlay(result.text, region, auto)


# ==============================
# 자동 번역 루프
# ==============================
def auto_loop(my_session_id):
    global auto_running
    while auto_running and my_session_id == auto_session_id:
        ocr_translate(auto_region, auto=True)
        time.sleep(1)


# ==============================
# 선택 번역
# ==============================
def start_select_translate():
    selector = AreaSelector(root)
    root.wait_window(selector.root)
    if selector.selection:
        ocr_translate(selector.selection, auto=False)


# ==============================
# 단축키 처리
# ==============================
def handle_hotkey():
    if mode_auto_translate.get():
        start_auto_translate()
    else:
        start_select_translate()


def start_auto_translate():
    global auto_running, auto_region, auto_session_id

    auto_running = False
    auto_region = None
    auto_session_id += 1
    remove_overlay()

    selector = AreaSelector(root)
    root.wait_window(selector.root)

    if selector.selection:
        auto_region = selector.selection
        auto_running = True
        my_id = auto_session_id
        threading.Thread(
            target=auto_loop,
            args=(my_id,),
            daemon=True
        ).start()


# ==============================
# 전역 단축키 리스너
# ==============================
def hotkey_listener():
    win32gui.RegisterHotKey(
        None, 1,
        win32con.MOD_CONTROL | win32con.MOD_SHIFT,
        ord("T")
    )
    try:
        while True:
            msg = win32gui.GetMessage(None, 0, 0)
            if msg[1][1] == win32con.WM_HOTKEY:
                root.after(0, handle_hotkey)
    finally:
        win32gui.UnregisterHotKey(None, 1)


# ==============================
# 모드 전환
# ==============================
def stop_auto():
    global auto_running, auto_region, auto_session_id
    auto_running = False
    auto_region = None
    auto_session_id += 1
    remove_overlay()


def toggle_select_mode():
    stop_auto()
    if not mode_select_translate.get():
        mode_select_translate.set(True)
    mode_auto_translate.set(False)


def toggle_auto_mode():
    stop_auto()
    if mode_auto_translate.get():
        mode_select_translate.set(False)
    else:
        mode_select_translate.set(True)


# ==============================
# 메인 GUI
# ==============================
def main():
    global root, mode_select_translate, mode_auto_translate

    root = tk.Tk()
    root.title("OCR Translator")
    root.geometry("400x240")
    root.resizable(False, False)

    mode_select_translate = tk.BooleanVar(value=True)
    mode_auto_translate = tk.BooleanVar(value=False)

    tk.Label(
        root,
        text="OCR 번역 모드",
        font=("Malgun Gothic", 13, "bold")
    ).pack(pady=10)

    tk.Checkbutton(
        root,
        text="선택 번역 모드 (Ctrl + Shift + T)",
        variable=mode_select_translate,
        command=toggle_select_mode
    ).pack(anchor="w", padx=30)

    tk.Checkbutton(
        root,
        text="자동 번역 모드 (1초 간격)",
        variable=mode_auto_translate,
        command=toggle_auto_mode
    ).pack(anchor="w", padx=30, pady=5)

    threading.Thread(
        target=hotkey_listener,
        daemon=True
    ).start()

    root.mainloop()


if __name__ == "__main__":
    main()
