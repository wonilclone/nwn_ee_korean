# Linux (x86-64) 한글 패치 바이너리 분석

## 바이너리 정보

| 항목 | 값 |
|------|------|
| 파일 | `bin/linux-x86/nwmain-linux` |
| 형식 | ELF 64-bit LSB PIE executable, x86-64 |
| 크기 | 26,557,296 bytes |
| 빌드 | 2025-10-06 (commit `26c6e57`) |
| 링킹 | 동적 (`ld-linux-x86-64.so.2`) |
| 심볼 | **not stripped** — 전체 심볼 테이블 보존 |
| BuildID | `3e2500a82e0c32008d24c3e74bbff3021da5e1b7` |

### 의존 라이브러리

```
libGL.so.1, librt.so.1, libopenal.so.1, libpthread.so.0,
libdl.so.2, libstdc++.so.6, libm.so.6, libgcc_s.so.1, libc.so.6
```

### ELF 섹션 구조

| 섹션 | 주소 | 크기 | 용도 |
|------|------|------|------|
| `.text` | `0x003fd000` | `0x00ef0d5c` (~15.6MB) | 코드 |
| `.rodata` | `0x012edd80` | `0x0012519c` (~1.2MB) | 읽기전용 데이터 |
| `.data` | `0x018aa000` | `0x0000f2d0` | 초기화된 데이터 |
| `.bss` | `0x018b92e0` | `0x00300ed0` (~3MB) | 미초기화 데이터 |
| `.got` | `0x018a87e0` | `0x00001808` | Global Offset Table |
| `.symtab` | — | `0x000ed7c8` | 심볼 테이블 (969KB) |

---

## 핵심 심볼 맵

### 폰트 렌더링 함수

| 심볼 | 주소 | 크기 | 타입 | 동적 |
|------|------|------|------|------|
| `CAurFontInfo::GetSymbolCoords` | `0x4856d0` | `0x6e` | 함수 | O |
| `CAurFontInfo::SetSymbolCoords` | `0x485740` | `0x68` | 함수 | O |
| `CAurFont::TextOut` | `0x496220` | `0x4da` | 함수 | O |
| `CAurFont::TextOutDoubleByte` | `0x496210` | `0x08` | **STUB** | O |
| `CAurFont::CalculateVisibleStringLengthAndWidth` | `0x496700` | `0x3c6` | 함수 | O |
| `CAurFont::UpdateCaret` | `0x496ad0` | `0x1b4` | 함수 | O |
| `CAurFont::ProcessTextMarkup` | `0x496070` | `0x195` | 함수 | O |
| `CAurTextureBasic::LoadFromTTF` | `0x4875b0` | `0x3c9` | 함수 | — |

### 폰트 베이킹

| 심볼 | 주소 | 크기 | 타입 |
|------|------|------|------|
| `AurGetTTFTexture` | `0x19abdd0` | 8 | BSS (함수 포인터) |
| `Encoding::SingleCharToUTF8` | `0x5fcef0` | `0xff` | 함수 |
| `CAuroraTTFTexture::EnhanceCharacter` | `0x1132810` | `0x1bf` | 함수 |

### Nuklear UI

| 심볼 | 주소 | 크기 | 타입 | 동적 |
|------|------|------|------|------|
| `nk_draw_text` | `0xddf9e0` | `0x245` | 함수 | **O** |
| `nk_draw_list_add_text` | `0xde3aa0` | `0x30c` | 함수 | O |

### 인코딩

| 심볼 | 주소 | 크기 | 타입 |
|------|------|------|------|
| `Encoding::g_DefaultLocale` | `0x18aa978` | 4 | 데이터 |
| `Encoding::SetDefaultLocale` | `0x5fce10` | `0x26` | 함수 |
| `Encoding::GetDefaultLocale` | `0x5fcdf0` | `0x0f` | 함수 |
| `Encoding::SetCustomEncoding` | `0x5fce40` | `0x61` | 함수 |

---

## Phase 1: 경계 체크 확장

### GetSymbolCoords 디스어셈블리

