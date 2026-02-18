# Nuklear UI 한글 지원 분석 (Windows x64)

## 문제

NWN:EE의 모듈 선택, 설정 등 Nuklear UI 화면에서 한글이 깨져 표시됨.

텍스트 흐름: TLK(CP949) -> Latin-1로 오인 -> UTF-8 인코딩 -> Nuklear 렌더링 -> 깨진 문자

Mac 버전에서는 `nk_draw_text` 함수를 직접 후킹하여 UTF-8 텍스트를 변환하는 방식으로 해결.

## Mac 버전 구현 (참고)

Mac(arm64)에서는 `nk_draw_text`가 독립 함수로 존재하여 직접 후킹:

- 훅 대상: offset `0xb38ef0` (nk_draw_text)
- 텍스트 파라미터: x1 (text pointer), w2 (length)
- 변환: Latin-1 corrupted UTF-8 → 정상 UTF-8, 또는 raw CP949 → UTF-8
- 추가: 첫 호출 시 locale을 3(Korean)으로 설정 + `nk_sdl_refresh_config()` 호출하여 글리프 범위 갱신

## 바이너리 분석 결과

### nk_draw_text가 독립 함수로 존재하지 않음

MSVC의 공격적 인라이닝으로 `nk_draw_text`가 46개 호출자에 모두 인라인됨.

증거:
- `mov edx, 0x10` (NK_COMMAND_TEXT) + `call 0x00c10434` 패턴이 46개소에서 발견
- 함수 RVA 0x00c10434, 프롤로그 `48 8b c4 4c 89 48 20 4c 89 40 18 48 89 50 10 53`
- 46개 함수는 각각 `nk_label`, `nk_button`, `nk_widget_text` 등의 인라인된 복사본

### 시도 1: nk_draw_list_add_text (RVA 0xa824b0)

프롤로그: `48 89 5c 24 18 48 89 74 24 20 41 54 41 56 41 57 48 83 ec 20` (20바이트)

결과:
- 4회 호출됨
- text 파라미터(r9): NULL 또는 `0xfeeefeeefeeefeee` (MSVC freed memory 패턴)
- rcx/r8이 코드 섹션 포인터 (힙/스택이 아님)
- 결론: 함수가 호출은 되지만 text 렌더링 경로가 아닌 것으로 판단

### 시도 2: nk_draw_text 후보 (RVA 0x952A10)

선정 근거:
- 46개 중 유일하게 `mov rax, rsp` 프롤로그를 가진 함수
- `test rcx, rcx` NULL 체크 존재
- `mov edx, 0x10` + `call nk_command_buffer_push` 확인

결과:
- 2회 호출됨 (빈도 너무 낮음)
- r8 (str): 항상 NULL
- r9 (len): nwmain.exe 베이스 주소 (길이값 아님)
- 결론: 파라미터 레이아웃이 nk_draw_text와 완전히 다름

### 시도 3: RVA 0xC10434 함수 훅 + 비휘발 레지스터 스캔

**이 함수는 nk_command_buffer_push가 아닌 것으로 판명.**

훅 인프라:
- 15바이트 프롤로그 → 14바이트 `jmp [rip+0]` + 1 NOP
- 동적 머신코드 naked 래퍼 (VirtualAlloc, 121바이트)
- 비휘발 레지스터 캡처: rbx, rsi, rdi, rbp, r12-r15를 글로벌 배열에 저장
- 호출자 스택 8슬롯 스캔

결과 (101K+ 호출 분석):

| 항목 | 값 |
|------|-----|
| type=0x10 호출 | 101,514회 |
| 레지스터/스택 텍스트 발견 | 8,383개 (첫 빌드), 50개 (개선 빌드) |
| 한글 텍스트 | **0개** |
| ASCII 텍스트 | fnt_maintext, zanzinabru, waldgeigne 등 (게임 리소스 이름) |

**판명 근거:**
- rcx(첫 번째 파라미터)에 "dialog.tlk", "INSTALL:", "nwclient" 등 리소스 경로 문자열이 들어있음
- 구조체가 Nuklear 커맨드 버퍼 형식이 아님 (포인터+int+int 반복 패턴)
- type 값 0x20, 0x28 등이 NK 커맨드 enum 범위(최대 0x12) 초과

