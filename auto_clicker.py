"""滑鼠連點小工具 1.0（Windows 用）。

按一下自訂快捷鍵就開始連點，再按一下停止；另有緊急停止鍵（預設 Esc）。
只用 pynput 同時做全域快捷鍵監聽與滑鼠點擊，不用 pyautogui。
點擊迴圈放 daemon 執行緒，用 Event 停止；關掉視窗就完全停止。

設定存在程式旁邊的 auto_clicker_config.json，下次開啟自動載入。
"""

import json
import os
import threading
import time

try:
    from pynput import keyboard, mouse
except Exception:  # 未安裝 pynput 時仍可 import 與測試純函式
    keyboard = None
    mouse = None

CONFIG_FILENAME = 'auto_clicker_config.json'
MIN_INTERVAL_MS = 10
MAX_INTERVAL_MS = 3600000

DEFAULT_CONFIG = {
    'hotkey': 'F6',
    'emergency_key': 'Esc',
    'interval_ms': 100,
    'button': 'left',
    'click_type': 'single',
    'position_mode': 'current',
    'fixed_x': 0,
    'fixed_y': 0,
    'stop_mode': 'infinite',
    'stop_count': 100,
    'stop_seconds': 60,
    'always_on_top': True,
}

BUTTONS = ('left', 'right', 'middle')
BUTTON_LABELS = {'left': '左鍵', 'right': '右鍵', 'middle': '中鍵'}
CLICK_TYPES = ('single', 'double')
CLICK_TYPE_LABELS = {'single': '單擊', 'double': '雙擊'}
POSITION_MODES = ('current', 'fixed')
STOP_MODES = ('infinite', 'count', 'time')

# 修飾鍵別名 -> 標準名
_MODIFIER_ALIASES = {
    'control': 'ctrl', 'ctrl': 'ctrl',
    'alt': 'alt', 'option': 'alt',
    'shift': 'shift',
    'win': 'win', 'cmd': 'win', 'command': 'win', 'meta': 'win', 'super': 'win',
    'esc': 'esc', 'escape': 'esc',
    'space': 'space', 'spacebar': 'space',
    'enter': 'enter', 'return': 'enter',
    'tab': 'tab',
    'backspace': 'backspace',
    'delete': 'delete',
    'up': 'up', 'down': 'down', 'left': 'left', 'right': 'right',
    'home': 'home', 'end': 'end', 'pageup': 'pageup', 'pagedown': 'pagedown',
    'insert': 'insert',
    'capslock': 'capslock',
    'numlock': 'numlock',
    'scrolllock': 'scrolllock',
    'printscreen': 'printscreen',
    'pause': 'pause',
    'menu': 'menu',
}

# 顯示順序：修飾鍵在前，主鍵在後
_MODIFIER_ORDER = ('ctrl', 'alt', 'shift', 'win')


def _normalize_key_name(name):
    """單一按鍵名稱正規化：小寫、去空白、別名統一。"""
    if name is None:
        return ''
    name = str(name).strip().lower()
    if not name:
        return ''
    return _MODIFIER_ALIASES.get(name, name)


def parse_hotkey(text):
    """快捷鍵字串 -> 按鍵集合（frozenset）。

    例：'F6' -> frozenset({'f6'})、'Ctrl+Alt+X' -> {'ctrl','alt','x'}。
    大小寫、空白、別名（Control/Cmd/Escape）都接受；空字串回空集合。
    """
    if not text:
        return frozenset()
    parts = [p for p in (str(text).split('+')) if p.strip()]
    keys = set()
    for part in parts:
        name = _normalize_key_name(part)
        if name:
            keys.add(name)
    return frozenset(keys)


def format_hotkey(keys):
    """按鍵集合 -> 顯示字串，修飾鍵在前、主鍵在後。

    例：{'alt','ctrl','x'} -> 'Ctrl+Alt+X'、{'f6'} -> 'F6'。
    """
    if not keys:
        return ''
    keys = {_normalize_key_name(k) for k in keys if _normalize_key_name(k)}
    ordered = [k for k in _MODIFIER_ORDER if k in keys]
    rest = sorted(k for k in keys if k not in _MODIFIER_ORDER)
    all_keys = ordered + rest
    out = []
    for k in all_keys:
        if k == 'ctrl':
            out.append('Ctrl')
        elif k == 'alt':
            out.append('Alt')
        elif k == 'shift':
            out.append('Shift')
        elif k == 'win':
            out.append('Win')
        elif k == 'esc':
            out.append('Esc')
        elif k == 'space':
            out.append('Space')
        elif len(k) == 1:
            out.append(k.upper())
        elif k.startswith('f') and k[1:].isdigit():
            out.append(k.upper())
        else:
            out.append(k.capitalize())
    return '+'.join(out)