```asm
; CAurFontInfo::GetSymbolCoords(int index, Vector* out1, Vector* out2)
; rdi=this, esi=index, rdx=out1, rcx=out2

4856d0: cmpb   $0x0, 0x68(%rdi)       ; fontInfo->field_0x68 체크
4856d4: push   %rbp
4856d8: je     0x4856e0
4856da: cmpb   $0x0, 0x69(%rdi)       ; fontInfo->field_0x69 (텍스처 준비됨?)
4856de: jne    0x485720                ; → 0 반환

4856e0: cmpl   $0xff, %esi            ; ★ 경계 체크: index > 255?
4856e6: ja     0x485720                ; → 0 반환 (범위 초과)

4856e8: movslq %esi, %rsi             ; index를 64비트로 확장
4856eb: leaq   (%rsi,%rsi,2), %rax    ; rax = index * 3
4856ef: movq   0x20(%rdi), %rsi       ; rsi = this->coordsArray1
4856f3: shlq   $0x2, %rax             ; rax = index * 12 (Vector 크기)
4856f7: movq   (%rsi,%rax), %r8       ; out1 복사 (8바이트)
4856fb: movq   %r8, (%rdx)
4856fe: movl   0x8(%rsi,%rax), %esi   ; out1 복사 (나머지 4바이트)
485702: movl   %esi, 0x8(%rdx)
485705: movq   0x30(%rdi), %rdx       ; rdx = this->coordsArray2
485709: pop    %rbp
48570a: movq   (%rdx,%rax), %rsi      ; out2 복사
48570e: movq   %rsi, (%rcx)
485711: movl   0x8(%rdx,%rax), %eax
485715: movl   %eax, 0x8(%rcx)
485718: ret

485720: ; 범위 초과 → 0 반환
        movq   $0x0, (%rdx)
        movl   $0x0, 0x8(%rdx)
        movq   $0x0, (%rcx)
        movl   $0x0, 0x8(%rcx)
        pop    %rbp
        ret
```

### 패치 내용

```
GetSymbolCoords @ 파일오프셋 계산 필요 (VA 0x4856e0):
  원본: 81 fe ff 00 00 00    cmpl $0xff, %esi
  패치: 81 fe 35 0a 00 00    cmpl $0xa35, %esi     ; 255 → 2613

SetSymbolCoords @ 파일오프셋 계산 필요 (VA 0x485750):
  원본: 81 fe ff 00 00 00    cmpl $0xff, %esi
  패치: 81 fe 35 0a 00 00    cmpl $0xa35, %esi     ; 255 → 2613
```

난이도: **매우 쉬움** — immediate 값 4바이트 변경

참고: VA → 파일오프셋 변환은 `.text` 섹션 기준:
- `.text` VA = `0x003fd000`, 파일오프셋 = `0x003fd000` (PIE, 첫 LOAD 세그먼트 오프셋 0)
- 따라서 VA == 파일오프셋 (첫 LOAD 세그먼트가 VA 0x0부터 매핑)

---

## Phase 2: 폰트 베이킹 후킹

### AurGetTTFTexture 호출 경로

`LoadFromTTF` @ `0x4875b0`에서의 호출 흐름:

```asm
; 글리프 수를 0x100(256)으로 설정
487636: movl   $0x100, (%rax)          ; ★ fontInfo->glyphCount = 256

; 글리프별 SingleCharToUTF8 호출 루프
487650: movsbl %r12b, %edi             ; char → int
487654: xorl   %esi, %esi             ; locale = 0
487656: addl   $0x1, %r12d            ; counter++
48765a: callq  Encoding::SingleCharToUTF8
48765f: movl   %eax, (%r13)           ; chars[i] = utf8_codepoint
487667: ...
48766e: cmpl   %r12d, %r15d           ; counter < glyphCount?
487671: jg     0x487650                ; → 루프 계속

; AurGetTTFTexture 함수 포인터 로드 및 호출
487673: leaq   0x1524756(%rip), %rdx   ; rdx = &AurGetTTFTexture (0x19abdd0)
48768e: movq   (%rdx), %r12            ; r12 = 실제 함수 포인터
...
4876f2: callq  *%r12                   ; AurGetTTFTexture(obj, chars, count, out, ...)
```

