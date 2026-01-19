# NWN:EE 한글 패치 (macOS)

Neverwinter Nights: Enhanced Edition macOS용 한글 패치입니다.

## 지원 환경

- Mac (Apple Silicon: M1, M2, M3, M4 칩)
- Steam 버전 NWN:EE

Intel Mac은 지원하지 않습니다.

---

## 설치 방법

### 1단계: 터미널 열기

1. `Cmd + Space`를 눌러 Spotlight 검색 열기
2. "터미널" 입력 후 Enter

### 2단계: 다운로드 폴더로 이동

터미널에 아래 명령어를 복사하여 붙여넣고 Enter:

```
cd ~/Downloads/mac
```

만약 다른 위치에 압축을 풀었다면 해당 경로로 이동하세요.

### 3단계: 설치 실행

터미널에 아래 명령어를 복사하여 붙여넣고 Enter:

```
python3 install.py
```

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

---

## 포함 파일

```
mac/
├── install.py              # 설치 프로그램
├── nwn_korean_hook.dylib   # 한글 처리 파일
├── README.md               # 이 파일
└── override/
    ├── dialog.tlk          # 한글 대사 파일
    └── fnt_*.ttf           # 한글 폰트
```

---

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
