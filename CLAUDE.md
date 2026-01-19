# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Korean language patch for Neverwinter Nights: Enhanced Edition (NWN:EE). Supports macOS (Apple Silicon arm64) with Windows support planned. The patch implements CP949 encoding support, expands the font glyph table from 256 to 2,606 characters, and includes KS X 1001 complete form Hangul (2,350 characters).

## Project Structure

```
nwn_ee_korean/
├── build_release.py           # 릴리스 빌드 스크립트 (플랫폼 공통)
├── tlk_to_csv.py              # TLK → CSV 추출
├── csv_to_tlk.py              # CSV → TLK 변환 (CP949 인코딩)
│
├── translate/                  # 번역 인프라
│   ├── merge_dialog_files.py  # 분할 CSV 병합 및 TLK 생성
│   ├── dialog.csv             # 원본 영문 대화
│   ├── dialog_translated/     # 모듈별 번역 CSV (1000+ 파일)
│   └── tools/                 # 번역 검증 유틸리티
│
├── mac/                        # macOS 구현
│   ├── hook/                  # 바이너리 패치 구현
│   │   ├── Makefile           # dylib 빌드
│   │   ├── nwn_korean_hook.c  # 메인 dylib 소스
│   │   ├── apply_korean_patch.py  # 개발용 패치 스크립트
│   │   └── *.h                # CP949/KSX1001 테이블
│   ├── release/               # 설치 스크립트 소스
│   │   ├── install.py         # 사용자 설치 스크립트
│   │   └── README.md
│   └── docs/                  # 기술 문서
│
├── windows/                    # Windows 구현 (예정)
│
└── release/                    # 빌드 산출물 (git ignored)
    ├── mac/
    └── windows/
```

## Build Commands

### 릴리스 빌드 (프로젝트 루트)
```bash
python3 build_release.py              # 전체 빌드 (TLK + 플랫폼별)
python3 build_release.py --mac        # macOS만 빌드
python3 build_release.py --debug      # 검수 모드 TLK ([StrRef] 접두사)
python3 build_release.py --skip-tlk   # TLK 빌드 건너뛰기
```

### dylib 빌드 (mac/hook/)
```bash
make                    # Universal binary (x64 + arm64)
make clean              # 빌드 파일 제거
```

### 번역 작업 (translate/)
```bash
python3 merge_dialog_files.py         # CSV 병합 + TLK 생성
python3 tools/check_translation_progress.py  # 번역 진행률
python3 tools/validate_all_translations.py   # 품질 검증
```

### 개발용 패치 (mac/hook/)
```bash
python3 apply_korean_patch.py              # 패치 적용
python3 apply_korean_patch.py --restore    # 원본 복원
python3 apply_korean_patch.py --check      # 상태 확인
```

## Architecture

### Binary Patching (macOS arm64)

**Phase 1: Boundary Check** - Extends glyph boundary from 256 to 2,614 by patching `GetSymbolCoords`/`SetSymbolCoords`.

**Phase 2: Font Baking Hook** - dylib hooks `_AurGetTTFTexture` to expand character array to 2,606 (4096x4096 texture).

**Phase 3: CP949 Decoding** - Inline trampoline in TextOut loop converts CP949 2-byte sequences to glyph indices.

### Translation Pipeline
```
dialog.csv → dialog_translated/ → merge_dialog_files.py → dialog_kor_merged.tlk
```

## Technical Details

- **Encoding**: CP949 for Korean text, CP1252 fallback for English
- **Glyph Count**: 2,606 (ASCII 256 + Hangul 2,350)
- **Font**: Spoqa Han Sans Neo (별도 다운로드 필요, `/fonts/`에 배치)
- **Binary Offsets**: `mac/docs/OFFSETS.md`
