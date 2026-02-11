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

# 기본 Steam 경로들
DEFAULT_STEAM_PATHS = [
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights"),
    Path(r"D:\Steam\steamapps\common\Neverwinter Nights"),
    Path(r"D:\SteamLibrary\steamapps\common\Neverwinter Nights"),
    Path(r"E:\Steam\steamapps\common\Neverwinter Nights"),
    Path(r"E:\SteamLibrary\steamapps\common\Neverwinter Nights"),
]

NWN_DIR = None  # find_nwn_path()에서 설정됨
NWMAIN = None   # find_nwn_path()에서 설정됨


def _get_documents_path() -> Path:
    """Windows 실제 '문서' 폴더 경로 반환 (OneDrive 리다이렉트 대응)"""
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-NoProfile", "-c",
             '[Environment]::GetFolderPath("MyDocuments")'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return Path.home() / "Documents"


NWN_DOCS = _get_documents_path() / "Neverwinter Nights"
BACKUP_DIR = SCRIPT_DIR / "backup"
BACKUP = BACKUP_DIR / "nwmain.exe.original"


def find_nwn_path() -> bool:
    """NWN:EE 설치 경로 찾기. 성공 시 True 반환"""
    global NWN_DIR, NWMAIN

    # 기본 경로들 확인
    for base_path in DEFAULT_STEAM_PATHS:
        nwmain_path = base_path / "bin" / "win32" / "nwmain.exe"
        if nwmain_path.exists():
            NWN_DIR = base_path / "bin" / "win32"
            NWMAIN = nwmain_path
            print(f"NWN:EE 발견: {base_path}")
            return True

    # 기본 경로에서 찾지 못함 - 사용자 입력 요청
    print("NWN:EE를 기본 경로에서 찾을 수 없습니다.")
    print()
    print("Steam 라이브러리에서 NWN:EE 설치 경로를 확인하세요:")
    print("  Steam → 라이브러리 → NWN:EE 우클릭 → 관리 → 로컬 파일 보기")
    print()

    while True:
        user_input = input("NWN:EE 설치 경로를 입력하세요 (취소: q): ").strip()

        if user_input.lower() == 'q':
            return False

        # 따옴표 제거
        user_input = user_input.strip('"').strip("'")

        user_path = Path(user_input)

        # bin/win32/nwmain.exe가 있는지 확인
        nwmain_path = user_path / "bin" / "win32" / "nwmain.exe"
        if nwmain_path.exists():
            NWN_DIR = user_path / "bin" / "win32"
            NWMAIN = nwmain_path
            return True

        # 사용자가 bin/win32까지 입력한 경우
        nwmain_path = user_path / "nwmain.exe"
        if nwmain_path.exists():
            NWN_DIR = user_path
            NWMAIN = nwmain_path
            return True

        # 실제 확인한 경로 출력 (디버깅용)
        check_path1 = user_path / "bin" / "win32" / "nwmain.exe"
        check_path2 = user_path / "nwmain.exe"
        print(f"  [!] 해당 경로에서 nwmain.exe를 찾을 수 없습니다.")
        print(f"      확인한 경로 1: {check_path1}")
        print(f"      확인한 경로 2: {check_path2}")
        print()

# ============================================================================
# 원본 바이너리 해시 및 버전별 오프셋
# ============================================================================

# SHA256 해시 - 테스트된 nwmain.exe 버전들
KNOWN_HASHES = {
    # Steam Build 8193.36+ (2025)
    "3b7cb1252e0edb2ce22d7971f333aade027039ae30a45b4bc64732c3e6bec73a": "8193.36+",
}