**오탐 패턴 (K# entries):**
- `40 53 48 83 ec 20...` = x86 기계어 (`push rbx; sub rsp, 0x20`) - printable('@','S','H')과 highbyte가 섞여 텍스트로 오인
- `d9 33 d0 f6 7f` = 스택 프레임 잔해 (rbp 고정값, 5바이트)
- `XX XX 3b 97 cb 01` = 힙 포인터 조각 (6바이트)
- 4-6바이트 임의 메모리 조각

**교훈:**
- 70% printable+highbyte 비율로는 x86 코드를 필터링할 수 없음
- 코드 프롤로그 패턴(`40 53`, `48 83 EC`, `55 48 8B`) 사전 제외 필요
- 짧은 바이트열(< 8바이트)은 대부분 포인터 잔해이므로 제외 필요
- 유효한 CP949는 `is_valid_korean()` 함수로 엄격 검증 필요

## 다음 단계

### 옵션 A: 레지스터 스캔 필터 강화 (현재 인프라 유지)

기존 RVA 0xC10434 훅에서 필터 강화:

```c
// 기계어 코드 패턴 제외
static int is_code_pattern(const unsigned char* sp) {
    if (sp[0] == 0x40 && sp[1] == 0x53) return 1;           // push rbx
    if (sp[0] == 0x48 && sp[1] == 0x83 && sp[2] == 0xEC) return 1;  // sub rsp, xx
    if (sp[0] == 0x55 && sp[1] == 0x48 && sp[2] == 0x8B) return 1;  // push rbp; mov rbp, rsp
    return 0;
}

// 최소 문자열 길이 8바이트 이상으로 상향
// nwmain.exe 코드 섹션 주소 범위 제외 (base ~ base + image_size)
```

**장점**: 기존 코드 재사용, 빠른 반복
**단점**: 이 함수가 NK 텍스트 경로에 있지 않다면 아무리 필터링해도 한글을 못 찾음
**리스크**: 높음 (함수 자체가 NK 무관일 가능성)

### 옵션 B: 렌더 루프 훅 (새 접근)

Nuklear 커맨드 버퍼를 **소비**하는 렌더 루프에서 NK_COMMAND_TEXT 분기점 찾기.
이 시점에서 `nk_command_text.string[]`에 텍스트가 완전히 채워져 있음.

찾는 방법:
1. `nk_draw_list_add_text` (RVA 0xa824b0)에 대한 xref 검색
2. xref 호출자에서 `cmp` + NK_COMMAND_TEXT(0x10) 분기 확인
3. 해당 렌더 루프 함수에 훅 설치

```c
// 렌더 루프 내 NK_COMMAND_TEXT 분기에서:
struct nk_command_text* t = (struct nk_command_text*)cmd;
char* text = t->string;   // 완전한 텍스트
int len = t->length;
// → 여기서 변환 수행
```

**장점**: 텍스트가 완전히 채워진 상태로 접근 가능
**단점**: 렌더 루프 위치 특정 필요, 인라인 여부 미지

### 옵션 C: nk_draw_list_add_text 재시도 (ABI 수정)

RVA 0xa824b0 함수를 MSVC x64 ABI 기준으로 재분석:

```
nk_draw_list_add_text(list, font, rect, text, len, font_height, fg)
MSVC x64 ABI:
  rcx = list (nk_draw_list*)
  rdx = font (nk_user_font*)
  r8  = &rect (hidden pointer, nk_rect는 16바이트이므로)
  r9  = text (const char*)
  [rsp+0x28] = len (int)
  [rsp+0x30] = font_height (float)
  [rsp+0x38] = fg (nk_color)
```

이전 시도에서 r9=NULL이었던 것은:
- 실제로 text가 NULL이었을 수 있음 (freed memory 접근 전 NULL 체크?)
- 호출 빈도 4회가 너무 낮음 → 이 함수가 text 렌더링 경로가 아닐 수 있음

**장점**: 독립 함수로 존재하여 안정적 후킹 가능
**단점**: 이전에 4회밖에 호출되지 않았음, text가 실제 NULL일 수 있음

### 옵션 D: 완전히 새로운 접근 (nk_sdl_refresh_config 등)

Mac 버전에서 사용하는 `nk_sdl_refresh_config` 함수의 Windows 등가물을 찾아:
1. locale 값을 Korean(3)으로 강제 설정
2. 글리프 범위 갱신 트리거
3. Nuklear 자체의 UTF-8 렌더링 파이프라인을 활용

**장점**: 텍스트 변환 없이 Nuklear 내부 메커니즘 활용
**단점**: Windows 바이너리에서 해당 함수 위치 특정 필요, Mac 버전에서 변경해보았으나 Latin-1으로 강제 처리되도록 되어 있었음

## 기술 참고

### MSVC x64 ABI: 16바이트 구조체 전달

`nk_rect` (4 floats = 16바이트)는 MSVC x64에서:
- 1/2/4/8바이트 구조체: 레지스터에 직접 전달
- 그 외 크기: 호출자가 스택에 복사본 생성, 포인터를 레지스터 슬롯에 전달

### nk_command_text 구조체 (Nuklear 소스)

```c
struct nk_command_text {
    struct nk_command header;    // type, next offset
    const struct nk_user_font *font;
    struct nk_color background;
    struct nk_color foreground;
    short x, y, w, h;
    float height;
    int length;
    char string[1];             // 가변 길이
};
```

### 관련 RVA 목록

| 주소 | 설명 | 상태 |
|------|------|------|
| 0x00c10434 | 범용 함수 (nk_command_buffer_push **아님**) | 훅 설치됨, NK 무관 판명 |
| 0x00a824b0 | nk_draw_list_add_text (추정) | 4회 호출, text=NULL |
| 0x00952A10 | nk_draw_text 인라인 후보 | 불일치 확인 |
| 0x000EBB20 | GetSymbolCoords (함수 내부 오프셋) | Phase 3에서 사용 |

### 현재 DLL 훅 인프라

| 컴포넌트 | 설명 |
|----------|------|
| naked 래퍼 | VirtualAlloc 256바이트, 비휘발 레지스터 저장 + 핸들러 call + 트램폴린 jmp |
| post-hook 트램폴린 | 58바이트, return-address hijacking (현재 비활성) |
| 핸들러 | classify_string() + dump_string() + 레지스터/스택 스캔 |
| 변환 코드 | is_latin1_corrupted_utf8(), convert_latin1_corrupted_to_utf8(), convert_cp949_to_utf8(), nk_process_text() - 구현 완료, 미사용 |
