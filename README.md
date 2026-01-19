# NWN:EE 한글 패치

Neverwinter Nights: Enhanced Edition 한글화 프로젝트입니다.

## 지원 플랫폼

| 플랫폼 | 상태 |
|--------|------|
| macOS (Apple Silicon) | ✅ 지원 |
| macOS (Intel) | ❌ 미지원 |
| Windows | 🚧 예정 |

## 빠른 시작

### 릴리스 빌드

```bash
python3 build_release.py
```

빌드 결과물은 `release/` 디렉토리에 생성됩니다.

### 옵션

```bash
python3 build_release.py --mac       # macOS만 빌드
python3 build_release.py --debug     # 검수 모드 (StrRef 표시)
python3 build_release.py --skip-tlk  # TLK 빌드 건너뛰기
```

## 프로젝트 구조

```
├── build_release.py         # 릴리스 빌드 스크립트
├── fonts/                   # 폰트 소스 (별도 다운로드)
├── mac/                     # macOS 구현
│   ├── hook/                # dylib 소스
│   ├── scripts/             # 설치 스크립트
│   └── README.md            # 개발 문서
├── translate/               # 번역 작업
│   ├── dialog_translated/   # 번역 CSV (수정 대상)
│   ├── editor.py            # Streamlit 번역 편집기
│   ├── merge_dialog_files.py # TLK 생성 스크립트
│   └── tools/               # 검사 도구
└── release/                 # 빌드 결과물 (gitignore)
```

## 요구 사항

- Python 3.10+
- macOS: Xcode Command Line Tools (`xcode-select --install`)

### 폰트

`fonts/` 디렉토리에 한글 TTF 폰트를 배치하세요. 권장: [Spoqa Han Sans Neo](https://spoqa.github.io/spoqa-han-sans/)

## 번역 수정

번역을 수정하려면 `translate/dialog_translated/` 디렉토리의 CSV 파일을 편집한 후 릴리스를 다시 빌드하세요.

`dialog.csv`는 자동 생성되는 중간 파일이므로 직접 수정하지 마세요.

### 번역 편집기

Streamlit 기반 웹 UI로 번역을 편집할 수 있습니다.

```bash
pip install streamlit
cd translate
streamlit run editor.py
```

기능:
- 파일별 또는 전체 검색
- StrRef로 특정 대사 검색
- 영어 원문과 한글 번역 비교
- 완성형(KS X 1001) 범위 외 한글 표시

## 기술 개요

- **인코딩**: CP949 (KS X 1001 완성형 한글 2,350자)
- **글리프**: ASCII 256 + 한글 2,350 = 2,606자
- **패치 방식**: 바이너리 패치 + dylib 후킹

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
