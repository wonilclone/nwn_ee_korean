#!/usr/bin/env python3
"""
NWN:EE 한글 패치 통합 스크립트

사용법:
    python3 apply_korean_patch.py              # 패치 적용
    python3 apply_korean_patch.py --restore    # 원본 복원
    python3 apply_korean_patch.py --check      # 상태 확인

이 스크립트는 다음을 수행합니다:
1. Phase 1: 바이너리 패치 (GetSymbolCoords/SetSymbolCoords 경계 확장)
2. Phase 2: dylib 삽입 (nwn_korean_hook.dylib) - 글리프 베이킹 확장
3. Phase 3: Inline Trampoline (CP949 디코딩)
4. 재서명
"""

import struct
import shutil
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
NWN_DIR = Path("/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/bin/macos/nwmain.app/Contents/MacOS")
NWMAIN = NWN_DIR / "nwmain"
BACKUP_DIR = SCRIPT_DIR / "backup"
BACKUP = BACKUP_DIR / "nwmain.original"
DYLIB_NAME = "nwn_korean_hook.dylib"
DYLIB_SRC = SCRIPT_DIR / DYLIB_NAME

# ============================================================================
# Phase 1 패치 정의
# ============================================================================

KOREAN_GLYPH_COUNT = 2614

# Phase 3: mov x1, x25 패치 (2바이트 한글 디코딩) - inline trampoline 방식
# b trampoline → (디코딩) → b return (LR/NZCV 유지)
ARM64_TEXTOUT_MOV_OFFSET = 0xa29fc      # mov x1, x25 위치 (실제 패치 대상)
ARM64_TEXTOUT_RETURN_OFFSET = 0xa2a00   # bl GetSymbolCoords 위치 (리턴 지점)
# Trampoline 위치: __TEXT 세그먼트 내 패딩 영역 사용
# __eh_frame 섹션 끝(0x10B7CB8)과 __DATA_CONST 시작(0x10B8000) 사이의 패딩
ARM64_TRAMPOLINE_OFFSET = 0x10B7D00     # __TEXT 세그먼트 내 패딩 영역 (안전한 code cave)

# Phase 4: 텍스처 크기 패치 (CAuroraTTFTexture::Load)
# 텍스처 height 계산: add w8, w8, #6 → add w8, w8, #2042
# 이렇게 하면 height >= 2048이 되어 2606개 글리프를 담을 수 있음
ARM64_TEXTURE_HEIGHT_OFFSET = 0xc5638   # add w8, w8, #6 위치

