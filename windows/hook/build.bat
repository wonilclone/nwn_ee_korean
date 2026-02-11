@echo off
REM NWN Korean Hook DLL 빌드 스크립트 (Windows x64)
REM 소스에 GCC 전용 문법(__attribute__((naked)), __asm__ volatile)이
REM 포함되어 있어 MinGW GCC가 필요합니다. MSVC로는 빌드할 수 없습니다.

echo ===============================================
echo NWN:EE Korean Hook DLL Builder
echo ===============================================
echo.

cd /d "%~dp0"

REM MinGW GCC 확인
where gcc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [-] GCC not found in PATH
    echo [-] MSYS2 설치 후 mingw-w64-x86_64-gcc 패키지를 설치하세요.
    echo [-] MSVC는 지원되지 않습니다 (GCC 전용 문법 사용)
    goto :end
)

echo [*] Using MinGW GCC
echo.

REM DLL 빌드
echo [*] Building DLL...
gcc -shared -O2 -Wall -o nwn_korean_hook.dll nwn_korean_hook.c -lpsapi
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] DLL build failed
    goto :end
)

echo [+] DLL build successful: nwn_korean_hook.dll
echo.

REM 로더 빌드
echo [*] Building loader...
gcc -O2 -Wall -o nwn_korean_loader.exe nwn_korean_loader.c
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] Loader build failed
    goto :end
)

echo [+] Loader build successful: nwn_korean_loader.exe
echo.

:end
echo ===============================================
if exist nwn_korean_hook.dll (
    echo [+] DLL build complete
    for %%I in (nwn_korean_hook.dll) do echo     Size: %%~zI bytes
)
if exist nwn_korean_loader.exe (
    echo [+] Loader build complete
    for %%I in (nwn_korean_loader.exe) do echo     Size: %%~zI bytes
)
echo.
if exist nwn_korean_hook.dll (
if exist nwn_korean_loader.exe (
    echo [!] Installation:
    echo     1. Copy both files to game directory
    echo     2. Run nwn_korean_loader.exe instead of nwmain.exe
    echo     3. Check nwn_korean_loader.log for details
)
)

pause
