# NWN:EE Android 한글 패치

Android (arm64) 버전의 Neverwinter Nights: Enhanced Edition에 한글을 지원하기 위한 바이너리 패치입니다.

> **주의**: 이 디렉토리에는 APK나 .so 바이너리 파일이 포함되어 있지 않습니다.
> 사용자가 직접 APK를 준비하고, 여기 포함된 스크립트로 패치를 적용해야 합니다.

> **면책 조항**: 이 스크립트는 개인 사용 목적으로 작성되었습니다.
> APK 변조 및 재서명은 게임의 이용약관(EULA/ToS)에 위배될 수 있으며,
> 사용에 따른 법적 책임은 전적으로 사용자에게 있습니다.
> 반드시 정품을 구매한 상태에서 사용하시기 바랍니다.

## 빠른 시작

APK 하나만 있으면 됩니다:

```bash
python3 build_patched_apk.py <원본APK>.apk
```

이 명령으로 .so 추출 → 패치 → 리패키징 → 서명이 한 번에 수행됩니다.
결과물: `NWN-EE-korean-signed.apk`

기기 설치까지 한 번에:
```bash
python3 build_patched_apk.py <원본APK>.apk --install
```

### 사전 요구 사항

- Python 3.10+
- Android SDK build-tools (`zipalign`, `apksigner`)
  ```bash
  # Android Studio 설치 시 자동 포함, 또는:
  sdkmanager "build-tools;35.0.0"
  ```
- 디버그 키스토어 (최초 1회 생성):
  ```bash
  keytool -genkey -v -keystore ~/.android/debug.keystore \
    -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass android -keypass android \
    -dname "CN=Android Debug,O=Android,C=US"
  ```

> 디버그 키스토어로 서명하면 원본 APK와 서명이 다르므로,
> 기존에 Play Store에서 설치한 앱은 삭제 후 재설치해야 합니다.

## 패치 구조

Android 버전은 macOS/Windows와 동일한 NWN:EE 엔진(`libnwmain.so`, arm64)을 사용하므로
패치 구조도 동일합니다:

| Phase | 내용 | 설명 |
|-------|------|------|
| Phase 1 | 경계 체크 확장 | GetSymbolCoords/SetSymbolCoords 글리프 경계 255 → 2613 |
| Phase 2 | 폰트 베이킹 확장 | CAuroraTTFTexture::Load 글리프 배열 256 → 2606 |
| Phase 3 | CP949 디코더 | TextOut 루프에 inline trampoline 삽입 |
| Phase 3b | Width/Caret CP949 | 문자열 폭 계산/커서 위치에도 CP949 디코딩 적용 |
| Phase 4 | Nuklear UI 훅 | nk_draw_text CP949/Latin-1 → UTF-8 변환 |
| Texture | 텍스처 확장 | 4096x4096, 글리프 패딩 3 → 16 |

## 스크립트 구성

| 스크립트 | 역할 |
|----------|------|
| `build_patched_apk.py` | 올인원 (추출 → 패치 → 리패키징 → 서명) |
| `patch_libnwmain.py` | arm64 바이너리 패치 단독 실행 |
| `repackage_apk.py` | APK 리패키징 + 서명 단독 실행 |

### build_patched_apk.py (권장)

```bash
python3 build_patched_apk.py <원본APK>.apk              # 기본
python3 build_patched_apk.py <원본APK>.apk --install     # 기기 설치까지
python3 build_patched_apk.py <원본APK>.apk -o out.apk    # 출력 경로 지정
python3 build_patched_apk.py <원본APK>.apk --keystore <path>  # 키스토어 지정
```

### patch_libnwmain.py (단독)

```bash
python3 patch_libnwmain.py              # 패치 적용 (libnwmain.so → libnwmain_patched.so)
python3 patch_libnwmain.py --check      # 패치 상태 확인
python3 patch_libnwmain.py --restore    # 원본 복원
```

### repackage_apk.py (단독)

```bash
python3 repackage_apk.py --apk <APK> --so <패치된.so>   # 리패키징 + 서명
python3 repackage_apk.py --apk <APK> --patch             # 패치부터 수행
python3 repackage_apk.py --install                        # 설치까지 수행
```

## TLK 파일 (번역 데이터)

패치된 APK를 실행하려면 한글 번역 TLK 파일도 필요합니다.

```bash
# 프로젝트 루트에서:
cd translate
python3 merge_dialog_files.py
```

생성된 `dialog_kor_merged.tlk`와 한글 폰트 파일을 기기에 복사합니다:

```bash
OVERRIDE=/sdcard/Android/data/com.beamdog.nwnandroid/files/user/override

# override 디렉토리 생성 (없는 경우)
adb shell mkdir -p $OVERRIDE

# TLK 복사
adb push dialog_kor_merged.tlk $OVERRIDE/dialog.tlk

# 폰트 복사 (3개 모두 필요)
adb push fnt_default.ttf $OVERRIDE/fnt_default.ttf
adb push fnt_default_hr.ttf $OVERRIDE/fnt_default_hr.ttf
adb push fnt_maintext.ttf $OVERRIDE/fnt_maintext.ttf
```

폰트 파일이 없으면 한글 글리프가 렌더링되지 않습니다.
macOS/Windows 릴리스 빌드(`release/mac/override/`)에 동일한 폰트 파일이 포함되어 있습니다.

## 대상 바이너리 버전

현재 패치 오프셋은 특정 빌드 버전(`v8193A00013`)에 맞춰져 있습니다.
다른 버전의 APK에서는 오프셋이 달라 패치가 실패할 수 있습니다.

패치 스크립트는 각 오프셋의 원본 바이트를 검증하므로,
불일치 시 에러 메시지로 알려줍니다.

## 제한 사항

- arm64 전용 (32-bit arm은 미지원)
- 특정 APK 빌드 버전에 종속 (오프셋 하드코딩)
- 디버그 키스토어 서명으로 인해 Play Store 업데이트와 호환 불가
- 한글 폰트 파일 3개를 override 디렉토리에 별도 배치 필요

### 오리지널 캠페인 프롤로그 일부 영문 표시

Android 버전은 오리지널 캠페인(OC)의 프롤로그 챕터에서 PC/macOS와 다른 모듈을 사용합니다.
(터치 조작에 맞춘 별도 튜토리얼 모듈)
이 모듈의 일부 대사는 `dialog.tlk`가 아닌 모듈 내부에 포함된 별도 문자열을 참조하기 때문에,
TLK 교체만으로는 번역이 적용되지 않아 영문으로 표시됩니다.
주로 튜토리얼 안내 문구와 NPC 이름 정도이며, 스토리 대사 대부분은 한글로 표시됩니다.
프롤로그 이후 챕터부터는 모든 텍스트가 정상적으로 한글이 표시됩니다.