### 훅 방법: LD_PRELOAD .so

```c
// .so constructor에서 AurGetTTFTexture 포인터를 교체

__attribute__((constructor))
static void init_hook(void) {
    // 1. /proc/self/maps에서 nwmain-linux 베이스 주소 확보
    // 2. base + 0x19abdd0 위치의 함수 포인터를 교체
    //    - mprotect()로 쓰기 권한 부여
    //    - 원본 포인터 저장
    //    - my_AurGetTTFTexture 주소로 교체
}
```

my_AurGetTTFTexture 구현:
- count == 256이면 2,606으로 확장 (256 ASCII + 2,350 한글)
- KSX1001 한글 유니코드 테이블로 chars[] 배열 확장
- 원본 함수 호출

### 텍스처 확장 패치

글리프 2,606자를 수용하기 위해 텍스처 크기 확장 필요.
`LoadFromTTF` 내부에서 텍스처 크기 관련 코드 분석 필요.

---

## Phase 3: TextOut CP949 디코더

### TextOut 메인 루프 분석

```asm
; ===== 루프 진입점 =====
4964f6: movslq %r12d, %r13            ; r13 = 루프 인덱스 (signed extend)
4964f9: addq   -0x90(%rbp), %r13      ; r13 = &string[index]

496500: movq   0x28(%r15), %rdi       ; rdi = this->fontInfo
496504: movq   -0xa8(%rbp), %rcx      ; rcx = &out2 (스택)
49650b: movq   -0xa0(%rbp), %rdx      ; rdx = &out1 (스택)

496512: movzbl (%r13), %esi           ; ★ esi = 현재 바이트 (1바이트만 읽음)

496517: movq   %r13, -0x98(%rbp)      ; 문자열 포인터 저장
49651e: movl   %esi, %r13d            ; r13d = 현재 바이트 (마크업 체크용)
496521: callq  GetSymbolCoords        ; GetSymbolCoords(fontInfo, charIndex, &out1, &out2)

496526: cmpb   $0x3c, %r13b           ; '<' 마크업 체크
49652a: jne    0x496398                ; → 일반 글리프 렌더링

; ===== 루프 카운터 증가 =====
4964e4: callq  AlignGUIToPixel
4964e9: cmpl   %r12d, -0x84(%rbp)     ; r12d < stringLength?
4964f0: jle    0x4965e0                ; → 루프 종료
```

### TextOutDoubleByte — 미구현 스텁

```asm
; TextOut 함수 초반에서 "더블바이트" 플래그 체크
496253: movq   0x28(%rdi), %rax       ; rax = fontInfo
496257: movl   0x40(%rax), %eax       ; eax = fontInfo->field_0x40 (더블바이트 플래그)
49625a: testl  %eax, %eax
49625c: jne    0x496670                ; → TextOutDoubleByte 호출

; TextOutDoubleByte는 스텁:
496210: push   %rbp
496211: xorl   %eax, %eax             ; return 0
496213: mov    %rsp, %rbp
496216: pop    %rbp
496217: ret
```

게임에 더블바이트 텍스트 렌더링 프레임워크가 존재하지만 **미구현 상태**.

### 패치 방법: 코드 케이브

`movzbl` 5바이트를 `jmp rel32` 5바이트로 교체:

```
패치 포인트 (VA 0x496512):
  원본: 41 0f b6 75 00       movzbl (%r13), %esi
  패치: e9 XX XX XX XX       jmp    <code_cave>
```

코드 케이브 내용 (x86-64):

