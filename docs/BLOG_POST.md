# Neverwinter Nights: Enhanced Edition 한글 패치

최신 NWN:EE (빌드 8193.35+)에서 동작하는 한글 패치를 배포합니다.

기존 한글 패치가 게임 업데이트로 인해 더 이상 작동하지 않아 제작했습니다. TLK 번역도 전면 재작업하여 자연스러운 한국어 표현으로 개선했습니다. 다만 개인작업이라 검수가 충분치 않은점은 양해 부탁드립니다.

## 다운로드

**GitHub 릴리스**: https://github.com/wonilclone/nwn_ee_korean/releases

| 플랫폼 | 파일 | 상태 |
|--------|------|------|
| macOS (Apple Silicon) | nwn-ee-korean-mac.zip | ✅ 완전 지원 |
| Windows (64-bit) | nwn-ee-korean-windows.zip | ⚠️ 부분 지원 |

## 지원 환경

- **macOS**: Apple Silicon (M1, M2, M3, M4) + Steam 버전
- **Windows**: Windows 10/11 64-bit + Steam 버전

Intel Mac은 지원하지 않습니다.

## 설치 방법

### macOS

1. zip 파일 압축 해제
2. 터미널 열기 (`Cmd + Space` → "터미널" 입력)
3. 압축 해제한 폴더로 이동 후 설치 스크립트 실행:

```bash
cd ~/Downloads/mac
python3 install.py
```

4. Steam에서 NWN:EE 실행

### Windows

1. zip 파일 압축 해제
2. `install.exe` 더블클릭
3. 게임 실행 방법 선택:
   - **방법 A**: 게임 폴더의 `nwn_korean_loader.exe` 실행
   - **방법 B** (권장): Steam 시작 옵션 설정
     1. Steam 라이브러리 → NWN:EE 우클릭 → 속성
     2. 시작 옵션에 입력:
     ```
     "C:\Program Files (x86)\Steam\steamapps\common\Neverwinter Nights\bin\win32\nwn_korean_loader.exe" %command%
     ```

## Windows 알려진 제한 사항

| 기능 | 상태 |
|------|------|
| 인게임 UI (대화, 저널 등) | ✅ 정상 |
| Nuklear UI (옵션, 모듈 선택) | ❌ 한글 깨짐 |
| 레거시 UI 버튼 텍스트 | ⚠️ 좌측으로 치우침 |

옵션 화면과 모듈 선택 화면에서 한글이 깨져 보이는 현상이 있습니다. 인게임 플레이에는 영향이 없으며, 향후 업데이트에서 개선할 예정입니다.

## 패치 제거

### macOS

```bash
python3 install.py --uninstall
```

### Windows

```
install.exe --uninstall
```

또는 Steam에서 "게임 파일 무결성 검사"를 실행하면 원본으로 복구됩니다.

## 한글 자막 시네마틱 (선택)

인트로 등 시네마틱 영상에 한글 자막을 추가한 HD 버전을 별도로 제공합니다.

**다운로드**: [Google Drive](https://drive.google.com/file/d/1XoF4CXkMQ93kP5BniN0K60wS_LBS2uDq/view?usp=sharing)

**설치 방법**:
1. 압축 파일 다운로드 및 해제
2. 영상 파일들을 다음 경로에 복사:
   - macOS: `~/Documents/Neverwinter Nights/movies/`
   - Windows: `문서\Neverwinter Nights\movies\`

## 기술 정보

- **대상 버전**: NWN:EE 빌드 8193.35+ (Steam)
- **인코딩**: CP949 (KS X 1001 완성형 한글 2,350자)
- **패치 방식**:
  - macOS: 바이너리 패치 + dylib 후킹
  - Windows: 바이너리 패치 + DLL 인젝션

## 문제 해결

### "NWN:EE를 찾을 수 없습니다" 오류

Steam 기본 경로에 설치되지 않은 경우 발생합니다. 수동 설치가 필요하며, 자세한 내용은 zip 파일 내 README를 참조하세요.

### 게임이 실행되지 않거나 크래시

1. Steam에서 "게임 파일 무결성 검사" 실행
2. 패치 재설치

### 한글이 표시되지 않음

설치 상태 확인:
```bash
# macOS
python3 install.py --check

# Windows
install.exe --check
```

## 소스 코드

https://github.com/wonilclone/nwn_ee_korean

오역이나 사용중 다른 이슈가 있으면 말씀해 주세요.

---

Neverwinter Nights는 Beamdog의 상표입니다.
