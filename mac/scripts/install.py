#!/usr/bin/env python3
"""
NWN:EE 한글 패치 설치 스크립트

사용법:
    python3 install.py              # 패치 설치
    python3 install.py --uninstall  # 패치 제거
    python3 install.py --check      # 상태 확인
"""

import hashlib
import struct
import shutil
import subprocess
import sys
from pathlib import Path

# ============================================================================
# 경로 설정
# ============================================================================

SCRIPT_DIR = Path(__file__).parent
NWN_DIR = Path.home() / "Library/Application Support/Steam/steamapps/common/Neverwinter Nights/bin/macos/nwmain.app/Contents/MacOS"
NWN_DOCS = Path.home() / "Documents/Neverwinter Nights"
NWMAIN = NWN_DIR / "nwmain"
BACKUP = SCRIPT_DIR / "nwmain.backup"
DYLIB_NAME = "nwn_korean_hook.dylib"
DYLIB_SRC = SCRIPT_DIR / DYLIB_NAME

# 지원 바이너리 해시 (SHA256)
# Steam Build ID: 20277208, Version: 8193.x (r1284)
SUPPORTED_HASHES = {
    "macos_arm64": "edfe1f579f1dc73bc79179c128e4a7b7dc581b0e482e3c8106720f18ec72fb38",
}

# ============================================================================
# 패치 정의
# ============================================================================

PATCHES = [
    {
        'name': 'GetSymbolCoords cmp 255 (1)',
        'offset': 0xab684,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
    },
    {
        'name': 'GetSymbolCoords cmp 256',
        'offset': 0xab6cc,
        'original': bytes.fromhex('3f000471'),
        'patched': bytes.fromhex('3fd82871'),
    },
    {
        'name': 'SetSymbolCoords cmp 255 (1)',
        'offset': 0xab6f4,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
    },
    {
        'name': 'SetSymbolCoords cmp 255 (2)',
        'offset': 0xab73c,
        'original': bytes.fromhex('3ffc0371'),
        'patched': bytes.fromhex('3fd42871'),
    },
    {
        'name': 'Texture height',
        'offset': 0xc5638,
        'original': bytes.fromhex('08190011'),
        'patched': bytes.fromhex('08008252'),
    },
    {
        'name': 'Texture width',
        'offset': 0xc5660,
        'original': bytes.fromhex('2801080b'),
        'patched': bytes.fromhex('08008252'),
    },
    {
        'name': 'Glyph padding',
        'offset': 0xc56c0,
        'original': bytes.fromhex('65008052'),
        'patched': bytes.fromhex('05028052'),
    },
    # Phase 4: Nuklear UI Korean glyph range
    # nk_sdl_refresh_config에서 glyph range 선택 시
    # 원본: add x20, x20, #0x624 (ASCII only: 0x100fad624)
    # 패치: add x20, x20, #0x680 (Korean: 0x100fad680)
    {
        'name': 'NK Korean glyph range',
        'offset': 0xb5b5f0,
        'original': bytes.fromhex('94921891'),
        'patched': bytes.fromhex('94021a91'),
    },
]

# Trampoline 설정 (레거시 UI)
ARM64_TEXTOUT_MOV_OFFSET = 0xa29fc
ARM64_TEXTOUT_RETURN_OFFSET = 0xa2a00
ARM64_TRAMPOLINE_OFFSET = 0x10B7D00

# Phase 4: Nuklear nk_draw_text 후킹
ARM64_NK_DRAW_TEXT_OFFSET = 0xb38ef0
ARM64_NK_TRAMPOLINE_OFFSET = 0x10B7D80  # TextOut 트램폴린 뒤
ARM64_NK_RETURN_OFFSET = 0xb38ef4       # nk_draw_text 첫 명령어 다음
# 함수 포인터를 __DATA 섹션의 빈 공간에 배치 (쓰기 가능)
ARM64_NK_HOOK_PTR_OFFSET = 0x115b218    # __DATA.__data 섹션 끝의 패딩 영역

# Phase 5: CalculateVisibleStringLengthAndWidth CP949 디코딩
# 텍스트 너비 계산 시 CP949 2바이트를 글리프 인덱스로 변환
ARM64_CALCWIDTH_LDRB_OFFSET = 0xa2cc0   # ldrb w24, [x1] 위치
ARM64_CALCWIDTH_RETURN_OFFSET = 0xa2cc4  # ldrb 다음 명령어
ARM64_CALCWIDTH_TRAMPOLINE_OFFSET = 0x10B7E00  # NK 트램폴린 뒤