PATCHES = [
    {
        'name': 'GetSymbolCoords cmp 255 (flags68!=0)',
        'offset': 0xab684,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
    {
        'name': 'GetSymbolCoords cmp 256 (flags68==0)',
        'offset': 0xab6cc,
        'original': bytes.fromhex('3f000471'),
        'patched': bytes.fromhex('3fd82871'),
        'description': 'alt path check 256 → 2614',
    },
    {
        'name': 'SetSymbolCoords cmp 255 (flags68!=0)',
        'offset': 0xab6f4,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
    {
        'name': 'SetSymbolCoords cmp 255 (flags68==0)',
        'offset': 0xab73c,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
        'description': 'boundary check 255 → 2613',
    },
    {
        'name': 'CAuroraTTFTexture::Load height target',
        'offset': 0xc5638,
        'original': bytes.fromhex('08190011'),  # add w8, w8, #6
        'patched': bytes.fromhex('08008252'),   # mov w8, #4096 → height = 4096 고정
        'description': 'texture height → 4096 (정사각형 텍스처)',
    },
    {
        'name': 'CAuroraTTFTexture::Load width target',
        'offset': 0xc5660,
        'original': bytes.fromhex('2801080b'),  # add w8, w9, w8
        'patched': bytes.fromhex('08008252'),   # mov w8, #4096 → width = 4096 고정
        'description': 'texture width → 4096 (정사각형 텍스처)',
    },
    {
        'name': 'CAuroraTTFTexture::Load glyph padding',
        'offset': 0xc56c0,
        'original': bytes.fromhex('65008052'),  # mov w5, #3
        'patched': bytes.fromhex('05028052'),   # mov w5, #16 → padding 3 → 16
        'description': 'glyph padding 3 → 16 (글리프 간 여백 증가)',
    },
    # Nuklear UI 패치 제거 - EE UI는 별도 시스템 (Nuklear GUI)을 사용하며,
    # 해당 UI 문자열은 영문 TLK를 사용하는 것으로 대체함.
    # 상세 내용은 docs/NUKLEAR_UI.md 참조
    # ascent margin 패치 비활성화 - 크래시 원인 조사 필요
    # {
    #     'name': 'CAuroraTTFTexture::Load ascent margin',
    #     'offset': 0xc57f0,
    #     'original': bytes.fromhex('0c102c1e'),  # fmov s12, #0.5
    #     'patched': bytes.fromhex('0c10201e'),   # fmov s12, #2.0 → ascent 여유분 증가
    #     'description': 'ascent margin 0.5 → 2.0 (글리프 상단 잘림 방지)',
    # },
    # 오버샘플링 패치 비활성화 - 글리프 크기가 2배로 커지는 문제 발생
    # {
    #     'name': 'CAuroraTTFTexture::Load oversampling',
    #     'offset': 0xc56cc,
    #     'original': bytes.fromhex('2004000f'),  # movi.2s v0, #1 (h_oversample=1, v_oversample=1)
    #     'patched': bytes.fromhex('4004000f'),   # movi.2s v0, #2 (h_oversample=2, v_oversample=2)
    #     'description': 'oversampling 1x1 → 2x2 (글리프 품질 향상)',
    # },
]

# ============================================================================
# ARM64 명령어 인코딩
# ============================================================================

def encode_b(from_offset: int, to_offset: int) -> bytes:
    """b (무조건 분기) 명령어 인코딩"""
    diff = to_offset - from_offset
    if diff % 4 != 0:
        raise ValueError(f"b offset not aligned: {diff}")
    imm26 = diff // 4
    if imm26 < -(1 << 25) or imm26 >= (1 << 25):
        raise ValueError(f"b offset out of range: {diff}")
    imm26 &= 0x3FFFFFF
    instr = (0b000101 << 26) | imm26
    return instr.to_bytes(4, 'little')


def encode_bcond(cond: int, offset: int) -> int:
    """조건부 브랜치 인코딩 (b.cond)

    cond: 0=eq, 1=ne, 2=cs/hs, 3=cc/lo, 8=hi, 9=ls, ...
    offset: 바이트 오프셋 (4의 배수, ±1MB 범위)
    """
    if offset % 4 != 0:
        raise ValueError(f"b.cond offset not aligned: {offset}")
    imm19 = offset // 4
    if imm19 < -(1 << 18) or imm19 >= (1 << 18):
        raise ValueError(f"b.cond offset out of range: {offset}")
    imm19 &= 0x7FFFF
    # b.cond: 0101 0100 | imm19 | 0 | cond
    instr = (0b01010100 << 24) | (imm19 << 5) | cond
    return instr


def generate_inline_trampoline(return_offset: int, trampoline_offset: int, passthrough_only: bool = False) -> bytes:
    """
    Inline trampoline 생성 (NZCV 플래그 보존)

    핵심: bl/call을 사용하지 않고 b(branch)만 사용
    - LR 유지 (bl 사용 안 함)
    - NZCV 플래그 저장/복원

    Args:
        passthrough_only: True면 pass-through만 수행 (디버깅용)
    """
    code = []

    if passthrough_only:
        # === Pass-through 모드: 원본 동작만 수행 ===
        # [0] mov x1, x25 - 원본 명령어
        code.append(0xAA1903E1)
        # [1] b return
        current_offset = trampoline_offset + len(code) * 4
        b_instr = encode_b(current_offset, return_offset)
        code.append(int.from_bytes(b_instr, 'little'))
        return b''.join(instr.to_bytes(4, 'little') for instr in code)

    # === 전체 트램폴린 (한글 디코딩 포함) ===
    #
    # 입력 레지스터 (TextOut에서 사용 중 - 건드리면 안 됨):
    #   x24: 문자열 포인터
    #   w25: 현재 바이트 (ldrb 결과)
    #   w28: 루프 인덱스
    #   x19, x20, x21, x22: TextOut 내부 상태
    #
    # 출력:
    #   x1: 글리프 인덱스 (GetSymbolCoords 인자)
    #   w28: 한글이면 +1
    #
    # 사용 레지스터 (안전한 caller-saved):
    #   x12: NZCV 저장 전용
    #   x13: trail byte
    #   x14: 계산용
    #   x15: 계산용 (94 상수)

    # [0] mrs x12, nzcv - NZCV 저장
    code.append(0xD53B420C)

    # [1] mov x1, x25 - 기본값 (ASCII)
    code.append(0xAA1903E1)

    # [2] cmp w25, #0xB0
    code.append(0x7102C33F)

    # [3] b.lo exit (cond=3=cc/lo) - exit는 [18]
    exit_idx = 18
    offset_3_to_exit = (exit_idx - 3) * 4  # 60 bytes
    code.append(encode_bcond(3, offset_3_to_exit))

    # [4] cmp w25, #0xC8
    code.append(0x7103233F)

    # [5] b.hi exit (cond=8=hi)
    offset_5_to_exit = (exit_idx - 5) * 4  # 52 bytes
    code.append(encode_bcond(8, offset_5_to_exit))

    # [6] ldrb w13, [x24, #1] - trail byte 읽기
    code.append(0x3940070D)

    # [7] cmp w13, #0xA1
    code.append(0x710285BF)

    # [8] b.lo exit
    offset_8_to_exit = (exit_idx - 8) * 4  # 40 bytes
    code.append(encode_bcond(3, offset_8_to_exit))

    # [9] cmp w13, #0xFE
    code.append(0x7103F9BF)

    # [10] b.hi exit
    offset_10_to_exit = (exit_idx - 10) * 4  # 32 bytes
    code.append(encode_bcond(8, offset_10_to_exit))

    # === 유효한 CP949 한글: 글리프 인덱스 계산 ===
    # glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

    # [11] sub w14, w25, #0xB0  ; w14 = lead - 0xB0
    code.append(0x5102C32E)

    # [12] mov w15, #94
    code.append(0x52800BCF)

    # [13] mul w14, w14, w15  ; w14 = (lead - 0xB0) * 94
    code.append(0x1B0F7DCE)

    # [14] sub w13, w13, #0xA1  ; w13 = trail - 0xA1
    code.append(0x510285AD)

    # [15] add w14, w14, w13  ; w14 = (lead-0xB0)*94 + (trail-0xA1)
    code.append(0x0B0D01CE)

    # [16] add x1, x14, #256  ; x1 = 256 + w14
    code.append(0x910401C1)

    # [17] add w28, w28, #1  ; w28 += 1 (2바이트 처리 표시)
    code.append(0x1100079C)

    # exit:
    # [18] msr nzcv, x12 - NZCV 복원
    code.append(0xD51B420C)

    # [19] b return - 원래 코드로 복귀
    current_offset = trampoline_offset + len(code) * 4
    b_instr = encode_b(current_offset, return_offset)
    code.append(int.from_bytes(b_instr, 'little'))

    return b''.join(instr.to_bytes(4, 'little') for instr in code)

# ============================================================================
# FAT Binary 처리
# ============================================================================

def find_arch_offsets(data: bytes) -> dict:
    """FAT binary에서 각 아키텍처 오프셋 찾기"""
    magic = struct.unpack(">I", data[:4])[0]
    if magic != 0xCAFEBABE:
        raise ValueError("FAT binary가 아닙니다")

    nfat = struct.unpack(">I", data[4:8])[0]
    result = {}

    for i in range(nfat):
        off = 8 + i * 20
        cputype, _, file_offset, size, _ = struct.unpack(">IIIII", data[off:off+20])
        if cputype == 0x0100000C:
            result['arm64'] = {'offset': file_offset, 'size': size}
        elif cputype == 0x01000007:
            result['x86_64'] = {'offset': file_offset, 'size': size}

    return result

# ============================================================================
# 패치 적용
# ============================================================================

def apply_patches(skip_trampoline=False, passthrough=False):
    """한글 패치 적용

    Args:
        skip_trampoline: True면 Phase 3 (Trampoline 패치) 건너뜀
        passthrough: True면 트램폴린이 pass-through만 수행 (디버깅용)
    """
    print("=== NWN:EE 한글 패치 ===\n")

    if not NWMAIN.exists():
        print(f"❌ 바이너리 없음: {NWMAIN}")
        return False

    if not DYLIB_SRC.exists():
        print(f"❌ dylib 없음: {DYLIB_SRC}")
        print("   빌드 명령: clang -arch arm64 -dynamiclib -o nwn_korean_hook.dylib nwn_korean_hook.c -lpthread")
        return False

    # 백업
    BACKUP_DIR.mkdir(exist_ok=True)
    if not BACKUP.exists():
        shutil.copy(NWMAIN, BACKUP)
        print(f"✅ 백업 생성: {BACKUP}")
    else:
        print(f"ℹ️  백업 이미 존재: {BACKUP}")
        # 백업에서 복원 (깨끗한 상태에서 시작)
        print("   깨끗한 상태에서 시작합니다...")
        shutil.copy(BACKUP, NWMAIN)

    # 바이너리 로드
    with open(NWMAIN, 'rb') as f:
        data = bytearray(f.read())

    try:
        arch_info = find_arch_offsets(data)
    except ValueError as e:
        print(f"❌ {e}")
        return False

    arm64_offset = arch_info['arm64']['offset']
    print(f"📍 arm64 오프셋: 0x{arm64_offset:X}\n")

    # =========================================
    # Phase 1 & 4: 바이너리 패치 (경계 체크 확장 + 텍스처 크기)
    # =========================================
    print("=== Phase 1 & 4: 바이너리 패치 ===")
    for patch in PATCHES:
        file_offset = arm64_offset + patch['offset']
        current = bytes(data[file_offset:file_offset+4])

        print(f"📍 {patch['name']}:")
        print(f"   {patch['description']}")

        if current == patch['patched']:
            print(f"   → 이미 패치됨 ✅")
        elif current == patch['original']:
            data[file_offset:file_offset+4] = patch['patched']
            print(f"   → 패치 적용 ✅")
        else:
            print(f"   → ⚠️ 예상치 못한 값: {current.hex()}")
            return False

    # =========================================
    # Phase 3: mov x1, x25 → b trampoline (inline 디코딩)
    # =========================================
    if skip_trampoline:
        print("\n=== Phase 3: Trampoline 패치 [건너뜀] ===")
    else:
        mode_str = "pass-through" if passthrough else "inline 디코딩"
        print(f"\n=== Phase 3: Inline Trampoline ({mode_str}) ===")
        print("   b 방식: LR/NZCV 유지")
        if passthrough:
            print("   ⚠️ Pass-through 모드: 원본 동작만 수행 (디버깅)")

        mov_file_offset = arm64_offset + ARM64_TEXTOUT_MOV_OFFSET
        mov_bytes = bytes(data[mov_file_offset:mov_file_offset+4])

        # 원본 mov x1, x25 = orr x1, xzr, x25 = 0xAA1903E1 (little-endian)
        expected_mov = bytes.fromhex('e10319aa')

        # 패치: b trampoline
        expected_patch_b = encode_b(ARM64_TEXTOUT_MOV_OFFSET, ARM64_TRAMPOLINE_OFFSET)

        print(f"📍 mov 위치 0x{ARM64_TEXTOUT_MOV_OFFSET:X}:")
        print(f"   현재: {mov_bytes.hex()}")
        print(f"   원본: {expected_mov.hex()} (mov x1, x25)")
        print(f"   패치: {expected_patch_b.hex()} (b trampoline @ 0x{ARM64_TRAMPOLINE_OFFSET:X})")

        # Trampoline 생성 및 삽입
        trampoline_code = generate_inline_trampoline(
            return_offset=ARM64_TEXTOUT_RETURN_OFFSET,
            trampoline_offset=ARM64_TRAMPOLINE_OFFSET,
            passthrough_only=passthrough
        )
        trampoline_file_offset = arm64_offset + ARM64_TRAMPOLINE_OFFSET

        print(f"\n📍 Trampoline 위치 0x{ARM64_TRAMPOLINE_OFFSET:X}:")
        print(f"   크기: {len(trampoline_code)} bytes ({len(trampoline_code)//4} 명령어)")
        print(f"   리턴: 0x{ARM64_TEXTOUT_RETURN_OFFSET:X} (bl GetSymbolCoords)")

        if mov_bytes == expected_mov:
            # 1. Trampoline 코드 삽입
            data[trampoline_file_offset:trampoline_file_offset+len(trampoline_code)] = trampoline_code
            print(f"   → Trampoline 삽입 완료 ✅")

            # 2. mov x1, x25 → b trampoline 패치
            data[mov_file_offset:mov_file_offset+4] = expected_patch_b
            print(f"   → mov 패치 적용 ✅")

        elif mov_bytes == expected_patch_b:
            print(f"   → 이미 패치됨 (b trampoline) ✅")
            # Trampoline 재삽입 (최신 버전으로)
            data[trampoline_file_offset:trampoline_file_offset+len(trampoline_code)] = trampoline_code
            print(f"   → Trampoline 재삽입 ✅")
        else:
            # b 명령어인지 확인
            instr = int.from_bytes(mov_bytes, 'little')
            if (instr >> 26) == 0b000101:  # b instruction
                imm26 = instr & 0x3FFFFFF
                if imm26 & (1 << 25):
                    imm26 -= (1 << 26)
                rel = imm26 * 4
                target = ARM64_TEXTOUT_MOV_OFFSET + rel
                print(f"   → 이미 다른 대상으로 패치됨: b 0x{target:X}")
                # Trampoline 재삽입 (최신 버전으로)
                data[trampoline_file_offset:trampoline_file_offset+len(trampoline_code)] = trampoline_code
                print(f"   → Trampoline 재삽입 ✅")
            else:
                print(f"   → ⚠️ 예상치 못한 값: {mov_bytes.hex()}, 패치 건너뜀")

    # 저장
    with open(NWMAIN, 'wb') as f:
        f.write(data)
    print("\n✅ 바이너리 패치 저장 완료")

    # =========================================
    # Phase 2: dylib 삽입
    # =========================================
    print("\n=== Phase 2: dylib 삽입 ===")

    # dylib 복사
    dylib_dst = NWN_DIR / DYLIB_NAME
    shutil.copy(DYLIB_SRC, dylib_dst)
    print(f"✅ dylib 복사: {dylib_dst}")

    # insert_dylib 실행
    insert_dylib = Path("/tmp/insert_dylib/insert_dylib_bin")
    if not insert_dylib.exists():
        print("⚠️  insert_dylib 빌드 중...")
        subprocess.run([
            "bash", "-c",
            "cd /tmp && rm -rf insert_dylib && "
            "git clone https://github.com/Tyilo/insert_dylib.git 2>/dev/null && "
            "cd insert_dylib && "
            "clang -o insert_dylib_bin insert_dylib/main.c -framework Foundation 2>/dev/null"
        ], check=True)

    result = subprocess.run([
        str(insert_dylib),
        "--all-yes",
        f"@executable_path/{DYLIB_NAME}",
        str(NWMAIN),
        str(NWMAIN)
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print(f"✅ dylib 삽입 완료")
    else:
        # 이미 삽입된 경우도 있음
        if "already" in result.stderr.lower() or "already" in result.stdout.lower():
            print(f"ℹ️  dylib 이미 삽입됨")
        else:
            print(f"⚠️  insert_dylib 경고: {result.stderr}")

    # 재서명
    print("\n=== 재서명 ===")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(NWMAIN)], check=True)
    print("✅ 재서명 완료")

    # 완료
    print(f"\n{'='*60}")
    print("📋 한글 패치 완료!")
    print(f"   글리프 개수: 256 → {KOREAN_GLYPH_COUNT}")
    print(f"   지원 범위: ASCII + 한글 (가~힣)")
    print(f"   로그: /tmp/nwn_korean.log")
    print(f"{'='*60}")

    return True

# ============================================================================
# 복원
# ============================================================================

def restore_binary():
    """원본 바이너리 복원"""
    print("=== 원본 복원 ===\n")

    if BACKUP.exists():
        shutil.copy(BACKUP, NWMAIN)
        print(f"✅ 복원 완료: {NWMAIN}")

        # 재서명
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(NWMAIN)], check=True)
        print("✅ 재서명 완료")

        # dylib 제거
        dylib_dst = NWN_DIR / DYLIB_NAME
        if dylib_dst.exists():
            dylib_dst.unlink()
            print(f"✅ dylib 제거: {dylib_dst}")

        return True
    else:
        print(f"❌ 백업 파일 없음: {BACKUP}")
        return False

