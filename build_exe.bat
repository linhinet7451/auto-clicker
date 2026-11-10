@echo off
chcp 65001 >nul
REM 滑鼠連點小工具：Windows 上雙擊此檔即可打包出 dist\AutoClicker.exe
REM 需要先安裝 Python 3.11 以上，並確認 python / pip 在 PATH 裡。

echo 正在安裝依賴（pynput、PyInstaller）…
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo 安裝失敗，請確認 Python 與網路連線。
    pause
    exit /b 1
)

echo 正在打包成 EXE…
python -m PyInstaller --onefile --windowed --name AutoClicker auto_clicker.py
if errorlevel 1 (
    echo 打包失敗。
    pause
    exit /b 1
)

echo.
echo 打包完成：dist\AutoClicker.exe
echo 直接雙擊 dist\AutoClicker.exe 即可使用，不需再安裝 Python。
pause
