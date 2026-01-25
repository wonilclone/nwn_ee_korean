#!/usr/bin/env python3
"""
NWN:EE Windows 한글 패치 설치 스크립트

사용법:
    python install.py              # 패치 설치
    python install.py --uninstall  # 패치 제거
    python install.py --check      # 상태 확인
"""

import hashlib
import struct
import shutil
import sys
from pathlib import Path
from typing import Optional, Tuple, List

# ============================================================================
# 경로 설정
# ============================================================================

# PyInstaller exe에서 실행될 때 실제 exe 위치 찾기
if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 exe
    SCRIPT_DIR = Path(sys.executable).parent
else:
    # 일반 Python 스크립트
    SCRIPT_DIR = Path(__file__).parent
NWN_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32")
NWN_DOCS = Path.home() / "Documents" / "Neverwinter Nights"
NWMAIN = NWN_DIR / "nwmain.exe"
BACKUP_DIR = SCRIPT_DIR / "backup"
BACKUP = BACKUP_DIR / "nwmain.exe.original"

# ============================================================================
# 원본 바이너리 해시 및 버전별 오프셋
# ============================================================================

# SHA256 해시 - 테스트된 nwmain.exe 버전들
KNOWN_HASHES = {
    # Steam Build 8193.35 (2024)
    "4e1bd743944027ddca7b11b96fa856b1f51e3b7ad0f2747ddfc53b35312be8df": "8193.35",
    # Steam Build 8193.36-40 (2025)
    "3b7cb1252e0edb2ce22d7971f333aade027039ae30a45b4bc64732c3e6bec73a": "8193.36+",
}

# 버전별 오프셋 테이블 (모든 값은 파일 오프셋)
# Note: RVA가 아닌 파일 오프셋 사용 (RVA - 0xC00 = file offset for .text section)
VERSION_OFFSETS = {
    "8193.35": {
        # Phase 1: 경계 체크
        "get_symbol_coords": 0x000eaf20,
        "set_symbol_coords": 0x000ed39f,
        # Glyph padding (RVA 0xfb880 -> file offset)
        "glyph_padding": 0x000fac80,
        # Texture 4096x4096 (RVA 0xfb7e7, 0x2df54f -> file offset)
        "texture_hook": 0x000fabe7,
        "texture_cave": 0x002de94f,
        # TextOut CP949 decoder (RVA 0x4ca06, 0x966dd3 -> file offset)
        "textout": 0x0004be06,
        "textout_next": 0x0004be0b,
        "textout_cave": 0x009661d3,
        # Nuklear glyph range (RVA -> file offset, 한글 글리프 로드)
        "nuklear_glyph_range": [
            (0xa70fe3, 0xa703e3, "Main font setup"),
            (0xa82fe8, 0xa823e8, "Secondary font"),
            (0xa8405c, 0xa8345c, "Font config init"),
            (0xa840b0, 0xa834b0, "Glyph range getter"),
        ],
        "korean_range_rva": 0xe8bd48,
    },
    "8193.36+": {
        # 8193.35와 동일한 파일 오프셋 (apply_korean_patch.py 테스트 결과)
        "get_symbol_coords": 0x000eaf20,
        "set_symbol_coords": 0x000ed39f,
        "glyph_padding": 0x000fac80,
        "texture_hook": 0x000fabe7,
        "texture_cave": 0x002de94f,
        "textout": 0x0004be06,
        "textout_next": 0x0004be0b,
        "textout_cave": 0x009661d3,
        # Nuklear glyph range (RVA -> file offset, 한글 글리프 로드)
        "nuklear_glyph_range": [
            (0xa70fe3, 0xa703e3, "Main font setup"),
            (0xa82fe8, 0xa823e8, "Secondary font"),
            (0xa8405c, 0xa8345c, "Font config init"),
            (0xa840b0, 0xa834b0, "Glyph range getter"),
        ],
        "korean_range_rva": 0xe8bd48,
    },
}

# 현재 사용할 오프셋 (설치 시 버전에 따라 설정됨)
CURRENT_OFFSETS = None

