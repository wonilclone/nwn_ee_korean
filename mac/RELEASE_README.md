# NWN:EE 한글 패치 (macOS)

Neverwinter Nights: Enhanced Edition macOS용 한글 패치입니다.

## 지원 환경

- macOS (Apple Silicon: M1, M2, M3, M4 칩)
- Steam 버전 NWN:EE

Intel Mac은 지원하지 않습니다.

## 지원 범위

| 기능 | 상태 |
|------|------|
| 인게임 UI (대화, 저널 등) | ✅ 지원 |
| 레거시 UI 버튼 텍스트 | ✅ 지원 |
| Nuklear UI (옵션, 모듈 선택) | ✅ 지원 |

---

## 설치 방법

### 1단계: 압축 해제

다운로드한 zip 파일을 원하는 위치에 압축 해제합니다.

### 2단계: 터미널 열기

1. `Cmd + Space`를 눌러 Spotlight 검색 열기
2. "터미널" 입력 후 Enter

### 3단계: 설치 실행

터미널에 아래 명령어를 복사하여 붙여넣고 Enter:

```
cd ~/Downloads/mac
python3 install.py
```

만약 다른 위치에 압축을 풀었다면 해당 경로로 이동하세요.

설치가 완료되면 "설치 완료!" 메시지가 표시됩니다.

### 4단계: 게임 실행

Steam에서 NWN:EE를 실행하면 한글이 적용됩니다.

---

## 패치 제거

### 방법 1: 제거 스크립트 사용

터미널에서:

```
cd ~/Downloads/mac
python3 install.py --uninstall
```

### 방법 2: Steam에서 복구

1. Steam 라이브러리에서 NWN:EE 우클릭
2. "속성" 클릭
3. "설치된 파일" 탭 선택
4. "게임 파일 무결성 검사" 클릭

---

## 문제 해결

### "NWN:EE를 찾을 수 없습니다" 오류

Steam 버전이 아니거나 기본 경로에 설치되지 않은 경우입니다.

**해결 방법:**
1. `install.py` 파일을 텍스트 편집기로 열기
2. 상단의 `NWN_DIR = ` 줄을 찾기
3. 실제 게임 설치 경로로 수정

### 게임이 실행되지 않음

1. Finder에서 게임 폴더로 이동:
   `/Users/사용자명/Library/Application Support/Steam/steamapps/common/Neverwinter Nights`
2. `bin/macos` 폴더 안의 `nwmain` 파일 삭제
3. Steam에서 "게임 파일 무결성 검사" 실행 (원본 nwmain 복구됨)
4. 다시 `python3 install.py` 실행

### 한글이 깨져 보임

터미널에서 설치 상태 확인:

```
python3 install.py --check
```

"패치 적용됨"이 표시되어야 합니다.

---

## 포함 파일

```
mac/
├── install.py              # 설치 스크립트
├── nwn_korean_hook.dylib   # 한글 처리 라이브러리
├── README.md               # 이 파일
└── override/
    ├── dialog.tlk          # 한글 대사 파일
    └── fnt_*.ttf           # 한글 폰트
```

---

## 기술 정보

이 패치는 다음과 같은 방식으로 동작합니다:

1. **바이너리 패치**: nwmain에 CP949 한글 디코딩 코드 삽입
2. **dylib 후킹**: 폰트 베이킹 시 한글 글리프 추가
3. **리소스 교체**: 한글 TLK 파일 및 폰트 설치

### 적용되는 패치

- Phase 1: GetSymbolCoords/SetSymbolCoords 경계 체크 확장 (255→2613)
- Phase 2: AurGetTTFTexture 후킹으로 한글 글리프 베이킹 (dylib)
- Phase 3: TextOut 내 CP949 2바이트 디코더
- Texture: 4096x4096 텍스처 크기 확장
- Glyph Padding: 글리프 간 여백 증가 (문자 침범 방지)
- Nuklear UI: EE UI 한글 글리프 범위 패치

---

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
