# NWN:EE 한글 번역 현황

## 1. NWN:EE 텍스트 저장 구조

NWN:EE의 텍스트는 세 가지 방식으로 저장된다.

### 1.1 TLK (Talk Table)

| TLK 파일 | StrRef 범위 | 용도 |
|----------|------------|------|
| `dialog.tlk` | 0 ~ 112,227 | 메인 게임 텍스트 (모든 모듈 공용) |
| 커스텀 TLK | 모듈별 지정 | 모듈 고유 추가 텍스트 |

### 1.2 인라인 텍스트 (CExoLocString)

- .dlg 파일 내부에 `StrRef=-1`로 직접 저장된 텍스트
- 프리미엄 모듈 대사의 **대부분**이 이 방식
- TLK를 거치지 않으므로 TLK 번역만으로는 커버 불가

### 1.3 리소스 로드 우선순위

```
override/          ← 최우선 (사용자 패치)
  ↓
module (.mod/.nwm)  ← 모듈 내부 리소스
  ↓
hak                ← 모듈 연결 HAK 파일
  ↓
patch / bif / key  ← 기본 게임 데이터
  ↓
dialog.tlk / custom tlk
```

같은 이름의 리소스가 여러 위치에 있으면 상위가 우선.
override에 .dlg를 넣으면 해당 대화가 교체됨.

## 2. dialog.tlk 번역 현황 (현재 한글패치 범위)

- **총 항목**: 112,228개 (StrRef 0 ~ 112,227)
- **번역 완료**: 104,525개
- **영문 유지 (의도적)**: ~3,030개 (고유명사, 태그, 내부 ID 등)
- **미번역 (플레이어에게 노출)**: ~190개
- **번역률**: 의도적 영문 유지 제외 시 ~99.8%

### 미번역 ~190개 상세 (translated.csv 내)

| 분류 | 수량 | 예시 StrRef |
|------|------|------------|
| SoU/HotU 대사 | ~45 | 75989-76063, 84770-86239, 94698-101079 |
| 오브젝트/크리처 설명 | ~100 | 9166, 110846-111700 |
| 시스템 메시지 | ~40 | 8838-8853, 110663-112063 |

### 의도적 영문 유지 (~3,030개)

| 분류 | 수량 |
|------|------|
| 짧은 고유명사 (10자 이하) | ~1,220 |
| 에셋 레이블 (타일, 크리처, 오브젝트) | ~500 |
| 기술 ID / 스크립트명 | ~230 |
| 툴셋 전용 문자열 (플레이어 비노출) | ~200 |
| 컴파일러 에러 메시지 | ~76 |
| UI/설정 메뉴 | ~150 |
| 기타 (개발자 노트, 스테이지 디렉션) | ~15 |

## 3. 프리미엄 모듈 전체 현황

### 3.1 모듈 파일 인벤토리

NWN 설치 경로: `~/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/`

#### 공식 캠페인 (.nwm)
| 모듈 | .dlg 수 | 텍스트 저장 방식 |
|------|---------|----------------|
| OC (Prelude ~ Chapter 4) | 7개 .nwm | dialog.tlk StrRef |
| SoU (XP1) | 3개 .nwm | dialog.tlk StrRef |
| HotU (XP2) | 3개 .nwm | dialog.tlk StrRef |

→ **dialog.tlk 번역으로 완전 커버됨**

#### 프리미엄 모듈 (.nwm + .hak)
| 모듈 | 제작사 | .dlg 수 | 인라인 텍스트 | dialog.tlk StrRef | 커스텀 TLK | HAK 파일 |
|------|-------|---------|-------------|------------------|-----------|----------|
| Dark Dreams of Furiae | Silverstring Media | 263 | 있음 | 있음 | 없음 | ddf |
| Darkness over Daggerford | Ossian Studios | 575 | **21,795개** | 2,283개 | ossian.tlk (190) | dodee_* (3개) |
| Infinite Dungeons | BioWare | 514 | 있음 | 있음 | 없음 | id_resources |
| Pirates of the Sword Coast | BioWare | 295 | 있음 | 있음 | 없음 | potsc_* (2개) |
| Tyrants of the Moonsea | Ossian Studios | 452 | **17,151개** | 3,018개 | tyrants.tlk (381) | tm_* (10개) |
| Wyvern Crown of Cormyr | DLA/BioWare | 263 | **13,094개** | 1,455개 | dla.tlk (354) | wc_* (7개) |

#### 무료 모듈 (.mod + .hak)
| 모듈 | .dlg 수 | HAK |
|------|---------|-----|
| Kingmaker | 234 | km_resources |
| ShadowGuard | 208 | sg_resources |
| Witch's Wake | 241 | ww_resources |
| Contest Of Champions | 10 | - |
| Neverwinter Chess | 13 | - |
| The Dark Ranger's Treasure | 21 | - |
| The Winds of Eremor | 50 | - |
| To Heir is Human | 9 | - |

#### 미설치 모듈
| 모듈 | 상태 |
|------|------|
| Doom of Icewind Dale (Creative Titan) | 미설치 (유료 DLC) |

### 3.2 .dlg 내부의 대화 저장 방식

