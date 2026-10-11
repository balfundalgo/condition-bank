"""Local PyInstaller build. GitHub Actions does the same thing on every push."""

import PyInstaller.__main__

PyInstaller.__main__.run([
    "app.py",
    "--onefile",
    "--windowed",
    "--name", "ConditionBank",
    "--collect-all", "customtkinter",
    "--collect-all", "darkdetect",
    "--hidden-import", "websocket",
    "--hidden-import", "pyotp",
    "--noconfirm",
])