# ============================================================================
# 유틸리티 함수
# ============================================================================

def calculate_file_hash(filepath: Path) -> str:
    """파일의 SHA256 해시 계산"""
    sha256 = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_binary_version(filepath: Path) -> tuple[bool, str]:
    """바이너리 버전 검증. (성공여부, 메시지) 반환"""
    if not filepath.exists():
        return False, "파일을 찾을 수 없습니다"

    file_hash = calculate_file_hash(filepath)

    if file_hash == SUPPORTED_HASHES.get("macos_arm64"):
        return True, "지원되는 버전입니다 (Steam Build 20277208)"

    return False, f"알 수 없는 바이너리 버전입니다\n      해시: {file_hash[:16]}..."


def find_arm64_offset(data: bytes) -> int:
    """FAT binary에서 arm64 오프셋 찾기"""
    magic = struct.unpack(">I", data[:4])[0]
    if magic != 0xCAFEBABE:
        raise ValueError("FAT binary가 아닙니다")

    nfat = struct.unpack(">I", data[4:8])[0]
    for i in range(nfat):
        off = 8 + i * 20
        cputype, _, file_offset, _, _ = struct.unpack(">IIIII", data[off:off+20])
        if cputype == 0x0100000C:  # arm64
            return file_offset

    raise ValueError("arm64 아키텍처를 찾을 수 없습니다")


def encode_b(from_offset: int, to_offset: int) -> bytes:
    """b (무조건 분기) 명령어 인코딩"""
    diff = to_offset - from_offset
    imm26 = diff // 4
    imm26 &= 0x3FFFFFF
    instr = (0b000101 << 26) | imm26
    return instr.to_bytes(4, 'little')


def encode_bcond(cond: int, offset: int) -> int:
    """조건부 브랜치 인코딩"""
    imm19 = offset // 4
    imm19 &= 0x7FFFF
    return (0b01010100 << 24) | (imm19 << 5) | cond


def generate_trampoline() -> bytes:
    """CP949 디코딩 트램폴린 생성 (레거시 UI용)"""
    code = []
    exit_idx = 18

    code.append(0xD53B420C)  # mrs x12, nzcv
    code.append(0xAA1903E1)  # mov x1, x25
    code.append(0x7102C33F)  # cmp w25, #0xB0
    code.append(encode_bcond(3, (exit_idx - 3) * 4))  # b.lo exit
    code.append(0x7103233F)  # cmp w25, #0xC8
    code.append(encode_bcond(8, (exit_idx - 5) * 4))  # b.hi exit
    code.append(0x3940070D)  # ldrb w13, [x24, #1]
    code.append(0x710285BF)  # cmp w13, #0xA1
    code.append(encode_bcond(3, (exit_idx - 8) * 4))  # b.lo exit
    code.append(0x7103F9BF)  # cmp w13, #0xFE
    code.append(encode_bcond(8, (exit_idx - 10) * 4))  # b.hi exit
    code.append(0x5102C32E)  # sub w14, w25, #0xB0
    code.append(0x52800BCF)  # mov w15, #94
    code.append(0x1B0F7DCE)  # mul w14, w14, w15
    code.append(0x510285AD)  # sub w13, w13, #0xA1
    code.append(0x0B0D01CE)  # add w14, w14, w13
    code.append(0x910401C1)  # add x1, x14, #256
    code.append(0x1100079C)  # add w28, w28, #1
    code.append(0xD51B420C)  # msr nzcv, x12

    b_instr = encode_b(ARM64_TRAMPOLINE_OFFSET + len(code) * 4, ARM64_TEXTOUT_RETURN_OFFSET)
    code.append(int.from_bytes(b_instr, 'little'))

    return b''.join(instr.to_bytes(4, 'little') for instr in code)


def encode_adrp(rd: int, pc: int, target_page: int) -> int:
    """ADRP 명령어 인코딩
    rd: 대상 레지스터 (0-30)
    pc: 현재 PC 주소
    target_page: 대상 페이지 주소 (4KB 정렬)
    """
    pc_page = pc & ~0xFFF
    page_offset = (target_page - pc_page) >> 12

    # 21비트 오프셋을 immhi(19비트)와 immlo(2비트)로 분할
    immlo = page_offset & 0x3
    immhi = (page_offset >> 2) & 0x7FFFF

    return (0x90000000 | (immlo << 29) | (immhi << 5) | rd)