프리미엄 모듈의 .dlg 파일은 두 가지 방식으로 텍스트를 참조한다:

```
.dlg (대화 트리 구조)
  ├── StrRef 참조 → dialog.tlk 또는 커스텀 TLK
  └── 인라인 텍스트 (StrRef=-1) → CExoLocString에 직접 저장
```

**공식 캠페인(OC/SoU/HotU)**: dialog.tlk StrRef만 사용 → TLK 번역으로 완전 커버
**프리미엄 모듈**: 인라인 텍스트가 대부분 → .dlg 파일 자체를 교체해야 함

### 3.3 커스텀 TLK 상세

#### ossian.tlk — Darkness over Daggerford
- **항목 수**: 190개 (StrRef 0-190)
- 동료 NPC 전투 대사/함성 (~100개)
- 지역/음악 이름 (~20개)
- 아이템 이름/설명 (~20개)
- 로딩 화면 팁 (4개), NPC 이름 (~15개)

#### tyrants.tlk — Tyrants of the Moonsea
- **항목 수**: 381개 (StrRef 5-505, 나머지 ~49,600개는 빈 패딩)
- 타일셋/문 레이블 (~65개)
- 배치물/크리처 이름 (~215개)
- 로딩 화면 팁 (6개)
- 아이템/게임 메커니즘 설명 (9개)

#### dla.tlk — Wyvern Crown of Cormyr
- **항목 수**: 354개 (StrRef 20100-27240)
- 종족/아종족 설명 (18개): DragonLance 종족
- 기승 시스템 (109개): 말 기승 특기/외형
- Purple Dragon Knight 클래스 (83개): 클래스/특기/스킬 설명
- 서적/저널/로어 (126개): 장문 텍스트
- DragonLance 특기 (14개), 플레이스홀더 (8개)

#### dla_bio.tlk — 스텁 파일 (무시 가능)
- 4개: "BadStrref", "Seagull", "seagull", "Seagulls"

## 4. 추가 번역 작업 요약

### 작업 A: dialog.tlk 미번역 항목 (~190개)
- 난이도: 낮음
- 방법: 기존 파이프라인 (translated.csv 편집 → TLK 빌드)
- 내용: SoU/HotU 대사 누락분, 오브젝트 설명, 시스템 메시지

### 작업 B: 커스텀 TLK 번역 (~925개)
- 난이도: 낮음
- 방법: TLK → CSV 추출 → 번역 → CSV → TLK 빌드
- 배포: `data/tlk/` 디렉토리에 배치 (override가 아님)

| 파일 | 항목 수 | 내용 |
|------|---------|------|
| dla.tlk | 354 | 클래스 설명, 서적, 기승 시스템 (장문 다수) |
| tyrants.tlk | 381 | 타일셋 레이블, 크리처 이름, 로딩 팁 |
| ossian.tlk | 190 | 전투 대사, NPC 이름, 지역명 |

### 작업 C: 프리미엄 모듈 인라인 텍스트 (대규모)
- 난이도: **높음**
- 예상 규모: **52,000개 이상** (Daggerford 21,795 + Tyrants 17,151 + Wyvern 13,094 + 기타)
- 방법:
  1. .nwm/.hak에서 .dlg 추출 (ERF 포맷 파싱)
  2. .dlg 내 CExoLocString 인라인 텍스트 추출
  3. 번역 작업
  4. 번역된 텍스트를 .dlg에 다시 삽입
  5. 번역된 .dlg를 override에 배치
- 필요 도구: ERF 파서, GFF/DLG 파서 (xoreos-tools 또는 자체 구현)
- 추가 고려: .dlg 외에도 .uti(아이템), .utc(크리처), .utp(배치물), .jrl(저널) 등에도 인라인 텍스트 존재

### 작업 D: 미설치 모듈 확인
- Doom of Icewind Dale 구매 후 구조 확인

## 5. 기술 참고

### 파일 위치
```
NWN 설치: ~/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/
커스텀 TLK: data/tlk/
모듈: data/nwm/ (공식), data/mod/ (무료)
HAK: data/hk/
override: override/
```

### 기존 번역 파이프라인 (dialog.tlk / 커스텀 TLK)
```bash
python3 tlk_to_csv.py <input.tlk> <output.csv>    # TLK → CSV
# CSV 번역 작업
python3 csv_to_tlk.py <input.csv> <output.tlk>    # CSV → TLK
```

### 프리미엄 모듈 인라인 텍스트 파이프라인 (신규 구축 필요)
```
.nwm/.hak (ERF)
  → .dlg/.uti/.utc/.utp/.jrl 추출
    → CExoLocString 인라인 텍스트 추출
      → CSV로 변환 → 번역
        → .dlg 등에 번역 텍스트 삽입
          → override/ 에 배치
```

### 관련 도구
- **xoreos-tools**: `tlk2xml`, `xml2tlk`, `gff2xml`, `xml2gff` 등 GFF/TLK 변환
- **NWN Explorer**: GUI 기반 ERF/GFF 뷰어
- **neverwinter.nim (nwn_resman, nwn_gff)**: Nim 기반 CLI 도구
- **자체 Python 스크립트**: ERF/GFF 파서 직접 구현 가능 (포맷 공개)
