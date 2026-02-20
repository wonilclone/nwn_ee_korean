#!/usr/bin/env python3
"""
NWN:EE Android (arm64) libnwmain.so 한글 패치 스크립트

Phase 1: GetSymbolCoords/SetSymbolCoords 경계 확장 (255 → 2613)
Phase 2: CAuroraTTFTexture::Load 폰트 베이킹 확장 (256 → 2606 글리프)
Phase 3: TextOut 내 CP949 디코더 (inline trampoline)
Phase 4: Nuklear UI nk_draw_text CP949/Latin1→UTF-8 변환
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


def _add_x_reg_sxtw(rd, rn, rm):
    """ADD Xd, Xn, Wm, SXTW (sign-extend word to 64-bit)"""
    return 0x8B20C000 | (rm << 16) | (rn << 5) | rd


def _add_x_reg(rd, rn, rm):
    """ADD Xd, Xn, Xm"""
    return 0x8B000000 | (rm << 16) | (rn << 5) | rd


def _sub_w_imm(rd, rn, imm12):
    """SUB Wd, Wn, #imm12"""
    assert 0 <= imm12 <= 0xFFF
    return 0x51000000 | (imm12 << 10) | (rn << 5) | rd


def _mul_w(rd, rn, rm):
    """MUL Wd, Wn, Wm (MADD Wd, Wn, Wm, WZR)"""
    return 0x1B007C00 | (rm << 16) | (rn << 5) | rd


def _ldrb_unsigned(rt, rn, imm12):
    """LDRB Wt, [Xn, #imm12] (unsigned offset)"""
    assert 0 <= imm12 <= 0xFFF
    return 0x39400000 | (imm12 << 10) | (rn << 5) | rt


def _mov_w(rd, rm):
    """MOV Wd, Wm (ORR Wd, WZR, Wm)"""
    return 0x2A0003E0 | (rm << 16) | rd


def _sub_x_imm(rd, rn, imm12):
    """SUB Xd, Xn, #imm12"""
    assert 0 <= imm12 <= 0xFFF
    return 0xD1000000 | (imm12 << 10) | (rn << 5) | rd


def _sub_x_reg(rd, rn, rm):
    """SUB Xd, Xn, Xm"""
    return 0xCB000000 | (rm << 16) | (rn << 5) | rd


def _add_x_w_uxtw(rd, rn, rm):
    """ADD Xd, Xn, Wm, UXTW (zero-extend W to X)"""
    return 0x8B204000 | (rm << 16) | (rn << 5) | rd


def _add_x_x_lsl(rd, rn, rm, shift):
    """ADD Xd, Xn, Xm, LSL #shift"""
    assert 0 <= shift <= 63
    return 0x8B000000 | (rm << 16) | (shift << 10) | (rn << 5) | rd


def _cmp_x_reg(rn, rm):
    """CMP Xn, Xm (SUBS XZR, Xn, Xm)"""
    return 0xEB00001F | (rm << 16) | (rn << 5)


def _lsr_w(rd, rn, shift):
    """LSR Wd, Wn, #shift (UBFM Wd, Wn, #shift, #31)"""
    assert 0 < shift < 32
    return 0x53007C00 | (shift << 16) | (rn << 5) | rd


def _and_w_0x3F(rd, rn):
    """AND Wd, Wn, #0x3F (bitmask: N=0, immr=0, imms=5)"""
    return 0x12001400 | (rn << 5) | rd


def _and_w_0xC0(rd, rn):
    """AND Wd, Wn, #0xC0 (bitmask: N=0, immr=26, imms=1)"""
    return 0x121A0400 | (rn << 5) | rd