def generate_nk_trampoline() -> bytes:
    """Nuklear nk_draw_text 트램폴린 생성

    nk_draw_text 함수 진입 시:
    - x0: cmd_buffer
    - x1: text pointer
    - x2: text length
    - x3: font
    - x4, x5: colors
    - v0-v3: rect (SIMD)

    트램폴린 동작:
    1. __DATA 섹션의 함수 포인터 주소 계산 (adrp + add)
    2. 함수 포인터 로드
    3. NULL이 아니면 호출 (dylib가 설정)
    4. 원본 프롤로그 실행: stp d11, d10, [sp, #-0x80]!
    5. 원본 함수 본문으로 점프

    주소 계산:
    - 트램폴린 위치: 0x10B7D80
    - 함수 포인터 위치: 0x115b218 (__DATA 섹션)
    - 페이지 차이: 164 페이지
    - 페이지 내 오프셋: 0x218
    """
    code = []

    # PC와 대상 주소
    trampoline_pc = ARM64_NK_TRAMPOLINE_OFFSET
    hook_ptr_addr = ARM64_NK_HOOK_PTR_OFFSET

    # 페이지 계산
    hook_ptr_page = hook_ptr_addr & ~0xFFF
    offset_in_page = hook_ptr_addr & 0xFFF

    # 0: adrp x9, <page_offset> - 함수 포인터가 있는 페이지 주소
    adrp_instr = encode_adrp(9, trampoline_pc, hook_ptr_page)
    code.append(adrp_instr)

    # 1: add x9, x9, #<offset> - 페이지 내 오프셋 추가
    # ADD (immediate): 0x91000000 | (shift << 22) | (imm12 << 10) | (Rn << 5) | Rd
    add_instr = 0x91000000 | (offset_in_page << 10) | (9 << 5) | 9
    code.append(add_instr)

    # 2: ldr x9, [x9] - 함수 포인터 로드
    code.append(0xF9400129)

    # 3: cbz x9, +8 (2개 명령어 뒤 = skip to prologue)
    # wrapper가 NULL이면 프롤로그로 점프
    code.append(0xB4000049)

    # 4: br x9 - wrapper로 점프 (blr 아님! x30 보존)
    # wrapper가 처리 후 직접 원본 함수로 점프하고,
    # 원본 함수가 ret하면 원래 호출자로 돌아감
    code.append(0xD61F0120)

    # 5: (skip) 원본 프롤로그: stp d11, d10, [sp, #-0x80]!
    code.append(0x6DB82BEB)

    # 6: b nk_draw_text+4
    b_instr = encode_b(ARM64_NK_TRAMPOLINE_OFFSET + 6 * 4, ARM64_NK_RETURN_OFFSET)
    code.append(int.from_bytes(b_instr, 'little'))

    return b''.join(instr.to_bytes(4, 'little') for instr in code)


