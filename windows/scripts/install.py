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

# ============================================================================
# 경로 설정
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
NWN_DIR = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32")
NWN_DOCS = Path.home() / "Documents" / "Neverwinter Nights"
NWMAIN = NWN_DIR / "nwmain.exe"
BACKUP_DIR = SCRIPT_DIR / "backup"
BACKUP = BACKUP_DIR / "nwmain.exe.original"

# ============================================================================
# 원본 바이너리 해시 (검증용)
# ============================================================================

# SHA256 해시 - 테스트된 nwmain.exe 버전들
KNOWN_HASHES = {
    # Steam Build 8193.35 (2024)
    "4e1bd743944027ddca7b11b96fa856b1f51e3b7ad0f2747ddfc53b35312be8df": "8193.35 (Steam)",
}

def calculate_sha256(filepath: Path) -> str:
    """파일의 SHA256 해시 계산"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()

def verify_binary(filepath: Path) -> tuple[bool, str]:
    """바이너리 해시 검증. (성공여부, 메시지) 반환"""
    if not filepath.exists():
        return False, "파일이 존재하지 않습니다"

    file_hash = calculate_sha256(filepath)

    if file_hash in KNOWN_HASHES:
        version = KNOWN_HASHES[file_hash]
        return True, f"검증됨: {version}"
    else:
        return False, f"알 수 없는 버전 (해시: {file_hash[:16]}...)"

# 필요한 파일들
DLL_NAME = "nwn_korean_hook.dll"
LOADER_NAME = "nwn_korean_loader.exe"
DLL_SRC = SCRIPT_DIR / DLL_NAME
LOADER_SRC = SCRIPT_DIR / LOADER_NAME

# ============================================================================
# 패치 정의
# ============================================================================

def rva_to_file_offset(data, rva):
    """RVA를 파일 오프셋으로 변환"""
    pe_offset = struct.unpack('<I', data[0x3C:0x40])[0]
    num_sections = struct.unpack('<H', data[pe_offset+6:pe_offset+8])[0]
    opt_hdr_size = struct.unpack('<H', data[pe_offset+20:pe_offset+22])[0]
    sec_table = pe_offset + 24 + opt_hdr_size
    for i in range(num_sections):
        sec_off = sec_table + i * 40
        virt_addr = struct.unpack('<I', data[sec_off+12:sec_off+16])[0]
        virt_size = struct.unpack('<I', data[sec_off+8:sec_off+12])[0]
        raw_ptr = struct.unpack('<I', data[sec_off+20:sec_off+24])[0]
        if virt_addr <= rva < virt_addr + virt_size:
            return raw_ptr + (rva - virt_addr)
    return None


# 패치 목록
PATCHES = [
    # Phase 1: 경계 체크 패치
    {
        'name': 'GetSymbolCoords boundary check',
        'rva': 0x000eaf20,
        'original': bytes([0x81, 0xfa, 0xff, 0x00, 0x00, 0x00]),  # cmp edx, 0xFF
        'patched': bytes([0x81, 0xfa, 0x35, 0x0a, 0x00, 0x00]),   # cmp edx, 0x0A35 (2613)
    },
    {
        'name': 'SetSymbolCoords boundary check',
        'rva': 0x000ed39f,
        'original': bytes([0x81, 0xfa, 0xff, 0x00, 0x00, 0x00]),  # cmp edx, 0xFF
        'patched': bytes([0x81, 0xfa, 0x35, 0x0a, 0x00, 0x00]),   # cmp edx, 0x0A35 (2613)
    },
    # Glyph Padding: 3 -> 16 (문자 침범 문제 해결)
    {
        'name': 'Glyph padding 3 -> 16',
        'rva': 0x000fb880,
        'original': bytes([0x48, 0xc7, 0x45, 0xbc, 0x03, 0x00, 0x00, 0x00]),
        'patched': bytes([0x48, 0xc7, 0x45, 0xbc, 0x10, 0x00, 0x00, 0x00]),
    },
]

# Texture 4096x4096 패치 (code cave 사용)
TEXTURE_HOOK_RVA = 0x000fb7e7
TEXTURE_CAVE_RVA = 0x002df54f

# TextOut CP949 디코더 (code cave 사용)
TEXTOUT_RVA = 0x0004ca06
TEXTOUT_NEXT_RVA = 0x0004ca0b
TEXTOUT_CAVE_RVA = 0x00966dd3

# Nuklear 한글 글리프 범위 패치
NUKLEAR_PATCHES = [
    (0xa70fe3, 0xa703e3, "Main font setup"),
    (0xa82fe8, 0xa823e8, "Secondary font"),
    (0xa8405c, 0xa8345c, "Font config init"),
    (0xa840b0, 0xa834b0, "Glyph range getter"),
]

# ============================================================================
# 패치 생성 함수
# ============================================================================

def generate_texture_patch():
    """4096x4096 텍스처 코드 생성"""
    code = bytearray()
    code += bytes([0xbe, 0x00, 0x10, 0x00, 0x00])  # mov esi, 0x1000 (4096)
    code += bytes([0xbb, 0x00, 0x10, 0x00, 0x00])  # mov ebx, 0x1000 (4096)
    code += bytes([0x44, 0x8b, 0xeb])              # mov r13d, ebx
    code += bytes([0x44, 0x0f, 0xaf, 0xee])        # imul r13d, esi

    # jmp back
    jmp_back_rva = TEXTURE_HOOK_RVA + 7
    jmp_from_rva = TEXTURE_CAVE_RVA + len(code) + 5
    jmp_rel = jmp_back_rva - jmp_from_rva
    code += bytes([0xe9]) + struct.pack('<i', jmp_rel)

    return code


def generate_textout_patch():
    """CP949 2-byte lookahead 디코더 생성"""
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

    # 7. Exit
    exit_offset = len(code)
    jmp_from_rva = TEXTOUT_CAVE_RVA + len(code) + 5
    jmp_to_rva = TEXTOUT_NEXT_RVA
    jmp_rel = jmp_to_rva - jmp_from_rva
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # Patch jump offsets
    code[jb_exit + 1] = (exit_offset - (jb_exit + 2)) & 0xFF
    code[ja_exit + 1] = (exit_offset - (ja_exit + 2)) & 0xFF
    code[jb_exit2 + 1] = (exit_offset - (jb_exit2 + 2)) & 0xFF
    code[ja_exit2 + 1] = (exit_offset - (ja_exit2 + 2)) & 0xFF

    return code


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
    if BACKUP.exists():
        print(f"기존 백업 발견: {BACKUP.name}")

        # 백업 파일 해시 검증
        is_valid, msg = verify_binary(BACKUP)
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
        is_valid, msg = verify_binary(NWMAIN)

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

    # 바이너리 읽기
    print()
    print("바이너리 패치 적용 중...")

    with open(NWMAIN, 'rb') as f:
        data = bytearray(f.read())

    # 기본 패치 적용
    for patch in PATCHES:
        file_offset = rva_to_file_offset(data, patch['rva'])
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

    texture_code = generate_texture_patch()
    cave_offset = rva_to_file_offset(data, TEXTURE_CAVE_RVA)
    data[cave_offset:cave_offset+len(texture_code)] = texture_code

    hook_offset = rva_to_file_offset(data, TEXTURE_HOOK_RVA)
    jmp_to_cave = TEXTURE_CAVE_RVA - (TEXTURE_HOOK_RVA + 5)
    hook_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave) + bytes([0x90, 0x90])
    data[hook_offset:hook_offset+7] = hook_bytes
    print("  [OK] Texture 4096x4096")

    # TextOut CP949 디코더
    print()
    print("CP949 디코더 패치 적용 중...")

    textout_code = generate_textout_patch()
    cave_offset = rva_to_file_offset(data, TEXTOUT_CAVE_RVA)
    data[cave_offset:cave_offset+len(textout_code)] = textout_code

    textout_offset = rva_to_file_offset(data, TEXTOUT_RVA)
    jmp_to_cave = TEXTOUT_CAVE_RVA - (TEXTOUT_RVA + 5)
    jmp_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave)
    data[textout_offset:textout_offset+5] = jmp_bytes
    print("  [OK] CP949 TextOut decoder")

    # Nuklear 한글 글리프 범위 패치
    print()
    print("Nuklear UI 패치 적용 중...")

    korean_range_rva = 0xe8bd48
    for rva, file_offset, desc in NUKLEAR_PATCHES:
        original = data[file_offset:file_offset+7]
        if original[0:2] == bytes([0x48, 0x8d]):
            new_disp = korean_range_rva - (rva + 7)
            new_bytes = original[0:3] + struct.pack('<i', new_disp)
            data[file_offset:file_offset+7] = new_bytes
            print(f"  [OK] {desc}")
        else:
            print(f"  [!] {desc} - 예상치 못한 opcode")

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
    file_hash = calculate_sha256(NWMAIN)
    if file_hash in KNOWN_HASHES:
        print(f"  현재: 패치됨 또는 원본 ({KNOWN_HASHES[file_hash]})")
    else:
        print(f"  현재: 알 수 없음 (해시: {file_hash[:16]}...)")

    if BACKUP.exists():
        backup_hash = calculate_sha256(BACKUP)
        if backup_hash in KNOWN_HASHES:
            print(f"  백업: {KNOWN_HASHES[backup_hash]}")
        else:
            print(f"  백업: 알 수 없음 (해시: {backup_hash[:16]}...)")
    else:
        print("  백업: 없음")

    print()

    with open(NWMAIN, 'rb') as f:
        data = f.read()

    print("바이너리 패치:")
    all_patched = True

    for patch in PATCHES:
        file_offset = rva_to_file_offset(data, patch['rva'])
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