def calculate_sha256(filepath: Path) -> str:
    """파일의 SHA256 해시 계산"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

def verify_binary(filepath: Path) -> Tuple[bool, str, Optional[str]]:
    """바이너리 해시 검증. (성공여부, 메시지, 버전) 반환"""
    if not filepath.exists():
        return False, "파일이 존재하지 않습니다", None

    file_hash = calculate_sha256(filepath)

    if file_hash in KNOWN_HASHES:
        version = KNOWN_HASHES[file_hash]
        return True, f"검증됨: {version}", version
    else:
        return False, f"알 수 없는 버전 (해시: {file_hash[:16]}...)", None


def set_offsets_for_version(version: str) -> bool:
    """버전에 맞는 오프셋 설정. 성공 시 True 반환"""
    global CURRENT_OFFSETS
    if version in VERSION_OFFSETS:
        CURRENT_OFFSETS = VERSION_OFFSETS[version]
        return True
    return False


def get_patches_for_version() -> List[dict]:
    """현재 버전에 맞는 패치 목록 반환"""
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다. set_offsets_for_version()을 먼저 호출하세요.")

    return [
        # Phase 1: 경계 체크 패치
        {
            'name': 'GetSymbolCoords boundary check',
            'offset': CURRENT_OFFSETS['get_symbol_coords'],
            'original': bytes([0x81, 0xfa, 0xff, 0x00, 0x00, 0x00]),  # cmp edx, 0xFF
            'patched': bytes([0x81, 0xfa, 0x35, 0x0a, 0x00, 0x00]),   # cmp edx, 0x0A35 (2613)
        },
        {
            'name': 'SetSymbolCoords boundary check',
            'offset': CURRENT_OFFSETS['set_symbol_coords'],
            'original': bytes([0x81, 0xfa, 0xff, 0x00, 0x00, 0x00]),  # cmp edx, 0xFF
            'patched': bytes([0x81, 0xfa, 0x35, 0x0a, 0x00, 0x00]),   # cmp edx, 0x0A35 (2613)
        },
        # Glyph Padding: 3 -> 16 (문자 침범 문제 해결)
        {
            'name': 'Glyph padding 3 -> 16',
            'offset': CURRENT_OFFSETS['glyph_padding'],
            'original': bytes([0x48, 0xc7, 0x45, 0xbc, 0x03, 0x00, 0x00, 0x00]),
            'patched': bytes([0x48, 0xc7, 0x45, 0xbc, 0x10, 0x00, 0x00, 0x00]),
        },
    ]

# 필요한 파일들
DLL_NAME = "nwn_korean_hook.dll"
LOADER_NAME = "nwn_korean_loader.exe"
DLL_SRC = SCRIPT_DIR / DLL_NAME
LOADER_SRC = SCRIPT_DIR / LOADER_NAME

# ============================================================================
# 패치 정의
# ============================================================================

# Note: 버전별 오프셋은 VERSION_OFFSETS에서 관리됨
# Nuklear UI: 글리프 범위 패치는 구현됨 (UTF-8 디코딩은 미구현)

# ============================================================================
# 패치 생성 함수
# ============================================================================

def generate_texture_patch():
    """4096x4096 텍스처 코드 생성"""
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다.")

    texture_hook = CURRENT_OFFSETS['texture_hook']
    texture_cave = CURRENT_OFFSETS['texture_cave']

    code = bytearray()
    code += bytes([0xbe, 0x00, 0x10, 0x00, 0x00])  # mov esi, 0x1000 (4096)
    code += bytes([0xbb, 0x00, 0x10, 0x00, 0x00])  # mov ebx, 0x1000 (4096)
    code += bytes([0x44, 0x8b, 0xeb])              # mov r13d, ebx
    code += bytes([0x44, 0x0f, 0xaf, 0xee])        # imul r13d, esi

    # jmp back (오프셋 기반 상대 점프 계산)
    jmp_back_offset = texture_hook + 7
    jmp_from_offset = texture_cave + len(code) + 5
    jmp_rel = jmp_back_offset - jmp_from_offset
    code += bytes([0xe9]) + struct.pack('<i', jmp_rel)

    return code


def generate_textout_patch():
    """CP949 2-byte lookahead 디코더 생성"""
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다.")

    textout_cave = CURRENT_OFFSETS['textout_cave']
    textout_next = CURRENT_OFFSETS['textout_next']

    code = bytearray()

    # 1. Original instruction: movzx ebx, byte [r12]
    code += bytes([0x41, 0x0f, 0xb6, 0x1c, 0x24])  # 5 bytes

    # 2. Check if current byte is lead (0xB0-0xC8)
    code += bytes([0x80, 0xfb, 0xb0])  # cmp bl, 0xB0
    jb_exit = len(code)
    code += bytes([0x72, 0x00])  # jb .exit (not a lead)

    code += bytes([0x80, 0xfb, 0xc8])  # cmp bl, 0xC8
    ja_exit = len(code)
    code += bytes([0x77, 0x00])  # ja .exit (not a lead)

    # 3. Lead byte confirmed. Read next byte into eax
    code += bytes([0x41, 0x0f, 0xb6, 0x44, 0x24, 0x01])  # movzx eax, byte [r12+1]

    # 4. Check if next byte is trail (0xA1-0xFE)
    code += bytes([0x3c, 0xa1])  # cmp al, 0xA1
    jb_exit2 = len(code)
    code += bytes([0x72, 0x00])  # jb .exit (not a valid trail)

    code += bytes([0x3c, 0xfe])  # cmp al, 0xFE
    ja_exit2 = len(code)
    code += bytes([0x77, 0x00])  # ja .exit (not a valid trail)

    # 5. Valid CP949 pair! Calculate glyph index
    # Formula: 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

    # Save trail to ecx
    code += bytes([0x89, 0xc1])  # mov ecx, eax (trail)

    # ebx = lead - 0xB0
    code += bytes([0x81, 0xeb, 0xb0, 0x00, 0x00, 0x00])  # sub ebx, 0xB0

    # ebx = (lead - 0xB0) * 94
    code += bytes([0x6b, 0xdb, 0x5e])  # imul ebx, ebx, 94

    # ecx = trail - 0xA1
    code += bytes([0x81, 0xe9, 0xa1, 0x00, 0x00, 0x00])  # sub ecx, 0xA1

    # ebx = (lead - 0xB0) * 94 + (trail - 0xA1)
    code += bytes([0x01, 0xcb])  # add ebx, ecx

    # ebx = 256 + result
    code += bytes([0x81, 0xc3, 0x00, 0x01, 0x00, 0x00])  # add ebx, 256

    # 6. Increment edi to skip the trail byte
    code += bytes([0xff, 0xc7])  # inc edi

    # 7. Exit (오프셋 기반 상대 점프 계산)
    exit_offset = len(code)
    jmp_from_offset = textout_cave + len(code) + 5
    jmp_to_offset = textout_next
    jmp_rel = jmp_to_offset - jmp_from_offset
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # Patch jump offsets
    code[jb_exit + 1] = (exit_offset - (jb_exit + 2)) & 0xFF
    code[ja_exit + 1] = (exit_offset - (ja_exit + 2)) & 0xFF
    code[jb_exit2 + 1] = (exit_offset - (jb_exit2 + 2)) & 0xFF
    code[ja_exit2 + 1] = (exit_offset - (ja_exit2 + 2)) & 0xFF

    return code


def apply_nuklear_glyph_range_patch(data: bytearray) -> int:
    """Nuklear UI: 한글 글리프 범위 패치

    Nuklear UI (모듈 선택, 설정 등)에서 한글 글리프를 로드하도록 패치.

    Windows 바이너리에는 두 가지 glyph range가 정의되어 있음:
    - ASCII only (0x20-0xFF): RVA 0xe8bce0
    - Korean (0x20-0xFF, 0x3131-0x3163, 0xAC00-0xD79D): RVA 0xe8bd48

    기본적으로 ASCII only range를 사용하는 4개 위치를 Korean range로 변경.

    Returns: 패치 적용된 개수
    """
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다.")

    patches = CURRENT_OFFSETS['nuklear_glyph_range']
    korean_range_rva = CURRENT_OFFSETS['korean_range_rva']
    patched_count = 0

    for rva, file_offset, desc in patches:
        # 원본 바이트 검증 (lea reg, [rip+disp])
        original = bytes(data[file_offset:file_offset+7])

        # 처음 2바이트는 lea 명령어 prefix (0x48 0x8d)
        if original[0:2] != bytes([0x48, 0x8d]):
            print(f"  [!] {desc}: 예상치 못한 opcode, 건너뜀")
            continue

        # 새 displacement 계산: korean_range_rva - (rva + 7)
        new_disp = korean_range_rva - (rva + 7)
        new_bytes = original[0:3] + struct.pack('<i', new_disp)

        data[file_offset:file_offset+7] = new_bytes
        print(f"  [OK] {desc}")
        patched_count += 1

    return patched_count


# ============================================================================
# 설치/제거
# ============================================================================

def install():
    """한글 패치 설치"""
    print("=" * 50)
    print("NWN:EE Windows 한글 패치 설치")
    print("=" * 50)
    print()

    # 파일 검증
    if not NWMAIN.exists():
        print(f"오류: NWN:EE를 찾을 수 없습니다")
        print(f"      경로: {NWMAIN}")
        return False

    if not DLL_SRC.exists():
        print(f"오류: DLL 파일이 없습니다: {DLL_SRC}")
        return False

    if not LOADER_SRC.exists():
        print(f"오류: 로더 파일이 없습니다: {LOADER_SRC}")
        return False

    # 백업 디렉토리 생성
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 백업 및 해시 검증
    detected_version = None

    if BACKUP.exists():
        print(f"기존 백업 발견: {BACKUP.name}")

        # 백업 파일 해시 검증
        is_valid, msg, detected_version = verify_binary(BACKUP)
        if is_valid:
            print(f"  -> 백업 검증: {msg}")
            print("  -> 백업에서 원본 복원 후 패치를 적용합니다")
            shutil.copy(BACKUP, NWMAIN)
        else:
            print(f"  [!] 백업 검증 실패: {msg}")
            print("      백업 파일이 손상되었거나 알 수 없는 버전입니다.")
            print("      Steam에서 게임 파일 무결성 검사 후 다시 시도하세요.")
            return False
    else:
        print("원본 바이너리 검증 중...")
        is_valid, msg, detected_version = verify_binary(NWMAIN)

        if is_valid:
            print(f"  [OK] {msg}")
        else:
            print(f"  [!] 경고: {msg}")
            print("      테스트되지 않은 버전입니다. 패치가 작동하지 않을 수 있습니다.")
            response = input("      계속하시겠습니까? (y/N): ").strip().lower()
            if response != 'y':
                print("      설치를 취소합니다.")
                return False

        print("백업 생성 중...")
        shutil.copy(NWMAIN, BACKUP)
        print(f"  -> {BACKUP}")

    # 버전별 오프셋 설정
    if detected_version:
        if not set_offsets_for_version(detected_version):
            print(f"  [!] 오류: 버전 {detected_version}에 대한 오프셋이 정의되지 않았습니다.")
            return False
        print(f"  -> 버전 {detected_version} 오프셋 사용")
    else:
        # 알 수 없는 버전 - 기본값으로 8193.35 시도
        print("  -> 알 수 없는 버전, 8193.35 오프셋으로 시도")
        set_offsets_for_version("8193.35")

    # 바이너리 읽기
    print()
    print("바이너리 패치 적용 중...")

    with open(NWMAIN, 'rb') as f:
        data = bytearray(f.read())

    # 기본 패치 적용
    patches = get_patches_for_version()
    for patch in patches:
        file_offset = patch['offset']
        patch_len = len(patch['original'])
        current = bytes(data[file_offset:file_offset+patch_len])

        if current == patch['original']:
            data[file_offset:file_offset+patch_len] = patch['patched']
            print(f"  [OK] {patch['name']}")
        elif current == patch['patched']:
            print(f"  [skip] {patch['name']} (이미 적용됨)")
        else:
            print(f"  [!] {patch['name']} - 예상치 못한 값: {current.hex()}")

    # Texture 4096x4096 패치
    print()
    print("텍스처 확장 패치 적용 중...")

    texture_hook = CURRENT_OFFSETS['texture_hook']
    texture_cave = CURRENT_OFFSETS['texture_cave']

    texture_code = generate_texture_patch()
    data[texture_cave:texture_cave+len(texture_code)] = texture_code

    jmp_to_cave = texture_cave - (texture_hook + 5)
    hook_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave) + bytes([0x90, 0x90])
    data[texture_hook:texture_hook+7] = hook_bytes
    print("  [OK] Texture 4096x4096")

    # TextOut CP949 디코더
    print()
    print("CP949 디코더 패치 적용 중...")

    textout_offset = CURRENT_OFFSETS['textout']
    textout_cave = CURRENT_OFFSETS['textout_cave']

    textout_code = generate_textout_patch()
    data[textout_cave:textout_cave+len(textout_code)] = textout_code

    jmp_to_cave = textout_cave - (textout_offset + 5)
    jmp_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave)
    data[textout_offset:textout_offset+5] = jmp_bytes
    print("  [OK] CP949 TextOut decoder")

    # Nuklear UI 글리프 범위 패치
    print()
    print("Nuklear 글리프 범위 패치 적용 중...")
    patched = apply_nuklear_glyph_range_patch(data)
    print(f"  Total: {patched}/4 patches applied")

    # 저장
    with open(NWMAIN, 'wb') as f:
        f.write(data)

    # DLL과 로더 복사
    print()
    print("DLL 및 로더 복사 중...")

    dll_dst = NWN_DIR / DLL_NAME
    loader_dst = NWN_DIR / LOADER_NAME

    shutil.copy(DLL_SRC, dll_dst)
    print(f"  [OK] {DLL_NAME}")

    shutil.copy(LOADER_SRC, loader_dst)
    print(f"  [OK] {LOADER_NAME}")

    # override 파일 복사 (TLK, 폰트)
    print()
    print("리소스 파일 설치 중...")
    override_src = SCRIPT_DIR / "override"
    override_dst = NWN_DOCS / "override"

    if override_src.exists():
        override_dst.mkdir(parents=True, exist_ok=True)
        for src_file in override_src.iterdir():
            if src_file.is_file():
                dst_file = override_dst / src_file.name
                shutil.copy(src_file, dst_file)
                print(f"  [OK] override/{src_file.name}")
    else:
        print("  [!] override 디렉토리가 없습니다")
        print("      dialog.tlk와 폰트 파일을 수동으로 복사해주세요:")
        print(f"      {NWN_DOCS}\\override\\")

    # 완료
    print()
    print("=" * 50)
    print("설치 완료!")
    print("=" * 50)
    print()
    print("게임 실행 방법:")
    print(f"  {NWN_DIR}\\{LOADER_NAME}")
    print()
    print("또는 Steam에서 시작 옵션 설정:")
    print(f'  "{loader_dst}" %command%')

    return True


def uninstall():
    """한글 패치 제거"""
    print("=" * 50)
    print("NWN:EE Windows 한글 패치 제거")
    print("=" * 50)
    print()

    if BACKUP.exists():
        print("백업에서 복원 중...")
        shutil.copy(BACKUP, NWMAIN)
        print("  [OK] 바이너리 복원")

        # DLL과 로더 제거
        dll_dst = NWN_DIR / DLL_NAME
        loader_dst = NWN_DIR / LOADER_NAME

        if dll_dst.exists():
            dll_dst.unlink()
            print(f"  [OK] {DLL_NAME} 제거")

        if loader_dst.exists():
            loader_dst.unlink()
            print(f"  [OK] {LOADER_NAME} 제거")

        print()
        print("제거 완료!")
        return True
    else:
        print("오류: 백업 파일이 없습니다")
        print("      Steam에서 게임 파일 무결성 검사를 실행하세요")
        return False


def check():
    """패치 상태 확인"""
    print("=" * 50)
    print("패치 상태 확인")
    print("=" * 50)
    print()

    if not NWMAIN.exists():
        print("오류: NWN:EE를 찾을 수 없습니다")
        return

    # 해시 정보
    print("바이너리 정보:")
    detected_version = None
    file_hash = calculate_sha256(NWMAIN)
    if file_hash in KNOWN_HASHES:
        print(f"  현재: 패치됨 또는 원본 ({KNOWN_HASHES[file_hash]})")
    else:
        print(f"  현재: 알 수 없음 (해시: {file_hash[:16]}...)")

    if BACKUP.exists():
        backup_hash = calculate_sha256(BACKUP)
        if backup_hash in KNOWN_HASHES:
            detected_version = KNOWN_HASHES[backup_hash]
            print(f"  백업: {detected_version}")
        else:
            print(f"  백업: 알 수 없음 (해시: {backup_hash[:16]}...)")
    else:
        print("  백업: 없음")

    print()

    # 버전 감지 및 오프셋 설정
    if detected_version:
        set_offsets_for_version(detected_version)
    else:
        # 기본 버전 사용
        set_offsets_for_version("8193.35")

    with open(NWMAIN, 'rb') as f:
        data = f.read()

    print("바이너리 패치:")
    all_patched = True

    patches = get_patches_for_version()
    for patch in patches:
        file_offset = patch['offset']
        patch_len = len(patch['original'])
        current = data[file_offset:file_offset+patch_len]

        if current == patch['patched']:
            status = "적용됨"
        elif current == patch['original']:
            status = "미적용"
            all_patched = False
        else:
            status = f"알 수 없음 ({current.hex()})"
            all_patched = False

        print(f"  {patch['name']}: {status}")

    print()
    print("파일:")
    dll_exists = (NWN_DIR / DLL_NAME).exists()
    loader_exists = (NWN_DIR / LOADER_NAME).exists()

    print(f"  {DLL_NAME}: {'있음' if dll_exists else '없음'}")
    print(f"  {LOADER_NAME}: {'있음' if loader_exists else '없음'}")

    print()
    if all_patched and dll_exists and loader_exists:
        print("상태: 패치 적용됨")
    else:
        print("상태: 패치 미적용 또는 불완전")


# ============================================================================
# 메인
# ============================================================================

def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == "--uninstall":
            uninstall()
        elif sys.argv[1] == "--check":
            check()
        elif sys.argv[1] in ["-h", "--help"]:
            print(__doc__)
        else:
            print(f"알 수 없는 옵션: {sys.argv[1]}")
            print("사용법: python install.py [--uninstall|--check]")
    else:
        install()


if __name__ == "__main__":
    main()
