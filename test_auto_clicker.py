"""滑鼠連點小工具純函式測試（不需 pytest，直接 python3 test_auto_clicker.py）。

只測不需滑鼠、不需 Tkinter、不需全域快捷鍵的純函式與引擎邏輯：
快捷鍵解析、間隔檢查、停止判斷、設定檔讀寫、點擊引擎（用假點擊函式）。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import auto_clicker
from auto_clicker import (
    AutoClicker, DEFAULT_CONFIG,
    parse_hotkey, format_hotkey,
    validate_interval, validate_button, validate_click_type,
    should_stop, load_config, save_config,
)


def test_parse_hotkey_single():
    assert parse_hotkey('F6') == frozenset({'f6'})
    assert parse_hotkey('f8') == frozenset({'f8'})
    assert parse_hotkey('  X  ') == frozenset({'x'})


def test_parse_hotkey_combo_aliases():
    assert parse_hotkey('Ctrl+Alt+X') == frozenset({'ctrl', 'alt', 'x'})
    # 別名與大小寫：Control=Ctl、Cmd=Win、Escape=Esc
    assert parse_hotkey('Control+Shift+F9') == frozenset({'ctrl', 'shift', 'f9'})
    assert parse_hotkey('cmd+alt+a') == frozenset({'win', 'alt', 'a'})
    assert parse_hotkey('Escape') == frozenset({'esc'})


def test_parse_hotkey_empty():
    assert parse_hotkey('') == frozenset()
    assert parse_hotkey(None) == frozenset()
    assert parse_hotkey('   ') == frozenset()


def test_format_hotkey_round_trip():
    assert format_hotkey(parse_hotkey('F6')) == 'F6'
    assert format_hotkey(parse_hotkey('Ctrl+Alt+X')) == 'Ctrl+Alt+X'
    # 修飾鍵在前、主鍵在後，不論輸入順序
    assert format_hotkey({'x', 'alt', 'ctrl'}) == 'Ctrl+Alt+X'
    assert format_hotkey(parse_hotkey('Shift+F12')) == 'Shift+F12'


def test_format_hotkey_empty():
    assert format_hotkey(set()) == ''
    assert format_hotkey(frozenset()) == ''


def test_validate_interval_valid():
    assert validate_interval(100) == 100
    assert validate_interval(10) == 10  # 下限剛好可接受
    assert validate_interval('250') == 250


def test_validate_interval_below_minimum():
    for bad in (0, 1, 9, -5):
        try:
            validate_interval(bad)
            raise AssertionError(f'間隔 {bad} 毫秒應被擋下')
        except ValueError as exc:
            assert '10' in str(exc), str(exc)


def test_validate_interval_non_integer():
    for bad in ('abc', None, 1.5, True):
        try:
            validate_interval(bad)
            raise AssertionError(f'間隔 {bad!r} 應報錯')
        except ValueError:
            pass


def test_validate_button_and_click_type():
    assert validate_button('left') == 'left'
    assert validate_button('RIGHT') == 'right'
    assert validate_click_type('double') == 'double'
    for bad_fn, bad in ((validate_button, 'up'), (validate_click_type, 'triple')):
        try:
            bad_fn(bad)
            raise AssertionError(f'{bad!r} 應報錯')
        except ValueError:
            pass


def test_should_stop_infinite():
    assert should_stop(100000, 9999, 'infinite', None) is False
    assert should_stop(0, 0, 'infinite', 10) is False


def test_should_stop_count():
    assert should_stop(99, 0, 'count', 100) is False
    assert should_stop(100, 0, 'count', 100) is True
    assert should_stop(150, 0, 'count', 100) is True
    assert should_stop(10, 0, 'count', None) is False
    assert should_stop(10, 0, 'count', 0) is False


def test_should_stop_time():
    assert should_stop(0, 59.9, 'time', 60) is False
    assert should_stop(0, 60, 'time', 60) is True
    assert should_stop(0, 120, 'time', 60) is True
    assert should_stop(0, 10, 'unknown_mode', 10) is False


def test_load_config_missing_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load_config(os.path.join(tmp, 'no-such-file.json'))
        assert cfg == DEFAULT_CONFIG
        assert cfg['hotkey'] == 'F6'
        assert cfg['interval_ms'] == 100


def test_load_config_corrupt_file_returns_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'bad.json')
        Path(path).write_text('這不是 json {', encoding='utf-8')
        assert load_config(path) == DEFAULT_CONFIG
        Path(path).write_text('[]', encoding='utf-8')
        assert load_config(path) == DEFAULT_CONFIG


def test_save_and_load_config_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'cfg.json')
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({'hotkey': 'Ctrl+Alt+X', 'interval_ms': 250,
                    'button': 'right', 'click_type': 'double',
                    'position_mode': 'fixed', 'fixed_x': 123, 'fixed_y': 456,
                    'stop_mode': 'count', 'stop_count': 50})
        assert save_config(cfg, path) is True
        loaded = load_config(path)
        for key, value in cfg.items():
            assert loaded[key] == value, (key, loaded[key], value)


def test_load_config_bad_values_fall_back_to_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'cfg.json')
        Path(path).write_text(json.dumps(
            {'interval_ms': 5, 'button': 'up', 'hotkey': ''}),
            encoding='utf-8')
        cfg = load_config(path)
        assert cfg['interval_ms'] == 100
        assert cfg['button'] == 'left'
        assert cfg['hotkey'] == 'F6'


def test_engine_stops_after_count_limit():
    calls = []

    def fake_click():
        calls.append(1)

    cfg = dict(DEFAULT_CONFIG)
    cfg.update({'interval_ms': 10, 'stop_mode': 'count', 'stop_count': 5})
    engine = AutoClicker(cfg, click_fn=fake_click)
    assert engine.start() is True
    assert engine.start() is False  # 已在跑，不能重複開始
    deadline = time.time() + 5
    while engine.running and time.time() < deadline:
        time.sleep(0.02)
    assert engine.running is False
    assert engine.clicks == 5, engine.clicks
    assert len(calls) == 5


def test_engine_stop_before_limit():
    calls = []

    def fake_click():
        calls.append(1)

    cfg = dict(DEFAULT_CONFIG)
    cfg.update({'interval_ms': 10, 'stop_mode': 'infinite'})
    engine = AutoClicker(cfg, click_fn=fake_click)
    assert engine.stop() is False  # 沒在跑，停止回 False
    assert engine.start() is True
    time.sleep(0.15)
    assert engine.stop() is True
    time.sleep(0.05)
    assert engine.running is False
    assert engine.clicks >= 1
    assert engine.clicks == len(calls)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for fn in tests:
        fn()
        print(f'PASS {fn.__name__}')
    print(f'全部通過：{len(tests)} 個測試')


if __name__ == '__main__':
    main()
