#!/usr/bin/env python3
"""
NWN:EE 한글 패치 릴리스 빌드 스크립트

플랫폼별 릴리스 디렉토리에 배포용 파일들을 생성합니다:
  release/
  ├── mac/
  │   ├── install.py
  │   ├── nwn_korean_hook.dylib
  │   ├── README.md
  │   └── override/
  │       ├── dialog.tlk
  │       └── fnt_*.ttf
  └── windows/  (예정)

사용법:
    python3 build_release.py              # 전체 빌드
    python3 build_release.py --mac        # macOS만 빌드
    python3 build_release.py --debug      # 검수 모드 TLK 생성
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
TRANSLATE_DIR = PROJECT_ROOT / "translate"
RELEASE_DIR = PROJECT_ROOT / "release"
FONTS_DIR = PROJECT_ROOT / "fonts"

# NWN:EE 폰트 파일명
NWN_FONT_FILES = [
    "fnt_default.ttf",
    "fnt_default_hr.ttf",
    "fnt_maintext.ttf",
]


def build_tlk(debug_mode: bool = False):
    """TLK 빌드 (translate/merge_dialog_files.py 호출)"""
    print()
    print("=" * 50)
    print("TLK 빌드")
    print("=" * 50)

    cmd = [sys.executable, "merge_dialog_files.py"]
    if debug_mode:
        cmd.append("--debug")

    result = subprocess.run(
        cmd,
        cwd=TRANSLATE_DIR,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"오류: TLK 빌드 실패")
        print(result.stderr)
        return None

    for line in result.stdout.split('\n'):
        if line.strip():
            print(f"  {line}")

    tlk_path = TRANSLATE_DIR / "dialog.tlk"
    if not tlk_path.exists():
        print(f"오류: TLK 파일이 생성되지 않았습니다")
        return None

    return tlk_path


def build_mac(tlk_path: Path):
    """macOS 릴리스 빌드"""
    print()
    print("=" * 50)
    print("macOS 빌드")
    print("=" * 50)

    mac_dir = PROJECT_ROOT / "mac"
    hook_dir = mac_dir / "hook"
    scripts_dir = mac_dir / "scripts"
    mac_release_dst = RELEASE_DIR / "mac"
    override_dst = mac_release_dst / "override"

    # 릴리스 디렉토리 생성
    mac_release_dst.mkdir(parents=True, exist_ok=True)
    override_dst.mkdir(parents=True, exist_ok=True)

    # 1. dylib 빌드
    print("\n[1/5] dylib 빌드...")
    subprocess.run(["make", "clean"], cwd=hook_dir, capture_output=True)
    result = subprocess.run(
        ["make", "universal"],
        cwd=hook_dir,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"  [!] dylib 빌드 실패")
        print(result.stderr)
        return False

    dylib_src = hook_dir / "nwn_korean_hook.dylib"
    dylib_dst = mac_release_dst / "nwn_korean_hook.dylib"
    shutil.copy2(dylib_src, dylib_dst)
    print(f"  [OK] {dylib_dst.name} ({dylib_dst.stat().st_size / 1024:.1f} KB)")

    # 2. TLK 복사 (override 디렉토리)
    print("\n[2/5] TLK 복사...")
    tlk_dst = override_dst / "dialog.tlk"
    shutil.copy2(tlk_path, tlk_dst)
    print(f"  [OK] override/{tlk_dst.name} ({tlk_dst.stat().st_size / 1024 / 1024:.1f} MB)")

    # 3. install.py 복사
    print("\n[3/5] 설치 스크립트 복사...")
    install_src = scripts_dir / "install.py"
    install_dst = mac_release_dst / "install.py"
    if install_src.exists():
        shutil.copy2(install_src, install_dst)
        print(f"  [OK] {install_dst.name}")
    else:
        print(f"  [!] install.py를 찾을 수 없습니다: {install_src}")

    # 4. README 복사
    print("\n[4/5] README 복사...")
    readme_src = mac_dir / "RELEASE_README.md"
    readme_dst = mac_release_dst / "README.md"
    if readme_src.exists():
        shutil.copy2(readme_src, readme_dst)
        print(f"  [OK] {readme_dst.name}")
    else:
        print(f"  [!] README를 찾을 수 없습니다: {readme_src}")

    # 5. 폰트 복사 (override 디렉토리)
    print("\n[5/5] 폰트 복사...")
    font_src_files = list(FONTS_DIR.glob("*.ttf")) + list(FONTS_DIR.glob("*.otf"))
    if font_src_files:
        # 첫 번째 폰트 파일을 NWN 폰트 파일명으로 복사
        src_font = font_src_files[0]
        for font_name in NWN_FONT_FILES:
            font_dst = override_dst / font_name
            shutil.copy2(src_font, font_dst)
            print(f"  [OK] override/{font_name} ({font_dst.stat().st_size / 1024 / 1024:.1f} MB)")
    else:
        print("  [!] fonts/ 디렉토리에 폰트 파일이 없습니다.")
        print("      Spoqa Han Sans Neo 등의 폰트를 fonts/에 넣어주세요.")

    return True


def build_windows(tlk_path: Path):
    """Windows 릴리스 빌드 (예정)"""
    print()
    print("=" * 50)
    print("Windows 빌드")
    print("=" * 50)
    print("  [!] Windows 빌드는 아직 구현되지 않았습니다")
    return True


def print_summary():
    """빌드 요약"""
    print()
    print("=" * 50)
    print("빌드 완료!")
    print("=" * 50)
    print()
    print(f"릴리스 디렉토리: {RELEASE_DIR}")

    for platform_dir in sorted(RELEASE_DIR.iterdir()):
        if platform_dir.is_dir():
            print(f"\n[{platform_dir.name}]")
            total_size = 0

            # 루트 파일들
            for item in sorted(platform_dir.iterdir()):
                if item.is_file():
                    size = item.stat().st_size
                    total_size += size
                    print(f"  {item.name:35s} {size / 1024 / 1024:6.2f} MB")

            # override 디렉토리
            override_dir = platform_dir / "override"
            if override_dir.exists():
                print(f"  override/")
                for item in sorted(override_dir.iterdir()):
                    if item.is_file():
                        size = item.stat().st_size
                        total_size += size
                        print(f"    {item.name:33s} {size / 1024 / 1024:6.2f} MB")

            print(f"  {'─' * 43}")
            print(f"  {'총합':35s} {total_size / 1024 / 1024:6.2f} MB")


def main():
    parser = argparse.ArgumentParser(
        description='NWN:EE 한글 패치 릴리스 빌드',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python3 build_release.py          # 전체 빌드
    python3 build_release.py --mac    # macOS만 빌드
    python3 build_release.py --debug  # 검수 모드
        """
    )
    parser.add_argument('--mac', action='store_true',
                        help='macOS만 빌드')
    parser.add_argument('--windows', action='store_true',
                        help='Windows만 빌드')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='검수 모드 TLK 생성 (텍스트 앞에 [StrRef] 추가)')
    parser.add_argument('--skip-tlk', action='store_true',
                        help='TLK 빌드 건너뛰기')

    args = parser.parse_args()

    # 플랫폼 미지정시 전체 빌드
    build_all = not args.mac and not args.windows

    print()
    print("╔════════════════════════════════════════════════╗")
    print("║      NWN:EE 한글 패치 릴리스 빌드              ║")
    print("╚════════════════════════════════════════════════╝")

    # TLK 빌드
    if args.skip_tlk:
        tlk_path = TRANSLATE_DIR / "dialog.tlk"
        if not tlk_path.exists():
            print("오류: TLK 파일이 없습니다. --skip-tlk 옵션을 제거하세요.")
            return 1
        print("\nTLK 빌드 건너뜀 (기존 파일 사용)")
    else:
        tlk_path = build_tlk(debug_mode=args.debug)
        if not tlk_path:
            return 1

    # 플랫폼별 빌드
    if build_all or args.mac:
        if not build_mac(tlk_path):
            return 1

    if build_all or args.windows:
        if not build_windows(tlk_path):
            return 1

    # 요약
    print_summary()

    return 0


if __name__ == "__main__":
    sys.exit(main())
