@echo off
REM NWN Korean Hook DLL 빌드 스크립트 (Windows x64)

echo ===============================================
echo NWN:EE Korean Hook DLL Builder
echo ===============================================
echo.

REM Visual Studio 환경 확인
where cl >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [!] Visual Studio compiler not found in PATH
    echo [!] Please run this from "Developer Command Prompt for VS"
    echo.
    echo Alternatively, trying MinGW...
    goto :mingw
)

echo [*] Using Visual Studio compiler
echo.

REM Visual Studio로 빌드
echo [*] Building DLL...
cl /LD /O2 /W3 /nologo nwn_korean_hook.c /Fe:nwn_korean_hook.dll /link /DEF:nwn_korean_hook.def
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] DLL build failed
    goto :end
)

echo [+] DLL build successful: nwn_korean_hook.dll
echo.

echo [*] Building loader...
cl /O2 /W3 /nologo nwn_korean_loader.c /Fe:nwn_korean_loader.exe
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] Loader build failed
    goto :end
)

echo [+] Loader build successful: nwn_korean_loader.exe
echo.
goto :end

:mingw
where gcc >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [-] GCC not found in PATH
    echo [-] Please install Visual Studio or MinGW-w64
    goto :end
)

echo [*] Using MinGW GCC
echo.

REM MinGW로 빌드
echo [*] Building DLL...
gcc -shared -O2 -Wall -o nwn_korean_hook.dll nwn_korean_hook.c -lpsapi
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [-] DLL build failed
    goto :end
)

echo [+] DLL build successful: nwn_korean_hook.dll
echo.

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
