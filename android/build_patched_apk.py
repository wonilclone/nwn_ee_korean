#!/usr/bin/env python3
"""
NWN:EE Android 한글 패치 올인원 스크립트

APK 하나만 넣으면 libnwmain.so 추출 → 패치 → 리패키징 → 서명까지 한 번에 수행합니다.

사용법:
    python3 build_patched_apk.py <원본APK>
    python3 build_patched_apk.py <원본APK> --install    # 기기 설치까지
    python3 build_patched_apk.py <원본APK> -o out.apk   # 출력 경로 지정
"""

import argparse
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SO_NAME = "lib/arm64-v8a/libnwmain.so"


def extract_so(apk_path: Path, output_path: Path) -> bool:
    """APK에서 arm64 libnwmain.so 추출"""
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            names = zf.namelist()
            if SO_NAME not in names:
                print(f"[에러] APK 내에 {SO_NAME}이 없습니다.")
                print(f"  포함된 .so 파일:")
                for n in names:
                    if n.endswith('.so'):
                        print(f"    {n}")
                return False

            info = zf.getinfo(SO_NAME)
            print(f"  {SO_NAME} ({info.file_size / 1024 / 1024:.1f} MB)")
            with zf.open(SO_NAME) as src, open(output_path, 'wb') as dst:
                dst.write(src.read())
        return True
    except zipfile.BadZipFile:
        print(f"[에러] 유효한 APK(ZIP) 파일이 아닙니다: {apk_path}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="NWN:EE Android 한글 패치 (올인원: 추출 → 패치 → 리패키징 → 서명)")
    parser.add_argument("apk", type=Path, help="원본 NWN:EE APK 파일")
    parser.add_argument("-o", "--output", type=Path,
                        default=SCRIPT_DIR / "NWN-EE-korean-signed.apk",
                        help="출력 APK 경로 (기본: NWN-EE-korean-signed.apk)")
    parser.add_argument("--install", action="store_true",
                        help="서명 후 adb install 수행")
    parser.add_argument("--keystore", type=Path,
                        default=Path.home() / ".android" / "debug.keystore",
                        help="서명용 키스토어 (기본: ~/.android/debug.keystore)")
    parser.add_argument("--ks-pass", default="android",
                        help="키스토어 비밀번호 (기본: android)")
    args = parser.parse_args()

    if not args.apk.exists():
        print(f"[에러] APK 파일 없음: {args.apk}")
        sys.exit(1)

    print("=== NWN:EE Android 한글 패치 (올인원) ===\n")

    # =========================================
    # Step 1: APK에서 libnwmain.so 추출
    # =========================================
    so_path = SCRIPT_DIR / "libnwmain.so"
    print(f"[1/3] APK에서 libnwmain.so 추출")
    if not extract_so(args.apk, so_path):
        sys.exit(1)
    print(f"  -> {so_path}\n")

    # =========================================
    # Step 2: libnwmain.so 패치
    # =========================================
    print(f"[2/3] libnwmain.so 한글 패치")

    # patch_libnwmain을 모듈로 import
    sys.path.insert(0, str(SCRIPT_DIR))
    import patch_libnwmain
    if not patch_libnwmain.apply_patches():
        print("\n[에러] 패치 실패")
        sys.exit(1)
    print()

    # =========================================
    # Step 3: 리패키징 + 서명
    # =========================================
    print(f"[3/3] APK 리패키징 + 서명")

    import repackage_apk
    build_tools = repackage_apk.find_build_tools()
    if not build_tools:
        print("[에러] Android SDK build-tools를 찾을 수 없습니다.")
        print("  ANDROID_HOME 또는 ANDROID_SDK_ROOT 환경변수를 설정하세요.")
        sys.exit(1)
    print(f"  build-tools: {build_tools}")

    if not args.keystore.exists():
        print(f"\n[에러] 키스토어 없음: {args.keystore}")
        print("  디버그 키스토어 생성:")
        print('    keytool -genkey -v -keystore ~/.android/debug.keystore '
              '-alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 '
              '-storepass android -keypass android '
              '-dname "CN=Android Debug,O=Android,C=US"')
        sys.exit(1)

    patched_so = SCRIPT_DIR / "libnwmain_patched.so"
    repackage_apk.repackage_apk(
        args.apk, patched_so, args.output,
        build_tools, args.keystore, args.ks_pass
    )

    # =========================================
    # 설치 (선택)
    # =========================================
    if args.install:
        repackage_apk.install_apk(args.output)

    print(f"\n{'=' * 60}")
    print(f"  완료: {args.output}")
    print(f"  크기: {args.output.stat().st_size / 1024 / 1024:.1f} MB")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
