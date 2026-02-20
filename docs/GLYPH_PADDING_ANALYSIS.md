# 글리프 패딩 분석 — UI 스케일에 따른 글리프 번짐(bleeding) 해결

## 요약

NWN:EE 한글 패치에서 폰트 아틀라스에 2,606개 글리프를 베이크할 때, `stbtt_PackBegin`의 padding 파라미터가 부족하면 UI 스케일을 올렸을 때 인접 글리프의 텍셀이 번져 보이는 현상이 발생한다. 이 문서는 Android에서의 분석 과정과 해결 방법을 기록하며, 다른 플랫폼(macOS, Windows, Linux)에도 적용 가능하다.

---

## 증상

- **저스케일 (100%)**: padding=3(원본) → 글리프 간 번짐 발생
- **저스케일 + padding=16**: 번짐 해소
- **고스케일 (150%~200%) + padding=16**: 번짐 재발 (수직/수평 방향 모두)
- **고스케일 + padding=48**: 번짐 완전 해소

번짐 패턴: 글리프 경계에서 인접 글리프의 픽셀이 얇은 선 형태로 보임.

---

## 원인 분석

### stbtt_PackBegin의 padding 동작

```c
// stb_truetype.h
int stbtt_PackBegin(stbtt_pack_context *spc,
                    unsigned char *pixels,
                    int width, int height,
                    int stride_in_bytes,
                    int padding,          // ← 이 값
                    void *alloc_context);
```

`padding` 파라미터는 아틀라스에서 각 글리프 주위에 padding/2 픽셀의 여백을 추가한다:
- padding=3 → 글리프당 1.5px 여백 (원본)
- padding=16 → 글리프당 8px 여백
- padding=48 → 글리프당 24px 여백

### 왜 bilinear filtering만으로는 설명이 안 되는가

표준 bilinear 텍스처 필터링은 인접 텍셀로부터 최대 0.5 텍셀 거리까지만 샘플링한다. 4096×4096 텍스처에서 0.5 텍셀은 겨우 0.012%이므로, padding=3(1.5px)이면 이론적으로 충분해야 한다.

그러나 NWN:EE 엔진은 텍스트 렌더링 시 추가적인 효과를 적용하는 것으로 추정된다:
- **텍스트 그림자(shadow)**: 오프셋된 위치에 텍스트를 한 번 더 렌더링
- **텍스트 윤곽선(outline/glow)**: 주변 픽셀을 샘플링하는 후처리 효과

이러한 효과가 적용되면 실질적인 샘플링 범위가 bilinear의 0.5 텍셀을 훨씬 넘어간다.

### UI 스케일과의 관계

UI 스케일을 올리면 아틀라스 텍스처가 확대되면서:
1. 1 화면 픽셀이 아틀라스에서 차지하는 범위가 줄어듦 (샘플 밀도 증가)
2. 그림자/윤곽선의 오프셋이 텍셀 단위로 고정되어 있으므로, 스케일이 커질수록 인접 글리프 영역까지 닿는 비율이 높아짐
3. padding이 부족하면 그림자/윤곽선 샘플링 시 인접 글리프 데이터를 읽게 됨

---

## 시도한 접근법

### 1. UV half-texel inset (실패)

GetSymbolCoords가 반환하는 UV 좌표를 0.5/4096 만큼 안쪽으로 축소하는 래퍼를 ARM64 코드 케이브에 구현.

```
원본 UV: [u0, v0, u1, v1]
수정 UV: [u0 + 0.5/4096, v0 + 0.5/4096, u1 - 0.5/4096, v1 - 0.5/4096]
```

**결과**: 효과 없음. UV 정밀도 문제가 아니라 아틀라스 자체의 패딩 부족이 원인이었다.

**교훈**: UV inset은 bilinear filtering에 의한 경계 샘플링에만 유효하며, 엔진 측 후처리(그림자/윤곽선) 효과로 인한 넓은 범위의 번짐에는 도움이 되지 않는다.

### 2. 오버샘플링 (실패, macOS에서 테스트)

`stbtt_PackSetOversampling(2, 2)` 적용:

```asm
; macOS 0xc56cc
movi.2s v0, #1  →  movi.2s v0, #2   ; h_oversample=2, v_oversample=2
```

**결과**: 글리프 크기가 2배로 표시됨. NWN:EE 엔진이 오버샘플링에 대한 스케일 보정 로직을 갖고 있지 않기 때문에 발생.

### 3. Ascent margin 조정 (실패, macOS에서 테스트)

```asm
; macOS 0xc57f0
fmov s12, #0.5  →  fmov s12, #2.0   ; ascent margin 증가
```

**결과**: 크래시 발생. 이후 분석에서 이 0.5 값이 ascent margin이 아니라 `fmadd → fcvtzu` 시퀀스의 **반올림 오프셋**임을 확인:

```asm
fmov  s2, #0.5        ; 반올림용 0.5
fmadd s0, s1, s0, s2  ; s0 = ascent * scale + 0.5
fcvtzu w8, s0          ; w8 = (unsigned int)s0   ← floor(x + 0.5) = round(x)
```

### 4. padding 증가 (성공)

`stbtt_PackBegin`에 전달되는 padding 값을 48로 증가:

```asm
; 원본:  mov w5, #3   →  0x65008052
; 패치:  mov w5, #48  →  0x05068052
```

**결과**: 고스케일에서도 번짐 완전 해소.

