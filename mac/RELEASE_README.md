# NWN:EE 한글 패치 (macOS Apple Silicon)

Neverwinter Nights: Enhanced Edition의 macOS Apple Silicon(M1/M2/M3/M4) 버전용 한글 패치입니다.

## 요구 사항

- macOS (Apple Silicon / arm64)
- Neverwinter Nights: Enhanced Edition (Steam 버전)
- Python 3

## 설치 방법

터미널에서 이 폴더로 이동 후 다음 명령 실행:

```bash
python3 install.py
```

설치 스크립트가 자동으로:
1. 게임 바이너리 패치
2. dylib 설치
3. TLK 및 폰트 파일 복사

## 패치 제거

```bash
python3 install.py --uninstall
```

또는 Steam에서 "게임 파일 무결성 검사"를 실행하세요.

## 상태 확인

```bash
python3 install.py --check
```

## 포함 파일

```
├── install.py              # 설치 스크립트
├── nwn_korean_hook.dylib   # 한글 처리 라이브러리
├── README.md               # 이 파일
└── override/
    ├── dialog.tlk          # 한글 TLK
    └── fnt_*.ttf           # 한글 폰트
```

## 문제 해결

### "NWN:EE를 찾을 수 없습니다"

Steam 버전이 아니거나 다른 경로에 설치된 경우입니다.
`install.py`를 열어 `NWN_DIR` 경로를 수정하세요.

### 게임이 실행되지 않음

1. Steam에서 "게임 파일 무결성 검사" 실행
2. 다시 `python3 install.py` 실행

### 한글이 깨져 보임

`python3 install.py --check`로 설치 상태를 확인하세요.

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
