# NWN:EE macOS 한글 패치 (개발 문서)

macOS Apple Silicon용 한글 패치 구현 문서입니다.

## 패치 구조

```
mac/
├── hook/                       # dylib 소스 및 빌드
│   ├── nwn_korean_hook.c       # 메인 hook 코드
│   ├── Makefile
│   ├── ksx1001_hangul.h        # KS X 1001 한글 테이블
│   └── cp949_table_*.h         # CP949 변환 테이블
├── scripts/
│   └── install.py              # 설치 스크립트 (바이너리 패치 + dylib 삽입)
├── docs/                       # 기술 문서
├── README.md                   # 이 파일 (개발자 문서)
└── RELEASE_README.md           # 사용자용 설치 가이드
```

## 빌드 요구사항

### Xcode Command Line Tools

```bash
xcode-select --install
```

### 빌드

```bash
cd mac/hook
make clean && make
```

또는 Universal Binary (x64 + arm64):

```bash
make universal
```

## 패치 단계

### Phase 1: 경계 체크 확장 (바이너리 패치)

글리프 인덱스 제한을 256 → 2614로 확장합니다.

| 오프셋 | 원본 | 패치 | 설명 |
|--------|------|------|------|
| `0xab684` | `3ffc0371` | `3fd42871` | GetSymbolCoords cmp 255→2613 |
| `0xab6cc` | `3f000471` | `3fd82871` | GetSymbolCoords cmp 256→2614 |
| `0xab6f4` | `3ffc0371` | `3fd42871` | SetSymbolCoords cmp 255→2613 |
| `0xab73c` | `3ffc0371` | `3fd42871` | SetSymbolCoords cmp 255→2613 |

### Phase 2: Bake 함수 후킹 (dylib)

`_AurGetTTFTexture` 포인터를 교체하여 폰트 베이킹 시 한글 글리프를 추가합니다.

- 256자 → 2606자 확장 (ASCII 256 + 한글 2350)
- float 인자 (s0~s3) 전달 필수
- scale 0.95 적용 (글리프 상단 잘림 방지)

### Phase 3: TextOut CP949 디코더 (바이너리 패치)

Inline Trampoline - TextOut 루프 내에서 CP949 2바이트를 글리프 인덱스로 변환합니다.

```
CP949 → 글리프 인덱스
glyph = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

예: "가" (0xB0A1) → 256
예: "힣" (0xC8FE) → 2605
```

### Phase 4: Nuklear UI 지원 (dylib)

EE UI (모듈 선택, 설정 등)용 `nk_draw_text` 후킹:
- Latin-1 손상 패턴 복원
- CP949 → UTF-8 변환

### 텍스처 확장 (바이너리 패치)

한글 2350자를 수용하기 위해 폰트 텍스처를 확장합니다.

| 오프셋 | 설명 |
|--------|------|
| `0xc5638` | 텍스처 높이 → 4096 |
| `0xc5660` | 텍스처 너비 → 4096 |
| `0xc56c0` | 글리프 패딩 3→16 |

## 아키텍처

### dylib 삽입 방식

```
install.py
    │
    ├── nwmain 바이너리 패치 (Phase 1, 3, 텍스처)
    │
    ├── install_name_tool로 dylib 의존성 추가
    │
    └── nwn_korean_hook.dylib 복사
         │
         ├── 로드 시 _AurGetTTFTexture 포인터 교체 (Phase 2)
         │
         └── nk_draw_text 후킹 (Phase 4)
```

### 후킹 방식

1. **함수 포인터 교체** (Phase 2)
   - `_AurGetTTFTexture` 포인터를 dylib 함수로 교체
   - 원본 함수 포인터 보존하여 호출

2. **dylib Interpose** (Phase 4)
   - `nk_draw_text` 심볼 인터포즈
   - Latin-1 → CP949 → UTF-8 변환

## 디버그 로그

```
/tmp/nwn_korean.log
```

## 참고: CP949 (KS X 1001)

완성형 한글 2350자:
- Lead byte: 0xB0~0xC8 (25개)
- Trail byte: 0xA1~0xFE (94개)
- 총: 25 × 94 = 2350자

## 바이너리 정보

- 대상: nwmain (Mach-O Universal, arm64)
- 버전: 8193.35+ (Steam Build 20277208)
- arm64 FAT 오프셋: 0x1700000
- 테스트 해시 (SHA256): `install.py`의 `SUPPORTED_HASHES` 참조

## 트러블슈팅

### dylib 로드 실패

1. Xcode Command Line Tools 설치 확인
2. `codesign --remove-signature nwmain` 후 재설치
3. 터미널에서 직접 실행하여 오류 메시지 확인

### 패치 후 크래시

1. Steam에서 게임 파일 무결성 검사
2. `python3 install.py --uninstall` 후 재설치
3. `/tmp/nwn_korean.log` 확인

### 한글이 표시되지 않음

1. `override/dialog.tlk` 확인
2. 폰트 파일 확인 (`fnt_*.ttf`)
3. dylib 로드 로그 확인