```asm
code_cave:
    movzbl (%r13), %esi            ; 원본 명령 복원
    cmpl   $0xb0, %esi             ; CP949 리드바이트 하한
    jb     .not_korean
    cmpl   $0xc8, %esi             ; CP949 리드바이트 상한
    ja     .not_korean
    movzbl 1(%r13), %eax           ; 트레일바이트 읽기
    cmpl   $0xa1, %eax             ; 트레일 하한
    jb     .not_korean
    cmpl   $0xfe, %eax             ; 트레일 상한
    ja     .not_korean

    ; glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    subl   $0xb0, %esi
    imull  $94, %esi, %esi
    subl   $0xa1, %eax
    addl   %eax, %esi
    addl   $256, %esi
    addl   $1, %r12d               ; 루프 카운터 +1 (2바이트 소비)

.not_korean:
    jmp    0x496517                 ; 원래 위치로 복귀
```

총 ~50바이트. 코드 케이브 위치 후보:
- `.text` 섹션 끝 패딩 (`0x12edd5c` 이후)
- 함수 간 NOP 패딩 영역
- `TextOutDoubleByte` 스텁 영역 재활용 (8바이트밖에 안 되므로 부족)

---

## Phase 4: Nuklear UI 한글 지원

### Windows와의 결정적 차이

| 항목 | Windows (MSVC) | Linux (GCC) |
|------|---------------|-------------|
| `nk_draw_text` | 46개소에 인라인 | **독립 함수** (`0xddf9e0`) |
| 동적 심볼 | 없음 | **있음** (`g DF .text`) |
| 훅 가능 여부 | **불가** | **`LD_PRELOAD` 인터포즈 가능** |

### nk_draw_text 프롤로그

```asm
ddf9e0: push   %rbp
ddf9e1: mov    %rsp, %rbp
ddf9e4: push   %r15
ddf9e6: push   %r14
ddf9e8: push   %r13
ddf9ea: push   %r12
ddf9ec: push   %rbx
ddf9ed: movslq %edx, %rbx             ; rbx = len
ddf9f0: sub    $0x38, %rsp
ddf9f4: movq   %xmm0, -0x48(%rbp)     ; rect.x, rect.y (packed float)
ddf9f9: ...
ddfa08: test   %rsi, %rsi              ; text == NULL?
ddfa0b: movq   %xmm1, -0x50(%rbp)     ; rect.w, rect.h (packed float)
ddfa13: test   %ebx, %ebx              ; len == 0?
```

### ABI 분석

System V AMD64 ABI (Linux):
```c
void nk_draw_text(
    struct nk_command_buffer *buf,  // rdi
    const char *text,               // rsi
    int len,                        // edx
    struct nk_rect rect,            // xmm0 (x,y), xmm1 (w,h)
    const struct nk_user_font *font,// rcx
    struct nk_color bg,             // r8d
    struct nk_color fg              // r9d
);
```

주의: `nk_rect`는 4개 float (16바이트)이지만 System V ABI에서 SSE 레지스터로 전달됨. MSVC ABI와 다른 점.

### 훅 구현

```c
// LD_PRELOAD .so에서 심볼 인터포즈
void nk_draw_text(struct nk_command_buffer *buf, const char *text,
                  int len, ...) {
    // 1. 비ASCII 바이트 감지
    // 2. Latin-1 손상 패턴 복원 (C2/C3 XX → 원본 바이트)
    // 3. CP949 → UTF-8 변환
    // 4. dlsym(RTLD_NEXT, "nk_draw_text")로 원본 호출
}
```

---

## Phase 5: CalcWidth CP949 디코더

### CalculateVisibleStringLengthAndWidth 분석

```asm
; 바이트 읽기 지점
496888: movzbl (%rsi), %r15d           ; ★ 1바이트만 읽음
49688c: cmpb   $0x3c, %r15b           ; '<' 마크업 체크
496890: je     0x4969e8

; 글리프 좌표 조회
4968af: movq   0x28(%r13), %rdi       ; fontInfo
4968b3: ...
4968bd: movzbl %r15b, %esi            ; charIndex
4968c1: callq  GetSymbolCoords
```

Phase 3과 동일한 코드 케이브 방식으로 CP949 2바이트 디코딩 필요.

### UpdateCaret 분석

