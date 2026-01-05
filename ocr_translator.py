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
from PIL import ImageGrab
import hashlib

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
auto_paused = False  # 일시정지 상태
auto_region = None
auto_session_id = 0
current_overlay = None
overlay_label = None
last_text = ""
last_image_hash = ""  # OCR 텍스트 변경 감지 최적화
multi_regions = []  # 여러 영역 저장
multi_overlays = []  # 여러 오버레이 저장
multi_auto_running = False  # 여러 영역 자동 번역 실행 여부
multi_auto_session_id = 0  # 여러 영역 자동 번역 세션 ID
region_display = None  # 영역 표시 창

# ==============================
# 영역 선택 클래스
# ==============================
class AreaSelector:
    def __init__(self, master, multi_mode=False):
        self.multi_mode = multi_mode
        self.selections = []
        
        self.root = tk.Toplevel(master)
        self.root.attributes("-alpha", 0.3)
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
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
            info = tk.Label(
                self.root,
                text="여러 영역을 드래그하세요. Enter: 완료 | ESC: 취소",
                bg="yellow",
                font=("Malgun Gothic", 12)
            )
            info.place(x=10, y=10)

    def cancel(self, event=None):
        self.selections = []
        self.root.destroy()

    def finish(self, event=None):
        if self.multi_mode and self.selections:
            self.root.destroy()

    def on_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2
        )

    def on_drag(self, event):
        self.canvas.coords(
            self.rect,
            self.start_x, self.start_y, event.x, event.y
        )

    def on_release(self, event):
        left = min(self.start_x, event.x)
        top = min(self.start_y, event.y)
        width = abs(self.start_x - event.x)
        height = abs(self.start_y - event.y)
        
        if width > 10 and height > 10:
            selection = (left, top, width, height)
            self.selections.append(selection)
            self.rects.append(self.rect)
            
            if not self.multi_mode:
                self.root.destroy()

# ==============================
# 이미지 해시 계산 (변경 감지)
# ==============================
def get_image_hash(region):
    try:
        screenshot = ImageGrab.grab(bbox=(
            region[0], region[1],
            region[0] + region[2],
            region[1] + region[3]
        ))
        return hashlib.md5(screenshot.tobytes()).hexdigest()
    except:
        return ""

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

def remove_multi_overlays():
    global multi_overlays
    for overlay in multi_overlays:
        try:
            overlay.destroy()
        except:
            pass
    multi_overlays = []

def remove_region_display():
    global region_display
    if region_display:
        try:
            region_display.destroy()
        except:
            pass
        region_display = None