def _tbz_w(rt, bit, offset):
    """TBZ Wt, #bit, label (test bit and branch if zero)"""
    assert offset % 4 == 0
    imm14 = (offset // 4) & 0x3FFF
    return 0x36000000 | (bit << 19) | (imm14 << 5) | rt


def _cbz_w(rt, offset):
    """CBZ Wt, label"""
    assert offset % 4 == 0
    imm19 = (offset // 4) & 0x7FFFF
    return 0x34000000 | (imm19 << 5) | rt


def _cbnz_w(rt, offset):
    """CBNZ Wt, label"""
    assert offset % 4 == 0
    imm19 = (offset // 4) & 0x7FFFF
    return 0x35000000 | (imm19 << 5) | rt


def _strb_post(rt, rn, imm9):
    """STRB Wt, [Xn], #imm9 (post-indexed)"""
    return 0x38000400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _strb_unsigned(rt, rn, imm12):
    """STRB Wt, [Xn, #imm12]"""
    assert 0 <= imm12 <= 0xFFF
    return 0x39000000 | (imm12 << 10) | (rn << 5) | rt


def _ldrh_unsigned(rt, rn, imm):
    """LDRH Wt, [Xn, #imm] (unsigned offset, imm in bytes, scaled by 2)"""
    assert imm % 2 == 0
    imm12 = imm // 2
    assert 0 <= imm12 <= 0xFFF
    return 0x79400000 | (imm12 << 10) | (rn << 5) | rt


def _strh_post(rt, rn, imm9):
    """STRH Wt, [Xn], #imm9 (post-indexed)"""
    return 0x78000400 | ((imm9 & 0x1FF) << 12) | (rn << 5) | rt


def _str_x_unsigned(rt, rn, byte_offset):
    """STR Xt, [Xn, #offset] (unsigned, scaled by 8)"""
    assert byte_offset % 8 == 0
    imm12 = byte_offset // 8
    assert 0 <= imm12 <= 0xFFF
    return 0xF9000000 | (imm12 << 10) | (rn << 5) | rt


def _str_w_unsigned(rt, rn, byte_offset):
    """STR Wt, [Xn, #offset] (unsigned, scaled by 4)"""
    assert byte_offset % 4 == 0
    imm12 = byte_offset // 4
    assert 0 <= imm12 <= 0xFFF
    return 0xB9000000 | (imm12 << 10) | (rn << 5) | rt


def _ldr_x_unsigned(rt, rn, byte_offset):
    """LDR Xt, [Xn, #offset] (unsigned, scaled by 8)"""
    assert byte_offset % 8 == 0
    imm12 = byte_offset // 8
    assert 0 <= imm12 <= 0xFFF
    return 0xF9400000 | (imm12 << 10) | (rn << 5) | rt


def _ldr_w_unsigned(rt, rn, byte_offset):
    """LDR Wt, [Xn, #offset] (unsigned, scaled by 4)"""
    assert byte_offset % 4 == 0
    imm12 = byte_offset // 4
    assert 0 <= imm12 <= 0xFFF
    return 0xB9400000 | (imm12 << 10) | (rn << 5) | rt


# STP/LDP 64-bit integer registers (signed offset)
def _stp_x_offset(rt, rt2, rn, byte_offset):
    """STP Xt, Xt2, [Xn, #offset]"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0xA9000000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


def _ldp_x_offset(rt, rt2, rn, byte_offset):
    """LDP Xt, Xt2, [Xn, #offset]"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0xA9400000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


def _stp_x_pre(rt, rt2, rn, byte_offset):
    """STP Xt, Xt2, [Xn, #offset]! (pre-indexed)"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0xA9800000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


def _ldp_x_post(rt, rt2, rn, byte_offset):
    """LDP Xt, Xt2, [Xn], #offset (post-indexed)"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0xA8C00000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


# STP/LDP 64-bit SIMD (D registers, signed offset)
def _stp_d_offset(rt, rt2, rn, byte_offset):
    """STP Dt, Dt2, [Xn, #offset]"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0x6D000000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


def _ldp_d_offset(rt, rt2, rn, byte_offset):
    """LDP Dt, Dt2, [Xn, #offset]"""
    imm7 = byte_offset // 8
    assert -64 <= imm7 <= 63
    return 0x6D400000 | ((imm7 & 0x7F) << 15) | (rt2 << 10) | (rn << 5) | rt


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
        'patched': bytes.fromhex('05068052'),    # mov w5, #48
        'description': 'glyph padding 3 → 48',
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
# Phase 3b: Width/Caret 함수 CP949 디코딩 트램폴린
# ============================================================================

# CalculateVisibleStringLengthAndWidth: 문자열 폭 계산 (가운데 정렬 등에 필요)
WIDTH_MOV_OFFSET = 0x8532d8          # mov w1, w24 위치
WIDTH_RETURN_OFFSET = 0x8532dc       # 다음 명령어 (cmp w24, #0x20)
WIDTH_TRAMPOLINE_OFFSET = 0x1417ae0  # Phase 2 훅 이후

# UpdateCaret: 커서 위치 계산
CARET_MOV_OFFSET = 0x853468          # mov w1, w23 위치
CARET_RETURN_OFFSET = 0x85346c       # 다음 명령어 (str d9, [sp, #0x8])
CARET_TRAMPOLINE_OFFSET = 0x1417b38  # Width 트램폴린 이후 (84 bytes = 0x54)

# ============================================================================
# Phase 4: Nuklear UI nk_draw_text 훅
# ============================================================================
#
# NK UI 텍스트는 CP949 또는 Latin-1-corrupted UTF-8로 도착.
# nk_draw_text를 후킹하여 UTF-8로 변환.
#
# nk_draw_text 시그니처 (AAPCS64):
#   x0: cmd_buffer, s0-s3(d0-d3): rect, x1: text, w2: len,
#   x3: font, w4: bg_color, w5: fg_color
#
NK_DRAW_TEXT_OFFSET = 0x121F09C        # nk_draw_text 시작
NK_DRAW_TEXT_PROLOGUE = 0xD10243FF     # sub sp, sp, #0x90 (원본 첫 명령)
NK_DRAW_TEXT_RETURN = 0x121F0A0        # nk_draw_text + 4
NK_HOOK_OFFSET = 0x1417b90             # 코드 케이브 (Caret 트램폴린 이후)

# nk_sdl_refresh_config: 한글 글리프 로드를 위한 폰트 아틀라스 재빌드
NK_SDL_REFRESH_CONFIG = 0x1240420

# nk_sdl_refresh_config 내부 글리프 범위 선택 패치
# locale==3(Korean)일 때 사용하는 글리프 범위 테이블:
#   원본 0x6760F8: {0x0020, 0x00FF, 0x0000} (ASCII만)
#   수정 0x676154: {0x0020, 0x00FF, 0x3131, 0x3163, 0xAC00, 0xD79D, 0x0000} (한글 포함)
# 패치: add x26, x26, #0xF8 → add x26, x26, #0x154
NK_GLYPH_RANGE_OFFSET = 0x12406C4
NK_GLYPH_RANGE_ORIGINAL = 0x9103E35A  # add x26, x26, #0xF8  (ASCII-only range)
NK_GLYPH_RANGE_PATCHED = 0x9105535A   # add x26, x26, #0x154 (Korean glyph range)

# Encoding::g_DefaultLocale (.data 섹션)
# nk_sdl_refresh_config에서 locale==3 체크하여 Korean glyph range 선택
G_DEFAULT_LOCALE_VA = 0x16A0C10
G_DEFAULT_LOCALE_FILE = 0x169EC10

# NOTE: .data 고정 버퍼(0x16A63E0)는 런타임에 전역변수와 충돌하여 크래시 유발.
# UTF-8 변환 버퍼는 스택에 할당 (generate_nk_hook 참조).
NK_UTF8_BUF_VA = 0x16A63E0            # 미사용 (스택 버퍼로 대체됨, 호환용)


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
# Phase 3b: Width/Caret 트램폴린 생성
# ============================================================================

def generate_width_trampoline(trampoline_offset, return_offset):
    """
    CalculateVisibleStringLengthAndWidth용 CP949 디코딩 트램폴린

    레지스터 (Width 함수 루프):
        w24: 현재 바이트 (ldrb 결과)
        w28: 루프 카운터 (32-bit)
        x22: 문자열 베이스 포인터

    출력:
        w1: 글리프 인덱스 (GetSymbolCoords 인자)
        w28: 한글이면 +1 (2바이트 처리)
    """
    code = []

    # [0] mrs x12, nzcv - NZCV 플래그 저장
    code.append(0xD53B420C)

    # [1] mov w1, w24 - 기본값 (ASCII) - 원본 명령어
    code.append(0x2A1803E1)

    # [2] cmp w24, #0xB0 - CP949 lead byte 하한
    code.append(_cmp_w_imm(24, 0xB0))

    exit_idx = 19  # exit label 위치
    # [3] b.lo exit
    code.append(encode_bcond(3, (exit_idx - 3) * 4))

    # [4] cmp w24, #0xC8 - CP949 lead byte 상한
    code.append(_cmp_w_imm(24, 0xC8))

    # [5] b.hi exit
    code.append(encode_bcond(8, (exit_idx - 5) * 4))

    # [6] add x13, x22, w28, sxtw - 문자열 포인터 재구성
    code.append(_add_x_reg_sxtw(13, 22, 28))

    # [7] ldrb w13, [x13, #1] - trail byte 읽기
    code.append(_ldrb_unsigned(13, 13, 1))

    # [8] cmp w13, #0xA1 - trail 하한
    code.append(_cmp_w_imm(13, 0xA1))

    # [9] b.lo exit
    code.append(encode_bcond(3, (exit_idx - 9) * 4))

    # [10] cmp w13, #0xFE - trail 상한
    code.append(_cmp_w_imm(13, 0xFE))

    # [11] b.hi exit
    code.append(encode_bcond(8, (exit_idx - 11) * 4))

    # glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    # [12] sub w14, w24, #0xB0
    code.append(_sub_w_imm(14, 24, 0xB0))

    # [13] mov w15, #94
    code.append(_movz_w(15, 94))

    # [14] mul w14, w14, w15
    code.append(_mul_w(14, 14, 15))

    # [15] sub w13, w13, #0xA1
    code.append(_sub_w_imm(13, 13, 0xA1))

    # [16] add w14, w14, w13
    code.append(_add_w_reg(14, 14, 13))

    # [17] add x1, x14, #256
    code.append(_add_x_imm(1, 14, 256))

    # [18] add w28, w28, #1 (trail byte skip)
    code.append(_add_w_imm(28, 28, 1))

    # exit:
    assert len(code) == exit_idx, f"exit_idx mismatch: {len(code)} != {exit_idx}"

    # [19] msr nzcv, x12 - NZCV 복원
    code.append(0xD51B420C)

    # [20] b return
    current_offset = trampoline_offset + len(code) * 4
    code.append(encode_b_int(current_offset, return_offset))

    return _instr_to_bytes(code)


def generate_caret_trampoline(trampoline_offset, return_offset):
    """
    UpdateCaret용 CP949 디코딩 트램폴린

    레지스터 (Caret 함수 루프):
        w23: 현재 바이트 (ldrb 결과)
        x25: 루프 카운터 (64-bit)
        x21: 문자열 베이스 포인터

    출력:
        w1: 글리프 인덱스 (GetSymbolCoords 인자)
        x25: 한글이면 +1 (2바이트 처리)
    """
    code = []

    # [0] mrs x12, nzcv
    code.append(0xD53B420C)

    # [1] mov w1, w23 - 기본값 (ASCII) - 원본 명령어
    code.append(0x2A1703E1)

    # [2] cmp w23, #0xB0
    code.append(_cmp_w_imm(23, 0xB0))

    exit_idx = 19
    # [3] b.lo exit
    code.append(encode_bcond(3, (exit_idx - 3) * 4))

    # [4] cmp w23, #0xC8
    code.append(_cmp_w_imm(23, 0xC8))

    # [5] b.hi exit
    code.append(encode_bcond(8, (exit_idx - 5) * 4))

    # [6] add x13, x21, x25 - 문자열 포인터 재구성
    code.append(_add_x_reg(13, 21, 25))

    # [7] ldrb w13, [x13, #1] - trail byte 읽기
    code.append(_ldrb_unsigned(13, 13, 1))

    # [8] cmp w13, #0xA1
    code.append(_cmp_w_imm(13, 0xA1))

    # [9] b.lo exit
    code.append(encode_bcond(3, (exit_idx - 9) * 4))

    # [10] cmp w13, #0xFE
    code.append(_cmp_w_imm(13, 0xFE))

    # [11] b.hi exit
    code.append(encode_bcond(8, (exit_idx - 11) * 4))

    # glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    # [12] sub w14, w23, #0xB0
    code.append(_sub_w_imm(14, 23, 0xB0))

    # [13] mov w15, #94
    code.append(_movz_w(15, 94))

    # [14] mul w14, w14, w15
    code.append(_mul_w(14, 14, 15))

    # [15] sub w13, w13, #0xA1
    code.append(_sub_w_imm(13, 13, 0xA1))

    # [16] add w14, w14, w13
    code.append(_add_w_reg(14, 14, 13))

    # [17] add x1, x14, #256
    code.append(_add_x_imm(1, 14, 256))

    # [18] add x25, x25, #1 (trail byte skip, x25는 64-bit)
    code.append(_add_x_imm(25, 25, 1))

    # exit:
    # [19] msr nzcv, x12
    code.append(0xD51B420C)

    # [20] b return
    current_offset = trampoline_offset + len(code) * 4
    code.append(encode_b_int(current_offset, return_offset))

    return _instr_to_bytes(code)


# ============================================================================
# Phase 4: Nuklear UI nk_draw_text 훅 코드 생성
# ============================================================================

def generate_nk_hook(hook_base, return_addr, utf8_buf_va, delta_table_va):
    """
    nk_draw_text 훅: CP949/Latin-1-corrupted → UTF-8 변환

    nk_draw_text(x0=cmd_buf, d0-d3=rect, x1=text, w2=len, x3=font, w4=bg, w5=fg)
    - 첫 명령어 (sub sp, sp, #0x90) 를 B hook 으로 교체
    - 훅에서 텍스트를 스캔하고 비ASCII 발견 시 UTF-8로 변환
    - 변환된 텍스트로 x1/w2 교체 후 원본 프롤로그 실행 → nk_draw_text+4
    - 글리프 범위/locale은 바이너리 패치로 설정 (런타임 init 불필요)

    레지스터:
      callee-saved (BL에서 보존): x19, x20
      caller-saved temps: x9-x18
      SP: stack pointer (31)

    스택 프레임 (0x80 bytes):
      [sp+0x00]: x29, x30
      [sp+0x10]: x0, x1
      [sp+0x20]: x2, x3
      [sp+0x30]: x4, x5
      [sp+0x40]: d0, d1
      [sp+0x50]: d2, d3
      [sp+0x60]: x19, x20
      [sp+0x70]: (unused padding)
    """
    code = []
    # 라벨 위치를 나중에 패치할 수 있도록 placeholder 사용
    # 먼저 모든 명령어를 리스트에 추가한 뒤, 라벨 참조를 패치

    # ===== 프롤로그: 스택 버퍼 할당 + 레지스터 저장 =====
    # 스택 레이아웃:
    #   [sp+0x00]: x29, x30  (saved regs frame 0x80 bytes)
    #   [sp+0x10]: x0, x1
    #   [sp+0x20]: x2, x3
    #   [sp+0x30]: x4, x5
    #   [sp+0x40]: d0, d1
    #   [sp+0x50]: d2, d3
    #   [sp+0x60]: x19, x20
    #   [sp+0x80]: UTF-8 변환 버퍼 (0x800 = 2048 bytes)
    # 총 할당: 0x80 + 0x800 = 0x880
    code.append(_sub_x_imm(31, 31, 0x800))            # sub sp, sp, #0x800 (버퍼 공간)
    code.append(_stp_x_pre(29, 30, 31, -0x80))       # stp x29, x30, [sp, #-0x80]!
    code.append(_stp_x_offset(0, 1, 31, 0x10))       # stp x0, x1, [sp, #0x10]
    code.append(_stp_x_offset(2, 3, 31, 0x20))       # stp x2, x3, [sp, #0x20]
    code.append(_stp_x_offset(4, 5, 31, 0x30))       # stp x4, x5, [sp, #0x30]
    code.append(_stp_d_offset(0, 1, 31, 0x40))       # stp d0, d1, [sp, #0x40]
    code.append(_stp_d_offset(2, 3, 31, 0x50))       # stp d2, d3, [sp, #0x50]
    code.append(_stp_x_offset(19, 20, 31, 0x60))     # stp x19, x20, [sp, #0x60]

    # ===== 비ASCII 빠른 스캔 =====
    # 바이너리 패치로 글리프 범위/locale을 설정하므로 런타임 init 호출 불필요
    # nk_sdl_refresh_config는 게임 초기화 시 자동 호출됨
    code.append(_ldr_x_unsigned(9, 31, 0x18))         # ldr x9, [sp, #0x18] (orig x1)
    code.append(_ldr_w_unsigned(10, 31, 0x20))        # ldr w10, [sp, #0x20] (orig w2)
    LBL_NO_CONVERT = 'no_convert'
    code.append((_cbz_w, 10, LBL_NO_CONVERT))         # cbz w10, no_convert
    # 버퍼 오버플로우 방지: 입력이 1300바이트 초과 시 변환 건너뛰기
    # (CP949 2byte→UTF-8 3byte = 1.5x 확장, 1300*1.5=1950 < 4096)
    code.append(_cmp_w_imm(10, 1300))                   # cmp w10, #1300
    code.append((encode_bcond, 8, LBL_NO_CONVERT))      # b.hi no_convert
    code.append(_add_x_w_uxtw(11, 9, 10))            # add x11, x9, w10, uxtw (end ptr)

    LBL_SCAN = len(code)
    code.append(_cmp_x_reg(9, 11))                    # cmp x9, x11
    code.append((encode_bcond, 2, LBL_NO_CONVERT))    # b.hs no_convert
    code.append(_ldrb_post(12, 9, 1))                 # ldrb w12, [x9], #1
    code.append((_tbz_w, 12, 7, LBL_SCAN))            # tbz w12, #7, scan_loop
    # 비ASCII 바이트 발견 (w12 = 해당 바이트)

    # ===== 버퍼/테이블 주소 로드 =====
    # 버퍼: 스택 버퍼 사용 (sp + 0x80)
    code.append(_add_x_imm(19, 31, 0x80))               # add x19, sp, #0x80 (stack buffer)

    idx = len(code)
    code.append(_adrp(20, hook_base + idx * 4, delta_table_va))
    code.append(_add_x_imm(20, 20, delta_table_va & 0xFFF))

    # ===== 변환 초기화 =====
    code.append(_ldr_x_unsigned(9, 31, 0x18))         # ldr x9, [sp, #0x18] (orig x1=text)
    code.append(_ldr_w_unsigned(11, 31, 0x20))        # ldr w11, [sp, #0x20] (orig w2=len)
    code.append(_add_x_w_uxtw(11, 9, 11))            # add x11, x9, w11, uxtw (src end)
    code.append(_mov_x(10, 19))                       # mov x10, x19 (dst ptr = buf)

    # ===== 메인 변환 루프 =====
    LBL_CONVERT = len(code)
    code.append(_cmp_x_reg(9, 11))                    # [22] cmp x9, x11
    LBL_CONVERT_DONE = 'convert_done'
    code.append((encode_bcond, 2, LBL_CONVERT_DONE))  # [23] b.hs convert_done (placeholder)

    code.append(_ldrb_unsigned(12, 9, 0))             # [24] ldrb w12, [x9]

    # --- ASCII 체크 ---
    LBL_ASCII = 'ascii'
    code.append((_tbz_w, 12, 7, LBL_ASCII))           # [25] tbz w12, #7, ascii (placeholder)

    # --- Latin-1 corrupted 체크 (C2/C3 XX) ---
    LBL_LATIN1 = 'latin1'
    code.append(_cmp_w_imm(12, 0xC2))                 # [26] cmp w12, #0xC2
    code.append((encode_bcond, 0, LBL_LATIN1))        # [27] b.eq latin1 (placeholder)
    code.append(_cmp_w_imm(12, 0xC3))                 # [28] cmp w12, #0xC3
    code.append((encode_bcond, 0, LBL_LATIN1))        # [29] b.eq latin1 (placeholder)

    # --- 기존 UTF-8 3바이트 (E0-EF) ---
    LBL_CHECK_CP949 = 'check_cp949'
    code.append(_cmp_w_imm(12, 0xE0))                 # [30] cmp w12, #0xE0
    code.append((encode_bcond, 3, LBL_CHECK_CP949))   # [31] b.lo check_cp949 (placeholder)
    code.append(_cmp_w_imm(12, 0xEF))                 # [32] cmp w12, #0xEF
    code.append((encode_bcond, 8, LBL_CHECK_CP949))   # [33] b.hi check_cp949 (placeholder)

    # 3바이트 UTF-8: 그대로 복사
    code.append(_strb_post(12, 10, 1))                # [34] strb w12, [x10], #1
    code.append(_add_x_imm(9, 9, 1))                  # [35] add x9, x9, #1
    code.append(_cmp_x_reg(9, 11))                    # [36] cmp x9, x11
    code.append((encode_bcond, 2, LBL_CONVERT_DONE))  # [37] b.hs convert_done
    code.append(_ldrb_post(12, 9, 1))                 # [38] ldrb w12, [x9], #1
    code.append(_strb_post(12, 10, 1))                # [39] strb w12, [x10], #1
    code.append(_cmp_x_reg(9, 11))                    # [40] cmp x9, x11
    code.append((encode_bcond, 2, LBL_CONVERT_DONE))  # [41] b.hs convert_done
    code.append(_ldrb_post(12, 9, 1))                 # [42] ldrb w12, [x9], #1
    code.append(_strb_post(12, 10, 1))                # [43] strb w12, [x10], #1
    code.append((encode_b_int, LBL_CONVERT))           # [44] b convert_loop

    # --- raw CP949 체크 (B0-C8 XX) ---
    LBL_CHECK_CP949_IDX = len(code)
    LBL_OTHER = 'other_byte'
    code.append(_cmp_w_imm(12, 0xB0))                 # [45] cmp w12, #0xB0
    code.append((encode_bcond, 3, LBL_OTHER))          # [46] b.lo other_byte
    code.append(_cmp_w_imm(12, 0xC8))                 # [47] cmp w12, #0xC8
    code.append((encode_bcond, 8, LBL_OTHER))          # [48] b.hi other_byte
    # trail byte 확인
    code.append(_add_x_imm(13, 9, 1))                 # [49] add x13, x9, #1
    code.append(_cmp_x_reg(13, 11))                    # [50] cmp x13, x11
    code.append((encode_bcond, 2, LBL_OTHER))          # [51] b.hs other_byte
    code.append(_ldrb_unsigned(14, 13, 0))             # [52] ldrb w14, [x13]
    code.append(_cmp_w_imm(14, 0xA1))                 # [53] cmp w14, #0xA1
    code.append((encode_bcond, 3, LBL_OTHER))          # [54] b.lo other_byte
    code.append(_cmp_w_imm(14, 0xFE))                 # [55] cmp w14, #0xFE
    code.append((encode_bcond, 8, LBL_OTHER))          # [56] b.hi other_byte
    # 유효한 CP949 쌍: w12=lead, w14=trail
    code.append(_add_x_imm(9, 9, 2))                  # [57] add x9, x9, #2
    LBL_CP949_UTF8 = 'cp949_to_utf8'
    code.append((encode_b_int, LBL_CP949_UTF8))        # [58] b cp949_to_utf8

    # --- Latin-1 디코딩 ---
    LBL_LATIN1_IDX = len(code)
    LBL_RE_ENCODE = 're_encode'
    # C2/C3 다음 continuation byte (80-BF)
    code.append(_add_x_imm(13, 9, 1))                 # [59] add x13, x9, #1
    code.append(_cmp_x_reg(13, 11))                    # [60] cmp x13, x11
    code.append((encode_bcond, 2, LBL_OTHER))          # [61] b.hs other_byte
    code.append(_ldrb_unsigned(14, 13, 0))             # [62] ldrb w14, [x13]
    code.append(_and_w_0xC0(15, 14))                   # [63] and w15, w14, #0xC0
    code.append(_cmp_w_imm(15, 0x80))                  # [64] cmp w15, #0x80
    code.append((encode_bcond, 1, LBL_OTHER))          # [65] b.ne other_byte

    # 디코딩: C2 XX → w15=XX(0x80-0xBF), C3 XX → w15=XX+0x40(0xC0-0xFF)
    code.append(_mov_w(15, 14))                        # [66] mov w15, w14
    code.append(_cmp_w_imm(12, 0xC3))                 # [67] cmp w12, #0xC3
    LBL_DECODED = 'decoded'
    code.append((encode_bcond, 1, LBL_DECODED))        # [68] b.ne decoded (C2 case)
    code.append(_add_w_imm(15, 14, 0x40))             # [69] add w15, w14, #0x40 (C3 case)

    # w15 = 디코딩된 바이트 (0x80-0xFF)
    LBL_DECODED_IDX = len(code)
    # CP949 lead인지 확인 (B0-C8)
    code.append(_cmp_w_imm(15, 0xB0))                 # [70] cmp w15, #0xB0
    code.append((encode_bcond, 3, LBL_RE_ENCODE))      # [71] b.lo re_encode
    code.append(_cmp_w_imm(15, 0xC8))                 # [72] cmp w15, #0xC8
    code.append((encode_bcond, 8, LBL_RE_ENCODE))      # [73] b.hi re_encode

    # CP949 lead 발견. 다음 C2/C3 쌍에서 trail 디코딩
    code.append(_add_x_imm(13, 9, 2))                 # [74] add x13, x9, #2
    code.append(_cmp_x_reg(13, 11))                    # [75] cmp x13, x11
    code.append((encode_bcond, 2, LBL_RE_ENCODE))      # [76] b.hs re_encode
    code.append(_add_x_imm(16, 9, 3))                 # [77] add x16, x9, #3
    code.append(_cmp_x_reg(16, 11))                    # [78] cmp x16, x11
    code.append((encode_bcond, 2, LBL_RE_ENCODE))      # [79] b.hs re_encode
    code.append(_ldrb_unsigned(16, 13, 0))             # [80] ldrb w16, [x13] (C2/C3?)
    code.append(_ldrb_unsigned(17, 13, 1))             # [81] ldrb w17, [x13, #1] (cont byte)
    # continuation 확인
    code.append(_and_w_0xC0(18, 17))                   # [82] and w18, w17, #0xC0
    code.append(_cmp_w_imm(18, 0x80))                  # [83] cmp w18, #0x80
    code.append((encode_bcond, 1, LBL_RE_ENCODE))      # [84] b.ne re_encode
    # C2/C3 확인 후 디코딩
    code.append(_cmp_w_imm(16, 0xC2))                 # [85] cmp w16, #0xC2
    LBL_TRAIL_C2 = 'trail_c2'
    code.append((encode_bcond, 0, LBL_TRAIL_C2))       # [86] b.eq trail_c2
    code.append(_cmp_w_imm(16, 0xC3))                 # [87] cmp w16, #0xC3
    code.append((encode_bcond, 1, LBL_RE_ENCODE))      # [88] b.ne re_encode
    # C3: trail = w17 + 0x40
    code.append(_add_w_imm(14, 17, 0x40))             # [89] add w14, w17, #0x40
    LBL_TRAIL_CHECK = 'trail_check'
    code.append((encode_b_int, LBL_TRAIL_CHECK))        # [90] b trail_check

    # trail_c2: trail = w17
    LBL_TRAIL_C2_IDX = len(code)
    code.append(_mov_w(14, 17))                        # [91] mov w14, w17

    # trail_check: trail 범위 확인 (A1-FE)
    LBL_TRAIL_CHECK_IDX = len(code)
    code.append(_cmp_w_imm(14, 0xA1))                 # [92] cmp w14, #0xA1
    code.append((encode_bcond, 3, LBL_RE_ENCODE))      # [93] b.lo re_encode
    code.append(_cmp_w_imm(14, 0xFE))                 # [94] cmp w14, #0xFE
    code.append((encode_bcond, 8, LBL_RE_ENCODE))      # [95] b.hi re_encode

    # Latin-1-corrupted CP949 쌍 확인! w15=lead, w14=trail
    code.append(_mov_w(12, 15))                        # [96] mov w12, w15 (lead)
    code.append(_add_x_imm(9, 9, 4))                  # [97] add x9, x9, #4 (4바이트 consumed)
    code.append((encode_b_int, LBL_CP949_UTF8))        # [98] b cp949_to_utf8

    # --- re_encode: 디코딩 바이트를 UTF-8로 재인코딩 ---
    LBL_RE_ENCODE_IDX = len(code)
    # w15 = 디코딩 바이트 (0x80-0xFF)
    code.append(_cmp_w_imm(15, 0xC0))                 # [99] cmp w15, #0xC0
    LBL_RE_C3 = 're_c3'
    code.append((encode_bcond, 2, LBL_RE_C3))          # [100] b.hs re_c3
    # 0x80-0xBF: UTF-8 = C2 XX
    code.append(_movz_w(16, 0xC2))                     # [101] mov w16, #0xC2
    code.append(_strb_post(16, 10, 1))                 # [102] strb w16, [x10], #1
    code.append(_strb_post(15, 10, 1))                 # [103] strb w15, [x10], #1
    code.append(_add_x_imm(9, 9, 2))                  # [104] add x9, x9, #2
    code.append((encode_b_int, LBL_CONVERT))            # [105] b convert_loop

    # re_c3: 0xC0-0xFF: UTF-8 = C3 (XX-0x40)
    LBL_RE_C3_IDX = len(code)
    code.append(_movz_w(16, 0xC3))                     # [106] mov w16, #0xC3
    code.append(_strb_post(16, 10, 1))                 # [107] strb w16, [x10], #1
    code.append(_sub_w_imm(15, 15, 0x40))              # [108] sub w15, w15, #0x40
    code.append(_strb_post(15, 10, 1))                 # [109] strb w15, [x10], #1
    code.append(_add_x_imm(9, 9, 2))                  # [110] add x9, x9, #2
    code.append((encode_b_int, LBL_CONVERT))            # [111] b convert_loop

    # --- ascii: 그대로 복사 ---
    LBL_ASCII_IDX = len(code)
    code.append(_strb_post(12, 10, 1))                 # [112] strb w12, [x10], #1
    code.append(_add_x_imm(9, 9, 1))                  # [113] add x9, x9, #1
    code.append((encode_b_int, LBL_CONVERT))            # [114] b convert_loop

    # --- other_byte: 알 수 없는 바이트 그대로 복사 ---
    LBL_OTHER_IDX = len(code)
    code.append(_strb_post(12, 10, 1))                 # [115] strb w12, [x10], #1
    code.append(_add_x_imm(9, 9, 1))                  # [116] add x9, x9, #1
    code.append((encode_b_int, LBL_CONVERT))            # [117] b convert_loop

    # --- cp949_to_utf8: CP949 쌍 → UTF-8 변환 ---
    # w12=lead(B0-C8), w14=trail(A1-FE)
    LBL_CP949_UTF8_IDX = len(code)
    # index = (lead-0xB0)*94 + (trail-0xA1)
    code.append(_sub_w_imm(15, 12, 0xB0))             # [118] sub w15, w12, #0xB0
    code.append(_movz_w(16, 94))                       # [119] mov w16, #94
    code.append(_mul_w(15, 15, 16))                    # [120] mul w15, w15, w16
    code.append(_sub_w_imm(16, 14, 0xA1))             # [121] sub w16, w14, #0xA1
    code.append(_add_w_reg(15, 15, 16))                # [122] add w15, w15, w16 (index)

    # 델타 테이블에서 유니코드 코드포인트 조회
    # x20 = delta_table, first 2 bytes = base codepoint, then delta bytes
    code.append(_ldrh_unsigned(16, 20, 0))             # [123] ldrh w16, [x20] (base: 0xAC00)
    LBL_DELTA_DONE = 'delta_done'
    code.append((_cbz_w, 15, LBL_DELTA_DONE))          # [124] cbz w15, delta_done (index=0)
    code.append(_add_x_imm(17, 20, 2))                # [125] add x17, x20, #2 (delta start)
    code.append(_movz_w(18, 0))                        # [126] mov w18, #0

    LBL_WALK = len(code)
    code.append(_ldrb_post(13, 17, 1))                 # [127] ldrb w13, [x17], #1
    code.append(_add_w_reg(16, 16, 13))                # [128] add w16, w16, w13
    code.append(_add_w_imm(18, 18, 1))                # [129] add w18, w18, #1
    code.append(_cmp_w_imm(0, 0))                      # [130] placeholder for cmp
    code.append((encode_bcond, 3, LBL_WALK))            # [131] b.lo walk (placeholder)
    # [130]을 실제 cmp w18, w15로 교체
    code[-2] = 'CMP_W18_W15'  # 마커

    # delta_done: w16 = 유니코드 코드포인트
    LBL_DELTA_DONE_IDX = len(code)
    # UTF-8 인코딩 (3바이트: 1110xxxx 10xxxxxx 10xxxxxx)
    code.append(_lsr_w(13, 16, 12))                    # [132] lsr w13, w16, #12
    code.append(_add_w_imm(13, 13, 0xE0))             # [133] add w13, w13, #0xE0
    code.append(_strb_post(13, 10, 1))                 # [134] strb w13, [x10], #1
    code.append(_lsr_w(13, 16, 6))                     # [135] lsr w13, w16, #6
    code.append(_and_w_0x3F(13, 13))                   # [136] and w13, w13, #0x3F
    code.append(_add_w_imm(13, 13, 0x80))             # [137] add w13, w13, #0x80
    code.append(_strb_post(13, 10, 1))                 # [138] strb w13, [x10], #1
    code.append(_and_w_0x3F(13, 16))                   # [139] and w13, w16, #0x3F
    code.append(_add_w_imm(13, 13, 0x80))             # [140] add w13, w13, #0x80
    code.append(_strb_post(13, 10, 1))                 # [141] strb w13, [x10], #1
    code.append((encode_b_int, LBL_CONVERT))            # [142] b convert_loop

    # ===== convert_done: 변환 완료 =====
    LBL_CONVERT_DONE_IDX = len(code)
    code.append(_strb_unsigned(31, 10, 0))             # [143] strb wzr, [x10] (null terminate)
    code.append(_sub_x_reg(10, 10, 19))                # [144] sub x10, x10, x19 (len = dst - base)
    # 스택의 x1, w2 덮어쓰기
    code.append(_str_x_unsigned(19, 31, 0x18))         # [145] str x19, [sp, #0x18] (x1 = buf)
    code.append(_str_w_unsigned(10, 31, 0x20))         # [146] str w10, [sp, #0x20] (w2 = len)

    # ===== no_convert: 에필로그 =====
    LBL_NO_CONVERT_IDX = len(code)
    code.append(_ldp_x_offset(19, 20, 31, 0x60))      # [147] ldp x19, x20, [sp, #0x60]
    code.append(_ldp_x_offset(0, 1, 31, 0x10))        # [148] ldp x0, x1, [sp, #0x10]
    code.append(_ldp_x_offset(2, 3, 31, 0x20))        # [149] ldp x2, x3, [sp, #0x20]
    code.append(_ldp_x_offset(4, 5, 31, 0x30))        # [150] ldp x4, x5, [sp, #0x30]
    code.append(_ldp_d_offset(0, 1, 31, 0x40))        # [151] ldp d0, d1, [sp, #0x40]
    code.append(_ldp_d_offset(2, 3, 31, 0x50))        # [152] ldp d2, d3, [sp, #0x50]
    code.append(_ldp_x_post(29, 30, 31, 0x80))        # ldp x29, x30, [sp], #0x80
    code.append(_add_x_imm(31, 31, 0x800))             # add sp, sp, #0x800 (버퍼 스택 해제)
    # 원본 프롤로그 실행
    code.append(_sub_x_imm(31, 31, 0x90))              # sub sp, sp, #0x90
    # nk_draw_text+4로 복귀
    code.append(('B_RETURN',))                          # [155] b nk_draw_text+4

    # ===== 라벨 테이블 구축 =====
    labels = {
        LBL_NO_CONVERT: LBL_NO_CONVERT_IDX,
        LBL_CONVERT_DONE: LBL_CONVERT_DONE_IDX,
        LBL_ASCII: LBL_ASCII_IDX,
        LBL_OTHER: LBL_OTHER_IDX,
        LBL_CHECK_CP949: LBL_CHECK_CP949_IDX,
        LBL_LATIN1: LBL_LATIN1_IDX,
        LBL_CP949_UTF8: LBL_CP949_UTF8_IDX,
        LBL_RE_ENCODE: LBL_RE_ENCODE_IDX,
        LBL_RE_C3: LBL_RE_C3_IDX,
        LBL_DECODED: LBL_DECODED_IDX,
        LBL_TRAIL_C2: LBL_TRAIL_C2_IDX,
        LBL_TRAIL_CHECK: LBL_TRAIL_CHECK_IDX,
        LBL_DELTA_DONE: LBL_DELTA_DONE_IDX,
    }

    # ===== placeholder 해결 (분기 명령 패치) =====
    resolved = []
    for i, instr in enumerate(code):
        if isinstance(instr, int):
            resolved.append(instr)
        elif isinstance(instr, tuple):
            if instr[0] == 'B_RETURN':
                resolved.append(encode_b_int(hook_base + i * 4, return_addr))
            elif instr[0] == 'CMP_W18_W15':
                # CMP Wn, Wm: SUBS WZR, W18, W15
                resolved.append(0x6B00001F | (15 << 16) | (18 << 5))
            elif instr[0] is _cbz_w:
                _, rt, label = instr
                target = labels[label]
                offset = (target - i) * 4
                resolved.append(_cbz_w(rt, offset))
            elif instr[0] is _cbnz_w:
                _, rt, label = instr
                target = labels[label]
                offset = (target - i) * 4
                resolved.append(_cbnz_w(rt, offset))
            elif instr[0] is _tbz_w:
                _, rt, bit, label_or_idx = instr
                if isinstance(label_or_idx, str):
                    target = labels[label_or_idx]
                else:
                    target = label_or_idx  # 직접 인덱스
                offset = (target - i) * 4
                resolved.append(_tbz_w(rt, bit, offset))
            elif instr[0] is encode_bcond:
                _, cond, label = instr
                if isinstance(label, str):
                    target = labels[label]
                else:
                    target = label
                offset = (target - i) * 4
                resolved.append(encode_bcond(cond, offset))
            elif instr[0] is encode_b_int:
                _, label = instr
                if isinstance(label, str):
                    target = labels[label]
                else:
                    target = label
                from_off = hook_base + i * 4
                to_off = hook_base + target * 4
                resolved.append(encode_b_int(from_off, to_off))
            else:
                raise ValueError(f"Unknown placeholder at [{i}]: {instr}")
        elif instr == 'CMP_W18_W15':
            resolved.append(0x6B00001F | (15 << 16) | (18 << 5))
        else:
            raise ValueError(f"Unknown instruction at [{i}]: {instr}")

    total = len(resolved)
    total_bytes = total * 4
    print(f"  [+] NK 훅 코드: {total_bytes} bytes ({total} instrs)")
    assert total_bytes <= 1120, f"NK hook too large: {total_bytes} > 1120 bytes"

    return _instr_to_bytes(resolved)


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

    # =========================================
    # Phase 3b: Width/Caret 함수 CP949 트램폴린
    # =========================================
    print("\n=== Phase 3b: Width/Caret CP949 트램폴린 ===")

    # --- Width (CalculateVisibleStringLengthAndWidth) ---
    width_tramp = generate_width_trampoline(
        trampoline_offset=WIDTH_TRAMPOLINE_OFFSET,
        return_offset=WIDTH_RETURN_OFFSET,
    )
    print(f"  Width trampoline @ 0x{WIDTH_TRAMPOLINE_OFFSET:X}: "
          f"{len(width_tramp)} bytes ({len(width_tramp) // 4} instrs)")

    width_mov = bytes(data[WIDTH_MOV_OFFSET:WIDTH_MOV_OFFSET + 4])
    expected_width_mov = bytes.fromhex('e103182a')  # mov w1, w24
    patch_b_width = encode_b(WIDTH_MOV_OFFSET, WIDTH_TRAMPOLINE_OFFSET)

    if width_mov == expected_width_mov:
        data[WIDTH_TRAMPOLINE_OFFSET:WIDTH_TRAMPOLINE_OFFSET + len(width_tramp)] = width_tramp
        data[WIDTH_MOV_OFFSET:WIDTH_MOV_OFFSET + 4] = patch_b_width
        print(f"  [+] Width: mov w1, w24 → b width_trampoline")
    elif width_mov == patch_b_width:
        print(f"  [=] Width: 이미 패치됨")
        data[WIDTH_TRAMPOLINE_OFFSET:WIDTH_TRAMPOLINE_OFFSET + len(width_tramp)] = width_tramp
    else:
        instr = int.from_bytes(width_mov, 'little')
        if (instr >> 26) == 0b000101:
            print(f"  [=] Width: 이미 b 명령으로 패치됨, 트램폴린 재삽입")
            data[WIDTH_TRAMPOLINE_OFFSET:WIDTH_TRAMPOLINE_OFFSET + len(width_tramp)] = width_tramp
        else:
            print(f"  [!] Width: 예상치 못한 값 {width_mov.hex()}")

    # --- Caret (UpdateCaret) ---
    caret_tramp = generate_caret_trampoline(
        trampoline_offset=CARET_TRAMPOLINE_OFFSET,
        return_offset=CARET_RETURN_OFFSET,
    )
    print(f"  Caret trampoline @ 0x{CARET_TRAMPOLINE_OFFSET:X}: "
          f"{len(caret_tramp)} bytes ({len(caret_tramp) // 4} instrs)")

    caret_mov = bytes(data[CARET_MOV_OFFSET:CARET_MOV_OFFSET + 4])
    expected_caret_mov = bytes.fromhex('e103172a')  # mov w1, w23
    patch_b_caret = encode_b(CARET_MOV_OFFSET, CARET_TRAMPOLINE_OFFSET)

    if caret_mov == expected_caret_mov:
        data[CARET_TRAMPOLINE_OFFSET:CARET_TRAMPOLINE_OFFSET + len(caret_tramp)] = caret_tramp
        data[CARET_MOV_OFFSET:CARET_MOV_OFFSET + 4] = patch_b_caret
        print(f"  [+] Caret: mov w1, w23 → b caret_trampoline")
    elif caret_mov == patch_b_caret:
        print(f"  [=] Caret: 이미 패치됨")
        data[CARET_TRAMPOLINE_OFFSET:CARET_TRAMPOLINE_OFFSET + len(caret_tramp)] = caret_tramp
    else:
        instr = int.from_bytes(caret_mov, 'little')
        if (instr >> 26) == 0b000101:
            print(f"  [=] Caret: 이미 b 명령으로 패치됨, 트램폴린 재삽입")
            data[CARET_TRAMPOLINE_OFFSET:CARET_TRAMPOLINE_OFFSET + len(caret_tramp)] = caret_tramp
        else:
            print(f"  [!] Caret: 예상치 못한 값 {caret_mov.hex()}")

    # =========================================
    # Phase 4: Nuklear UI nk_draw_text 훅
    # =========================================
    print("\n=== Phase 4: Nuklear UI nk_draw_text 훅 ===")

    # 4a: 글리프 범위 패치
    glyph_range_val = struct.unpack('<I', data[NK_GLYPH_RANGE_OFFSET:NK_GLYPH_RANGE_OFFSET + 4])[0]
    if glyph_range_val == NK_GLYPH_RANGE_ORIGINAL:
        data[NK_GLYPH_RANGE_OFFSET:NK_GLYPH_RANGE_OFFSET + 4] = struct.pack('<I', NK_GLYPH_RANGE_PATCHED)
        print(f"  [+] 글리프 범위: add x26, #0xF8 → add x26, #0x154 (Korean range)")
    elif glyph_range_val == NK_GLYPH_RANGE_PATCHED:
        print(f"  [=] 글리프 범위: 이미 패치됨")
    else:
        print(f"  [!] 글리프 범위: 예상치 못한 값 0x{glyph_range_val:08X}")

    # 4b: nk_draw_text 훅 (CP949/Latin-1 → UTF-8 변환, 스택 버퍼)
    nk_hook_code = generate_nk_hook(
        NK_HOOK_OFFSET,
        NK_DRAW_TEXT_RETURN,
        NK_UTF8_BUF_VA,     # 더 이상 사용 안함 (스택 버퍼로 교체됨)
        DELTA_TABLE_OFFSET   # .text 섹션은 VA == file offset
    )
    data[NK_HOOK_OFFSET:NK_HOOK_OFFSET + len(nk_hook_code)] = nk_hook_code

    # B nk_draw_text → hook
    nk_orig = struct.unpack('<I', data[NK_DRAW_TEXT_OFFSET:NK_DRAW_TEXT_OFFSET + 4])[0]
    if nk_orig == NK_DRAW_TEXT_PROLOGUE:
        b_instr = encode_b_int(NK_DRAW_TEXT_OFFSET, NK_HOOK_OFFSET)
        data[NK_DRAW_TEXT_OFFSET:NK_DRAW_TEXT_OFFSET + 4] = struct.pack('<I', b_instr)
        print(f"  [+] nk_draw_text: sub sp → B hook")
    else:
        print(f"  [!] nk_draw_text 원본 불일치: 0x{nk_orig:08X}")

    # 저장
    with open(PATCHED, 'wb') as f:
        f.write(data)

    print(f"\n{'=' * 60}")
    print(f"[+] 패치 완료: {PATCHED}")
    print(f"    Phase 1: 경계 확장 (256 → {KOREAN_GLYPH_COUNT})")
    print(f"    Phase 2: 폰트 베이킹 (256 → {TOTAL_GLYPH_COUNT} 글리프)")
    print(f"    Phase 3: CP949 디코더 (TextOut trampoline)")
    print(f"    Phase 3b: CP949 디코더 (Width/Caret trampoline)")
    print(f"    Phase 4: Nuklear UI (글리프 범위 + locale + CP949/Latin1→UTF-8)")
    print(f"    Texture: 4096x4096, padding=48")
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

    # Phase 3b (Width/Caret)
    print("\nPhase 3b (Width/Caret):")
    for name, mov_off, tramp_off, expected_hex in [
        ("Width", WIDTH_MOV_OFFSET, WIDTH_TRAMPOLINE_OFFSET, 'e103182a'),
        ("Caret", CARET_MOV_OFFSET, CARET_TRAMPOLINE_OFFSET, 'e103172a'),
    ]:
        mov_bytes = data[mov_off:mov_off + 4]
        expected_mov = bytes.fromhex(expected_hex)
        patch_b = encode_b(mov_off, tramp_off)
        if mov_bytes == expected_mov:
            status = "original"
        elif mov_bytes == patch_b:
            status = "patched [OK]"
        else:
            instr = int.from_bytes(mov_bytes, 'little')
            if (instr >> 26) == 0b000101:
                imm26 = instr & 0x3FFFFFF
                if imm26 & (1 << 25):
                    imm26 -= (1 << 26)
                target_addr = mov_off + imm26 * 4
                status = f"b 0x{target_addr:X}"
            else:
                status = f"unknown ({mov_bytes.hex()})"
        print(f"  {name} @ 0x{mov_off:X}: {status}")

        tramp_bytes = data[tramp_off:tramp_off + 4]
        if tramp_bytes == b'\x00\x00\x00\x00':
            print(f"  {name} trampoline @ 0x{tramp_off:X}: empty")
        else:
            print(f"  {name} trampoline @ 0x{tramp_off:X}: installed")

    # Phase 4 (NK draw_text)
    print("\nPhase 4 (NK draw_text):")

    # 글리프 범위 패치
    glyph_bytes = data[NK_GLYPH_RANGE_OFFSET:NK_GLYPH_RANGE_OFFSET + 4]
    original_glyph = NK_GLYPH_RANGE_ORIGINAL.to_bytes(4, 'little')
    patched_glyph = NK_GLYPH_RANGE_PATCHED.to_bytes(4, 'little')
    if glyph_bytes == original_glyph:
        print(f"  NK glyph range @ 0x{NK_GLYPH_RANGE_OFFSET:X}: original (ASCII-only)")
    elif glyph_bytes == patched_glyph:
        print(f"  NK glyph range @ 0x{NK_GLYPH_RANGE_OFFSET:X}: patched (Korean) [OK]")
    else:
        print(f"  NK glyph range @ 0x{NK_GLYPH_RANGE_OFFSET:X}: unknown ({glyph_bytes.hex()})")

    # locale 확인
    locale_val = struct.unpack('<I', data[G_DEFAULT_LOCALE_FILE:G_DEFAULT_LOCALE_FILE + 4])[0]
    print(f"  g_DefaultLocale @ file 0x{G_DEFAULT_LOCALE_FILE:X}: {locale_val} "
          f"({'Korean' if locale_val == 3 else 'NOT Korean'})")

    nk_bytes = data[NK_DRAW_TEXT_OFFSET:NK_DRAW_TEXT_OFFSET + 4]
    expected_prologue = NK_DRAW_TEXT_PROLOGUE.to_bytes(4, 'little')
    patch_b_nk = encode_b(NK_DRAW_TEXT_OFFSET, NK_HOOK_OFFSET)

    if nk_bytes == expected_prologue:
        status = "original (sub sp, #0x90)"
    elif nk_bytes == patch_b_nk:
        status = "patched (b nk_hook) [OK]"
    else:
        instr = int.from_bytes(nk_bytes, 'little')
        if (instr >> 26) == 0b000101:
            imm26 = instr & 0x3FFFFFF
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            target_addr = NK_DRAW_TEXT_OFFSET + imm26 * 4
            status = f"b 0x{target_addr:X}"
        else:
            status = f"unknown ({nk_bytes.hex()})"
    print(f"  nk_draw_text @ 0x{NK_DRAW_TEXT_OFFSET:X}: {status}")

    nk_hook_bytes = data[NK_HOOK_OFFSET:NK_HOOK_OFFSET + 4]
    if nk_hook_bytes == b'\x00\x00\x00\x00':
        print(f"  NK hook @ 0x{NK_HOOK_OFFSET:X}: empty")
    else:
        print(f"  NK hook @ 0x{NK_HOOK_OFFSET:X}: installed")

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