```asm
; 바이트 읽기 지점
496bed: movzbl (%rax,%r14), %esi       ; ★ 1바이트만 읽음
496bf2: ...
496c04: callq  GetSymbolCoords
```

UpdateCaret도 동일한 패치 필요.

---

## 패치 전략 요약

| Phase | 방법 | 대상 | 난이도 |
|-------|------|------|--------|
| 1. 경계 확장 | 바이너리 패치 | `cmpl $0xff` × 2 | 쉬움 |
| 2. 폰트 베이킹 | LD_PRELOAD .so | `AurGetTTFTexture` 포인터 교체 | 보통 |
| 3. TextOut CP949 | 바이너리 패치 + 코드 케이브 | `movzbl` → `jmp cave` | 보통 |
| 4. Nuklear UI | LD_PRELOAD .so | `nk_draw_text` 인터포즈 | 보통 |
| 5. CalcWidth CP949 | 바이너리 패치 + 코드 케이브 | `movzbl` → `jmp cave` | 보통 |
| 6. UpdateCaret CP949 | 바이너리 패치 + 코드 케이브 | `movzbl` → `jmp cave` | 보통 |
| 7. 텍스처 확장 | 바이너리 패치 | 텍스처 크기 4096×4096 | 분석 필요 |

### 실행 방법

```bash
# 설치 스크립트가 바이너리 패치 적용 후:
LD_PRELOAD=./nwn_korean_hook.so ./nwmain-linux
```

또는 런치 스크립트로 래핑:

```bash
#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
LD_PRELOAD="$DIR/nwn_korean_hook.so" exec "$DIR/nwmain-linux" "$@"
```

---

## 플랫폼 비교

| 항목 | macOS (arm64) | Windows (x64) | **Linux (x86-64)** |
|------|--------------|---------------|-------------------|
| 바이너리 형식 | Mach-O FAT | PE/COFF | **ELF PIE** |
| 심볼 | 일부 | Stripped | **전부 보존** |
| .so 주입 | `install_name_tool` | DLL Loader exe | **`LD_PRELOAD`** |
| 코드사이닝 | 필요 | 불필요 | **불필요** |
| nk_draw_text | dylib interpose | **불가** (인라인) | **LD_PRELOAD 가능** |
| 인코딩 | ARM64 | x86-64 | x86-64 |
| 코드 케이브 | __TEXT 패딩 | .rodata 패딩 | 섹션 패딩 |

### Linux 장점

1. **nk_draw_text 독립 함수** — Windows에서 불가능했던 Nuklear UI 한글 지원 가능
2. **심볼 전부 보존** — 함수 이름, 크기, 타입 정보 완비
3. **LD_PRELOAD** — 가장 깔끔한 라이브러리 주입 방식
4. **코드사이닝 불필요** — macOS의 서명 제거/재서명 과정 생략
5. **x86-64 인코딩 단순** — ARM64 대비 immediate/branch 인코딩이 직관적

### Linux 고려사항

1. **PIE 바이너리** — 런타임 주소 변동, .so에서 `/proc/self/maps` 파싱 필요
2. **Steam 업데이트** — 패치된 바이너리 덮어쓰기 가능, 해시 검증 필요
3. **코드 케이브 확보** — Phase 3/5/6용 ~150바이트 연속 공간 필요
4. **스팀덱 호환** — 네이티브 Linux 빌드, Proton 불필요

---

## 파일오프셋 참고

PIE 바이너리의 첫 LOAD 세그먼트:
```
LOAD off=0x000000 vaddr=0x000000 filesz=0x1636ac3 flags=r-x
```

vaddr 시작이 0이므로 **VA == 파일오프셋** (첫 LOAD 세그먼트 내).

따라서:
- GetSymbolCoords `cmpl`: 파일오프셋 `0x4856e0`
- SetSymbolCoords `cmpl`: 파일오프셋 `0x485750`
- TextOut `movzbl`: 파일오프셋 `0x496512`
- CalcWidth `movzbl`: 파일오프셋 `0x496888`
- UpdateCaret `movzbl`: 파일오프셋 `0x496bed`
