# NWN:EE Windows 한글 패치 (개발 문서)

Windows x64용 한글 패치 구현 문서입니다.

## 패치 구조

```
windows/
├── hook/                       # DLL 소스 및 빌드
│   ├── nwn_korean_hook.c       # 메인 hook DLL 코드
│   ├── nwn_korean_loader.c     # DLL 인젝터 (로더)
│   ├── cp949_utils.h           # CP949 → Unicode 변환 테이블
│   ├── build.bat               # 빌드 스크립트
│   ├── nwn_korean_hook.dll     # 빌드된 DLL
│   └── nwn_korean_loader.exe   # 빌드된 로더
├── scripts/
│   └── install.py              # 설치 스크립트 (바이너리 패치)
├── README.md                   # 이 파일 (개발자 문서)
└── RELEASE_README.md           # 사용자용 설치 가이드
```

## 빌드 요구사항

### Visual Studio (권장)

```batch
:: Visual Studio Developer Command Prompt에서 실행
cd windows\hook

:: DLL 빌드
cl /LD /O2 nwn_korean_hook.c /Fe:nwn_korean_hook.dll /link psapi.lib

:: 로더 빌드
cl /O2 nwn_korean_loader.c /Fe:nwn_korean_loader.exe
```

### MinGW-w64

```batch
cd windows\hook

:: DLL 빌드
gcc -shared -O2 -o nwn_korean_hook.dll nwn_korean_hook.c -lpsapi

:: 로더 빌드
gcc -O2 -o nwn_korean_loader.exe nwn_korean_loader.c
```

### 자동 빌드 (build.bat)

```batch
cd windows\hook
build.bat
```

`build.bat`은 Visual Studio와 MinGW 중 사용 가능한 컴파일러를 자동 감지합니다.

## 패치 단계

### Phase 1: 경계 체크 확장 (바이너리 패치)

글리프 인덱스 제한을 256 → 2613으로 확장합니다.

| RVA | 원본 | 패치 | 설명 |
|-----|------|------|------|
| `0x000eaf20` | `81 fa ff 00 00 00` | `81 fa 35 0a 00 00` | GetSymbolCoords cmp 255→2613 |
| `0x000ed39f` | `81 fa ff 00 00 00` | `81 fa 35 0a 00 00` | SetSymbolCoords cmp 255→2613 |
| `0x000fb880` | `48 c7 45 bc 03...` | `48 c7 45 bc 10...` | Glyph padding 3→16 |

### Phase 2: Bake 함수 후킹 (DLL)

`AurGetTTFTexture` 함수 포인터(RVA `0x0140b278`)를 교체하여 폰트 베이킹 시 한글 글리프를 추가합니다.

- 256자 → 2606자 확장 (ASCII 256 + 한글 2350)
- 함수 포인터 방식으로 안전하게 후킹
- 지연 후킹: 게임 초기화 후 자동 설치

### Phase 3: TextOut CP949 디코더 (바이너리 패치)

TextOut 루프 내에서 CP949 2바이트를 글리프 인덱스로 변환합니다.

```
CP949 → 글리프 인덱스
glyph = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

예: "가" (0xB0A1) → 256
예: "힣" (0xC8FE) → 2605
```

Code Cave 사용:
- Hook point: RVA `0x0004ca06`
- Cave location: RVA `0x00966dd3`

### Phase 4: Nuklear UI 지원 - 미구현

> **현재 상태: 미구현** - EE UI(모듈 선택, 설정 화면 등)의 한글은 아직 지원되지 않습니다.

#### 문제 상황

TLK 로더가 CP949를 Latin-1으로 해석하여 깨진 텍스트가 표시됩니다:

```
CP949: B0 A1 ("가") → Latin-1: ° ¡ → UTF-8: C2 B0 C2 A1
```

#### 시도한 접근법 및 실패 원인

**1. DLL 트램폴린 후킹 (실패)**

`nk_draw_text` 함수(RVA `0xa70d90`) 후킹 시도:

```asm
; 프롤로그 (19바이트)
mov rax, rsp           ; ← 문제의 원인
push rbp
push r12~r15
lea rbp, [rax-208h]    ; rax 기반 스택 프레임
```

**실패 원인**: `mov rax, rsp`는 함수 **직접 호출** 시점의 rsp를 기대함.
트램폴린에서 호출하면 rsp가 달라져서 `lea rbp, [rax-208h]` 계산이 틀어짐.

