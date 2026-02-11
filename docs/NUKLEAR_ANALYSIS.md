# Nuklear UI 한글 지원 분석 (Windows x64)

## 문제

NWN:EE의 모듈 선택, 설정 등 Nuklear UI 화면에서 한글이 깨져 표시됨.

텍스트 흐름: TLK(CP949) -> Latin-1로 오인 -> UTF-8 인코딩 -> Nuklear 렌더링 -> 깨진 문자

Mac 버전에서는 `nk_draw_text` 함수를 직접 후킹하여 UTF-8 텍스트를 변환하는 방식으로 해결.

## 바이너리 분석 결과

### nk_draw_text가 독립 함수로 존재하지 않음

MSVC의 공격적 인라이닝으로 `nk_draw_text`가 46개 호출자에 모두 인라인됨.

증거:
- `mov edx, 0x10` (NK_COMMAND_TEXT) + `call 0x00c10434` (nk_command_buffer_push) 패턴이 46개소에서 발견
- `nk_command_buffer_push` 확인: RVA 0x00c10434, 프롤로그 `48 8b c4 4c 89 48 20 4c 89 40 18 48 89 50 10 53`
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

프롤로그 (18바이트):
```
+00: 48 8b c4              mov rax, rsp
+03: 55                    push rbp
+04: 57                    push rdi
+05: 41 54                 push r12
+07: 41 56                 push r14
+09: 41 57                 push r15
+0B: 48 8d a8 b8 fd ff ff  lea rbp, [rax-248h]
```

결과:
- 2회 호출됨 (빈도 너무 낮음)
- r8 (str): 항상 `0x0000000000000000` (NULL)
- r9 (len): `0x00007FF604CE0000` = nwmain.exe 베이스 주소 (길이값 아님)
- bg: `0x746c7561` = ASCII "ault" ("default" 문자열 조각)
- rect: (0, 0, 0, 0) 또는 쓰레기 float 값
- 결론: 이 함수의 파라미터 레이아웃은 nk_draw_text와 완전히 다름

## 미시도 전략

### 1. nk_command_buffer_push 훅 (RVA 0xc10434)
- edx=0x10 (NK_COMMAND_TEXT)일 때 가로채기
- 반환된 command 구조체에서 text 데이터 추출
- 장점: 모든 인라인된 nk_draw_text 인스턴스를 한 곳에서 포착
- 단점: push 시점에는 구조체가 아직 비어있음 (호출자가 이후에 채움)

### 2. 렌더 루프 훅
- Nuklear command buffer를 소비하는 렌더러에서 NK_COMMAND_TEXT 분기점 찾기
- `nk_command_text` 구조체에서 직접 text/len 읽기
- 장점: 구조체가 완전히 채워진 상태
- 단점: 렌더 루프 위치 특정 필요

### 3. nk_draw_list_add_text 재시도 (MSVC ABI 수정)
- nk_rect (16바이트) -> hidden pointer로 r8에 전달
- text가 r9로 밀리고, len이 [rsp+28h]로 이동
- 이전 시도의 freed memory 문제가 ABI 해석 오류 때문인지 재검증

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

| 주소 | 설명 |
|------|------|
| 0x00c10434 | nk_command_buffer_push |
| 0x00a824b0 | nk_draw_list_add_text (추정) |
| 0x00952A10 | nk_draw_text 인라인 후보 (불일치 확인) |
| 0x000EBB20 | GetSymbolCoords (함수 내부 오프셋) |
