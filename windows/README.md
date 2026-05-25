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

### MinGW-w64 (필수)

소스에 GCC 전용 문법(`__attribute__((naked))`, `__asm__ volatile`)이 포함되어 있어 **MSVC로는 빌드할 수 없습니다**. MinGW-w64 GCC가 필요합니다.

#### MSYS2 설치

```batch
:: 1. MSYS2 설치
winget install MSYS2.MSYS2

:: 2. MSYS2 터미널에서 GCC 설치
pacman -S mingw-w64-x86_64-gcc

:: 3. PATH에 추가 (시스템 환경변수 또는 터미널에서)
set PATH=C:\msys64\mingw64\bin;%PATH%
```

#### 수동 빌드

```batch
cd windows\hook

:: DLL 빌드
gcc -shared -O2 -o nwn_korean_hook.dll nwn_korean_hook.c -lpsapi

:: 로더 빌드
gcc -O2 -o nwn_korean_loader.exe nwn_korean_loader.c
```

#### 자동 빌드 (build.bat)

```batch
cd windows\hook
build.bat
```

## 패치 단계

### Phase 1: 경계 체크 확장 (바이너리 패치)

글리프 인덱스 제한을 256 → 2613으로 확장합니다.

| RVA | 원본 | 패치 | 설명 |
|-----|------|------|------|
| `0x000eaf20` | `81 fa ff 00 00 00` | `81 fa 35 0a 00 00` | GetSymbolCoords cmp 255→2613 |
| `0x000ed39f` | `81 fa ff 00 00 00` | `81 fa 35 0a 00 00` | SetSymbolCoords cmp 255→2613 |
| `0x000fb880` | `48 c7 45 bc 03...` | `48 c7 45 bc 30...` | Glyph padding 3→48 (Android와 동일) |

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
> 상세 분석: [docs/NUKLEAR_ANALYSIS.md](../docs/NUKLEAR_ANALYSIS.md) 참조

### Phase 5: CalcWidth CP949 디코더 (바이너리 패치)

`CalculateVisibleStringLengthAndWidth` 함수 내에서 CP949 2바이트를 글리프 인덱스로 변환합니다.
TextOut과 동일한 CP949 디코딩 로직이지만, 텍스트 **폭 계산** 시점에 적용되어 한글 텍스트의 정렬 및 레이아웃을 보정합니다.

- Hook point: RVA `0x0004e263` (movzx eax, byte → jmp)
- Cave location: .rodata 빈 영역 (TextOut cave 직후)
- 효과: 한글 텍스트 중앙정렬 수정, 인접 글리프 침범 해소

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
- 테스트 해시 (SHA256): `3b7cb1252e0edb2ce22d7971f333aade027039ae30a45b4bc64732c3e6bec73a`

## 알려진 제한사항

1. **Nuklear UI 미지원**: EE UI(모듈 선택, 설정 화면)의 한글이 깨져 표시됨
   - 원인: MSVC 인라이닝으로 인한 후킹 불가
   - 상세 분석: [docs/NUKLEAR_ANALYSIS.md](../docs/NUKLEAR_ANALYSIS.md)
   - 게임 내 대화창, 인벤토리 등은 정상 작동

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
