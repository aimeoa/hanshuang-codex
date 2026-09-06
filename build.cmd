@echo off
echo Building 富江注入工具 EXE ...
pip install pyinstaller PySide6 -q
pyinstaller fj_tool.spec --noconfirm --clean
if exist dist\富江注入工具\富江注入工具.exe (
    echo BUILD SUCCESS: dist\富江注入工具\富江注入工具.exe
) else (
    echo BUILD FAILED
    pause
)
