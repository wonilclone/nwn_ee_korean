#!/bin/bash
# NWN:EE 한글 패치 실행 스크립트
#
# 사용법:
#   ./run_nwn_korean.sh
#
# 주의:
#   - SIP(System Integrity Protection)이 비활성화되어 있어야 합니다.
#   - 또는 nwmain 바이너리의 코드 서명이 제거되어야 합니다.
#
# SIP 비활성화 방법 (복구 모드에서):
#   csrutil disable
#
# 코드 서명 제거 방법:
#   codesign --remove-signature /path/to/nwmain

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_LIB="$SCRIPT_DIR/nwn_cp949_hook.dylib"

# NWN:EE 경로 (Steam 설치 기본값)
NWN_APP="/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/bin/macos/nwmain.app"
NWN_BINARY="$NWN_APP/Contents/MacOS/nwmain"

# 후킹 라이브러리 확인
if [ ! -f "$HOOK_LIB" ]; then
    echo "오류: 후킹 라이브러리를 찾을 수 없습니다: $HOOK_LIB"
    echo "먼저 빌드하세요: make"
    exit 1
fi

# NWN 바이너리 확인
if [ ! -f "$NWN_BINARY" ]; then
    echo "오류: NWN:EE 바이너리를 찾을 수 없습니다: $NWN_BINARY"
    echo "Steam에서 Neverwinter Nights: Enhanced Edition을 설치하세요."
    exit 1
fi

echo "======================================"
echo "NWN:EE 한글 패치 (CP949 지원)"
echo "======================================"
echo ""
echo "후킹 라이브러리: $HOOK_LIB"
echo "게임 바이너리: $NWN_BINARY"
echo ""

# 환경 변수 설정하여 실행
echo "게임 실행 중..."
echo "(오류 발생 시 SIP 설정 또는 코드 서명 확인 필요)"
echo ""

DYLD_INSERT_LIBRARIES="$HOOK_LIB" "$NWN_BINARY" "$@"

EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "======================================"
    echo "오류가 발생했습니다 (종료 코드: $EXIT_CODE)"
    echo "======================================"
    echo ""
    echo "문제 해결:"
    echo "1. SIP 비활성화 확인:"
    echo "   csrutil status"
    echo ""
    echo "2. 코드 서명 제거 (필요시):"
    echo "   sudo codesign --remove-signature '$NWN_BINARY'"
    echo ""
    echo "3. 권한 부여 (필요시):"
    echo "   chmod +x '$NWN_BINARY'"
fi

exit $EXIT_CODE
