import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import tkinter as tk
from tkinter import ttk
import pytesseract
import time
from deep_translator import GoogleTranslator
import threading
import win32con
import win32gui
from PIL import Image, ImageOps
import hashlib
import mss
import numpy as np
import re  # 정규표현식 추가

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
auto_paused = False
auto_region = None
auto_session_id = 0
current_overlay = None
overlay_label = None

last_text = ""
last_image_hash = ""
last_ocr_text = ""
multi_last_ocr_texts = []

multi_regions = []
multi_overlays = []
multi_auto_running = False
multi_auto_session_id = 0
region_display = None

translator_engine = GoogleTranslator(source='en', target='ko')

# ==============================
# 고속 캡처 및 전처리
# ==============================
def get_screenshot_mss(region, binarize=False):
    with mss.mss() as sct:
        monitor = {"left": region[0], "top": region[1], "width": region[2], "height": region[3]}
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        img = img.convert('L')
        if binarize:
            # 임계값을 140으로 설정하여 글자를 더 뚜렷하게 만듦
            img = img.point(lambda x: 0 if x < 140 else 255, '1')
        return img

# ==============================
# [핵심] 노이즈 필터링 OCR 함수
# ==============================
def get_filtered_ocr_text(screenshot):
    """신뢰도와 정규표현식을 사용하여 의미 있는 글자만 추출"""
    try:
        # image_to_data는 단어별 좌표 및 신뢰도(conf)를 반환함
        data = pytesseract.image_to_data(screenshot, lang="eng", config="--psm 6 --oem 1", output_type=pytesseract.Output.DICT)
        
        valid_words = []
        conf_scores = []
        
        for i in range(len(data['text'])):
            word = data['text'][i].strip()
            conf = int(data['conf'][i])
            
            # 필터 1: 신뢰도 45점 이상 (노이즈는 보통 10~30점)
            # 필터 2: 1글자 초과 (파편 제거)
            # 필터 3: 알파벳이나 숫자가 최소 하나는 포함 (순수 특수문자 제거)
            if conf > 45 and len(word) > 1:
                if re.search('[a-zA-Z0-9]', word):
                    valid_words.append(word)
                    conf_scores.append(conf)
        
        if not valid_words:
            return ""
            
        # 전체 문장의 평균 신뢰도가 너무 낮으면 노이즈로 판단
        if sum(conf_scores) / len(conf_scores) < 50:
            return ""
            
        return " ".join(valid_words).strip()
    except:
        return ""

# ==============================
# 영역 선택 클래스 (유지)
# ==============================
class AreaSelector:
    def __init__(self, master, multi_mode=False):
        self.multi_mode = multi_mode
        self.selections = []
        self.root = tk.Toplevel(master)
        self.root.attributes("-alpha", 0.3, "-fullscreen", True, "-topmost", True)
        self.root.config(cursor="cross")
        self.canvas = tk.Canvas(self.root, bg="gray")
        self.canvas.pack(fill="both", expand=True)
        self.start_x = self.start_y = 0
        self.rect = None
        self.rects = []
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Escape>", self.cancel)
        self.root.bind("<Return>", self.finish)
        if multi_mode:
            tk.Label(self.root, text="여러 영역을 드래그하세요. Enter: 완료 | ESC: 취소",
                     bg="yellow", font=("Malgun Gothic", 12)).place(x=10, y=10)

    def cancel(self, event=None): self.selections = []; self.root.destroy()
    def finish(self, event=None): 
        if self.multi_mode and self.selections: self.root.destroy()

    def on_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)

    def on_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_release(self, event):
        left, top = min(self.start_x, event.x), min(self.start_y, event.y)
        width, height = abs(self.start_x - event.x), abs(self.start_y - event.y)
        if width > 10 and height > 10:
            self.selections.append((left, top, width, height))
            self.rects.append(self.rect)
            if not self.multi_mode: self.root.destroy()

# ==============================
# 유틸리티 함수
# ==============================
def make_draggable(window):
    def start_move(event): window.x, window.y = event.x, event.y
    def stop_move(event): window.x = window.y = None
    def on_motion(event):
        x = window.winfo_x() + (event.x - window.x)
        y = window.winfo_y() + (event.y - window.y)
        window.geometry(f"+{x}+{y}")
    window.bind("<ButtonPress-1>", start_move)
    window.bind("<ButtonRelease-1>", stop_move)
    window.bind("<B1-Motion>", on_motion)

def remove_overlay():
    global current_overlay, overlay_label, last_text, last_ocr_text
    if current_overlay:
        current_overlay.destroy()
        current_overlay = overlay_label = None
        last_text = last_ocr_text = ""

def remove_multi_overlays():
    global multi_overlays, multi_last_ocr_texts
    for overlay in multi_overlays:
        try: overlay.destroy()
        except: pass
    multi_overlays = []; multi_last_ocr_texts = []

def remove_region_display():
    global region_display
    if region_display:
        try: region_display.destroy()
        except: pass
        region_display = None

