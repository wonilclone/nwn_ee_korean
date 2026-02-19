#!/usr/bin/env python3
"""
NWN:EE Android (arm64) libnwmain.so 한글 패치 스크립트

Phase 1: GetSymbolCoords/SetSymbolCoords 경계 확장 (255 → 2613)
Phase 2: CAuroraTTFTexture::Load 폰트 베이킹 확장 (256 → 2606 글리프)
Phase 3: TextOut 내 CP949 디코더 (inline trampoline)
Texture: 텍스처 크기 4096x4096, 글리프 패딩 확장

사용법:
    python3 patch_libnwmain.py              # 패치 적용
    python3 patch_libnwmain.py --check      # 상태 확인
    python3 patch_libnwmain.py --restore    # 원본 복원
"""

import re
import struct
import shutil
import argparse
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ORIGINAL = SCRIPT_DIR / "libnwmain.so"
PATCHED = SCRIPT_DIR / "libnwmain_patched.so"
BACKUP = SCRIPT_DIR / "libnwmain.so.backup"
KSX1001_PATH = SCRIPT_DIR.parent / "mac" / "hook" / "ksx1001_hangul.h"

KOREAN_GLYPH_COUNT = 2614  # 0-2613
TOTAL_GLYPH_COUNT = 2606   # 256 ASCII + 2350 Korean
HANGUL_COUNT = 2350

# ============================================================================
# ARM64 명령어 인코딩 헬퍼
# ============================================================================


def encode_b(from_offset: int, to_offset: int) -> bytes:
    """ARM64 B (무조건 분기) 명령어 인코딩"""
    diff = to_offset - from_offset
    assert diff % 4 == 0, f"offset not aligned: {diff}"
    imm26 = diff // 4
    assert -(1 << 25) <= imm26 < (1 << 25), f"branch offset out of range: {diff:#x}"
    imm26 &= 0x3FFFFFF
    instr = (0b000101 << 26) | imm26
    return instr.to_bytes(4, 'little')


def encode_b_int(from_offset: int, to_offset: int) -> int:
    """ARM64 B 명령어 (int 반환)"""
    return int.from_bytes(encode_b(from_offset, to_offset), 'little')


def encode_bcond(cond: int, offset: int) -> int:
    """ARM64 B.cond 인코딩
    cond: 0=eq, 1=ne, 2=cs/hs, 3=cc/lo, 8=hi, 9=ls
    """
    assert offset % 4 == 0
    imm19 = offset // 4
    assert -(1 << 18) <= imm19 < (1 << 18)
    imm19 &= 0x7FFFF
    return (0b01010100 << 24) | (imm19 << 5) | cond


def _movz_w(rd, imm16, hw=0):
    """MOVZ Wd, #imm16{, LSL #(hw*16)}"""
    assert 0 <= imm16 <= 0xFFFF
    return 0x52800000 | (hw << 21) | (imm16 << 5) | rd


def _mov_x(rd, rm):
    """MOV Xd, Xm (ORR Xd, XZR, Xm)"""
    return 0xAA0003E0 | (rm << 16) | rd


def _cmp_w_imm(rn, imm12):
    """CMP Wn, #imm12 (SUBS WZR, Wn, #imm12)"""
    assert 0 <= imm12 <= 0xFFF
    return 0x71000000 | (imm12 << 10) | (rn << 5) | 0x1F


def _add_w_imm(rd, rn, imm12):
    """ADD Wd, Wn, #imm12"""
    assert 0 <= imm12 <= 0xFFF
    return 0x11000000 | (imm12 << 10) | (rn << 5) | rd


def _add_x_imm(rd, rn, imm12):
    """ADD Xd, Xn, #imm12"""
    assert 0 <= imm12 <= 0xFFF
    return 0x91000000 | (imm12 << 10) | (rn << 5) | rd


def _add_w_reg(rd, rn, rm):
    """ADD Wd, Wn, Wm"""
    return 0x0B000000 | (rm << 16) | (rn << 5) | rd