# ============================================================================
# 상태 확인
# ============================================================================

def check_status():
    """패치 상태 확인"""
    print("=== 패치 상태 확인 ===\n")

    if not NWMAIN.exists():
        print(f"❌ 바이너리 없음")
        return

    with open(NWMAIN, 'rb') as f:
        data = f.read()

    try:
        arch_info = find_arch_offsets(data)
    except ValueError as e:
        print(f"❌ {e}")
        return

    arm64_offset = arch_info['arm64']['offset']

    print("Phase 1 & 4 (바이너리 패치):")
    for patch in PATCHES:
        file_offset = arm64_offset + patch['offset']
        current = data[file_offset:file_offset+4]

        if current == patch['original']:
            status = "original ❌"
        elif current == patch['patched']:
            status = "patched ✅"
        else:
            status = f"unknown ({current.hex()}) ⚠️"

        print(f"  {patch['name']}: {status}")

    # Phase 3 확인
    print("\nPhase 3 (Trampoline 패치):")
    mov_file_offset = arm64_offset + ARM64_TEXTOUT_MOV_OFFSET
    mov_bytes = data[mov_file_offset:mov_file_offset+4]
    expected_mov = bytes.fromhex('e10319aa')
    expected_patch_b = encode_b(ARM64_TEXTOUT_MOV_OFFSET, ARM64_TRAMPOLINE_OFFSET)

    if mov_bytes == expected_mov:
        status = "original (mov x1, x25) ❌"
    elif mov_bytes == expected_patch_b:
        status = "patched (b trampoline) ✅"
    else:
        instr = int.from_bytes(mov_bytes, 'little')
        if (instr >> 26) == 0b000101:
            imm26 = instr & 0x3FFFFFF
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            rel = imm26 * 4
            target = ARM64_TEXTOUT_MOV_OFFSET + rel
            status = f"other (b 0x{target:X}) ⚠️"
        else:
            status = f"unknown ({mov_bytes.hex()}) ⚠️"

    print(f"  mov x1, x25 @ 0x{ARM64_TEXTOUT_MOV_OFFSET:X}: {status}")

    # dylib 확인
    print("\nPhase 2 (dylib 삽입):")
    result = subprocess.run(["otool", "-L", str(NWMAIN)], capture_output=True, text=True)
    if DYLIB_NAME in result.stdout:
        print(f"  {DYLIB_NAME}: inserted ✅")
    else:
        print(f"  {DYLIB_NAME}: not inserted ❌")

    # dylib 파일 확인
    dylib_dst = NWN_DIR / DYLIB_NAME
    if dylib_dst.exists():
        print(f"  dylib file: exists ✅")
    else:
        print(f"  dylib file: missing ❌")

# ============================================================================
# 메인
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='NWN:EE 한글 패치')
    parser.add_argument('--restore', action='store_true', help='원본 복원')
    parser.add_argument('--check', action='store_true', help='상태 확인')
    parser.add_argument('--skip-trampoline', action='store_true', help='Phase 3 (Trampoline 패치) 건너뜀')
    parser.add_argument('--passthrough', action='store_true', help='트램폴린 pass-through 모드 (디버깅용)')
    args = parser.parse_args()

    if args.restore:
        restore_binary()
    elif args.check:
        check_status()
    else:
        apply_patches(skip_trampoline=args.skip_trampoline, passthrough=args.passthrough)

if __name__ == "__main__":
    main()