def validate_interval(value):
    """檢查間隔毫秒：必須是整數，10～3600000 之間；低於 10 要擋下。

    回傳 int；不合法時 raise ValueError（訊息為中文）。
    """
    if isinstance(value, bool):
        raise ValueError('間隔必須是整數毫秒')
    try:
        ms = int(value)
    except (TypeError, ValueError):
        raise ValueError('間隔必須是整數毫秒')
    if isinstance(value, float) and not float(value).is_integer():
        raise ValueError('間隔必須是整數毫秒')
    if ms < MIN_INTERVAL_MS:
        raise ValueError(f'間隔最少 {MIN_INTERVAL_MS} 毫秒（每秒最多 100 下），請調大一點')
    if ms > MAX_INTERVAL_MS:
        raise ValueError(f'間隔最多 {MAX_INTERVAL_MS} 毫秒')
    return ms


def validate_button(value):
    """檢查按鍵：left / right / middle，不合法 raise ValueError。"""
    value = str(value or '').strip().lower()
    if value not in BUTTONS:
        raise ValueError('點擊按鍵必須是 left / right / middle')
    return value


def validate_click_type(value):
    """檢查點擊方式：single / double，不合法 raise ValueError。"""
    value = str(value or '').strip().lower()
    if value not in CLICK_TYPES:
        raise ValueError('點擊方式必須是 single / double')
    return value


def should_stop(clicks, elapsed_seconds, stop_mode, limit):
    """判斷點擊迴圈是否該停止（純函式，不碰滑鼠）。

    stop_mode：'infinite' 永遠不自動停；'count' 點滿 limit 下就停；
    'time' 跑滿 limit 秒就停。limit 為 None 或 <= 0 時視為無限制。
    """
    if stop_mode not in STOP_MODES:
        return False
    if stop_mode == 'infinite':
        return False
    if limit is None:
        return False
    try:
        limit = float(limit)
    except (TypeError, ValueError):
        return False
    if limit <= 0:
        return False
    if stop_mode == 'count':
        return clicks >= limit
    if stop_mode == 'time':
        return elapsed_seconds >= limit
    return False


def load_config(path=None):
    """讀設定檔；檔案不存在或損壞時回傳預設值（絕不拋錯）。"""
    cfg = dict(DEFAULT_CONFIG)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            CONFIG_FILENAME)
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return cfg
        for key, default in DEFAULT_CONFIG.items():
            if key in data:
                cfg[key] = data[key]
        # 基本防呆：壞值用預設值取代
        try:
            cfg['interval_ms'] = validate_interval(cfg['interval_ms'])
        except ValueError:
            cfg['interval_ms'] = DEFAULT_CONFIG['interval_ms']
        try:
            cfg['button'] = validate_button(cfg['button'])
        except ValueError:
            cfg['button'] = DEFAULT_CONFIG['button']
        try:
            cfg['click_type'] = validate_click_type(cfg['click_type'])
        except ValueError:
            cfg['click_type'] = DEFAULT_CONFIG['click_type']
        if cfg['position_mode'] not in POSITION_MODES:
            cfg['position_mode'] = DEFAULT_CONFIG['position_mode']
        if cfg['stop_mode'] not in STOP_MODES:
            cfg['stop_mode'] = DEFAULT_CONFIG['stop_mode']
        if not parse_hotkey(cfg.get('hotkey') or ''):
            cfg['hotkey'] = DEFAULT_CONFIG['hotkey']
        cfg['always_on_top'] = bool(cfg.get('always_on_top', True))
    except Exception:
        return dict(DEFAULT_CONFIG)
    return cfg