def _ldr_w_post(rt, rn, imm9):
    """LDR Wt, [Xn], #imm9 (post-indexed)"""
    return 0xB8400400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _str_w_post(rt, rn, imm9):
    """STR Wt, [Xn], #imm9 (post-indexed)"""
    return 0xB8000400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _ldrh_post(rt, rn, imm9):
    """LDRH Wt, [Xn], #imm9 (post-indexed)"""
    return 0x78400400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _ldrb_post(rt, rn, imm9):
    """LDRB Wt, [Xn], #imm9 (post-indexed)"""
    return 0x38400400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _adrp(rd, current_pc, target_addr):
    """ADRP Xd, target_page (PC-relative page address load)"""
    target_page = target_addr & ~0xFFF
    current_page = current_pc & ~0xFFF
    page_diff = (target_page - current_page) >> 12
    # 21-bit signed immediate
    assert -(1 << 20) <= page_diff < (1 << 20), f"ADRP offset out of range: {page_diff}"
    imm = page_diff & 0x1FFFFF
    immlo = imm & 0x3
    immhi = (imm >> 2) & 0x7FFFF
    return (1 << 31) | (immlo << 29) | (0x10 << 24) | (immhi << 5) | rd


def _bl(current_pc, target_addr):
    """BL target (branch with link)"""
    offset = target_addr - current_pc
    assert offset % 4 == 0
    imm26 = (offset // 4) & 0x3FFFFFF
    return 0x94000000 | imm26


def _instr_to_bytes(code_list):
    """명령어 리스트를 bytes로 변환"""
    return b''.join(instr.to_bytes(4, 'little') for instr in code_list)


# ============================================================================
# Phase 1: 경계 체크 패치
# ============================================================================

PATCHES = [
    {
        'name': 'GetSymbolCoords cmp 255 (built flag set)',
        'offset': 0x8deda8,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
    {
        'name': 'GetSymbolCoords cmp 256 (built flag clear)',
        'offset': 0x8dedf4,
        'original': bytes.fromhex('3f000471'),
        'patched': bytes.fromhex('3fd82871'),
        'description': 'alt path check 256 → 2614',
    },
    {
        'name': 'SetSymbolCoords cmp 255 (built flag set)',
        'offset': 0x8dee1c,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
    {
        'name': 'SetSymbolCoords cmp 255 (built flag clear)',
        'offset': 0x8dee6c,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
]

# ============================================================================
# Texture 패치
# ============================================================================

TEXTURE_PATCHES = [
    {
        'name': 'CAuroraTTFTexture::Load height',
        'offset': 0xa954f4,
        'original': bytes.fromhex('08190011'),  # add w8, w8, #6
        'patched': bytes.fromhex('08008252'),    # mov w8, #4096
        'description': 'texture height → 4096',
    },
    {
        'name': 'CAuroraTTFTexture::Load width',
        'offset': 0xa95510,
        'original': bytes.fromhex('2801080b'),  # add w8, w9, w8
        'patched': bytes.fromhex('08008252'),    # mov w8, #4096
        'description': 'texture width → 4096',
    },
    {
        'name': 'CAuroraTTFTexture::Load glyph padding',
        'offset': 0xa95564,
        'original': bytes.fromhex('65008052'),  # mov w5, #3
        'patched': bytes.fromhex('05028052'),    # mov w5, #16
        'description': 'glyph padding 3 → 16',
    },
]

# ============================================================================
# Phase 2: 폰트 베이킹 확장 (CAuroraTTFTexture::Load 훅)
# ============================================================================
#
# Load()는 stbtt_PackFontRanges를 호출하여 폰트 글리프를 텍스처에 베이크.
# 원본: chars[256] = {0, 1, ..., 255} (ASCII만)
# 패치: chars[2606] = {0, ..., 255, 0xAC00, 0xAC01, ...} (ASCII + 한글)
#
# 훅 위치: 0xa95538 (mov x26, x0) → B phase2_hook
# 복귀 위치: 0xa9553c (mov w23, w20)
#
# 레지스터 상태:
#   x0 = 비트맵 포인터 (from _Znam), x24 = chars, w20 = count
#   x26 = 비트맵 (hook에서 설정), w8 = 0x1c (hook에서 복원)

PHASE2_HOOK_OFFSET = 0x1417a70     # Code cave (Phase 3 trampoline 이후)
PHASE2_PATCH_OFFSET = 0xa95538     # mov x26, x0 in Load()
PHASE2_RETURN_OFFSET = 0xa9553c    # mov w23, w20 (복귀 지점)
DELTA_TABLE_OFFSET = 0x84469c      # .eh_frame → .text 갭 (RX, 2404 bytes)
ZNAM_PLT = 0x15a6fb0               # operator new[](_Znam) PLT entry

# ============================================================================
# Phase 3: Inline Trampoline (CP949 디코딩)
# ============================================================================

TEXTOUT_MOV_OFFSET = 0x852f5c       # mov w1, w25 위치
TEXTOUT_RETURN_OFFSET = 0x852f60    # bl GetSymbolCoords (리턴 지점)
TRAMPOLINE_OFFSET = 0x1417a20       # Code cave 시작, 16바이트 정렬


# ============================================================================
# KSX1001 데이터 처리
# ============================================================================

def parse_ksx1001_codepoints() -> list:
    """ksx1001_hangul.h에서 유니코드 코드포인트 2350개 추출"""
    with open(KSX1001_PATH, 'r') as f:
        content = f.read()
    values = [int(v, 16) for v in re.findall(r'0x([0-9A-Fa-f]+)', content)]
    assert len(values) == HANGUL_COUNT, f"Expected {HANGUL_COUNT}, got {len(values)}"
    # 정렬 확인
    assert all(values[i] < values[i + 1] for i in range(len(values) - 1)), \
        "Codepoints are not strictly ascending"
    return values


def encode_delta_table(codepoints: list) -> bytes:
    """
    델타 인코딩: first_cp (uint16 LE) + deltas (uint8 each)
    모든 KSX1001 델타가 1-91 범위이므로 1바이트로 충분.
    총 크기: 2 + 2349 = 2351 bytes
    """
    result = struct.pack('<H', codepoints[0])
    for i in range(1, len(codepoints)):
        delta = codepoints[i] - codepoints[i - 1]
        assert 1 <= delta <= 255, f"Delta {delta} at index {i} out of uint8 range"
        result += struct.pack('B', delta)
    return result


# ============================================================================
# Phase 2 훅 코드 생성
# ============================================================================

def generate_phase2_hook(hook_base, return_addr, znam_plt, delta_table_addr):
    """
    Phase 2: 폰트 베이킹 확장 훅 ARM64 코드 생성

    Load() 0xa95538의 mov x26, x0 대신 이 훅으로 분기.
    w20 == 256이면:
      1. 2606*4 바이트 할당 (operator new[])
      2. 원본 256개 복사
      3. 델타 테이블에서 한글 2350개 디코딩
      4. x24 = 확장 배열, w20 = 2606 교체
    w20 != 256이면 건너뜀.
    항상 w8 = 0x1c 복원 후 복귀.

    caller-saved (x0-x15): _Znam 호출 후 유실 → OK
    callee-saved (x19-x28): _Znam이 보존 → x24,w20,x26 안전
    """
    code = []

    # [0] mov x26, x0          ; 덮어쓴 원본 명령 (비트맵 ptr 저장)
    code.append(_mov_x(26, 0))

    # [1] cmp w20, #256         ; 256-char 케이스만 확장
    code.append(_cmp_w_imm(20, 256))

    EXIT_IDX = 26  # phase2_exit 인덱스

    # [2] b.ne phase2_exit      ; 256이 아니면 건너뜀
    code.append(encode_bcond(1, (EXIT_IDX - 2) * 4))

    # [3] movz w0, #0x28B8     ; 2606 * 4 = 10424 bytes
    code.append(_movz_w(0, TOTAL_GLYPH_COUNT * 4))

    # [4] bl _Znam@plt          ; x0 = operator new[](10424)
    code.append(_bl(hook_base + 4 * 4, znam_plt))

    # [5] mov x10, x0           ; 쓰기 포인터 (새 배열)
    code.append(_mov_x(10, 0))

    # [6] mov x11, x24          ; 읽기 포인터 (원본 chars)
    code.append(_mov_x(11, 24))

    # [7] movz w12, #0          ; 카운터 초기화
    code.append(_movz_w(12, 0))

    COPY_IDX = 8  # copy_loop 시작

    # === copy_loop: 원본 256개 복사 ===
    # [8] ldr w13, [x11], #4    ; chars[i] 읽기 (post-increment)
    code.append(_ldr_w_post(13, 11, 4))

    # [9] str w13, [x10], #4    ; new_array[i]에 쓰기
    code.append(_str_w_post(13, 10, 4))

    # [10] add w12, w12, #1
    code.append(_add_w_imm(12, 12, 1))

    # [11] cmp w12, #256
    code.append(_cmp_w_imm(12, 256))

    # [12] b.lo copy_loop       ; 256개까지 반복
    code.append(encode_bcond(3, (COPY_IDX - 12) * 4))

    # === 델타 테이블 디코딩 ===
    # x10은 post-increment로 이미 &new_array[256]을 가리킴

    # [13] adrp x11, delta_table_page
    code.append(_adrp(11, hook_base + 13 * 4, delta_table_addr))

    # [14] add x11, x11, #page_offset
    code.append(_add_x_imm(11, 11, delta_table_addr & 0xFFF))

    # [15] ldrh w13, [x11], #2  ; 첫 코드포인트 (0xAC00, uint16 LE)
    code.append(_ldrh_post(13, 11, 2))

    # [16] str w13, [x10], #4   ; int32로 저장
    code.append(_str_w_post(13, 10, 4))

    # [17] movz w12, #1          ; 1개 저장됨
    code.append(_movz_w(12, 1))

    DECODE_IDX = 18  # decode_loop 시작

    # === decode_loop: 한글 2350개 디코딩 ===
    # [18] ldrb w14, [x11], #1   ; 델타 바이트 읽기
    code.append(_ldrb_post(14, 11, 1))

    # [19] add w13, w13, w14     ; 누적 (현재 = 이전 + 델타)
    code.append(_add_w_reg(13, 13, 14))

    # [20] str w13, [x10], #4    ; int32로 저장
    code.append(_str_w_post(13, 10, 4))

    # [21] add w12, w12, #1
    code.append(_add_w_imm(12, 12, 1))

    # [22] cmp w12, #2350
    code.append(_cmp_w_imm(12, HANGUL_COUNT))

    # [23] b.lo decode_loop      ; 2350개까지 반복
    code.append(encode_bcond(3, (DECODE_IDX - 23) * 4))

    # [24] mov x24, x0           ; chars = 확장 배열
    code.append(_mov_x(24, 0))

    # [25] movz w20, #2606       ; count = 2606
    code.append(_movz_w(20, TOTAL_GLYPH_COUNT))

    # === phase2_exit ===
    assert len(code) == EXIT_IDX, f"EXIT_IDX mismatch: {len(code)} != {EXIT_IDX}"

    # [26] movz w8, #0x1c        ; sizeof(stbtt_packedchar) 복원
    code.append(_movz_w(8, 0x1c))

    # [27] b return_addr          ; Load() + 0xC0으로 복귀
    code.append(encode_b_int(hook_base + 27 * 4, return_addr))

    assert len(code) == 28, f"Expected 28 instructions, got {len(code)}"
    return _instr_to_bytes(code)


# ============================================================================
# Phase 3 Trampoline 생성
# ============================================================================

def generate_trampoline(return_offset: int, trampoline_offset: int) -> bytes:
    """
    CP949 디코딩 inline trampoline 생성

    입력 레지스터 (TextOut 루프):
        x24: 문자열 포인터
        w25: 현재 바이트 (ldrb 결과)
        w27: 루프 카운터 (Android; macOS는 w28)

    출력:
        x1: 글리프 인덱스 (GetSymbolCoords 인자)
        w27: 한글이면 +1 (2바이트 처리)
    """
    code = []

    # [0] mrs x12, nzcv - NZCV 플래그 저장
    code.append(0xD53B420C)

    # [1] mov w1, w25 - 기본값 (ASCII 바이트)
    code.append(0x2A1903E1)

    # [2] cmp w25, #0xB0 - CP949 lead byte 하한
    code.append(0x7102C33F)

    exit_idx = 18
    # [3] b.lo exit (ASCII) - cond=3 (cc/lo)
    code.append(encode_bcond(3, (exit_idx - 3) * 4))

    # [4] cmp w25, #0xC8 - CP949 lead byte 상한
    code.append(0x7103233F)

    # [5] b.hi exit - cond=8 (hi)
    code.append(encode_bcond(8, (exit_idx - 5) * 4))

    # [6] ldrb w13, [x24, #1] - trail byte 읽기
    code.append(0x3940070D)

    # [7] cmp w13, #0xA1 - trail 하한
    code.append(0x710285BF)

    # [8] b.lo exit
    code.append(encode_bcond(3, (exit_idx - 8) * 4))

    # [9] cmp w13, #0xFE - trail 상한
    code.append(0x7103F9BF)

    # [10] b.hi exit
    code.append(encode_bcond(8, (exit_idx - 10) * 4))

    # glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    # [11] sub w14, w25, #0xB0
    code.append(0x5102C32E)

    # [12] mov w15, #94
    code.append(0x52800BCF)

    # [13] mul w14, w14, w15
    code.append(0x1B0F7DCE)

    # [14] sub w13, w13, #0xA1
    code.append(0x510285AD)

    # [15] add w14, w14, w13
    code.append(0x0B0D01CE)

    # [16] add x1, x14, #256
    code.append(0x910401C1)

    # [17] add w27, w27, #1  (2바이트: 루프 인덱스 +1)
    code.append(0x1100077B)

    # exit:
    # [18] msr nzcv, x12 - NZCV 복원
    code.append(0xD51B420C)

    # [19] b return - bl GetSymbolCoords로 복귀
    current_offset = trampoline_offset + len(code) * 4
    code.append(encode_b_int(current_offset, return_offset))

    return _instr_to_bytes(code)


# ============================================================================
# 메인 로직
# ============================================================================

def verify_elf(data: bytes):
    """ELF arm64 검증"""
    assert data[:4] == b'\x7fELF', "Not an ELF file"
    assert data[4] == 2, "Not 64-bit ELF"
    assert data[5] == 1, "Not little-endian"
    e_machine = struct.unpack('<H', data[18:20])[0]
    assert e_machine == 183, f"Not AArch64 (e_machine={e_machine})"


def apply_patches():
    """패치 적용"""
    print("=== NWN:EE Android arm64 한글 패치 ===\n")

    if not ORIGINAL.exists():
        print(f"[!] 바이너리 없음: {ORIGINAL}")
        return False

    # 백업
    if not BACKUP.exists():
        shutil.copy(ORIGINAL, BACKUP)
        print(f"[+] 백업 생성: {BACKUP}")

    with open(ORIGINAL, 'rb') as f:
        data = bytearray(f.read())

    verify_elf(data)
    print(f"[+] ELF arm64 확인 ({len(data):,} bytes)\n")

    # =========================================
    # Phase 1: 경계 체크 확장
    # =========================================
    print("=== Phase 1: 경계 체크 확장 (255 → 2613) ===")
    for patch in PATCHES:
        current = bytes(data[patch['offset']:patch['offset'] + 4])
        if current == patch['original']:
            data[patch['offset']:patch['offset'] + 4] = patch['patched']
            print(f"  [+] {patch['name']}: {patch['description']}")
        elif current == patch['patched']:
            print(f"  [=] {patch['name']}: 이미 패치됨")
        else:
            print(f"  [!] {patch['name']}: 예상치 못한 값 {current.hex()}")
            return False

    # =========================================
    # Texture 패치 (크기 + 패딩)
    # =========================================
    print("\n=== Texture 패치 ===")
    for patch in TEXTURE_PATCHES:
        current = bytes(data[patch['offset']:patch['offset'] + 4])
        if current == patch['original']:
            data[patch['offset']:patch['offset'] + 4] = patch['patched']
            print(f"  [+] {patch['name']}: {patch['description']}")
        elif current == patch['patched']:
            print(f"  [=] {patch['name']}: 이미 패치됨")
        else:
            print(f"  [!] {patch['name']}: 예상치 못한 값 {current.hex()}")
            return False

    # =========================================
    # Phase 2: 폰트 베이킹 확장
    # =========================================
    print("\n=== Phase 2: 폰트 베이킹 확장 (256 → 2606 글리프) ===")

    # KSX1001 델타 테이블 생성
    if not KSX1001_PATH.exists():
        print(f"  [!] KSX1001 테이블 없음: {KSX1001_PATH}")
        return False

    codepoints = parse_ksx1001_codepoints()
    delta_table = encode_delta_table(codepoints)
    print(f"  [+] KSX1001 델타 테이블: {len(delta_table)} bytes "
          f"(첫 코드포인트: 0x{codepoints[0]:04X}, "
          f"최대 델타: {max(codepoints[i+1] - codepoints[i] for i in range(len(codepoints)-1))})")

    # 델타 테이블을 .eh_frame → .text 갭에 삽입
    gap_check = bytes(data[DELTA_TABLE_OFFSET:DELTA_TABLE_OFFSET + 16])
    if gap_check == b'\x00' * 16 or gap_check == delta_table[:16]:
        data[DELTA_TABLE_OFFSET:DELTA_TABLE_OFFSET + len(delta_table)] = delta_table
        print(f"  [+] 델타 테이블 삽입 @ 0x{DELTA_TABLE_OFFSET:X} ({len(delta_table)} bytes)")
    else:
        print(f"  [!] 갭 영역이 비어있지 않음 @ 0x{DELTA_TABLE_OFFSET:X}: {gap_check.hex()}")
        return False

    # Phase 2 훅 코드 생성
    phase2_hook = generate_phase2_hook(
        hook_base=PHASE2_HOOK_OFFSET,
        return_addr=PHASE2_RETURN_OFFSET,
        znam_plt=ZNAM_PLT,
        delta_table_addr=DELTA_TABLE_OFFSET,
    )
    print(f"  [+] Phase 2 훅 코드: {len(phase2_hook)} bytes ({len(phase2_hook) // 4} instrs)")

    # 훅 코드를 코드 케이브에 삽입
    cave_check = bytes(data[PHASE2_HOOK_OFFSET:PHASE2_HOOK_OFFSET + 4])
    if cave_check == b'\x00\x00\x00\x00' or cave_check == phase2_hook[:4]:
        data[PHASE2_HOOK_OFFSET:PHASE2_HOOK_OFFSET + len(phase2_hook)] = phase2_hook
        print(f"  [+] 훅 코드 삽입 @ 0x{PHASE2_HOOK_OFFSET:X}")
    else:
        print(f"  [!] 코드 케이브가 비어있지 않음 @ 0x{PHASE2_HOOK_OFFSET:X}")
        return False

    # Load()의 mov x26, x0 → B phase2_hook 패치
    load_patch_bytes = bytes(data[PHASE2_PATCH_OFFSET:PHASE2_PATCH_OFFSET + 4])
    expected_mov = bytes.fromhex('fa0300aa')  # mov x26, x0
    patch_b_bytes = encode_b(PHASE2_PATCH_OFFSET, PHASE2_HOOK_OFFSET)

    if load_patch_bytes == expected_mov:
        data[PHASE2_PATCH_OFFSET:PHASE2_PATCH_OFFSET + 4] = patch_b_bytes
        print(f"  [+] Load() 훅: mov x26, x0 → B phase2_hook")
    elif load_patch_bytes == patch_b_bytes:
        print(f"  [=] Load() 훅: 이미 패치됨")
    else:
        print(f"  [!] Load() @ 0x{PHASE2_PATCH_OFFSET:X}: "
              f"예상치 못한 값 {load_patch_bytes.hex()}")
        return False

    # =========================================
    # Phase 3: Inline Trampoline (CP949 디코딩)
    # =========================================
    print("\n=== Phase 3: CP949 Inline Trampoline ===")

    # 루프 카운터 w27 확인
    loop_inc = bytes(data[0x852f3c:0x852f3c + 4])
    if loop_inc == bytes.fromhex('7b070011'):
        print(f"  [+] 루프 카운터: w27 (확인됨)")
    else:
        print(f"  [?] 0x852f3c: {loop_inc.hex()} (w27 카운터 미확인, 계속 진행)")

    # mov w1, w25 확인
    mov_bytes = bytes(data[TEXTOUT_MOV_OFFSET:TEXTOUT_MOV_OFFSET + 4])
    expected_mov3 = bytes.fromhex('e103192a')  # mov w1, w25
    patch_b3 = encode_b(TEXTOUT_MOV_OFFSET, TRAMPOLINE_OFFSET)

    # Trampoline 생성
    trampoline = generate_trampoline(
        return_offset=TEXTOUT_RETURN_OFFSET,
        trampoline_offset=TRAMPOLINE_OFFSET,
    )

    print(f"  Trampoline @ 0x{TRAMPOLINE_OFFSET:X}: "
          f"{len(trampoline)} bytes ({len(trampoline) // 4} instrs)")

    if mov_bytes == expected_mov3:
        data[TRAMPOLINE_OFFSET:TRAMPOLINE_OFFSET + len(trampoline)] = trampoline
        print(f"  [+] Trampoline 삽입 완료")

        data[TEXTOUT_MOV_OFFSET:TEXTOUT_MOV_OFFSET + 4] = patch_b3
        print(f"  [+] mov → b trampoline 패치 완료")
    elif mov_bytes == patch_b3:
        print(f"  [=] 이미 패치됨 (b trampoline)")
        data[TRAMPOLINE_OFFSET:TRAMPOLINE_OFFSET + len(trampoline)] = trampoline
        print(f"  [+] Trampoline 재삽입")
    else:
        instr = int.from_bytes(mov_bytes, 'little')
        if (instr >> 26) == 0b000101:
            print(f"  [=] 이미 다른 b 명령으로 패치됨, Trampoline 재삽입")
            data[TRAMPOLINE_OFFSET:TRAMPOLINE_OFFSET + len(trampoline)] = trampoline
        else:
            print(f"  [!] 예상치 못한 값: {mov_bytes.hex()}")

    # 저장
    with open(PATCHED, 'wb') as f:
        f.write(data)

    print(f"\n{'=' * 60}")
    print(f"[+] 패치 완료: {PATCHED}")
    print(f"    Phase 1: 경계 확장 (256 → {KOREAN_GLYPH_COUNT})")
    print(f"    Phase 2: 폰트 베이킹 (256 → {TOTAL_GLYPH_COUNT} 글리프)")
    print(f"    Phase 3: CP949 디코더 (inline trampoline)")
    print(f"    Texture: 4096x4096, padding=16")
    print(f"{'=' * 60}")

    return True


def check_status():
    """패치 상태 확인"""
    print("=== 패치 상태 확인 ===\n")

    target = PATCHED if PATCHED.exists() else ORIGINAL
    print(f"검사 대상: {target}\n")

    with open(target, 'rb') as f:
        data = f.read()

    verify_elf(data)

    print("Phase 1 (경계 체크):")
    for patch in PATCHES:
        current = data[patch['offset']:patch['offset'] + 4]
        if current == patch['original']:
            status = "original"
        elif current == patch['patched']:
            status = "patched [OK]"
        else:
            status = f"unknown ({current.hex()})"
        print(f"  {patch['name']}: {status}")

    print("\nTexture 패치:")
    for patch in TEXTURE_PATCHES:
        current = data[patch['offset']:patch['offset'] + 4]
        if current == patch['original']:
            status = "original"
        elif current == patch['patched']:
            status = "patched [OK]"
        else:
            status = f"unknown ({current.hex()})"
        print(f"  {patch['name']}: {status}")

    print("\nPhase 2 (폰트 베이킹):")
    load_bytes = data[PHASE2_PATCH_OFFSET:PHASE2_PATCH_OFFSET + 4]
    expected_mov = bytes.fromhex('fa0300aa')
    patch_b2 = encode_b(PHASE2_PATCH_OFFSET, PHASE2_HOOK_OFFSET)

    if load_bytes == expected_mov:
        status = "original (mov x26, x0)"
    elif load_bytes == patch_b2:
        status = "patched (b phase2_hook) [OK]"
    else:
        instr = int.from_bytes(load_bytes, 'little')
        if (instr >> 26) == 0b000101:
            imm26 = instr & 0x3FFFFFF
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            target_addr = PHASE2_PATCH_OFFSET + imm26 * 4
            status = f"b 0x{target_addr:X}"
        else:
            status = f"unknown ({load_bytes.hex()})"
    print(f"  Load() @ 0x{PHASE2_PATCH_OFFSET:X}: {status}")

    hook_bytes = data[PHASE2_HOOK_OFFSET:PHASE2_HOOK_OFFSET + 4]
    if hook_bytes == b'\x00\x00\x00\x00':
        print(f"  Hook @ 0x{PHASE2_HOOK_OFFSET:X}: empty")
    else:
        print(f"  Hook @ 0x{PHASE2_HOOK_OFFSET:X}: installed")

    delta_bytes = data[DELTA_TABLE_OFFSET:DELTA_TABLE_OFFSET + 4]
    if delta_bytes == b'\x00\x00\x00\x00':
        print(f"  Delta table @ 0x{DELTA_TABLE_OFFSET:X}: empty")
    else:
        first_cp = struct.unpack('<H', delta_bytes[:2])[0]
        print(f"  Delta table @ 0x{DELTA_TABLE_OFFSET:X}: installed "
              f"(first: 0x{first_cp:04X})")

    print("\nPhase 3 (Trampoline):")
    mov_bytes = data[TEXTOUT_MOV_OFFSET:TEXTOUT_MOV_OFFSET + 4]
    expected_mov3 = bytes.fromhex('e103192a')
    patch_b3 = encode_b(TEXTOUT_MOV_OFFSET, TRAMPOLINE_OFFSET)

    if mov_bytes == expected_mov3:
        status = "original (mov w1, w25)"
    elif mov_bytes == patch_b3:
        status = "patched (b trampoline) [OK]"
    else:
        instr = int.from_bytes(mov_bytes, 'little')
        if (instr >> 26) == 0b000101:
            imm26 = instr & 0x3FFFFFF
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            target_addr = TEXTOUT_MOV_OFFSET + imm26 * 4
            status = f"b 0x{target_addr:X}"
        else:
            status = f"unknown ({mov_bytes.hex()})"
    print(f"  TextOut @ 0x{TEXTOUT_MOV_OFFSET:X}: {status}")

    trampoline_bytes = data[TRAMPOLINE_OFFSET:TRAMPOLINE_OFFSET + 4]
    if trampoline_bytes == b'\x00\x00\x00\x00':
        print(f"  Trampoline @ 0x{TRAMPOLINE_OFFSET:X}: empty")
    else:
        print(f"  Trampoline @ 0x{TRAMPOLINE_OFFSET:X}: installed")


def restore():
    """원본 복원"""
    print("=== 원본 복원 ===\n")
    if BACKUP.exists():
        shutil.copy(BACKUP, ORIGINAL)
        if PATCHED.exists():
            PATCHED.unlink()
        print(f"[+] 복원 완료: {ORIGINAL}")
    else:
        print(f"[!] 백업 없음: {BACKUP}")


def main():
    parser = argparse.ArgumentParser(description='NWN:EE Android arm64 한글 패치')
    parser.add_argument('--check', action='store_true', help='상태 확인')
    parser.add_argument('--restore', action='store_true', help='원본 복원')
    args = parser.parse_args()

    if args.check:
        check_status()
    elif args.restore:
        restore()
    else:
        apply_patches()


if __name__ == "__main__":
    main()
