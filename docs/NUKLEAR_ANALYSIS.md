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

### 시도 4: nk_user_font->width 콜백 훅 (Phase 4)

**접근법**: 메모리 스캔으로 `nk_user_font` 구조체를 찾아 `width` 함수 포인터를 교체.
인라인 불가능한 함수 포인터이므로 안정적 후킹 가능.

**nk_user_font 구조체 레이아웃 (x64)**:
```
offset 0x00: userdata  (8B, nk_handle)
offset 0x08: height    (4B float + 4B padding)
offset 0x10: width     (8B, 함수 포인터) ← 훅 대상
offset 0x18: query     (8B, 함수 포인터)
offset 0x20: texture   (8B, nk_handle)
```

**스캔 필터**:
- MEM_PRIVATE 힙 메모리만 스캔 (ReadProcessMemory 사용, VirtualQuery 타이밍 문제 회피)
- height: 5.0-50.0 범위
- width/query: nwmain.exe 코드 섹션 내 주소
- texture: 1-1000 범위 정수
- width 함수 프롤로그: 0x48/0x40/0x41/0x55/0x53/0x56/0x57 첫 바이트

**결과**:
- 4개 nk_user_font 구조체 발견: h=17.0 x2, h=22.1 x2, 모두 tex=29
- 원본 width callback: RVA 0xa6ba50
- 프롤로그: `48 89 5c 24 10 48 89 6c 24 18 48 89 74 24 20 57`
- NK UI가 표시된 상태에서만 구조체 존재 (lazy init)
- alt-tab 화면 전환 시 width 콜백이 재호출됨 (NK 리레이아웃 트리거)

**한글 텍스트 감지 성공**:
```
c2 bf c3 89 c2 bc c3 87 → "옵션" (Latin-1 corrupted CP949 BF C9 BC C7)
c2 b0 c3 8b c2 bb c3 b6 → "검색" (Latin-1 corrupted CP949 B0 CB BB F6)
```

**변환 시도 A: UTF-8 Unicode 코드포인트**
- CP949 → Unicode (U+AC00-U+D7A3) → UTF-8 인코딩
- 결과: ???? 표시
- 원인: 엔진 폰트 lookup이 `chardata[codepoint]` 직접 인덱싱 사용 추정
  → U+AC00(44032)은 chardata[2606] 범위 초과

**변환 시도 B: chardata 배열 인덱스**
- CP949 → KSX1001 순차 인덱스 → chardata_index(256-2605) → UTF-8 인코딩
- 예: "옵" → index 1706 → UTF-8 DA AA
- 결과: 여전히 ???? 표시
- 원인: 엔진이 chars[] 배열 기반 lookup (해시/검색)을 사용하거나,
  width/query 콜백과 별도의 렌더링 lookup 테이블이 존재

**핵심 미해결 문제**:
- width 콜백은 **폭 계산**만 담당, 실제 **렌더링**은 query 콜백 + 별도 경로
- in-place 텍스트 수정은 성공하지만, 렌더링 단계에서 글리프를 찾지 못함
- 엔진의 codepoint → chardata index 매핑 방식이 불명
- query 콜백(RVA 0xa6b9a0)도 동일한 문제를 가질 것으로 추정

## 현재 상태

**NK UI 한글 지원: 비활성화** (릴리즈 빌드에서 제외)

성공한 부분:
- nk_user_font 구조체 메모리 스캔 및 width 콜백 훅
- Latin-1 corrupted UTF-8 텍스트 감지 및 디코딩
- in-place 텍스트 수정 (width 콜백에서 원본 버퍼 직접 수정)

미해결:
- 렌더링 경로에서 한글 글리프 참조 불가 (codepoint → chardata 매핑 문제)
- nk_draw_text 인라인으로 렌더링 단계 직접 후킹 불가

## 향후 접근 방향

### 옵션 A: query 콜백 훅 + 커스텀 글리프 lookup
query 콜백(RVA 0xa6b9a0)을 훅하여 한글 codepoint에 대해 직접 stbtt_GetBakedQuad 호출.
베이크된 chardata 포인터를 저장해야 함.

### 옵션 B: 렌더 루프 훅
Nuklear 커맨드 버퍼를 소비하는 렌더 루프에서 NK_COMMAND_TEXT 분기점을 찾아
텍스트 변환 수행.

### 옵션 C: nk_sdl_refresh_config + locale 강제 설정
엔진 내부 locale을 Korean(3)으로 설정하여 Nuklear 자체의 글리프 범위 갱신 트리거.

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
| 0x00a6ba50 | nk_user_font width callback | 훅 성공, 한글 감지됨, 렌더링 미해결 |
| 0x00a6b9a0 | nk_user_font query callback | 미시도 |
| 0x00c10434 | 범용 함수 (nk_command_buffer_push **아님**) | NK 무관 판명 |
| 0x00a824b0 | nk_draw_list_add_text (추정) | 4회 호출, text=NULL |
| 0x00952A10 | nk_draw_text 인라인 후보 | 불일치 확인 |
| 0x000EBB20 | GetSymbolCoords (함수 내부 오프셋) | Phase 3에서 사용 |

### DLL 훅 인프라 (비활성화 상태)

| 컴포넌트 | 설명 |
|----------|------|
| nk_user_font 스캐너 | ReadProcessMemory 기반 힙 메모리 스캔, 구조체 패턴 매칭 |
| width 콜백 훅 | 함수 포인터 교체, in-place 텍스트 수정 |
| 변환 코드 | convert_latin1_corrupted_to_nk_glyphs(), convert_cp949_to_nk_glyphs(), nk_process_text() |