def show_region_display(regions, auto_mode=False, duration=None):
    """선택된 영역들을 화면에 표시"""
    global region_display
    
    remove_region_display()
    
    region_display = tk.Toplevel(root)
    region_display.attributes("-alpha", 0.3)
    region_display.attributes("-fullscreen", True)
    region_display.attributes("-topmost", True)
    
    if auto_mode:
        # 자동 모드: 이동 가능하도록 타이틀바 유지
        region_display.overrideredirect(False)
        region_display.title("선택 영역 표시 (이동/닫기 가능)")
    else:
        # 선택 모드: 타이틀바 없음
        region_display.overrideredirect(True)
    
    canvas = tk.Canvas(region_display, bg="black", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    
    # 투명한 배경 만들기
    region_display.wm_attributes("-transparentcolor", "black")
    
    # 각 영역을 빨간 테두리로 표시
    for region in regions:
        left, top, width, height = region
        canvas.create_rectangle(
            left, top, left + width, top + height,
            outline="red", width=3
        )
    
    if not auto_mode:
        # 선택 모드: 클릭하면 표시 제거
        def remove_on_click(e):
            remove_region_display()
        canvas.bind("<Button-1>", remove_on_click)
        
        # 선택 모드: 지정된 시간 후 자동 제거
        if duration:
            region_display.after(duration, remove_region_display)

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

def create_multi_overlay(text, region):
    left, top, width, height = region
    
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
    
    return overlay

# ==============================
# OCR + 번역
# ==============================
def ocr_translate(region, auto=False, check_change=False):
    global last_image_hash
    
    # 변경 감지 최적화
    if check_change:
        new_hash = get_image_hash(region)
        if new_hash == last_image_hash:
            return
        last_image_hash = new_hash
    
    screenshot = pyautogui.screenshot(region=region)
    text = pytesseract.image_to_string(
        screenshot,
        lang="eng",
        config="--psm 6"
    ).strip()
    
    if not text:
        return
    
    result = Translator().translate(text, src="en", dest="ko")
    show_or_update_overlay(result.text, region, auto)
    
    # 선택 번역 모드에서는 영역 표시도 함께 표시
    if not auto:
        show_region_display([region], auto_mode=False, duration=5000)

# ==============================
# 여러 영역 번역
# ==============================
def translate_multi_regions_once():
    """여러 영역을 한 번만 번역 (선택 모드)"""
    global multi_regions, multi_overlays
    
    remove_multi_overlays()
    
    # 선택 모드에서는 영역 표시도 함께 (5초 후 자동 제거)
    show_region_display(multi_regions, auto_mode=False, duration=5000)
    
    for region in multi_regions:
        screenshot = pyautogui.screenshot(region=region)
        text = pytesseract.image_to_string(
            screenshot,
            lang="eng",
            config="--psm 6"
        ).strip()
        
        if text:
            result = Translator().translate(text, src="en", dest="ko")
            overlay = create_multi_overlay(result.text, region)
            multi_overlays.append(overlay)
    
    # 5초 후 자동으로 모든 오버레이 제거
    if multi_overlays:
        root.after(5000, remove_multi_overlays)

def translate_multi_regions_auto(region_index):
    """특정 영역을 자동으로 번역"""
    if region_index >= len(multi_regions):
        return
    
    region = multi_regions[region_index]
    screenshot = pyautogui.screenshot(region=region)
    text = pytesseract.image_to_string(
        screenshot,
        lang="eng",
        config="--psm 6"
    ).strip()
    
    if text:
        result = Translator().translate(text, src="en", dest="ko")
        
        # 해당 인덱스의 오버레이 업데이트
        if region_index < len(multi_overlays) and multi_overlays[region_index]:
            try:
                # 기존 오버레이의 라벨만 업데이트
                for widget in multi_overlays[region_index].winfo_children():
                    if isinstance(widget, tk.Label):
                        widget.config(text=result.text)
            except:
                pass

def multi_auto_loop(my_session_id):
    """여러 영역을 자동으로 계속 번역 (자동 모드)"""
    global multi_auto_running, multi_regions, multi_overlays
    
    # 초기 오버레이 생성
    if not multi_overlays:
        for region in multi_regions:
            overlay = create_multi_overlay("번역 중...", region)
            multi_overlays.append(overlay)
    
    while multi_auto_running and my_session_id == multi_auto_session_id:
        if not auto_paused:
            for i in range(len(multi_regions)):
                translate_multi_regions_auto(i)
        time.sleep(1)

# ==============================
# 자동 번역 루프
# ==============================
def auto_loop(my_session_id):
    global auto_running, auto_paused
    
    while auto_running and my_session_id == auto_session_id:
        if not auto_paused:
            ocr_translate(auto_region, auto=True, check_change=True)
        time.sleep(1)

# ==============================
# 선택 번역
# ==============================
def start_select_translate():
    selector = AreaSelector(root)
    root.wait_window(selector.root)
    if selector.selections:
        ocr_translate(selector.selections[0], auto=False)

# ==============================
# 여러 영역 선택
# ==============================
def start_multi_translate():
    global multi_regions, multi_auto_running, multi_auto_session_id
    
    # 기존 실행 중단
    multi_auto_running = False
    multi_auto_session_id += 1
    remove_multi_overlays()
    remove_region_display()
    
    selector = AreaSelector(root, multi_mode=True)
    root.wait_window(selector.root)
    
    if selector.selections:
        multi_regions = selector.selections
        
        # 모드에 따라 다르게 동작
        if mode_auto_translate.get():
            # 자동 번역 모드: 계속 번역, 영역 표시 (이동/닫기 가능)
            show_region_display(multi_regions, auto_mode=True)
            multi_auto_running = True
            my_id = multi_auto_session_id
            threading.Thread(
                target=multi_auto_loop,
                args=(my_id,),
                daemon=True
            ).start()
        else:
            # 선택 번역 모드: 한 번만 번역, 영역 표시는 함수 내부에서 처리
            translate_multi_regions_once()

# ==============================
# 자동 번역 시작
# ==============================
def start_auto_translate():
    global auto_running, auto_region, auto_session_id, auto_paused, last_image_hash
    
    auto_running = False
    auto_paused = False
    auto_region = None
    auto_session_id += 1
    last_image_hash = ""
    remove_overlay()
    remove_region_display()
    
    selector = AreaSelector(root)
    root.wait_window(selector.root)
    
    if selector.selections:
        auto_region = selector.selections[0]
        auto_running = True
        
        # 자동 모드에서는 영역 표시 (이동/닫기 가능)
        show_region_display([auto_region], auto_mode=True)
        
        my_id = auto_session_id
        threading.Thread(
            target=auto_loop,
            args=(my_id,),
            daemon=True
        ).start()

# ==============================
# 일시정지/재개
# ==============================
def toggle_pause():
    global auto_paused
    auto_paused = not auto_paused
    status = "일시정지됨" if auto_paused else "재개됨"
    print(f"자동 번역 {status}")

# ==============================
# 단축키 처리
# ==============================
def handle_hotkey():
    if mode_auto_translate.get():
        start_auto_translate()
    else:
        start_select_translate()

# ==============================
# 전역 단축키 리스너
# ==============================
def hotkey_listener():
    # Ctrl + Shift + 1: 선택 번역 모드로 전환
    win32gui.RegisterHotKey(None, 1, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("1"))
    # Ctrl + Shift + 2: 자동 번역 모드로 전환
    win32gui.RegisterHotKey(None, 2, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("2"))
    # Ctrl + Shift + T: 영역 선택 및 번역 실행
    win32gui.RegisterHotKey(None, 3, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("T"))
    # Ctrl + Shift + P: 일시정지/재개
    win32gui.RegisterHotKey(None, 4, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("P"))
    # Ctrl + Shift + M: 여러 영역 번역
    win32gui.RegisterHotKey(None, 5, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("M"))
    # Ctrl + Shift + R: 영역 표시 제거
    win32gui.RegisterHotKey(None, 6, win32con.MOD_CONTROL | win32con.MOD_SHIFT, ord("R"))
    
    try:
        while True:
            msg = win32gui.GetMessage(None, 0, 0)
            if msg[1][1] == win32con.WM_HOTKEY:
                if msg[1][2] == 1:  # Ctrl+Shift+1
                    root.after(0, switch_to_select_mode)
                elif msg[1][2] == 2:  # Ctrl+Shift+2
                    root.after(0, switch_to_auto_mode)
                elif msg[1][2] == 3:  # Ctrl+Shift+T
                    root.after(0, execute_current_mode)
                elif msg[1][2] == 4:  # Ctrl+Shift+P
                    root.after(0, toggle_pause)
                elif msg[1][2] == 5:  # Ctrl+Shift+M
                    root.after(0, start_multi_translate)
                elif msg[1][2] == 6:  # Ctrl+Shift+R
                    root.after(0, remove_region_display)
    finally:
        win32gui.UnregisterHotKey(None, 1)
        win32gui.UnregisterHotKey(None, 2)
        win32gui.UnregisterHotKey(None, 3)
        win32gui.UnregisterHotKey(None, 4)
        win32gui.UnregisterHotKey(None, 5)
        win32gui.UnregisterHotKey(None, 6)

# ==============================
# 모드 전환
# ==============================
def stop_auto():
    global auto_running, auto_region, auto_session_id, auto_paused, last_image_hash
    global multi_auto_running, multi_auto_session_id
    
    auto_running = False
    auto_paused = False
    auto_region = None
    auto_session_id += 1
    last_image_hash = ""
    
    multi_auto_running = False
    multi_auto_session_id += 1
    
    remove_overlay()
    remove_multi_overlays()
    remove_region_display()

def switch_to_select_mode():
    """선택 번역 모드로 전환만"""
    stop_auto()
    mode_select_translate.set(True)
    mode_auto_translate.set(False)
    print("선택 번역 모드로 전환됨 (Ctrl+Shift+T로 영역 선택)")

def switch_to_auto_mode():
    """자동 번역 모드로 전환만"""
    stop_auto()
    mode_select_translate.set(False)
    mode_auto_translate.set(True)
    print("자동 번역 모드로 전환됨 (Ctrl+Shift+T로 영역 선택)")

def execute_current_mode():
    """현재 모드에 따라 번역 실행"""
    if mode_auto_translate.get():
        start_auto_translate()
    else:
        start_select_translate()

def toggle_select_mode():
    """체크박스로 선택 모드 전환"""
    if mode_select_translate.get():
        stop_auto()
        mode_auto_translate.set(False)
    else:
        mode_select_translate.set(True)

def toggle_auto_mode():
    """체크박스로 자동 모드 전환"""
    if mode_auto_translate.get():
        stop_auto()
        mode_select_translate.set(False)
    else:
        mode_auto_translate.set(True)

# ==============================
# 메인 GUI
# ==============================
def main():
    global root, mode_select_translate, mode_auto_translate
    
    root = tk.Tk()
    root.title("OCR Translator - Enhanced")
    root.geometry("500x420")
    root.resizable(True, True)
    
    mode_select_translate = tk.BooleanVar(value=True)
    mode_auto_translate = tk.BooleanVar(value=False)
    
    tk.Label(
        root,
        text="OCR 번역 모드",
        font=("Malgun Gothic", 13, "bold")
    ).pack(pady=10)
    
    tk.Checkbutton(
        root,
        text="선택 번역 모드 (한 번만 번역)",
        variable=mode_select_translate,
        command=toggle_select_mode,
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=30)
    
    tk.Checkbutton(
        root,
        text="자동 번역 모드 (1초마다 계속 번역)",
        variable=mode_auto_translate,
        command=toggle_auto_mode,
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=30, pady=5)
    
    tk.Label(
        root,
        text="\n모드 전환 단축키:",
        font=("Malgun Gothic", 11, "bold")
    ).pack(anchor="w", padx=30)
    
    tk.Label(
        root,
        text="🔢 Ctrl + Shift + 1: 선택 번역 모드로 전환",
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="🔢 Ctrl + Shift + 2: 자동 번역 모드로 전환",
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="\n실행 단축키:",
        font=("Malgun Gothic", 11, "bold")
    ).pack(anchor="w", padx=30)
    
    tk.Label(
        root,
        text="▶ Ctrl + Shift + T: 영역 선택 및 번역 실행",
        font=("Malgun Gothic", 10),
        fg="blue"
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="\n추가 기능:",
        font=("Malgun Gothic", 11, "bold")
    ).pack(anchor="w", padx=30)
    
    tk.Label(
        root,
        text="⏸ Ctrl + Shift + P: 자동 번역 일시정지/재개",
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="📌 Ctrl + Shift + M: 여러 영역 번역 (모드에 따라 동작)",
        font=("Malgun Gothic", 10)
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="❌ Ctrl + Shift + R: 영역 표시 제거",
        font=("Malgun Gothic", 10),
        fg="red"
    ).pack(anchor="w", padx=40)
    
    tk.Label(
        root,
        text="\n※ 선택된 영역은 빨간 테두리로 표시됩니다",
        font=("Malgun Gothic", 9),
        fg="gray"
    ).pack(anchor="w", padx=30)
    
    tk.Label(
        root,
        text="※ 선택 모드: 5초 후 자동 제거 | 자동 모드: 이동/닫기 가능",
        font=("Malgun Gothic", 9),
        fg="gray"
    ).pack(anchor="w", padx=30)
    
    tk.Label(
        root,
        text="\n※ OCR 텍스트 변경 감지 최적화 적용됨",
        font=("Malgun Gothic", 9),
        fg="blue"
    ).pack(anchor="w", padx=30)
    
    threading.Thread(
        target=hotkey_listener,
        daemon=True
    ).start()
    
    root.mainloop()

if __name__ == "__main__":
    main()