def save_config(cfg, path=None):
    """寫設定檔；只存已知欄位。回傳 True/False（失敗不拋錯）。"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            CONFIG_FILENAME)
    data = {key: cfg.get(key, DEFAULT_CONFIG[key]) for key in DEFAULT_CONFIG}
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def _pynput_key_to_name(key):
    """把 pynput 的按鍵物件轉成正規化名稱；無法辨識回 ''。"""
    if keyboard is None:
        return ''
    try:
        if isinstance(key, keyboard.Key):
            return _normalize_key_name(key.name or '')
        if isinstance(key, keyboard.KeyCode):
            if key.char:
                return _normalize_key_name(key.char)
            if key.vk is not None:
                # F1–F12 的 virtual key code 是 112–123
                if 112 <= key.vk <= 123:
                    return f'f{key.vk - 111}'
            return ''
    except Exception:
        return ''
    return ''


class AutoClicker:
    """點擊引擎（不含 Tkinter，可獨立測試邏輯）。

    click_fn 由外部注入（預設用 pynput 的滑鼠），測試時可換成假函式。
    """

    def __init__(self, config=None, click_fn=None):
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self.click_fn = click_fn
        self.clicks = 0
        self.running = False
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._mouse = None

    def _default_click(self):
        if mouse is None:
            raise RuntimeError('尚未安裝 pynput，請先執行：pip install pynput')
        if self._mouse is None:
            self._mouse = mouse.Controller()
        button = {
            'left': mouse.Button.left,
            'right': mouse.Button.right,
            'middle': mouse.Button.middle,
        }[self.config['button']]
        count = 2 if self.config['click_type'] == 'double' else 1
        if self.config['position_mode'] == 'fixed':
            self._mouse.position = (int(self.config['fixed_x']),
                                    int(self.config['fixed_y']))
        self._mouse.click(button, count)

    def start(self):
        """開始連點；已在跑時回 False。"""
        with self._lock:
            if self.running:
                return False
            self._stop_event.clear()
            self.clicks = 0
            self.running = True
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
            return True

    def stop(self):
        """停止連點；沒在跑時回 False。"""
        with self._lock:
            if not self.running:
                return False
            self._stop_event.set()
            self.running = False
            return True

    def _loop(self):
        interval = self.config['interval_ms'] / 1000.0
        stop_mode = self.config['stop_mode']
        if stop_mode == 'count':
            limit = self.config.get('stop_count', 0)
        elif stop_mode == 'time':
            limit = self.config.get('stop_seconds', 0)
        else:
            limit = None
        start_time = time.monotonic()
        click_fn = self.click_fn or self._default_click
        while not self._stop_event.is_set():
            try:
                click_fn()
            except Exception:
                break
            with self._lock:
                self.clicks += 1
                clicks = self.clicks
            elapsed = time.monotonic() - start_time
            if should_stop(clicks, elapsed, stop_mode, limit):
                break
            self._stop_event.wait(interval)
        with self._lock:
            self.running = False


def main():
    import tkinter as tk
    from tkinter import ttk, messagebox

    if keyboard is None or mouse is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            '缺少 pynput',
            '尚未安裝 pynput，請先在終端機執行：\n\npip install -r requirements.txt')
        root.destroy()
        return

    cfg = load_config()
    engine = AutoClicker(cfg)
    mouse_controller = mouse.Controller()

    root = tk.Tk()
    root.title('滑鼠連點小工具 1.0')
    root.resizable(False, False)
    if cfg.get('always_on_top', True):
        root.attributes('-topmost', True)

    status_var = tk.StringVar(value='已停止')
    clicks_var = tk.StringVar(value='已點：0 下')
    hotkey_var = tk.StringVar(value=cfg['hotkey'])
    emergency_var = tk.StringVar(value=cfg['emergency_key'])
    interval_var = tk.IntVar(value=cfg['interval_ms'])
    button_var = tk.StringVar(value=BUTTON_LABELS[cfg['button']])
    click_type_var = tk.StringVar(value=CLICK_TYPE_LABELS[cfg['click_type']])
    position_var = tk.StringVar(value=cfg['position_mode'])
    fixed_x_var = tk.IntVar(value=cfg['fixed_x'])
    fixed_y_var = tk.IntVar(value=cfg['fixed_y'])
    stop_mode_var = tk.StringVar(value=cfg['stop_mode'])
    stop_count_var = tk.IntVar(value=cfg['stop_count'])
    stop_seconds_var = tk.IntVar(value=cfg['stop_seconds'])
    topmost_var = tk.BooleanVar(value=cfg.get('always_on_top', True))
    capturing = {'target': None}  # 'hotkey' / 'emergency' / None

    def current_config():
        return {
            'hotkey': hotkey_var.get(),
            'emergency_key': emergency_var.get(),
            'interval_ms': interval_var.get(),
            'button': {v: k for k, v in BUTTON_LABELS.items()}[button_var.get()],
            'click_type': {v: k for k, v in CLICK_TYPE_LABELS.items()}[click_type_var.get()],
            'position_mode': position_var.get(),
            'fixed_x': fixed_x_var.get(),
            'fixed_y': fixed_y_var.get(),
            'stop_mode': stop_mode_var.get(),
            'stop_count': stop_count_var.get(),
            'stop_seconds': stop_seconds_var.get(),
            'always_on_top': topmost_var.get(),
        }

    def save_current_config():
        engine.config.update(current_config())
        save_config(engine.config)

    def refresh_status():
        if engine.running:
            status_var.set('執行中…（再按一次快捷鍵停止）')
        else:
            status_var.set('已停止')
        clicks_var.set(f'已點：{engine.clicks} 下')
        info_var.set(f"快捷鍵：{hotkey_var.get()}　間隔：{interval_var.get()} 毫秒　"
                     f"{button_var.get()} {click_type_var.get()}")
        root.after(200, refresh_status)

    def toggle_clicking():
        if engine.running:
            engine.stop()
            save_current_config()
        else:
            try:
                interval_var.set(validate_interval(interval_var.get()))
            except ValueError as exc:
                messagebox.showwarning('間隔錯誤', str(exc))
                return
            engine.config.update(current_config())
            save_current_config()
            engine.start()

    def stop_clicking():
        if engine.running:
            engine.stop()
            save_current_config()

    # ── 全域快捷鍵監聽 ──
    pressed = set()
    hotkey_fired = {'value': False}

    def on_press(key):
        name = _pynput_key_to_name(key)
        if not name:
            return
        if capturing['target']:
            if name == 'esc':
                capturing['target'] = None
                set_btn.config(text='設定快捷鍵')
                set_emergency_btn.config(text='設定緊急停止鍵')
                status_var.set('已取消設定')
                return
            pressed.add(name)
            return
        pressed.add(name)
        # 緊急停止鍵：單獨按 Esc 就停（優先於開關）
        emergency = parse_hotkey(emergency_var.get())
        if emergency and emergency <= pressed and engine.running:
            stop_clicking()
            pressed.clear()
            return
        target = parse_hotkey(hotkey_var.get())
        if target and target <= pressed and not hotkey_fired['value']:
            hotkey_fired['value'] = True
            root.after(0, toggle_clicking)

    def on_release(key):
        name = _pynput_key_to_name(key)
        if capturing['target'] and pressed:
            target = capturing['target']
            text = format_hotkey(pressed)
            if target == 'hotkey':
                hotkey_var.set(text)
            else:
                emergency_var.set(text)
            capturing['target'] = None
            set_btn.config(text='設定快捷鍵')
            set_emergency_btn.config(text='設定緊急停止鍵')
            save_current_config()
            pressed.clear()
            return
        if name in pressed:
            pressed.discard(name)
        if not pressed:
            hotkey_fired['value'] = False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    # ── 介面 ──
    outer = ttk.Frame(root, padding=12)
    outer.pack(fill='both', expand=True)

    ttk.Label(outer, text='滑鼠連點小工具', font=('Arial', 18, 'bold')).pack(anchor='w')
    ttk.Label(outer, text='按一下快捷鍵開始連點，再按一下停止；Esc 可隨時緊急停止。',
              foreground='gray').pack(anchor='w', pady=(0, 8))

    # 快捷鍵
    hk_frame = ttk.LabelFrame(outer, text='快捷鍵', padding=8)
    hk_frame.pack(fill='x', pady=4)
    ttk.Label(hk_frame, text='開關快捷鍵：').grid(row=0, column=0, sticky='w')
    ttk.Entry(hk_frame, textvariable=hotkey_var, width=14, state='readonly').grid(
        row=0, column=1, sticky='w')
    set_btn = ttk.Button(hk_frame, text='設定快捷鍵')
    set_btn.grid(row=0, column=2, padx=6)
    ttk.Label(hk_frame, text='緊急停止鍵：').grid(row=1, column=0, sticky='w', pady=4)
    ttk.Entry(hk_frame, textvariable=emergency_var, width=14, state='readonly').grid(
        row=1, column=1, sticky='w', pady=4)
    set_emergency_btn = ttk.Button(hk_frame, text='設定緊急停止鍵')
    set_emergency_btn.grid(row=1, column=2, padx=6, pady=4)

    def begin_capture(target):
        capturing['target'] = target
        pressed.clear()
        status_var.set('請按下要設定的按鍵（Esc 取消）…')
        if target == 'hotkey':
            set_btn.config(text='按鍵中…')
        else:
            set_emergency_btn.config(text='按鍵中…')

    set_btn.config(command=lambda: begin_capture('hotkey'))
    set_emergency_btn.config(command=lambda: begin_capture('emergency'))

    # 點擊設定
    cfg_frame = ttk.LabelFrame(outer, text='點擊設定', padding=8)
    cfg_frame.pack(fill='x', pady=4)
    ttk.Label(cfg_frame, text='間隔（毫秒）：').grid(row=0, column=0, sticky='w')
    ttk.Spinbox(cfg_frame, from_=10, to=3600000, increment=10,
                textvariable=interval_var, width=10).grid(row=0, column=1, sticky='w')
    ttk.Label(cfg_frame, text='（最少 10 毫秒）').grid(row=0, column=2, sticky='w')
    ttk.Label(cfg_frame, text='按鍵：').grid(row=1, column=0, sticky='w', pady=4)
    ttk.Combobox(cfg_frame, textvariable=button_var,
                 values=list(BUTTON_LABELS.values()),
                 state='readonly', width=8).grid(row=1, column=1, sticky='w', pady=4)
    ttk.Label(cfg_frame, text='方式：').grid(row=1, column=2, sticky='w', pady=4)
    ttk.Combobox(cfg_frame, textvariable=click_type_var,
                 values=list(CLICK_TYPE_LABELS.values()),
                 state='readonly', width=8).grid(row=1, column=3, sticky='w', pady=4)
    ttk.Radiobutton(cfg_frame, text='目前滑鼠位置', variable=position_var,
                    value='current').grid(row=2, column=0, columnspan=2, sticky='w')
    ttk.Radiobutton(cfg_frame, text='固定座標：', variable=position_var,
                    value='fixed').grid(row=3, column=0, sticky='w')
    coord_frame = ttk.Frame(cfg_frame)
    coord_frame.grid(row=3, column=1, columnspan=3, sticky='w')
    ttk.Label(coord_frame, text='X').pack(side='left')
    ttk.Spinbox(coord_frame, from_=0, to=10000, textvariable=fixed_x_var,
                width=6).pack(side='left')
    ttk.Label(coord_frame, text='Y').pack(side='left', padx=(6, 0))
    ttk.Spinbox(coord_frame, from_=0, to=10000, textvariable=fixed_y_var,
                width=6).pack(side='left')
    ttk.Button(coord_frame, text='記錄目前位置', command=lambda: (
        fixed_x_var.set(mouse_controller.position[0]),
        fixed_y_var.set(mouse_controller.position[1]),
        position_var.set('fixed'))).pack(side='left', padx=6)

    # 停止條件
    stop_frame = ttk.LabelFrame(outer, text='停止條件', padding=8)
    stop_frame.pack(fill='x', pady=4)
    ttk.Radiobutton(stop_frame, text='無限連點（按快捷鍵停止）',
                    variable=stop_mode_var, value='infinite').pack(anchor='w')
    row_c = ttk.Frame(stop_frame)
    row_c.pack(anchor='w', fill='x')
    ttk.Radiobutton(row_c, text='點', variable=stop_mode_var,
                    value='count').pack(side='left')
    ttk.Spinbox(row_c, from_=1, to=1000000, textvariable=stop_count_var,
                width=8).pack(side='left', padx=2)
    ttk.Label(row_c, text='下就停').pack(side='left')
    row_t = ttk.Frame(stop_frame)
    row_t.pack(anchor='w', fill='x')
    ttk.Radiobutton(row_t, text='跑', variable=stop_mode_var,
                    value='time').pack(side='left')
    ttk.Spinbox(row_t, from_=1, to=86400, textvariable=stop_seconds_var,
                width=8).pack(side='left', padx=2)
    ttk.Label(row_t, text='秒就停').pack(side='left')

    # 控制與狀態
    btn_frame = ttk.Frame(outer)
    btn_frame.pack(fill='x', pady=8)
    start_btn = ttk.Button(btn_frame, text='開始連點', command=toggle_clicking)
    start_btn.pack(side='left', padx=(0, 6))
    ttk.Button(btn_frame, text='停止', command=stop_clicking).pack(side='left')
    ttk.Checkbutton(btn_frame, text='視窗永遠在最上層', variable=topmost_var,
                    command=lambda: root.attributes(
                        '-topmost', topmost_var.get())).pack(side='right')

    info_var = tk.StringVar()
    ttk.Label(outer, textvariable=status_var, font=('Arial', 12, 'bold')).pack(anchor='w')
    ttk.Label(outer, textvariable=clicks_var).pack(anchor='w')
    ttk.Label(outer, textvariable=info_var, foreground='gray').pack(anchor='w')
    ttk.Label(outer, text='注意：請勿在遊戲或不允許自動操作的程式中使用；'
              '關掉視窗就會完全停止。', foreground='gray').pack(anchor='w', pady=(6, 0))

    def on_close():
        engine.stop()
        save_current_config()
        try:
            listener.stop()
        except Exception:
            pass
        root.destroy()

    root.protocol('WM_DELETE_WINDOW', on_close)
    refresh_status()
    root.mainloop()


if __name__ == '__main__':
    main()