def generate_calcwidth_trampoline() -> bytes:
    """CalculateVisibleStringLengthAndWidth용 CP949 디코딩 트램폴린

    원본 코드 (0xa2cbc~0xa2cc4):
        add x1, x22, w27, sxtw    ; x1 = string + index
        ldrb w24, [x1]            ; w24 = 1바이트 읽기 ← 이것을 교체
        cmp w24, #0x3c            ; '<' 체크 (마크업)

    문제: ldrb는 1바이트만 읽으므로 CP949 한글의 첫 바이트만 가져옴
    해결: CP949 lead byte 감지 시 2바이트 읽고 글리프 인덱스로 변환

    레지스터 상태:
        x1: 현재 문자 포인터 (string + index)
        x22: 문자열 시작 주소
        w27: 현재 인덱스
        w24: 읽은 문자 (출력)

    트램폴린 동작:
        1. ldrb w24, [x1] 실행 (원본)
        2. w24가 CP949 lead byte (0xB0~0xC8)인지 확인
        3. 맞으면 trail byte 읽고 글리프 인덱스 계산, w27 += 1
        4. 원래 코드로 복귀
    """
    code = []
    exit_idx = 17  # 종료 위치 인덱스

    # 0: ldrb w24, [x1] - 원본 명령어
    code.append(0x39400038)

    # 1: cmp w24, #0xB0 - CP949 lead byte 시작
    code.append(0x7102C31F)

    # 2: b.lo exit - lead byte 미만이면 ASCII
    code.append(encode_bcond(3, (exit_idx - 2) * 4))

    # 3: cmp w24, #0xC8 - CP949 lead byte 끝
    code.append(0x7103231F)

    # 4: b.hi exit - lead byte 초과면 ASCII 아님
    code.append(encode_bcond(8, (exit_idx - 4) * 4))

    # 5: ldrb w9, [x1, #1] - trail byte 읽기
    code.append(0x39400429)

    # 6: cmp w9, #0xA1 - trail byte 시작
    code.append(0x7102853F)

    # 7: b.lo exit - 유효하지 않음
    code.append(encode_bcond(3, (exit_idx - 7) * 4))

    # 8: cmp w9, #0xFE - trail byte 끝
    code.append(0x7103F93F)

    # 9: b.hi exit - 유효하지 않음
    code.append(encode_bcond(8, (exit_idx - 9) * 4))

    # === 유효한 CP949 한글 ===
    # glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

    # 10: sub w10, w24, #0xB0
    code.append(0x5102C30A)

    # 11: mov w11, #94
    code.append(0x52800BCB)

    # 12: mul w10, w10, w11
    code.append(0x1B0B7D4A)

    # 13: sub w9, w9, #0xA1
    code.append(0x51028529)

    # 14: add w10, w10, w9
    code.append(0x0B09014A)

    # 15: add w24, w10, #256 - 결과를 w24에 저장 (글리프 인덱스)
    code.append(0x11040158)

    # 16: add w27, w27, #1 - 2바이트 처리했으므로 인덱스 +1
    code.append(0x1100077B)

    # 17 (exit_idx): b return - 원래 코드로 복귀
    b_instr = encode_b(ARM64_CALCWIDTH_TRAMPOLINE_OFFSET + exit_idx * 4,
                       ARM64_CALCWIDTH_RETURN_OFFSET)
    code.append(int.from_bytes(b_instr, 'little'))

    return b''.join(instr.to_bytes(4, 'little') for instr in code)


# ============================================================================
# 설치/제거
# ============================================================================

