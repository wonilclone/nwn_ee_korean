#!/usr/bin/env python3
from __future__ import annotations

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
    python3 build_release.py                # 전체 빌드
    python3 build_release.py --mac          # macOS만 빌드
    python3 build_release.py --debug        # 검수 모드 TLK 생성
    python3 build_release.py --zip v0.1.0   # 빌드 후 zip 생성
"""

import argparse
import shutil
import subprocess
import sys
import zipfile
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
    """Windows 릴리스 빌드"""
    print()
    print("=" * 50)
    print("Windows 빌드")
    print("=" * 50)

    win_dir = PROJECT_ROOT / "windows"
    hook_dir = win_dir / "hook"
    scripts_dir = win_dir / "scripts"
    win_release_dst = RELEASE_DIR / "windows"
    override_dst = win_release_dst / "override"

    # 릴리스 디렉토리 생성
    win_release_dst.mkdir(parents=True, exist_ok=True)
    override_dst.mkdir(parents=True, exist_ok=True)

    # 1. DLL과 로더 확인/복사
    print("\n[1/5] DLL 및 로더 확인...")

    dll_src = hook_dir / "nwn_korean_hook.dll"
    loader_src = hook_dir / "nwn_korean_loader.exe"

    if dll_src.exists():
        dll_dst = win_release_dst / "nwn_korean_hook.dll"
        shutil.copy2(dll_src, dll_dst)
        print(f"  [OK] {dll_dst.name} ({dll_dst.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"  [!] DLL을 찾을 수 없습니다: {dll_src}")
        print("      hook 디렉토리에 빌드된 DLL을 복사해주세요.")

    if loader_src.exists():
        loader_dst = win_release_dst / "nwn_korean_loader.exe"
        shutil.copy2(loader_src, loader_dst)
        print(f"  [OK] {loader_dst.name} ({loader_dst.stat().st_size / 1024:.1f} KB)")
    else:
        print(f"  [!] 로더를 찾을 수 없습니다: {loader_src}")
        print("      hook 디렉토리에 빌드된 로더를 복사해주세요.")

    # 2. TLK 복사 (override 디렉토리)
    print("\n[2/5] TLK 복사...")
    tlk_dst = override_dst / "dialog.tlk"
    shutil.copy2(tlk_path, tlk_dst)
    print(f"  [OK] override/{tlk_dst.name} ({tlk_dst.stat().st_size / 1024 / 1024:.1f} MB)")

    # 3. install.py 복사
    print("\n[3/5] 설치 스크립트 복사...")
    install_src = scripts_dir / "install.py"
    install_dst = win_release_dst / "install.py"
    if install_src.exists():
        shutil.copy2(install_src, install_dst)
        print(f"  [OK] {install_dst.name}")
    else:
        print(f"  [!] install.py를 찾을 수 없습니다: {install_src}")

    # 4. README 복사
    print("\n[4/5] README 복사...")
    readme_src = win_dir / "RELEASE_README.md"
    readme_dst = win_release_dst / "README.md"
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


# 릴리스에 포함할 파일 화이트리스트
RELEASE_FILES = {
    'mac': [
        'install.py',
        'nwn_korean_hook.dylib',
        'README.md',
        'override/dialog.tlk',
        'override/fnt_default.ttf',
        'override/fnt_default_hr.ttf',
        'override/fnt_maintext.ttf',
    ],
    'windows': [
        'install.py',
        'nwn_korean_hook.dll',
        'nwn_korean_loader.exe',
        'README.md',
        'override/dialog.tlk',
        'override/fnt_default.ttf',
        'override/fnt_default_hr.ttf',
        'override/fnt_maintext.ttf',
    ],
}


def create_zip(platform: str, version: str | None = None) -> Path | None:
    """플랫폼별 릴리스 zip 파일 생성 (화이트리스트 기반)"""
    platform_dir = RELEASE_DIR / platform
    if not platform_dir.exists():
        return None

    whitelist = RELEASE_FILES.get(platform, [])
    if not whitelist:
        print(f"  [!] {platform}: 화이트리스트가 비어있습니다")
        return None

    # 버전 태그가 없으면 파일명에서 제외
    if version:
        zip_name = f"nwn-ee-korean-{platform}-{version}.zip"
    else:
        zip_name = f"nwn-ee-korean-{platform}.zip"

    zip_path = RELEASE_DIR / zip_name

    print(f"\n[{platform}] 압축 중...")

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_path in whitelist:
            file_path = platform_dir / rel_path
            if file_path.exists():
                arcname = f"{platform}/{rel_path}"
                zf.write(file_path, arcname)
                print(f"  + {rel_path}")
            else:
                print(f"  [!] 누락: {rel_path}")

    print(f"  [OK] {zip_name} ({zip_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return zip_path


def print_summary(zip_files: list[Path] | None = None):
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

    if zip_files:
        print()
        print("=" * 50)
        print("릴리스 파일")
        print("=" * 50)
        for zf in zip_files:
            print(f"  {zf.name}")


def main():
    parser = argparse.ArgumentParser(
        description='NWN:EE 한글 패치 릴리스 빌드',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
    python3 build_release.py                # 전체 빌드
    python3 build_release.py --mac          # macOS만 빌드
    python3 build_release.py --debug        # 검수 모드
    python3 build_release.py --zip v0.1.0   # 빌드 후 zip 생성
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
    parser.add_argument('--zip', nargs='?', const='', metavar='VERSION',
                        help='릴리스 zip 파일 생성 (예: --zip v0.1.0)')

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

    # zip 생성
    zip_files = []
    if args.zip is not None:
        print()
        print("=" * 50)
        print("릴리스 압축")
        print("=" * 50)

        version = args.zip if args.zip else None
        platforms = []
        if build_all:
            platforms = ['mac', 'windows']
        else:
            if args.mac:
                platforms.append('mac')
            if args.windows:
                platforms.append('windows')

        for platform in platforms:
            zf = create_zip(platform, version)
            if zf:
                zip_files.append(zf)

    # 요약
    print_summary(zip_files if zip_files else None)

    return 0


if __name__ == "__main__":
    sys.exit(main())
