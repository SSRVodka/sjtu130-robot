@echo off
chcp 65001 >nul
cd /d "%~dp0"

for %%f in (*.mp3) do (
    if exist "%%~nf.wav" (
        echo ✅ existed: "%%~nf.wav"
    ) else (
        echo 🔄 converting: "%%~nxf" -^> "%%~nf.wav"
        ffmpeg -i "%%f" -vn -acodec pcm_s16le -ar 44100 -ac 2 "%%~nf.wav" -hide_banner -loglevel error
        
        if errorlevel 1 (
            echo ❌ failed: "%%~nxf"
        ) else (
            echo ✅ converted: "%%~nf.wav"
        )
        echo ----------------------------------------
    )
)

echo.
echo 🎉 finished!
pause
