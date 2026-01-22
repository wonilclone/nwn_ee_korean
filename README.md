# NWN:EE 한글 패치

Neverwinter Nights: Enhanced Edition 한글화 프로젝트입니다.

## 지원 플랫폼

| 플랫폼 | 상태 |
|--------|------|
| macOS (Apple Silicon) | ✅ 지원 |
| macOS (Intel) | ❌ 미지원 |
| Windows (64-bit) | ⚠️ 부분 지원 |

### 플랫폼별 지원 범위

| 기능 | macOS | Windows |
|------|-------|---------|
| 인게임 UI (대화, 저널 등) | ✅ | ✅ |
| 레거시 UI 버튼 텍스트 정렬 | ✅ | ⚠️ 치우침 |
| Nuklear UI (옵션, 모듈 선택) | ✅ | ❌ |

**Windows 제한 사항**:
- Nuklear UI에서 한글이 Latin-1로 깨져서 표시됨 (옵션 화면, 모듈 선택 화면)
- 레거시 UI 버튼에서 한글 글리프가 2바이트 너비로 계산되어 텍스트가 좌측으로 치우침
- 후킹 포인트 차이로 인해 macOS와 다른 접근 방식 필요

## 빠른 시작

### 릴리스 빌드

```bash
python3 build_release.py
```

빌드 결과물은 `release/` 디렉토리에 생성됩니다.

### 옵션

```bash
python3 build_release.py --mac       # macOS만 빌드
python3 build_release.py --windows   # Windows만 빌드
python3 build_release.py --debug     # 검수 모드 (StrRef 표시)
python3 build_release.py --skip-tlk  # TLK 빌드 건너뛰기
python3 build_release.py --zip v1.0  # 빌드 후 zip 압축
```

## 프로젝트 구조

```
├── build_release.py         # 릴리스 빌드 스크립트
├── fonts/                   # 폰트 소스 (별도 다운로드)
├── mac/                     # macOS 구현
│   ├── hook/                # dylib 소스
│   ├── scripts/             # 설치 스크립트
│   └── docs/                # 기술 문서
├── windows/                 # Windows 구현
│   ├── hook/                # DLL/로더 소스
│   └── scripts/             # 설치 스크립트
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
- Windows: Visual Studio 또는 MinGW (DLL/로더 빌드 시)

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

## 한글 자막 시네마틱 (선택)

인게임 시네마틱에 한글 자막을 추가한 HD 버전 영상 파일을 별도로 제공합니다.

**다운로드**: [Google Drive](https://drive.google.com/file/d/1XoF4CXkMQ93kP5BniN0K60wS_LBS2uDq/view?usp=sharing)

**설치 방법**:
1. 압축 파일 다운로드 및 해제
2. 영상 파일들을 다음 경로에 복사:
   - macOS: `~/Documents/Neverwinter Nights/movies/`
   - Windows: `문서\Neverwinter Nights\movies\`

## 기술 개요

- **인코딩**: CP949 (KS X 1001 완성형 한글 2,350자)
- **글리프**: ASCII 256 + 한글 2,350 = 2,606자
- **패치 방식**:
  - macOS: 바이너리 패치 + dylib 후킹
  - Windows: DLL 인젝션 + 런타임 후킹

## 저작권

Neverwinter Nights는 Beamdog의 상표입니다.