def remove_all_displays():
    global auto_running, multi_auto_running, auto_session_id, multi_auto_session_id
    auto_running = multi_auto_running = False
    auto_session_id += 1; multi_auto_session_id += 1
    remove_region_display(); remove_overlay(); remove_multi_overlays()

def show_region_display(regions, auto_mode=False, duration=None):
    global region_display
    remove_region_display()
    region_display = tk.Toplevel(root)
    region_display.attributes("-alpha", 0.3, "-fullscreen", True, "-topmost", True)
    region_display.overrideredirect(not auto_mode)
    canvas = tk.Canvas(region_display, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    region_display.wm_attributes("-transparentcolor", "black")
    for r in regions:
        canvas.create_rectangle(r[0], r[1], r[0]+r[2], r[1]+r[3], outline="red", width=3)
    if not auto_mode and duration: region_display.after(duration, remove_region_display)

def show_or_update_overlay(text, region, auto=False):
    global current_overlay, overlay_label, last_text
    if text == last_text: return
    last_text = text
    left, top, width, height = region
    if auto and current_overlay:
        overlay_label.config(text=text)
        return
    remove_overlay()
    overlay = tk.Toplevel(root)
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True, "-alpha", 0.85)
    overlay.configure(bg="black")
    overlay.geometry(f"+{left}+{top + height + 5}")
    label = tk.Label(overlay, text=text, bg="black", fg="white", font=("Malgun Gothic", 11), 
                     wraplength=600, justify="left", cursor="fleur")
    label.pack(padx=10, pady=6)
    make_draggable(overlay)
    current_overlay, overlay_label = overlay, label
    if not auto: overlay.after(5000, remove_overlay)

def create_multi_overlay(text, region):
    left, top, width, height = region
    overlay = tk.Toplevel(root)
    overlay.overrideredirect(True)
    overlay.attributes("-topmost", True, "-alpha", 0.85)
    overlay.configure(bg="black")
    overlay.geometry(f"+{left}+{top + height + 5}")
    label = tk.Label(overlay, text=text, bg="black", fg="white", font=("Malgun Gothic", 11), 
                     wraplength=600, justify="left", cursor="fleur")
    label.pack(padx=10, pady=6)
    make_draggable(overlay)
    return overlay

# ==============================
# 개선된 번역 로직 (노이즈 필터링 포함)
# ==============================
def ocr_translate(region, auto=False, check_change=False):
    global last_image_hash, last_ocr_text
    try:
        screenshot = get_screenshot_mss(region, binarize=True)
        
        if check_change:
            new_hash = hashlib.md5(screenshot.tobytes()).hexdigest()
            if new_hash == last_image_hash: return
            last_image_hash = new_hash

        # 필터링 로직 적용
        text = get_filtered_ocr_text(screenshot)
        
        if not text or text == last_ocr_text: return
        last_ocr_text = text

        result = translator_engine.translate(text)
        show_or_update_overlay(result, region, auto)
        if not auto: show_region_display([region], auto_mode=False, duration=5000)
    except: pass

def translate_multi_regions_once():
    global multi_regions, multi_overlays
    remove_multi_overlays()
    show_region_display(multi_regions, auto_mode=False, duration=5000)
    for region in multi_regions:
        try:
            screenshot = get_screenshot_mss(region, binarize=True)
            text = get_filtered_ocr_text(screenshot)
            if text:
                result = translator_engine.translate(text)
                multi_overlays.append(create_multi_overlay(result, region))
        except: pass
    if multi_overlays: root.after(5000, remove_multi_overlays)

def multi_auto_loop(my_session_id):
    global multi_auto_running, multi_regions, multi_overlays, multi_last_ocr_texts
    if not multi_overlays:
        multi_last_ocr_texts = [""] * len(multi_regions)
        for region in multi_regions:
            multi_overlays.append(create_multi_overlay("번역 대기 중...", region))
            
    while multi_auto_running and my_session_id == multi_auto_session_id:
        if not auto_paused:
            for i, region in enumerate(multi_regions):
                try:
                    screenshot = get_screenshot_mss(region, binarize=True)
                    text = get_filtered_ocr_text(screenshot)
                    if text and text != multi_last_ocr_texts[i]:
                        multi_last_ocr_texts[i] = text
                        res = translator_engine.translate(text)
                        for w in multi_overlays[i].winfo_children():
                            if isinstance(w, tk.Label): w.config(text=res)
                except: pass
        time.sleep(0.3)

def auto_loop(my_session_id):
    global auto_running
    while auto_running and my_session_id == auto_session_id:
        if not auto_paused:
            ocr_translate(auto_region, auto=True, check_change=True)
        time.sleep(0.3)

# ==============================
# 모드 제어 및 메인
# ==============================
def start_select_translate():
    selector = AreaSelector(root)
    root.wait_window(selector.root)
    if selector.selections: ocr_translate(selector.selections[0], auto=False)