def install():
    """한글 패치 설치"""
    print("=" * 50)
    print("NWN:EE 한글 패치 설치")
    print("=" * 50)
    print()

    # 검증
    if not NWMAIN.exists():
        print(f"오류: NWN:EE를 찾을 수 없습니다")
        print(f"      경로: {NWMAIN}")
        return False

    if not DYLIB_SRC.exists():
        print(f"오류: dylib 파일이 없습니다: {DYLIB_SRC}")
        return False

    # 바이너리 버전 확인
    print("바이너리 버전 확인 중...")
    version_ok, version_msg = verify_binary_version(NWMAIN)
    if version_ok:
        print(f"  [OK] {version_msg}")
    else:
        print(f"  [!] 경고: {version_msg}")
        print("      패치가 정상 동작하지 않을 수 있습니다.")
        print("      계속하시겠습니까? (y/N): ", end="")
        response = input().strip().lower()
        if response != 'y':
            print("설치가 취소되었습니다.")
            return False
    print()

    # 아키텍처 확인
    result = subprocess.run(["uname", "-m"], capture_output=True, text=True)
    arch = result.stdout.strip()
    if arch != "arm64":
        print(f"오류: 이 패치는 Apple Silicon (arm64) 전용입니다")
        print(f"      현재 아키텍처: {arch}")
        return False

    # 백업 - 기존 백업이 있으면 보호 (덮어쓰기 금지)
    if BACKUP.exists():
        print(f"기존 백업 발견: {BACKUP.name}")
        print("  -> 기존 백업을 보호합니다 (덮어쓰기 안 함)")
        print("  -> 백업에서 원본 복원 후 패치를 적용합니다")
        shutil.copy(BACKUP, NWMAIN)
    else:
        print("백업 생성 중...")
        shutil.copy(NWMAIN, BACKUP)
        print(f"  -> {BACKUP.name}")

    # 바이너리 패치
    print()
    print("바이너리 패치 적용 중...")

    with open(NWMAIN, 'rb') as f:
        data = bytearray(f.read())

    try:
        arm64_offset = find_arm64_offset(data)
    except ValueError as e:
        print(f"오류: {e}")
        return False

    for patch in PATCHES:
        file_offset = arm64_offset + patch['offset']
        current = bytes(data[file_offset:file_offset+4])

        if current == patch['original']:
            data[file_offset:file_offset+4] = patch['patched']
            print(f"  [OK] {patch['name']}")
        elif current == patch['patched']:
            print(f"  [skip] {patch['name']} (이미 적용됨)")
        else:
            print(f"  [!] {patch['name']} - 예상치 못한 값")
            return False

    # Trampoline 삽입
    print()
    print("트램폴린 삽입 중...")

    mov_offset = arm64_offset + ARM64_TEXTOUT_MOV_OFFSET
    expected_mov = bytes.fromhex('e10319aa')
    expected_b = encode_b(ARM64_TEXTOUT_MOV_OFFSET, ARM64_TRAMPOLINE_OFFSET)

    trampoline = generate_trampoline()
    trampoline_offset = arm64_offset + ARM64_TRAMPOLINE_OFFSET

    if bytes(data[mov_offset:mov_offset+4]) == expected_mov:
        data[trampoline_offset:trampoline_offset+len(trampoline)] = trampoline
        data[mov_offset:mov_offset+4] = expected_b
        print("  [OK] 레거시 UI 트램폴린 설치 완료")
    elif bytes(data[mov_offset:mov_offset+4]) == expected_b:
        data[trampoline_offset:trampoline_offset+len(trampoline)] = trampoline
        print("  [skip] 레거시 UI 트램폴린 이미 적용됨")
    else:
        print("  [!] 레거시 UI 트램폴린 - 예상치 못한 상태")

    # Nuklear 트램폴린 삽입
    print()
    print("Nuklear UI 트램폴린 삽입 중...")

    nk_func_offset = arm64_offset + ARM64_NK_DRAW_TEXT_OFFSET
    nk_trampoline_offset = arm64_offset + ARM64_NK_TRAMPOLINE_OFFSET

    # nk_draw_text 원본 첫 명령어: stp d11, d10, [sp, #-0x80]!
    expected_nk_prologue = bytes.fromhex('eb2bb86d')  # little-endian
    expected_nk_b = encode_b(ARM64_NK_DRAW_TEXT_OFFSET, ARM64_NK_TRAMPOLINE_OFFSET)

    nk_trampoline = generate_nk_trampoline()

    current_nk = bytes(data[nk_func_offset:nk_func_offset+4])
    if current_nk == expected_nk_prologue:
        # 트램폴린 배치
        data[nk_trampoline_offset:nk_trampoline_offset+len(nk_trampoline)] = nk_trampoline
        # 첫 명령어를 b trampoline으로 교체
        data[nk_func_offset:nk_func_offset+4] = expected_nk_b
        print("  [OK] Nuklear UI 트램폴린 설치 완료")
    elif current_nk == expected_nk_b:
        # 이미 패치됨 - 트램폴린만 업데이트
        data[nk_trampoline_offset:nk_trampoline_offset+len(nk_trampoline)] = nk_trampoline
        print("  [skip] Nuklear UI 트램폴린 이미 적용됨")
    else:
        print(f"  [!] 예상치 못한 상태: {current_nk.hex()}")

    # Phase 5: CalculateVisibleStringLengthAndWidth CP949 디코딩 트램폴린
    print()
    print("텍스트 너비 계산 패치 적용 중...")

    calcwidth_ldrb_offset = arm64_offset + ARM64_CALCWIDTH_LDRB_OFFSET
    calcwidth_trampoline_offset = arm64_offset + ARM64_CALCWIDTH_TRAMPOLINE_OFFSET

    # 원본 ldrb w24, [x1] 명령어
    expected_calcwidth_ldrb = bytes.fromhex('38004039')  # little-endian
    expected_calcwidth_b = encode_b(ARM64_CALCWIDTH_LDRB_OFFSET, ARM64_CALCWIDTH_TRAMPOLINE_OFFSET)

    calcwidth_trampoline = generate_calcwidth_trampoline()

    current_calcwidth = bytes(data[calcwidth_ldrb_offset:calcwidth_ldrb_offset+4])
    if current_calcwidth == expected_calcwidth_ldrb:
        # 트램폴린 배치
        data[calcwidth_trampoline_offset:calcwidth_trampoline_offset+len(calcwidth_trampoline)] = calcwidth_trampoline
        # ldrb를 b trampoline으로 교체
        data[calcwidth_ldrb_offset:calcwidth_ldrb_offset+4] = expected_calcwidth_b
        print("  [OK] 텍스트 너비 계산 패치 완료")
    elif current_calcwidth == expected_calcwidth_b:
        # 이미 패치됨 - 트램폴린만 업데이트
        data[calcwidth_trampoline_offset:calcwidth_trampoline_offset+len(calcwidth_trampoline)] = calcwidth_trampoline
        print("  [skip] 텍스트 너비 계산 패치 이미 적용됨")
    else:
        print(f"  [!] 예상치 못한 상태: {current_calcwidth.hex()}")

    with open(NWMAIN, 'wb') as f:
        f.write(data)

    # dylib 복사
    print()
    print("dylib 설치 중...")
    dylib_dst = NWN_DIR / DYLIB_NAME
    shutil.copy(DYLIB_SRC, dylib_dst)
    print(f"  -> {dylib_dst.name}")

    # dylib 삽입
    print()
    print("dylib 연결 중...")

    insert_dylib = Path("/tmp/insert_dylib/insert_dylib_bin")
    if not insert_dylib.exists():
        print("  insert_dylib 빌드 중...")
        subprocess.run([
            "bash", "-c",
            "cd /tmp && rm -rf insert_dylib && "
            "git clone https://github.com/Tyilo/insert_dylib.git 2>/dev/null && "
            "cd insert_dylib && "
            "clang -o insert_dylib_bin insert_dylib/main.c -framework Foundation 2>/dev/null"
        ], check=True, capture_output=True)

    result = subprocess.run([
        str(insert_dylib), "--all-yes",
        f"@executable_path/{DYLIB_NAME}",
        str(NWMAIN), str(NWMAIN)
    ], capture_output=True, text=True)

    if "already" in result.stdout.lower() or "already" in result.stderr.lower():
        print("  [skip] 이미 연결됨")
    elif result.returncode == 0:
        print("  [OK] dylib 연결 완료")
    else:
        print(f"  [!] 경고: {result.stderr[:100]}")

    # 재서명
    print()
    print("코드 서명 중...")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(NWMAIN)],
                   capture_output=True, check=True)
    print("  [OK] 서명 완료")

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
        print(f"      {NWN_DOCS}/override/")

    # 완료
    print()
    print("=" * 50)
    print("설치 완료!")
    print("=" * 50)

    return True


