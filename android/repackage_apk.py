#!/usr/bin/env python3
"""
NWN:EE Android APK 리패키징 스크립트

패치된 libnwmain.so를 APK에 삽입하고 zipalign + 서명합니다.

사용법:
    python3 repackage_apk.py                          # 기본 (패치 + 리패키징)
    python3 repackage_apk.py --apk <path>             # 원본 APK 지정
    python3 repackage_apk.py --so <path>              # 패치된 .so 지정
    python3 repackage_apk.py --output <path>          # 출력 APK 경로 지정
    python3 repackage_apk.py --install                # 설치까지 수행
    python3 repackage_apk.py --keystore <path>        # 키스토어 지정
    python3 repackage_apk.py --patch                  # .so 패치부터 수행
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

# 기본 파일 경로
DEFAULT_APK = SCRIPT_DIR / "NWN-EE-v8193A00013-patched.apk"
DEFAULT_SO = SCRIPT_DIR / "libnwmain_patched.so"
DEFAULT_OUTPUT = SCRIPT_DIR / "NWN-EE-korean-signed.apk"
DEFAULT_KEYSTORE = Path.home() / ".android" / "debug.keystore"
DEFAULT_KS_PASS = "android"

# Android SDK build-tools 경로 후보
BUILD_TOOLS_CANDIDATES = [
    Path.home() / "Library" / "Android" / "sdk" / "build-tools",  # macOS
    Path(os.environ.get("ANDROID_HOME", "")) / "build-tools",
    Path(os.environ.get("ANDROID_SDK_ROOT", "")) / "build-tools",
]

# APK 내에서 비압축으로 저장해야 하는 파일 패턴
STORE_UNCOMPRESSED = {
    "resources.arsc",   # Android R+ 필수
}

# 확장자 기반 비압축 저장 (네이티브 라이브러리는 extractNativeLibs=false일 때 필수)
STORE_UNCOMPRESSED_EXT = {".so"}


def find_build_tools():
    """Android SDK build-tools 디렉토리에서 최신 버전을 찾습니다."""
    for base in BUILD_TOOLS_CANDIDATES:
        if base.is_dir():
            versions = sorted(base.iterdir(), reverse=True)
            for v in versions:
                zipalign = v / "zipalign"
                apksigner = v / "apksigner"
                if zipalign.exists() and apksigner.exists():
                    return v
    return None


def find_tool(name):
    """PATH에서 도구를 찾습니다."""
    return shutil.which(name)


def run(cmd, desc=None, check=True):
    """명령 실행 헬퍼."""
    if desc:
        print(f"  {desc}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [실패] {' '.join(str(c) for c in cmd)}")
        if result.stderr:
            print(f"  stderr: {result.stderr.strip()}")
        if result.stdout:
            print(f"  stdout: {result.stdout.strip()}")
        sys.exit(1)
    return result


def repackage_apk(apk_path, so_path, output_path, build_tools_dir,
                   keystore_path, ks_pass):
    """APK 리패키징 메인 로직."""

    print(f"\n[1/4] APK 압축 해제: {apk_path.name}")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        unsigned_apk = tmpdir / "unsigned.apk"
        aligned_apk = tmpdir / "aligned.apk"

        # 원본 APK 열기
        with zipfile.ZipFile(apk_path, 'r') as zin:
            # 새 APK 생성
            with zipfile.ZipFile(unsigned_apk, 'w') as zout:
                for item in zin.infolist():
                    # 기존 서명 파일 제거
                    if item.filename.startswith("META-INF/") and (
                        item.filename.endswith(".RSA") or
                        item.filename.endswith(".SF") or
                        item.filename.endswith(".DSA") or
                        item.filename == "META-INF/MANIFEST.MF"
                    ):
                        continue

                    # arm64 libnwmain.so 교체
                    if item.filename == "lib/arm64-v8a/libnwmain.so":
                        print(f"  -> lib/arm64-v8a/libnwmain.so 교체 ({so_path.name})")
                        info = zipfile.ZipInfo(item.filename)
                        info.compress_type = zipfile.ZIP_STORED
                        with open(so_path, 'rb') as f:
                            zout.writestr(info, f.read())
                        continue

                    # 비압축 저장 대상 판별
                    basename = os.path.basename(item.filename)
                    _, ext = os.path.splitext(item.filename)
                    should_store = (
                        basename in STORE_UNCOMPRESSED or
                        ext in STORE_UNCOMPRESSED_EXT
                    )

                    data = zin.read(item.filename)
                    info = zipfile.ZipInfo(item.filename)
                    if should_store:
                        info.compress_type = zipfile.ZIP_STORED
                    else:
                        info.compress_type = zipfile.ZIP_DEFLATED
                    zout.writestr(info, data)

        print(f"  -> {unsigned_apk.stat().st_size / 1024 / 1024:.1f} MB")

        # zipalign
        print(f"\n[2/4] zipalign 실행")
        zipalign = build_tools_dir / "zipalign"
        run([str(zipalign), "-f", "4", str(unsigned_apk), str(aligned_apk)],
            desc="4바이트 정렬 중")

        # 서명 검증
        run([str(zipalign), "-c", "4", str(aligned_apk)],
            desc="정렬 검증 중")
        print("  -> 정렬 OK")

        # apksigner 서명
        print(f"\n[3/4] APK 서명 (keystore: {keystore_path.name})")
        apksigner = build_tools_dir / "apksigner"
        run([
            str(apksigner), "sign",
            "--ks", str(keystore_path),
            "--ks-pass", f"pass:{ks_pass}",
            "--key-pass", f"pass:{ks_pass}",
            "--out", str(output_path),
            str(aligned_apk),
        ], desc="서명 중")

        # 서명 검증
        result = run([str(apksigner), "verify", "--print-certs", str(output_path)],
                     desc="서명 검증 중")
        print("  -> 서명 OK")

    print(f"\n[4/4] 완료: {output_path}")
    print(f"  크기: {output_path.stat().st_size / 1024 / 1024:.1f} MB")


def install_apk(apk_path):
    """adb install 수행."""
    adb = find_tool("adb")
    if not adb:
        print("\n[설치] adb를 찾을 수 없습니다. 수동으로 설치하세요:")
        print(f"  adb install {apk_path}")
        return False

    print(f"\n[설치] adb install {apk_path.name}")
    result = run([adb, "install", str(apk_path)], desc="설치 중", check=False)
    if result.returncode != 0:
        if "INSTALL_FAILED_UPDATE_INCOMPATIBLE" in (result.stdout + result.stderr):
            print("  -> 서명 불일치. 기존 앱 제거 후 재설치합니다.")
            # 패키지명 추출
            pkg_result = run([
                adb, "shell", "pm", "list", "packages"
            ], check=False)
            pkg_name = None
            for line in pkg_result.stdout.splitlines():
                if "nwn" in line.lower() or "neverwinter" in line.lower():
                    pkg_name = line.strip().replace("package:", "")
                    break
            if pkg_name:
                print(f"  -> 기존 패키지 제거: {pkg_name}")
                run([adb, "uninstall", pkg_name], check=False)
                result = run([adb, "install", str(apk_path)], desc="재설치 중", check=False)

        if result.returncode != 0:
            print(f"  [실패] {result.stdout} {result.stderr}")
            return False

    print("  -> 설치 성공!")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="NWN:EE Android APK 리패키징 (패치 .so 삽입 + 서명)")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK,
                        help=f"원본 APK 경로 (기본: {DEFAULT_APK.name})")
    parser.add_argument("--so", type=Path, default=DEFAULT_SO,
                        help=f"패치된 .so 경로 (기본: {DEFAULT_SO.name})")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT,
                        help=f"출력 APK 경로 (기본: {DEFAULT_OUTPUT.name})")
    parser.add_argument("--keystore", type=Path, default=DEFAULT_KEYSTORE,
                        help="서명용 키스토어 (기본: ~/.android/debug.keystore)")
    parser.add_argument("--ks-pass", default=DEFAULT_KS_PASS,
                        help="키스토어 비밀번호 (기본: android)")
    parser.add_argument("--install", action="store_true",
                        help="서명 후 adb install 수행")
    parser.add_argument("--patch", action="store_true",
                        help=".so 패치부터 수행 (patch_libnwmain.py 실행)")
    args = parser.parse_args()

    print("=== NWN:EE Android APK 리패키징 ===")

    # .so 패치 옵션
    if args.patch:
        print("\n[패치] libnwmain.so 패치 중...")
        patch_script = SCRIPT_DIR / "patch_libnwmain.py"
        if not patch_script.exists():
            print(f"  [에러] {patch_script} 없음")
            sys.exit(1)
        run([sys.executable, str(patch_script)], desc="patch_libnwmain.py 실행")

    # 입력 파일 확인
    if not args.apk.exists():
        print(f"[에러] APK 없음: {args.apk}")
        sys.exit(1)
    if not args.so.exists():
        print(f"[에러] 패치된 .so 없음: {args.so}")
        if not args.patch:
            print("  힌트: --patch 옵션으로 패치부터 수행하세요")
        sys.exit(1)

    # build-tools 찾기
    build_tools = find_build_tools()
    if not build_tools:
        print("[에러] Android SDK build-tools를 찾을 수 없습니다.")
        print("  ANDROID_HOME 또는 ANDROID_SDK_ROOT 환경변수를 설정하세요.")
        sys.exit(1)
    print(f"  build-tools: {build_tools}")

    # 키스토어 확인
    if not args.keystore.exists():
        print(f"[에러] 키스토어 없음: {args.keystore}")
        print("  디버그 키스토어 생성:")
        print("    keytool -genkey -v -keystore ~/.android/debug.keystore "
              "-alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 "
              "-storepass android -keypass android "
              '-dname "CN=Android Debug,O=Android,C=US"')
        sys.exit(1)

    # 리패키징
    repackage_apk(args.apk, args.so, args.output, build_tools,
                   args.keystore, args.ks_pass)

    # 설치
    if args.install:
        install_apk(args.output)

    print("\n완료!")


if __name__ == "__main__":
    main()