```
[NK Handler #1] text=00007FF7C98D6590 len=484  ← 첫 호출만 성공
[NK Handler #3] text=0000000000000000 len=-922015669  ← 이후 전부 손상
```

**2. nk_draw_list_add_text 후킹 (복잡)**

RVA `0xa824b0` - 프롤로그는 트램폴린 가능하나, 파라미터가 XMM 레지스터와 스택에 혼합 전달되어 C 함수로 캡처 불가.

#### 검토 중인 대안

| 접근법 | 장점 | 단점 |
|--------|------|------|
| MinHook/Detours 라이브러리 | 복잡한 프롤로그 처리 가능 | 외부 의존성 |
| font->query 함수 포인터 교체 | DLL에서 구현 가능 | font 생성 시점 후킹 필요 |
| UTF-8 디코딩 루프 바이너리 패치 | 근본적 해결 | 대규모 코드 케이브 필요 |

#### 관련 함수 RVA

| 함수 | RVA | 설명 |
|------|-----|------|
| nk_draw_text | `0xa70d90` | 상위 레벨 텍스트 렌더링 |
| nk_draw_list_add_text | `0xa824b0` | 하위 레벨 글리프 렌더링 |
| UTF-8 디코딩 루프 | `0xa70500` | codepoint 추출 |

### 텍스처 확장 (바이너리 패치)

한글 2350자를 수용하기 위해 폰트 텍스처를 확장합니다.

- Hook point: RVA `0x000fb7e7`
- Cave location: RVA `0x002df54f`
- 크기: 512x512 → 4096x4096

## 아키텍처

### DLL 인젝션 방식

```
nwn_korean_loader.exe
    │
    ├── CreateProcess(nwmain.exe, CREATE_SUSPENDED)
    │
    ├── VirtualAllocEx → WriteProcessMemory (DLL 경로)
    │
    ├── CreateRemoteThread(LoadLibraryA)
    │
    └── ResumeThread → 게임 실행
```

### 후킹 방식

1. **함수 포인터 교체** (Phase 2)
   - `AurGetTTFTexture` 포인터를 DLL 함수로 교체
   - 원본 함수 포인터 보존하여 호출

2. **Code Cave 패치** (Phase 3, 텍스처)
   - 기존 코드를 jmp 명령으로 교체
   - 빈 공간(code cave)에 새 코드 삽입
   - 처리 후 원래 위치로 복귀

## 디버그 로그

```
C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32\nwn_korean.log
```

## 참고: CP949 (KS X 1001)

완성형 한글 2350자:
- Lead byte: 0xB0~0xC8 (25개)
- Trail byte: 0xA1~0xFE (94개)
- 총: 25 × 94 = 2350자

## 바이너리 정보

- 대상: nwmain.exe (PE32+ x86-64)
- 버전: 8193.35+ (Steam Build)
- 테스트 해시 (SHA256): `4e1bd743944027ddca7b11b96fa856b1f51e3b7ad0f2747ddfc53b35312be8df`

## 알려진 제한사항

1. **Nuklear UI 미지원**: EE UI(모듈 선택, 설정 화면)의 한글이 깨져 표시됨
   - 원인: `mov rax, rsp` 프롤로그 패턴으로 트램폴린 후킹 불가
   - 게임 내 대화창, 인벤토리 등은 정상 작동

2. **한글 글리프 위치 치우침**: 한글이 왼쪽으로 치우쳐 표시됨
   - Width 계산 패치 시도 시 대화 화면 진입 시 크래시 발생
   - GetSymbolCoords의 advance 값이 정규화된 값(0.1~0.9)이라 단순 조정 불가
   - 글리프 겹침 문제는 glyph padding 16 패치로 해결됨

## 트러블슈팅

### DLL 로드 실패

1. Visual C++ 런타임 설치 확인
2. 안티바이러스 예외 추가
3. 관리자 권한으로 실행

### 패치 후 크래시

1. Steam에서 게임 파일 무결성 검사
2. `python install.py --uninstall` 후 재설치
3. `nwn_korean.log` 확인

### 한글이 표시되지 않음

1. `override/dialog.tlk` 확인
2. 폰트 파일 확인 (`fnt_*.ttf`)
3. DLL 로드 로그 확인