def uninstall():
    """한글 패치 제거"""
    print("=" * 50)
    print("NWN:EE 한글 패치 제거")
    print("=" * 50)
    print()

    if BACKUP.exists():
        print("백업에서 복원 중...")
        shutil.copy(BACKUP, NWMAIN)
        print("  [OK] 바이너리 복원")

        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(NWMAIN)],
                       capture_output=True, check=True)
        print("  [OK] 재서명 완료")

        dylib_dst = NWN_DIR / DYLIB_NAME
        if dylib_dst.exists():
            dylib_dst.unlink()
            print("  [OK] dylib 제거")

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

    # 버전 확인
    print("바이너리 버전:")
    version_ok, version_msg = verify_binary_version(NWMAIN)
    print(f"  {version_msg}")
    print()

    with open(NWMAIN, 'rb') as f:
        data = f.read()

    try:
        arm64_offset = find_arm64_offset(data)
    except ValueError as e:
        print(f"오류: {e}")
        return

    print("바이너리 패치:")
    all_patched = True
    for patch in PATCHES:
        file_offset = arm64_offset + patch['offset']
        current = data[file_offset:file_offset+4]

        if current == patch['patched']:
            status = "적용됨"
        elif current == patch['original']:
            status = "미적용"
            all_patched = False
        else:
            status = "알 수 없음"
            all_patched = False

        print(f"  {patch['name']}: {status}")

    print()
    print("dylib:")
    result = subprocess.run(["otool", "-L", str(NWMAIN)], capture_output=True, text=True)
    dylib_linked = DYLIB_NAME in result.stdout
    dylib_exists = (NWN_DIR / DYLIB_NAME).exists()

    print(f"  연결됨: {'예' if dylib_linked else '아니오'}")
    print(f"  파일 존재: {'예' if dylib_exists else '아니오'}")

    print()
    if all_patched and dylib_linked and dylib_exists:
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
            print("사용법: python3 install.py [--uninstall|--check]")
    else:
        install()


if __name__ == "__main__":
    main()
