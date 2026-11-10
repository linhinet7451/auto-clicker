# 滑鼠連點小工具

按一下自訂快捷鍵就開始連點，再按一下停止；Esc 可隨時緊急停止。
Windows 用，Python + Tkinter 單檔程式，只用 `pynput` 做全域快捷鍵監聽與滑鼠點擊。

## 用法

```bash
pip install -r requirements.txt
python auto_clicker.py
```

1. **設定快捷鍵**：預設 `F6`。按「設定快捷鍵」，再按你要的鍵（單鍵如 F8，或組合鍵如 Ctrl+Alt+X）即可改；按 Esc 取消設定。同一鍵按一下開始、再按一下停止。
2. **緊急停止鍵**：預設 `Esc`，執行中隨時按一下就停。
3. **點擊設定**：間隔毫秒（預設 100，最少 10）、左鍵／右鍵／中鍵、單擊／雙擊。
4. **點擊位置**：「目前滑鼠位置」就是滑鼠在哪點哪；選「固定座標」可按「記錄目前位置」存下目前座標。
5. **停止條件**：無限連點、點 N 下就停、跑 N 秒就停，三選一。
6. 狀態列會顯示執行中／已停止、已點幾下、目前快捷鍵與間隔；可勾選「視窗永遠在最上層」。
7. 設定會自動存到程式旁邊的 `auto_clicker_config.json`，下次開啟自動載入（此檔案不進 git）。

## 打包成 EXE

**重要限制：Linux 上無法直接產出 Windows EXE**，PyInstaller 不支援跨平台打包，
所以 EXE 要用下面兩種方式之一取得：

### 方法一：在 Windows 上跑批次檔（最簡單）

在 Windows 電腦上，雙擊 `build_exe.bat`，它會自動安裝依賴與 PyInstaller，
打包完成後產出 `dist\AutoClicker.exe`，雙擊就能用，不需再安裝 Python。

### 方法二：從 GitHub Actions 下載

把專案 push 到 GitHub 後，Actions 會在 `windows-latest` 上自動打包，
到 Actions 頁面下載 artifact `AutoClicker-Windows`（裡面就是 `AutoClicker.exe`）。
本專案不做自動發 release。

## 注意

- 請勿在遊戲或不允許自動操作的程式中使用；關掉視窗就會完全停止。
- 間隔最少 10 毫秒（每秒最多 100 下），低於 10 會被擋下並提示。
- 第一次執行時，防毒軟體或 Windows SmartScreen 可能會跳出警告，
  因為這是未簽名的自製程式，請自行確認後再允許執行。

## 測試

```bash
python3 test_auto_clicker.py
```

只測純函式（快捷鍵解析、間隔檢查、停止判斷、設定檔讀寫、點擊引擎用假點擊函式），
不真的點滑鼠、不啟動 Tkinter、不監聽全域快捷鍵。
真的滑鼠點擊、全域快捷鍵、Windows EXE 產出無法在 Linux VM 驗證，
請在 Windows 電腦上實測。
