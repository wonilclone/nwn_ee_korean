# NWN:EE 한글 패치 (Windows)

Neverwinter Nights: Enhanced Edition Windows용 한글 패치입니다.

## 지원 환경

- Windows 10/11 64-bit
- Steam 버전 NWN:EE

---

## 설치 방법

### 1단계: 압축 해제

다운로드한 zip 파일을 원하는 위치에 압축 해제합니다.

### 2단계: 설치 프로그램 실행

`install.py`를 더블클릭하거나, 명령 프롬프트에서 실행:

```
cd 압축해제한폴더\windows
python install.py
```

Python이 설치되어 있지 않다면:
1. [python.org](https://www.python.org/downloads/)에서 Python 3.x 다운로드
2. 설치 시 "Add Python to PATH" 체크
3. 다시 install.py 실행

### 3단계: 게임 실행

**방법 1: 로더로 직접 실행**

게임 폴더의 `nwn_korean_loader.exe`를 실행합니다:
```
C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32\nwn_korean_loader.exe
```

**방법 2: Steam 시작 옵션 설정 (권장)**

1. Steam 라이브러리에서 NWN:EE 우클릭
2. "속성" 클릭
3. "일반" 탭에서 "시작 옵션"에 입력:
```
"C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32\nwn_korean_loader.exe" %command%
```
4. Steam에서 게임을 실행하면 자동으로 한글 패치가 적용됩니다

---

## 패치 제거

### 방법 1: 제거 스크립트 사용

명령 프롬프트에서:

```
cd 압축해제한폴더\windows
python install.py --uninstall
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
1. `install.py` 파일을 메모장으로 열기
2. 상단의 `NWN_DIR = ` 줄을 찾기
3. 실제 게임 설치 경로로 수정

### 게임이 크래시됨

1. Steam에서 "게임 파일 무결성 검사" 실행
2. 패치를 다시 설치: `python install.py`

### 한글이 깨져 보임

설치 상태 확인:

```
python install.py --check
```

"패치 적용됨"이 표시되어야 합니다.

### 로더 실행 시 "DLL을 찾을 수 없습니다" 오류

`nwn_korean_hook.dll`이 게임 폴더에 있는지 확인하세요:
```
C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32\nwn_korean_hook.dll
```

---

## 포함 파일

```
windows/
├── install.py              # 설치 프로그램
├── nwn_korean_hook.dll     # 한글 처리 DLL
├── nwn_korean_loader.exe   # 게임 로더
├── README.md               # 이 파일
└── override/
    ├── dialog.tlk          # 한글 대사 파일
    └── fnt_*.ttf           # 한글 폰트
```

---

## 기술 정보

이 패치는 다음과 같은 방식으로 동작합니다:

1. **바이너리 패치**: nwmain.exe에 CP949 한글 디코딩 코드 삽입
2. **DLL 인젝션**: 폰트 베이킹 시 한글 글리프 추가
3. **리소스 교체**: 한글 TLK 파일 및 폰트 설치

### 적용되는 패치

- Phase 1: GetSymbolCoords/SetSymbolCoords 경계 체크 확장 (255→2613)
- Phase 2: AurGetTTFTexture 후킹으로 한글 글리프 베이킹 (DLL)
- Phase 3: TextOut 내 CP949 2바이트 디코더
- Texture: 4096x4096 텍스처 크기 확장
- Glyph Padding: 글리프 간 여백 증가 (문자 침범 방지)
- Nuklear: EE UI 한글 글리프 범위 패치

---

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