# 버전별 오프셋 테이블 (모든 값은 파일 오프셋)
# Note: RVA가 아닌 파일 오프셋 사용 (RVA - 0xC00 = file offset for .text section)
VERSION_OFFSETS = {
    "8193.36+": {
        # Phase 1: 경계 체크
        "get_symbol_coords": 0x000eaf20,
        "set_symbol_coords": 0x000ed39f,
        "glyph_padding": 0x000fac80,
        "texture_hook": 0x000fabe7,
        "texture_cave": 0x002de94f,
        "textout": 0x0004be06,
        "textout_next": 0x0004be0b,       # -> mov edx, ebx (single byte path)
        "textout_next_korean": 0x0004be0d, # -> lea r9, ... (skip mov edx,ebx for Korean)
        "textout_cave": 0x01373210,  # .rodata 섹션 끝 여유 공간 (496 bytes)
        # Phase 5: CalculateVisibleStringLengthAndWidth CP949 디코더
        # 폭 계산 루프에서 1바이트씩 읽어 advance를 조회하므로
        # CP949 2바이트 문자가 반으로 쪼개져 폭이 과소 계산됨 → 중앙정렬 깨짐 + 문자 침범
        "calcwidth": 0x0004b640,           # movsxd rdx, ebx (루프 내 바이트 읽기 시작)
        "calcwidth_next": 0x0004b649,      # cmp dil, 0x3C (single byte path)
        "calcwidth_next_korean": 0x0004b717, # lea r9, [rsp+28h] (GetSymbolCoords 파라미터 설정)
        "calcwidth_cave": 0x01373260,      # .rodata cave (textout cave 직후)
        # 섹션별 file_offset → RVA 변환값 (상대 점프 계산용)
        "text_fo2rva": 0xC00,            # .text: RVA = file_offset + 0xC00
        "textout_cave_fo2rva": 0x2FB800, # .rodata: RVA = file_offset + 0x2FB800
        # .rodata PE 섹션 헤더 (code cave 실행 권한)
        "rodata_vsize_offset": 0x300,
        "rodata_chars_offset": 0x31C,
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
    """CP949 2-byte lookahead 디코더 생성

    원본 코드 흐름:
        0x4CA06: movzx ebx, byte [r12]   ; hook point
        0x4CA0B: mov   edx, ebx          ; textout_next (edx = glyph for GetSymbolCoords)
        0x4CA0D: lea   r9, [rbp-0x71]    ; textout_next_korean (skip mov edx,ebx)
        ...
        0x4CA19: call  GetSymbolCoords
        0x4CA1E: cmp   bl, 0x3c          ; '<' 색상코드 체크

    버그 수정 (v2): 한글 글리프 인덱스(256+)의 하위 8비트가 0x3C('<')와
    일치하면 색상코드 파서로 잘못 진입하여 크래시 발생.
    한글 경로에서는 edx에 직접 글리프를 넣고 ebx=0으로 설정하여
    cmp bl, 0x3c를 안전하게 통과시킴.
    """
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다.")

    textout_cave = CURRENT_OFFSETS['textout_cave']
    textout_next = CURRENT_OFFSETS['textout_next']
    textout_next_korean = CURRENT_OFFSETS['textout_next_korean']

    # 섹션 간 상대 점프를 위한 RVA 변환 (.text ↔ .rodata)
    text_fo2rva = CURRENT_OFFSETS['text_fo2rva']
    cave_fo2rva = CURRENT_OFFSETS['textout_cave_fo2rva']
    cave_rva = textout_cave + cave_fo2rva
    textout_next_rva = textout_next + text_fo2rva
    textout_next_korean_rva = textout_next_korean + text_fo2rva

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

    # ebx = 256 + result (glyph index)
    code += bytes([0x81, 0xc3, 0x00, 0x01, 0x00, 0x00])  # add ebx, 256

    # 6. Korean path: set edx = glyph, ebx = 0 (safe for cmp bl, 0x3c)
    code += bytes([0x8b, 0xd3])  # mov edx, ebx (edx = glyph index)
    code += bytes([0x31, 0xdb])  # xor ebx, ebx (ebx = 0, bl != 0x3c)

    # 7. Increment edi to skip the trail byte
    code += bytes([0xff, 0xc7])  # inc edi

    # 8. Korean exit: jump past 'mov edx, ebx' to lea r9, ... (RVA 기반)
    korean_exit_offset = len(code)
    jmp_from_rva = cave_rva + len(code) + 5
    jmp_rel = textout_next_korean_rva - jmp_from_rva
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # 9. Single-byte exit: jump to 'mov edx, ebx' (original flow, RVA 기반)
    exit_offset = len(code)
    jmp_from_rva = cave_rva + len(code) + 5
    jmp_rel = textout_next_rva - jmp_from_rva
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # Patch conditional jump offsets (all jump to single-byte exit)
    code[jb_exit + 1] = (exit_offset - (jb_exit + 2)) & 0xFF
    code[ja_exit + 1] = (exit_offset - (ja_exit + 2)) & 0xFF
    code[jb_exit2 + 1] = (exit_offset - (jb_exit2 + 2)) & 0xFF
    code[ja_exit2 + 1] = (exit_offset - (ja_exit2 + 2)) & 0xFF

    return code


def generate_calcwidth_patch():
    """CalculateVisibleStringLengthAndWidth CP949 2-byte 디코더 생성

    원본 코드 흐름 (RVA):
        0x4C240: movsxd rdx, ebx          ; 루프 인덱스 확장
        0x4C243: add    rdx, r12           ; 문자열 base + index
        0x4C246: movzx  edi, byte [rdx]    ; ← 1바이트만 읽음 (문제의 원인)
        0x4C249: cmp    dil, 0x3C          ; '<' 색상코드 체크
        ...
        0x4C313: movzx  edx, dil           ; ← 하위 8비트만 GetSymbolCoords에 전달
        0x4C317: lea    r9, [rsp+28h]      ; GetSymbolCoords 파라미터 설정 시작
        ...
        0x4C343: call   GetSymbolCoords

    한글 경로: CP949 디코딩 후 edx에 글리프 인덱스를 직접 넣고
    movzx edx, dil (8비트 절삭)과 문자 타입 체크를 건너뛰어
    GetSymbolCoords 파라미터 설정(0x4C317)으로 직행.
    edi=0으로 설정하여 후속 newline/space 체크 안전 통과.
    """
    if CURRENT_OFFSETS is None:
        raise RuntimeError("오프셋이 설정되지 않았습니다.")

    calcwidth_cave = CURRENT_OFFSETS['calcwidth_cave']
    calcwidth_next = CURRENT_OFFSETS['calcwidth_next']
    calcwidth_next_korean = CURRENT_OFFSETS['calcwidth_next_korean']

    # 섹션 간 상대 점프를 위한 RVA 변환
    text_fo2rva = CURRENT_OFFSETS['text_fo2rva']
    cave_fo2rva = CURRENT_OFFSETS['textout_cave_fo2rva']  # 같은 .rodata 섹션
    cave_rva = calcwidth_cave + cave_fo2rva
    calcwidth_next_rva = calcwidth_next + text_fo2rva
    calcwidth_next_korean_rva = calcwidth_next_korean + text_fo2rva

    code = bytearray()

    # 1. Replaced instructions
    code += bytes([0x48, 0x63, 0xd3])              # movsxd rdx, ebx
    code += bytes([0x49, 0x03, 0xd4])              # add rdx, r12
    code += bytes([0x0f, 0xb6, 0x3a])              # movzx edi, byte [rdx]

    # 2. Check if lead byte (0xB0-0xC8)
    code += bytes([0x40, 0x80, 0xff, 0xb0])        # cmp dil, 0xB0
    jb_exit = len(code)
    code += bytes([0x72, 0x00])                     # jb .not_korean

    code += bytes([0x40, 0x80, 0xff, 0xc8])        # cmp dil, 0xC8
    ja_exit = len(code)
    code += bytes([0x77, 0x00])                     # ja .not_korean

    # 3. Read trail byte
    code += bytes([0x0f, 0xb6, 0x42, 0x01])        # movzx eax, byte [rdx+1]

    # 4. Check trail byte (0xA1-0xFE)
    code += bytes([0x3c, 0xa1])                     # cmp al, 0xA1
    jb_exit2 = len(code)
    code += bytes([0x72, 0x00])                     # jb .not_korean

    code += bytes([0x3c, 0xfe])                     # cmp al, 0xFE
    ja_exit2 = len(code)
    code += bytes([0x77, 0x00])                     # ja .not_korean

    # 5. Compute glyph index: 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    code += bytes([0x89, 0xc1])                     # mov ecx, eax (save trail)
    code += bytes([0x81, 0xef, 0xb0, 0x00, 0x00, 0x00])  # sub edi, 0xB0
    code += bytes([0x6b, 0xff, 0x5e])               # imul edi, edi, 94
    code += bytes([0x81, 0xe9, 0xa1, 0x00, 0x00, 0x00])  # sub ecx, 0xA1
    code += bytes([0x01, 0xcf])                     # add edi, ecx
    code += bytes([0x81, 0xc7, 0x00, 0x01, 0x00, 0x00])  # add edi, 256

    # 6. Korean path: edx=glyph, rcx=font, edi=0(safe), inc ebx
    code += bytes([0x8b, 0xd7])                     # mov edx, edi
    code += bytes([0x48, 0x8b, 0x4d, 0x28])         # mov rcx, [rbp+28h]
    code += bytes([0x31, 0xff])                     # xor edi, edi
    code += bytes([0xff, 0xc3])                     # inc ebx

    # 7. Korean exit: jump to lea r9, [rsp+28h] (GetSymbolCoords 파라미터 설정)
    jmp_from_rva = cave_rva + len(code) + 5
    jmp_rel = calcwidth_next_korean_rva - jmp_from_rva
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # 8. Non-Korean exit: jump back to cmp dil, 0x3C
    exit_offset = len(code)
    jmp_from_rva = cave_rva + len(code) + 5
    jmp_rel = calcwidth_next_rva - jmp_from_rva
    code += bytes([0xe9])
    code += struct.pack('<i', jmp_rel)

    # Patch conditional jump offsets
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

def install(skip_patches=None):
    """한글 패치 설치

    Args:
        skip_patches: 건너뛸 패치 목록 (예: ['textout', 'nuklear', 'texture', 'padding', 'boundary'])
    """
    if skip_patches is None:
        skip_patches = []

    print("=" * 50)
    print("NWN:EE Windows 한글 패치 설치")
    print("=" * 50)
    if skip_patches:
        print(f"  [진단 모드] 비활성화: {', '.join(skip_patches)}")
    print()

    # NWN:EE 경로 찾기
    if not find_nwn_path():
        print("설치를 취소합니다.")
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
        # 알 수 없는 버전 - 기본값으로 8193.36+ 시도
        print("  -> 알 수 없는 버전, 8193.36+ 오프셋으로 시도")
        set_offsets_for_version("8193.36+")

    # 바이너리 읽기
    print()
    print("바이너리 패치 적용 중...")

    with open(NWMAIN, 'rb') as f:
        data = bytearray(f.read())

    # 기본 패치 적용
    patches = get_patches_for_version()
    for patch in patches:
        # boundary skip: 경계 패치 건너뛰기
        if 'boundary' in skip_patches and 'boundary' in patch['name'].lower():
            print(f"  [SKIP] {patch['name']} (진단: boundary 비활성화)")
            continue
        # padding skip
        if 'padding' in skip_patches and 'padding' in patch['name'].lower():
            print(f"  [SKIP] {patch['name']} (진단: padding 비활성화)")
            continue

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
    if 'texture' in skip_patches:
        print()
        print("  [SKIP] Texture 4096x4096 (진단: texture 비활성화)")
    else:
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

    # .rodata 섹션 헤더 패치 (TextOut/CalcWidth code cave 공통)
    text_fo2rva = CURRENT_OFFSETS['text_fo2rva']
    cave_fo2rva = CURRENT_OFFSETS['textout_cave_fo2rva']

    if 'textout' not in skip_patches or 'calcwidth' not in skip_patches:
        rodata_vsize_off = CURRENT_OFFSETS['rodata_vsize_offset']
        rodata_chars_off = CURRENT_OFFSETS['rodata_chars_offset']

        vsize_val = struct.unpack('<I', data[rodata_vsize_off:rodata_vsize_off+4])[0]
        if vsize_val == 0x00000A10:
            data[rodata_vsize_off:rodata_vsize_off+4] = struct.pack('<I', 0x00000C00)
        elif vsize_val != 0x00000C00:
            print(f"  [!] .rodata VirtualSize 예상치 못한 값: 0x{vsize_val:08X}")

        chars_val = struct.unpack('<I', data[rodata_chars_off:rodata_chars_off+4])[0]
        if chars_val == 0x40000040:
            data[rodata_chars_off:rodata_chars_off+4] = struct.pack('<I', 0x60000060)
        elif chars_val != 0x60000060:
            print(f"  [!] .rodata Characteristics 예상치 못한 값: 0x{chars_val:08X}")

        print("  [OK] .rodata 섹션 헤더 (실행 권한 추가)")

    # TextOut CP949 디코더
    if 'textout' in skip_patches:
        print()
        print("  [SKIP] CP949 TextOut decoder (진단: textout 비활성화)")
    else:
        print()
        print("CP949 디코더 패치 적용 중...")

        textout_offset = CURRENT_OFFSETS['textout']
        textout_cave = CURRENT_OFFSETS['textout_cave']

        # Code cave 작성 (파일 오프셋)
        textout_code = generate_textout_patch()
        data[textout_cave:textout_cave+len(textout_code)] = textout_code

        # Hook: jmp to cave (RVA 기반 상대 점프, .text → .rodata 섹션 간 이동)
        textout_rva = textout_offset + text_fo2rva
        cave_rva = textout_cave + cave_fo2rva
        jmp_to_cave = cave_rva - (textout_rva + 5)
        jmp_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave)
        data[textout_offset:textout_offset+5] = jmp_bytes
        print("  [OK] CP949 TextOut decoder")

    # CalcWidth CP949 디코더 (중앙정렬 + 문자 침범 수정)
    if 'calcwidth' in skip_patches:
        print()
        print("  [SKIP] CP949 CalcWidth decoder (진단: calcwidth 비활성화)")
    else:
        print()
        print("CP949 폭 계산 디코더 패치 적용 중...")

        calcwidth_offset = CURRENT_OFFSETS['calcwidth']
        calcwidth_cave = CURRENT_OFFSETS['calcwidth_cave']

        # Code cave 작성
        calcwidth_code = generate_calcwidth_patch()
        data[calcwidth_cave:calcwidth_cave+len(calcwidth_code)] = calcwidth_code

        # Hook: jmp to cave (RVA 기반 상대 점프)
        calcwidth_rva = calcwidth_offset + text_fo2rva
        cw_cave_rva = calcwidth_cave + cave_fo2rva
        jmp_to_cave = cw_cave_rva - (calcwidth_rva + 5)
        jmp_bytes = bytes([0xe9]) + struct.pack('<i', jmp_to_cave)
        # 9바이트 교체: 5바이트 JMP + 4바이트 NOP
        data[calcwidth_offset:calcwidth_offset+9] = jmp_bytes + bytes([0x90] * 4)
        print("  [OK] CP949 CalcWidth decoder (중앙정렬 수정)")

    # Nuklear UI 글리프 범위 패치 - 비활성화
    # Nuklear 텍스트 변환 훅이 미완성이므로 글리프 범위 패치도 비활성화
    # 상세 분석: docs/NUKLEAR_ANALYSIS.md 참조
    # if 'nuklear' not in skip_patches:
    #     print()
    #     print("Nuklear 글리프 범위 패치 적용 중...")
    #     patched = apply_nuklear_glyph_range_patch(data)
    #     print(f"  Total: {patched}/4 patches applied")

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

    # NWN:EE 경로 찾기
    if not find_nwn_path():
        print("제거를 취소합니다.")
        return False

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

    # NWN:EE 경로 찾기
    if not find_nwn_path():
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
        set_offsets_for_version("8193.36+")

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
    args = sys.argv[1:]

    if "--uninstall" in args:
        uninstall()
        return
    if "--check" in args:
        check()
        return
    if "-h" in args or "--help" in args:
        print(__doc__)
        print()
        print("진단 옵션:")
        print("  --skip textout    CP949 TextOut 디코더 비활성화")
        print("  --skip calcwidth  CP949 폭 계산 디코더 비활성화")
        print("  --skip nuklear    Nuklear 글리프 범위 패치 비활성화")
        print("  --skip texture    텍스처 4096 패치 비활성화")
        print("  --skip padding    글리프 패딩 패치 비활성화")
        print("  --skip boundary   경계 체크 패치 비활성화")
        print()
        print("예: python install.py --skip textout --skip nuklear")
        return

    # --skip 옵션 파싱
    skip_patches = []
    i = 0
    while i < len(args):
        if args[i] == "--skip" and i + 1 < len(args):
            skip_patches.append(args[i + 1])
            i += 2
        else:
            print(f"알 수 없는 옵션: {args[i]}")
            print("사용법: python install.py [--uninstall|--check|--skip <patch>]")
            return
            i += 1

    install(skip_patches=skip_patches)


if __name__ == "__main__":
    main()