def start_multi_translate():
    global multi_regions, multi_auto_running, multi_auto_session_id
    stop_auto()
    selector = AreaSelector(root, multi_mode=True)
    root.wait_window(selector.root)
    if selector.selections:
        multi_regions = selector.selections
        if mode_auto_translate.get():
            show_region_display(multi_regions, auto_mode=True)
            multi_auto_running = True
            threading.Thread(target=multi_auto_loop, args=(multi_auto_session_id,), daemon=True).start()
        else:
            translate_multi_regions_once()

def start_auto_translate():
    global auto_running, auto_region, auto_session_id
    stop_auto()
    selector = AreaSelector(root)
    root.wait_window(selector.root)
    if selector.selections:
        auto_region = selector.selections[0]
        auto_running = True
        show_region_display([auto_region], auto_mode=True)
        threading.Thread(target=auto_loop, args=(auto_session_id,), daemon=True).start()

def stop_auto():
    global auto_running, auto_paused, auto_session_id, multi_auto_running, multi_auto_session_id, last_image_hash, last_ocr_text
    auto_running = multi_auto_running = False
    auto_paused = False
    auto_session_id += 1; multi_auto_session_id += 1
    last_image_hash = last_ocr_text = ""
    remove_all_displays()

def toggle_pause():
    global auto_paused; auto_paused = not auto_paused

def switch_to_select_mode():
    stop_auto(); mode_select_translate.set(True); mode_auto_translate.set(False)

def switch_to_auto_mode():
    stop_auto(); mode_select_translate.set(False); mode_auto_translate.set(True)

def execute_current_mode():
    if mode_auto_translate.get(): start_auto_translate()
    else: start_select_translate()

def toggle_select_mode():
    if mode_select_translate.get(): stop_auto(); mode_auto_translate.set(False)
    else: mode_select_translate.set(True)

def toggle_auto_mode():
    if mode_auto_translate.get(): stop_auto(); mode_select_translate.set(False)
    else: mode_auto_translate.set(True)

def hotkey_listener():
    hotkeys = [(1, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("1")),
               (2, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("2")),
               (3, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("T")),
               (4, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("P")),
               (5, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("M")),
               (6, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("R"))]
    for id, mod, key in hotkeys: win32gui.RegisterHotKey(None, id, mod, key)
    try:
        while True:
            msg = win32gui.GetMessage(None, 0, 0)
            if msg[1][1] == win32con.WM_HOTKEY:
                mid = msg[1][2]
                if mid == 1: root.after(0, switch_to_select_mode)
                elif mid == 2: root.after(0, switch_to_auto_mode)
                elif mid == 3: root.after(0, execute_current_mode)
                elif mid == 4: root.after(0, toggle_pause)
                elif mid == 5: root.after(0, start_multi_translate)
                elif mid == 6: root.after(0, remove_all_displays)
    finally:
        for id, _, _ in hotkeys: win32gui.UnregisterHotKey(None, id)

def main():
    global root, mode_select_translate, mode_auto_translate
    root = tk.Tk()
    root.title("고속 번역기 Pro (Anti-Noise)")
    root.geometry("750x750")
    style = ttk.Style()
    style.configure("Large.TCheckbutton", font=("Malgun Gothic", 12), padding=10)
    mode_select_translate = tk.BooleanVar(value=True)
    mode_auto_translate = tk.BooleanVar(value=False)
    tk.Label(root, text="번역기 컨트롤러 (Noise Filtered)", font=("Malgun Gothic", 16, "bold")).pack(pady=20)
    ttk.Checkbutton(root, text="선택 번역 모드 (1회성)", variable=mode_select_translate, command=toggle_select_mode, style="Large.TCheckbutton").pack(anchor="w", padx=50)
    ttk.Checkbutton(root, text="자동 번역 모드 (실시간 루프)", variable=mode_auto_translate, command=toggle_auto_mode, style="Large.TCheckbutton").pack(anchor="w", padx=50)
    info_frame = tk.Frame(root, relief="groove", borderwidth=1)
    info_frame.pack(fill="both", padx=40, pady=20)
    instructions = [
        ("\n[단축키 안내]", ("Malgun Gothic", 11, "bold"), "black"),
        ("🔢 Ctrl+Shift+1/2 : 모드 전환", ("Malgun Gothic", 10), "black"),
        ("▶ Ctrl+Shift+T : 번역 실행/영역 지정", ("Malgun Gothic", 10), "blue"),
        ("⏸ Ctrl+Shift+P : 자동 번역 일시정지", ("Malgun Gothic", 10), "black"),
        ("📌 Ctrl+Shift+M : 다중 영역 지정 번역", ("Malgun Gothic", 10), "black"),
        ("❌ Ctrl+Shift+R : 모든 표시 제거 및 번역 중지", ("Malgun Gothic", 10, "bold"), "red"),
        ("\n* 최적화: 신뢰도가 낮은 노이즈 문자는 자동으로 필터링합니다.", ("Malgun Gothic", 9), "green"),
    ]
    for text, font, color in instructions:
        tk.Label(info_frame, text=text, font=font, fg=color).pack(anchor="w", padx=10)
    threading.Thread(target=hotkey_listener, daemon=True).start()
    root.mainloop()

if __name__ == "__main__":
    main()