---

## 패딩 값별 공간 분석

4096×4096 아틀라스에 2,606개 글리프를 배치할 때:

| padding | 글리프당 여백 | 예상 가용 면적 | 상태 |
|---------|-------------|--------------|------|
| 3 (원본) | 1.5px | ~16M px² | 번짐 발생 |
| 16 | 8px | ~14M px² | 저스케일 OK, 고스케일 번짐 |
| 48 | 24px | ~10M px² | 모든 스케일 OK |

padding=48에서도 4096×4096 텍스처에 2,606개 글리프가 모두 수용된다. 글리프당 실질 셀 크기가 충분히 크기 때문이다.

---

## 플랫폼별 현황

### 텍스처 크기 및 패딩 비교

| 플랫폼 | 아키텍처 | 텍스처 크기 | 현재 padding | 최대 UI 스케일 | 상태 |
|--------|---------|-----------|-------------|--------------|------|
| Android | arm64 | 4096×4096 | **48** | 1.5× | 해결 완료 |
| macOS | arm64 | 4096×4096 | 16 | ? | 48로 상향 필요 |
| Windows | x86-64 | 4096×4096 | 16 | 1.5× 이상 가능 | 48로 상향 필요 |
| Linux | x86-64 | 분석 필요 | 분석 필요 | ? | — |

모든 플랫폼이 동일한 4096×4096 아틀라스를 사용하므로, padding=48로 통일해도 글리프 수용에 문제없다. Windows 등 UI 스케일을 1.5× 이상으로 올릴 수 있는 플랫폼에서는 padding=48이 특히 중요하며, 추가 여유를 확보하려면 플랫폼별 최대 스케일에 맞춰 패딩을 더 높이는 것도 고려할 수 있다.

> **권장사항**: 모든 플랫폼에서 padding=48을 기본값으로 통일. 텍스처 크기가 동일하므로 공간 문제 없음.

### 패치 위치 상세

#### Android (arm64, libnwmain.so) — 적용 완료

```python
{
    'offset': 0xa95564,
    'original': bytes.fromhex('65008052'),  # mov w5, #3
    'patched': bytes.fromhex('05068052'),   # mov w5, #48
}
```

#### macOS (arm64, nwmain) — 현재 16, 상향 필요

```python
{
    'offset': 0xc56c0,
    'original': bytes.fromhex('65008052'),  # mov w5, #3
    'patched': bytes.fromhex('05068052'),   # mov w5, #48   ← 현재 05028052(#16), 상향 필요
}
```

#### Windows (x86-64, nwmain.exe) — 현재 16, 상향 필요

```python
{
    'offset': 0x000fac80,
    # mov qword ptr [rbp-0x44], 3  →  mov qword ptr [rbp-0x44], 48
    'original': bytes.fromhex('48c745bc03000000'),  # padding = 3
    'patched': bytes.fromhex('48c745bc30000000'),   # padding = 48 (0x30)
    # 참고: 현재 코드는 0x10(=16)으로 패치 중, 0x30(=48)으로 변경 필요
}
```

#### Linux (x86-64, nwmain-linux) — 분석 필요

`CAuroraTTFTexture::LoadFromTTF` (VA `0x4875b0`) 내에서 `stbtt_PackBegin` 호출 직전의 padding 인자 설정 위치를 찾아야 함. System V AMD64 ABI에서 6번째 정수 인자(padding)는 `r9` 레지스터로 전달.

---

## 명령어 인코딩 참고

### ARM64: `mov w5, #imm` (MOVZ)

```
MOVZ Wd, #imm16, LSL #shift
31 30 29 28 27 26 25 24 23 22 21 ← 16 15 ← 5 4 ← 0
 0  1  0  1  0  0  1  0  1  hw     imm16        Rd

mov w5, #3  → 0x65008052   (imm16=3,    Rd=5)
mov w5, #16 → 0x05028052   (imm16=16,   Rd=5)
mov w5, #48 → 0x05068052   (imm16=48,   Rd=5)
```

### x86-64: `mov qword ptr [rbp-0x44], imm32`

```
48 C7 45 BC XX 00 00 00

padding=3:   48 C7 45 BC 03 00 00 00
padding=16:  48 C7 45 BC 10 00 00 00
padding=48:  48 C7 45 BC 30 00 00 00
```

---

## 결론

1. NWN:EE의 글리프 번짐은 UV 좌표 정밀도가 아닌 **아틀라스 패딩 부족**이 근본 원인
2. 엔진의 텍스트 그림자/윤곽선 효과가 bilinear filtering 범위를 넘어서는 샘플링을 유발
3. UI 스케일이 높을수록 더 넓은 패딩이 필요
4. **padding=48**이 Android(최대 1.5× 스케일)에서 안정적으로 동작함을 확인
5. Windows 등 1.5× 이상 스케일을 지원하는 플랫폼에서는 padding=48 이상이 필요할 수 있음
6. 모든 플랫폼의 아틀라스가 4096×4096으로 동일하므로 **padding=48 통일 권장**

---

## 관련 파일

- `android/patch_libnwmain.py` — Android 패치 (padding=48 적용됨)
- `mac/hook/apply_korean_patch.py` — macOS 패치 (현재 padding=16, 상향 필요)
- `windows/scripts/install.py` — Windows 패치 (현재 padding=16, 상향 필요)
- `docs/LINUX_ANALYSIS.md` — Linux 바이너리 분석
