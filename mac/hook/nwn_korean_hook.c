/**
 * NWN:EE 한글 통합 패치 dylib
 *
 * Phase 2 + Phase 3 통합:
 * - Phase 2: _AurGetTTFTexture 후킹으로 한글 글리프 베이크
 * - Phase 3: TextOut 후킹으로 CP949 → 글리프 인덱스 변환
 *
 * 글리프 매핑:
 * - 0~255: ASCII + 기본 Latin-1 (원본 그대로)
 * - 256~2613: 한글 가(U+AC00)~힣 중 앞 2358자
 *
 * CP949 한글 범위:
 * - lead: 0xB0~0xC8, trail: 0xA1~0xFE (완성형)
 * - 또는 확장 완성형: 0x81~0xFE
 *
 * 빌드:
 *   clang -arch arm64 -dynamiclib -o nwn_korean_hook.dylib nwn_korean_hook.c -lpthread
 *
 * 사용법:
 *   1. Phase 1 패치 적용 (apply_korean_font_patch.py)
 *   2. 이 dylib을 nwmain에 삽입 (insert_dylib)
 *   3. 재서명 (codesign)
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <sys/mman.h>
#include <pthread.h>
#include <unistd.h>
#include <mach-o/dyld.h>
#include <mach/mach.h>
#include <mach/vm_prot.h>

// CP949 변환 테이블
#include "cp949_table_hangul.h"
// KS X 1001 한글 유니코드 테이블 (실제 완성형 2350자)
#include "ksx1001_hangul.h"

// ============================================================================
// 상수 정의
// ============================================================================

// Phase 2: 폰트 베이크 후킹
#define ARM64_BAKE_PTR_OFFSET  0x1444F00

// Phase 3: TextOut 후킹 (Callsite 패치 방식)
// GOT 엔트리: stub이 참조하는 GOT 위치 (apply_stub_patch.py와 동일)
#define ARM64_GOT_HOOK_PTR_OFFSET  0x11483F8
#define ARM64_TEXTOUT_OFFSET  0xa2798

// Phase 3.5: GetSymbolCoords 후킹
// GetSymbolCoords(fontInfo, byte_index, out1, out2) → UV 좌표 반환
// 이 함수를 후킹하여 CP949 2바이트를 글리프 인덱스로 변환
#define ARM64_GETSYMBOLCOORDS_OFFSET  0xab67c

// Phase 4: Nuklear UI 한글 지원
// nk_draw_text를 후킹하여 CP949→UTF-8 변환
#define ARM64_NK_DRAW_TEXT_OFFSET  0xb38ef0

// 한글 글리프 설정
#define GLYPH_BASE_INDEX  256
// KS X 1001 완성형 한글: 2350자 (lead 0xB0~0xC8, trail 0xA1~0xFE)
// 총 글리프: 256(기본) + 25*94 = 2606
#define HANGUL_GLYPH_COUNT  KSX1001_HANGUL_COUNT  // 2350
#define TOTAL_GLYPH_COUNT  (256 + 25 * 94)  // 2606

// ============================================================================
// 타입 정의
// ============================================================================

typedef struct CAurFont CAurFont;
typedef struct CAurFontInfo CAurFontInfo;
typedef void (*TextOut_fn)(CAurFont* self, const char* text, int param);

// GetSymbolCoords: fontInfo에서 글리프 UV 좌표를 가져옴
// 반환값: 0=실패, 1=성공
typedef int (*GetSymbolCoords_fn)(CAurFontInfo* fontInfo, int index, void* out1, void* out2);

// 실제 함수 시그니처 (float 인자 포함!)
// ARM64에서 float 인자는 s0~s7 레지스터로 전달됨
typedef void* (*AurGetTTFTexture_fn)(
    void* ttf_obj,      // x0
    uint32_t* chars,    // x1
    int count,          // w2
    void* out,          // x3
    float scale,        // s0: GUI scale 계산 결과
    float param1,       // s1: 폰트 파라미터
    float param2,       // s2: 폰트 파라미터
    float param3        // s3: 폰트 파라미터
);

// Phase 4: Nuklear nk_draw_text 함수 시그니처
// nk_rect와 nk_color는 SIMD 레지스터로 전달됨
typedef void (*nk_draw_text_fn)(
    void* cmd_buffer,   // x0: nk_command_buffer*
    const char* text,   // x1: text pointer
    int len,            // w2: text length
    void* font,         // x3: nk_user_font*
    uint32_t bg,        // x4: background color (packed)
    uint32_t fg         // x5: foreground color (packed)
    // v0-v3: rect (float x4)
);

// ============================================================================
// 전역 변수
// ============================================================================

static void* nwmain_base = NULL;

// Phase 2
static AurGetTTFTexture_fn original_bake = NULL;
static uint32_t* korean_chars = NULL;
static volatile int bake_hook_active = 0;
static void** bake_ptr_global = NULL;

// Phase 3: TextOut 훅 (입력 인코딩 확인용)
static TextOut_fn original_textout = NULL;
static void** textout_got_ptr = NULL;

// Phase 4: Nuklear 후킹
static nk_draw_text_fn original_nk_draw_text = NULL;
static volatile int nk_hook_active = 0;
static int nk_log_count = 0;
#define MAX_NK_LOG 20

// Phase 3.5: Decode 함수 (stub에서 호출)
// GOT 엔트리: stub1 (0xEE8154) → GOT 0x1148400
#define ARM64_DECODE_GOT_OFFSET  0x1148400

// 로깅
static int log_count = 0;
static int textout_log_count = 0;
#define MAX_LOG_COUNT 50
#define MAX_TEXTOUT_LOG 20

// Phase 2 지연 훅킹
static pthread_t bake_hook_thread;
static volatile int bake_thread_running = 0;

// ============================================================================
// 원본 TextOut 프롤로그 (16바이트) - 더 이상 사용 안 함
// ============================================================================

// static const uint8_t original_prologue[] = {
//     0xff, 0x03, 0x03, 0xd1,  // sub sp, sp, #0xC0
//     0xeb, 0x2b, 0x04, 0x6d,  // stp d11, d10, [sp, #0x40]
//     0xe9, 0x23, 0x05, 0x6d,  // stp d9, d8, [sp, #0x50]
//     0xfc, 0x6f, 0x06, 0xa9,  // stp x28, x27, [sp, #0x60]
// };

// ============================================================================
// nwmain 베이스 주소 찾기
// ============================================================================

static void* find_nwmain_base(void) {
    uint32_t count = _dyld_image_count();
    for (uint32_t i = 0; i < count; i++) {
        const char* name = _dyld_get_image_name(i);
        if (strstr(name, "nwmain")) {
            return (void*)_dyld_get_image_header(i);
        }
    }
    return NULL;
}

// ============================================================================
// Phase 2: 폰트 베이크 후킹 (지연 훅킹 포함)
// ============================================================================

// 전방 선언
void* my_AurGetTTFTexture(void* ttf_obj, uint32_t* chars, int count, void* out,
                          float scale, float param1, float param2, float param3);

/**
 * 지연 훅킹 스레드
 * - bake 함수 포인터가 NULL인 경우, 게임 초기화 완료까지 폴링
 * - 최대 30초 대기 (100ms 간격)
 */
static void* bake_hook_thread_func(void* arg) {
    (void)arg;

    FILE* log = fopen("/tmp/nwn_korean.log", "a");
    if (log) {
        fprintf(log, "[Bake Thread] Started polling for bake function...\n");
        fclose(log);
    }

    int attempts = 0;
    const int max_attempts = 300;  // 30초 (100ms * 300)

    while (bake_thread_running && attempts < max_attempts) {
        void* current_value = *bake_ptr_global;

        if (current_value != NULL && (uintptr_t)current_value > 0x100000000) {
            // 유효한 함수 포인터 발견!
            original_bake = (AurGetTTFTexture_fn)current_value;
            *bake_ptr_global = (void*)my_AurGetTTFTexture;
            bake_hook_active = 1;

            log = fopen("/tmp/nwn_korean.log", "a");
            if (log) {
                fprintf(log, "[Bake Thread] SUCCESS! Hook installed after %d attempts\n", attempts);
                fprintf(log, "[Bake Thread] Original bake: %p -> Hook: %p\n",
                        original_bake, (void*)my_AurGetTTFTexture);
                fclose(log);
            }
            break;
        }

        // 100ms 대기 (폰트 초기화가 완료될 때까지)
        usleep(100 * 1000);
        attempts++;

        // 매 50번째 시도마다 로깅
        if (attempts % 50 == 0) {
            log = fopen("/tmp/nwn_korean.log", "a");
            if (log) {
                fprintf(log, "[Bake Thread] Still waiting... attempt %d, current=%p\n",
                        attempts, current_value);
                fclose(log);
            }
        }
    }

    if (!bake_hook_active) {
        log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            fprintf(log, "[Bake Thread] TIMEOUT - bake hook not installed\n");
            fclose(log);
        }
    }

    bake_thread_running = 0;
    return NULL;
}

static void init_korean_chars(uint32_t* original_chars) {
    if (korean_chars) return;

    korean_chars = (uint32_t*)malloc(TOTAL_GLYPH_COUNT * sizeof(uint32_t));
    if (!korean_chars) return;

    // 원본 256자 복사
    memcpy(korean_chars, original_chars, 256 * sizeof(uint32_t));

    // KS X 1001 완성형 한글 2350자를 CP949 lead/trail 순서대로 배치
    // 글리프 인덱스 = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
    // 이렇게 해야 TextOut에서 CP949 코드로 직접 글리프 인덱스 계산 가능
    int glyph_idx = 256;
    for (int lead = 0xB0; lead <= 0xC8; lead++) {
        for (int trail = 0xA1; trail <= 0xFE; trail++) {
            // CP949→Unicode 변환
            uint16_t unicode = cp949_hangul_to_ucs2(lead, trail);
            if (unicode != 0) {
                korean_chars[glyph_idx] = unicode;
            } else {
                // 유효하지 않은 코드는 공백으로
                korean_chars[glyph_idx] = 0x0020;
            }
            glyph_idx++;
        }
    }

    FILE* log = fopen("/tmp/nwn_korean.log", "a");
    if (log) {
        fprintf(log, "[Bake] Initialized %d characters (256 base + %d Korean slots)\n",
                TOTAL_GLYPH_COUNT, glyph_idx - 256);
        // 샘플 출력
        fprintf(log, "[Bake] Sample: glyph[256]=U+%04X (가), glyph[1512]=U+%04X (시)\n",
                korean_chars[256], korean_chars[256 + (0xBD - 0xB0) * 94 + (0xC3 - 0xA1)]);
        fclose(log);
    }
}

void* my_AurGetTTFTexture(void* ttf_obj, uint32_t* chars, int count, void* out,
                          float scale, float param1, float param2, float param3) {
    if (!original_bake) return NULL;

    FILE* log = fopen("/tmp/nwn_korean.log", "a");

    if (log && log_count < MAX_LOG_COUNT) {
        fprintf(log, "[Bake] Called: ttf=%p chars=%p count=%d out=%p scale=%.3f\n",
                ttf_obj, chars, count, out, scale);
        log_count++;
    }

    // 한글 글리프 확장 모드
    #if 1
    // 기본 256 베이크 요청 감지
    if (count == 256 && chars != NULL) {
        if (log) fprintf(log, "[Bake] Expanding 256 -> %d\n", TOTAL_GLYPH_COUNT);

        init_korean_chars(chars);

        if (korean_chars) {
            // ttf_obj 구조체 분석
            if (log && ttf_obj) {
                int* ttf_ints = (int*)ttf_obj;
                fprintf(log, "[Bake] TTF obj: ");
                for (int i = 0; i < 32; i++) {
                    fprintf(log, "[%d]=%d ", i, ttf_ints[i]);
                    if (i % 8 == 7) fprintf(log, "\n[Bake] TTF obj: ");
                }
                fprintf(log, "\n");

                // float로도 해석
                float* ttf_floats = (float*)ttf_obj;
                fprintf(log, "[Bake] TTF floats: ");
                for (int i = 0; i < 16; i++) {
                    fprintf(log, "[%d]=%.2f ", i, ttf_floats[i]);
                }
                fprintf(log, "\n");
            }

            // 스케일 조정 - 원본 스케일 유지
            float adjusted_scale = scale;  // 100% (원본)
            if (log) fprintf(log, "[Bake] Scale: %.3f\n", scale);

            void* result = original_bake(ttf_obj, korean_chars, TOTAL_GLYPH_COUNT, out,
                                         adjusted_scale, param1, param2, param3);

            if (log) {
                fprintf(log, "[Bake] Expanded bake done, result=%p\n", result);
                if (out) {
                    // out 구조체 분석 (베이크 후)
                    uint8_t* out_bytes = (uint8_t*)out;
                    fprintf(log, "[Bake] OUT after:  ");
                    for (int i = 0; i < 64; i += 4) {
                        fprintf(log, "%02X%02X%02X%02X ",
                                out_bytes[i], out_bytes[i+1], out_bytes[i+2], out_bytes[i+3]);
                    }
                    fprintf(log, "\n");

                    // 주요 필드 해석
                    int* out_ints = (int*)out;
                    fprintf(log, "[Bake] OUT fields: [0]=%d [1]=%d [2]=%d [3]=%d [4]=%d [5]=%d [6]=%d [7]=%d\n",
                            out_ints[0], out_ints[1], out_ints[2], out_ints[3],
                            out_ints[4], out_ints[5], out_ints[6], out_ints[7]);
                    fprintf(log, "[Bake] OUT fields: [8]=%d [9]=%d [10]=%d [11]=%d [12]=%d [13]=%d [14]=%d [15]=%d\n",
                            out_ints[8], out_ints[9], out_ints[10], out_ints[11],
                            out_ints[12], out_ints[13], out_ints[14], out_ints[15]);
                }
                fclose(log);
            }
            return result;
        }
    }
    #endif

    if (log) {
        fprintf(log, "[Bake] Pass-through (count=%d) scale=%.3f p1=%.3f p2=%.3f p3=%.3f\n",
                count, scale, param1, param2, param3);
        fclose(log);
    }

    // float 인자들을 그대로 전달
    return original_bake(ttf_obj, chars, count, out, scale, param1, param2, param3);
}

// ============================================================================
// Phase 3: CP949 → 글리프 인덱스 변환
// ============================================================================

/**
 * CP949 lead/trail 바이트를 글리프 인덱스로 직접 변환
 *
 * 완성형(KS X 1001) 범위:
 * - lead: 0xB0~0xC8 (25개)
 * - trail: 0xA1~0xFE (94개)
 * - 총 25 * 94 = 2350자
 *
 * 글리프 인덱스 = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
 */
static inline uint16_t cp949_to_glyph_index(uint8_t lead, uint8_t trail) {
    // 완성형 범위 체크
    if (lead >= 0xB0 && lead <= 0xC8 && trail >= 0xA1 && trail <= 0xFE) {
        return GLYPH_BASE_INDEX + (lead - 0xB0) * 94 + (trail - 0xA1);
    }
    return '?';  // 미지원
}

// ============================================================================
// Phase 3.5: Decode 함수 (어셈블리에서 호출)
// ============================================================================

/**
 * CP949 2바이트 한글 디코딩
 *
 * 호출 규약: stub에서 br로 점프하므로 레지스터 상태 그대로 전달됨
 * 입력 레지스터 (TextOut 루프 상태):
 *   x24: 현재 문자열 포인터
 *   w25: 현재 바이트 (ldrb 결과)
 *   w28: 루프 인덱스
 *   x30(LR): bl 다음 주소 (0xa2a00 = bl GetSymbolCoords)
 *
 * 출력:
 *   x1: GetSymbolCoords에 전달할 글리프 인덱스
 *   w28: 2바이트 처리 시 +1 (한글)
 *
 * 동작:
 *   1. w25가 CP949 lead byte (0xB0~0xC8)인지 확인
 *   2. 맞으면 trail byte를 읽고 글리프 인덱스 계산
 *   3. x1에 결과 저장, w28 += 1
 *   4. 아니면 x1 = w25 (원본 동작)
 *   5. ret으로 bl GetSymbolCoords로 복귀
 *
 * 네이키드 함수로 작성 - 프롤로그/에필로그 없이 직접 제어
 */

// C 함수: 실제 디코딩 로직 (어셈블리에서 호출)
// x24, w25, w28을 인자로 받고, 결과와 증가량 반환
uint64_t decode_cp949_impl(uint8_t* str_ptr, uint8_t current_byte, int* out_increment) {
    // CP949 lead byte 체크 (0xB0~0xC8)
    if (current_byte >= 0xB0 && current_byte <= 0xC8) {
        uint8_t trail = str_ptr[1];  // x24 + 1에서 trail byte

        // trail byte 체크 (0xA1~0xFE)
        if (trail >= 0xA1 && trail <= 0xFE) {
            // 글리프 인덱스 계산: 256 + (lead - 0xB0) * 94 + (trail - 0xA1)
            uint16_t glyph_idx = GLYPH_BASE_INDEX + (current_byte - 0xB0) * 94 + (trail - 0xA1);
            *out_increment = 1;  // 2바이트 처리했으므로 w28 += 1
            return glyph_idx;
        }
    }

    // ASCII 또는 미지원: 원본 동작
    *out_increment = 0;
    return current_byte;
}

// 호출 카운터 (디버깅용)
static volatile int decode_call_count = 0;

// 어셈블리 decode 함수 (stub에서 br로 호출됨)
// 네이키드 함수 - 레지스터 상태 유지
//
// 순수 어셈블리로 CP949 디코딩 (C 함수 호출 없음)
// 입력: x24 = string ptr, w25 = current byte, w28 = loop index
// 출력: x1 = glyph index, w28 += 1 if Korean
__attribute__((naked))
void decode_glyph_asm(void) {
    __asm__ volatile (
        // 디버깅: 호출 카운터 증가
        "adrp x9, _decode_call_count@PAGE\n"
        "add x9, x9, _decode_call_count@PAGEOFF\n"
        "ldr w10, [x9]\n"
        "add w10, w10, #1\n"
        "str w10, [x9]\n"

        // 기본값: x1 = w25 (ASCII)
        "and x1, x25, #0xFF\n"

        // w25 < 0xB0 이면 ASCII → 바로 리턴
        "cmp w25, #0xB0\n"
        "b.lo 1f\n"              // ASCII

        // w25 > 0xC8 이면 ASCII 범위 밖 → 바로 리턴
        "cmp w25, #0xC8\n"
        "b.hi 1f\n"              // Not Korean lead

        // x24+1에서 trail byte 읽기
        "ldrb w9, [x24, #1]\n"

        // trail < 0xA1 이면 무효
        "cmp w9, #0xA1\n"
        "b.lo 1f\n"

        // trail > 0xFE 이면 무효
        "cmp w9, #0xFE\n"
        "b.hi 1f\n"

        // === 유효한 CP949 한글 ===
        // glyph_index = 256 + (lead - 0xB0) * 94 + (trail - 0xA1)

        // w10 = lead - 0xB0
        "sub w10, w25, #0xB0\n"

        // w10 = w10 * 94
        "mov w11, #94\n"
        "mul w10, w10, w11\n"

        // w9 = trail - 0xA1
        "sub w9, w9, #0xA1\n"

        // w10 = w10 + w9
        "add w10, w10, w9\n"

        // x1 = 256 + w10
        "add x1, x10, #256\n"

        // w28 += 1 (2바이트 처리)
        "add w28, w28, #1\n"

    "1:\n"
        // 리턴
        "ret\n"
    );
}

// 전방 선언 (실제 정의는 Phase 4 섹션에 있음)
extern volatile int nk_wrapper_call_count;
extern volatile int nk_conversion_count;

// 디버깅: 호출 횟수 로깅
__attribute__((destructor))
static void log_decode_stats(void) {
    FILE* log = fopen("/tmp/nwn_korean.log", "a");
    if (log) {
        fprintf(log, "\n[Decode Stats] Total calls: %d\n", decode_call_count);
        fprintf(log, "[NK Wrapper Stats] Total calls: %d, CP949 conversions: %d\n",
                nk_wrapper_call_count, nk_conversion_count);
        fclose(log);
    }
}

// ============================================================================
// Phase 4: Nuklear CP949→UTF-8 변환
// ============================================================================

/**
 * Latin-1으로 손상된 CP949 문자열 감지
 *
 * TLK 로더가 CP949 바이트를 Latin-1으로 해석하면:
 * - CP949 `비` = 0xBA 0xF1
 * - Latin-1 해석: º (U+00BA) + ñ (U+00F1)
 * - UTF-8 인코딩: C2 BA C3 B1
 *
 * 따라서 UTF-8 2바이트 시퀀스 (C2/C3 XX) 형태로 나타남
 */
static int is_latin1_corrupted_utf8(const char* text, int len) {
    if (!text || len < 4) return 0;

    // UTF-8 2바이트 시퀀스가 연속으로 나타나는지 확인
    // Latin-1 0x80~0xFF → UTF-8 C2 80 ~ C3 BF
    unsigned char b0 = (unsigned char)text[0];
    unsigned char b1 = (unsigned char)text[1];

    // C2 또는 C3로 시작하는 UTF-8 시퀀스
    if ((b0 == 0xC2 || b0 == 0xC3) && (b1 >= 0x80 && b1 <= 0xBF)) {
        // 두 번째 문자도 확인
        if (len >= 4) {
            unsigned char b2 = (unsigned char)text[2];
            unsigned char b3 = (unsigned char)text[3];
            if ((b2 == 0xC2 || b2 == 0xC3) && (b3 >= 0x80 && b3 <= 0xBF)) {
                return 1;  // Latin-1 손상된 CP949로 추정
            }
        }
        return 1;
    }

    return 0;
}

/**
 * Latin-1 손상된 UTF-8 → CP949 원본 복원 → UTF-8 한글 변환
 *
 * 입력: UTF-8 인코딩된 Latin-1 문자열 (원본은 CP949)
 * 출력: UTF-8 인코딩된 한글 문자열
 *
 * 과정:
 * 1. UTF-8 디코딩하여 유니코드 코드포인트 추출
 * 2. 0x80~0xFF 범위 코드포인트는 원래 CP949 바이트
 * 3. 연속된 두 바이트를 CP949로 해석하여 한글 유니코드로 변환
 * 4. UTF-8로 인코딩하여 출력
 */
int convert_latin1_corrupted_to_utf8(const char* src, int src_len, char* dst, int dst_size) {
    if (!src || !dst || src_len <= 0 || dst_size <= 0) return 0;

    int si = 0;  // source index
    int di = 0;  // dest index

    // 먼저 UTF-8 → 바이트 배열로 디코딩
    unsigned char bytes[4096];
    int byte_count = 0;

    while (si < src_len && byte_count < 4096) {
        unsigned char b = (unsigned char)src[si];

        if (b < 0x80) {
            // ASCII
            bytes[byte_count++] = b;
            si++;
        }
        else if ((b & 0xE0) == 0xC0 && si + 1 < src_len) {
            // UTF-8 2바이트 시퀀스 (C0-DF XX)
            unsigned char b1 = (unsigned char)src[si + 1];
            if ((b1 & 0xC0) == 0x80) {
                // 유니코드 코드포인트 추출
                uint16_t cp = ((b & 0x1F) << 6) | (b1 & 0x3F);
                // Latin-1 범위 (U+0080~U+00FF)는 원래 바이트로 복원
                if (cp <= 0xFF) {
                    bytes[byte_count++] = (unsigned char)cp;
                } else {
                    // 그 외는 원본 유지 (나중에 처리)
                    bytes[byte_count++] = b;
                    bytes[byte_count++] = b1;
                }
                si += 2;
            } else {
                bytes[byte_count++] = b;
                si++;
            }
        }
        else if ((b & 0xF0) == 0xE0 && si + 2 < src_len) {
            // UTF-8 3바이트 시퀀스 - 이미 한글일 수 있음, 그대로 출력
            unsigned char b1 = (unsigned char)src[si + 1];
            unsigned char b2 = (unsigned char)src[si + 2];
            if (di + 3 < dst_size) {
                dst[di++] = b;
                dst[di++] = b1;
                dst[di++] = b2;
            }
            si += 3;
            continue;  // bytes 배열 건너뜀
        }
        else {
            bytes[byte_count++] = b;
            si++;
        }
    }

    // bytes 배열을 CP949로 해석하여 UTF-8로 변환
    int bi = 0;
    while (bi < byte_count && di < dst_size - 3) {
        unsigned char b0 = bytes[bi];

        if (b0 < 0x80) {
            // ASCII
            dst[di++] = b0;
            bi++;
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && bi + 1 < byte_count) {
            // CP949 완성형 한글 가능성
            unsigned char b1 = bytes[bi + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                // CP949 → Unicode 변환
                uint16_t unicode = cp949_hangul_to_ucs2(b0, b1);

                if (unicode != 0 && unicode >= 0xAC00 && unicode <= 0xD7A3) {
                    // 유효한 한글: UTF-8로 인코딩
                    dst[di++] = 0xE0 | ((unicode >> 12) & 0x0F);
                    dst[di++] = 0x80 | ((unicode >> 6) & 0x3F);
                    dst[di++] = 0x80 | (unicode & 0x3F);
                    bi += 2;
                    continue;
                }
            }
            // 변환 실패: 원본 바이트 유지
            dst[di++] = b0;
            bi++;
        }
        else {
            // 그 외: 그대로 복사
            dst[di++] = b0;
            bi++;
        }
    }

    dst[di] = '\0';
    return di;
}

/**
 * CP949 문자열을 UTF-8로 변환
 *
 * @param src      CP949 인코딩된 소스 문자열
 * @param src_len  소스 길이
 * @param dst      UTF-8 출력 버퍼
 * @param dst_size 출력 버퍼 크기
 * @return         변환된 UTF-8 문자열 길이 (널 제외)
 */
// 어셈블리에서 호출하므로 static 제거
int convert_cp949_to_utf8(const char* src, int src_len, char* dst, int dst_size) {
    if (!src || !dst || src_len <= 0 || dst_size <= 0) return 0;

    int si = 0;  // source index
    int di = 0;  // dest index

    while (si < src_len && di < dst_size - 3) {  // UTF-8은 최대 3바이트
        unsigned char b0 = (unsigned char)src[si];

        if (b0 < 0x80) {
            // ASCII: 그대로 복사
            dst[di++] = src[si++];
        }
        else if (b0 >= 0xB0 && b0 <= 0xC8 && si + 1 < src_len) {
            // CP949 완성형 한글 가능성
            unsigned char b1 = (unsigned char)src[si + 1];

            if (b1 >= 0xA1 && b1 <= 0xFE) {
                // CP949 → Unicode 변환
                uint16_t unicode = cp949_hangul_to_ucs2(b0, b1);

                if (unicode != 0 && unicode >= 0xAC00 && unicode <= 0xD7A3) {
                    // 유효한 한글: UTF-8로 인코딩 (3바이트)
                    // U+AC00~U+D7A3 → 0xEA~0xED 범위
                    dst[di++] = 0xE0 | ((unicode >> 12) & 0x0F);
                    dst[di++] = 0x80 | ((unicode >> 6) & 0x3F);
                    dst[di++] = 0x80 | (unicode & 0x3F);
                    si += 2;
                    continue;
                }
            }

            // 변환 실패: 원본 바이트 유지
            dst[di++] = src[si++];
        }
        else {
            // 기타 바이트: 그대로 복사
            dst[di++] = src[si++];
        }
    }

    dst[di] = '\0';
    return di;
}

/**
 * nk_draw_text 후킹
 *
 * 접근법: 함수 시작 부분에 분기 명령어 삽입
 * nk_draw_text 첫 명령어: stp d11, d10, [sp, #-0x80]! (6db82beb)
 *
 * 후킹 방식:
 * 1. 첫 4바이트를 b trampoline으로 교체
 * 2. 트램폴린에서 CP949→UTF-8 변환 후 원본 함수 호출
 * 3. 원본 프롤로그 실행 후 원본 함수 본문으로 점프
 */

// UTF-8 변환 버퍼 (thread-local 대신 정적 버퍼 사용)
// 어셈블리에서 참조하므로 static 제거
char nk_utf8_buf[4096];

// wrapper 호출 카운터 (디버깅용)
volatile int nk_wrapper_call_count = 0;
volatile int nk_conversion_count = 0;

// 디버깅용: 비ASCII 텍스트 로깅
static int nk_debug_log_count = 0;
#define MAX_NK_DEBUG_LOG 30

// nk_sdl_refresh_config 호출 플래그
static int nk_refresh_called = 0;

// nwmain 베이스 주소 (init에서 설정됨)
extern void* nwmain_base;

/**
 * C wrapper: 텍스트 변환 처리
 * 어셈블리에서 호출됨
 *
 * @param text  입력 텍스트
 * @param len   텍스트 길이
 * @return      변환된 길이 (0이면 변환 안 함)
 */
int nk_process_text(const char* text, int len) {
    if (!text || len <= 0) return 0;

    // 첫 번째 호출 시 nk_sdl_refresh_config 호출하여 폰트 아틀라스 재빌드
    // 이 시점에서는 NK가 초기화되어 있음
    if (!nk_refresh_called && nwmain_base) {
        nk_refresh_called = 1;

        // Locale 변수를 3 (Korean)으로 다시 설정
        // 게임 초기화 과정에서 덮어썼을 수 있음
        #define ARM64_LOCALE_OFFSET_LOCAL  0x114ca88
        uint32_t* locale_ptr = (uint32_t*)((uintptr_t)nwmain_base + ARM64_LOCALE_OFFSET_LOCAL);
        uint32_t old_locale = *locale_ptr;
        *locale_ptr = 3;

        #define ARM64_NK_SDL_REFRESH_CONFIG_OFFSET_LOCAL  0xb5affc
        typedef void (*nk_sdl_refresh_config_fn)(void);
        nk_sdl_refresh_config_fn refresh_config = (nk_sdl_refresh_config_fn)(
            (uintptr_t)nwmain_base + ARM64_NK_SDL_REFRESH_CONFIG_OFFSET_LOCAL
        );

        FILE* log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            fprintf(log, "[NK Refresh] Locale was %u, set to 3 (Korean)\n", old_locale);
            fprintf(log, "[NK Refresh] Calling nk_sdl_refresh_config at %p to reload Korean glyphs\n",
                    (void*)refresh_config);
            fclose(log);
        }

        // 폰트 아틀라스 재빌드 - 한글 글리프 로드
        refresh_config();

        log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            fprintf(log, "[NK Refresh] Done - Korean glyphs should now be available\n");
            uint32_t new_locale = *locale_ptr;
            fprintf(log, "[NK Refresh] Locale after refresh: %u\n", new_locale);
            fclose(log);
        }
    }

    // 문자열 전체에서 비ASCII 바이트 찾기
    int has_non_ascii = 0;
    int first_non_ascii = -1;
    for (int i = 0; i < len; i++) {
        if ((unsigned char)text[i] >= 0x80) {
            has_non_ascii = 1;
            first_non_ascii = i;
            break;
        }
    }

    // 비ASCII 텍스트 디버깅 로그
    if (has_non_ascii && nk_debug_log_count < MAX_NK_DEBUG_LOG) {
        FILE* log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            fprintf(log, "[NK Debug #%d] len=%d, first_non_ascii=%d, bytes: ",
                    nk_debug_log_count, len, first_non_ascii);
            int log_len = len > 48 ? 48 : len;
            for (int i = 0; i < log_len; i++) {
                fprintf(log, "%02X ", (unsigned char)text[i]);
            }
            fprintf(log, "\n  text: \"");
            for (int i = 0; i < log_len && i < 40; i++) {
                unsigned char c = (unsigned char)text[i];
                if (c >= 0x20 && c < 0x7F) {
                    fprintf(log, "%c", c);
                } else {
                    fprintf(log, ".");
                }
            }
            fprintf(log, "\"\n");
            fclose(log);
            nk_debug_log_count++;
        }
    }

    // 비ASCII가 없으면 변환 불필요
    if (!has_non_ascii) return 0;

    // Latin-1 손상된 UTF-8 감지 (C2/C3 XX 패턴) - 문자열 전체 스캔
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        unsigned char b1 = (unsigned char)text[i + 1];
        if ((b0 == 0xC2 || b0 == 0xC3) && (b1 >= 0x80 && b1 <= 0xBF)) {
            // Latin-1 손상 패턴 발견
            nk_conversion_count++;
            return convert_latin1_corrupted_to_utf8(text, len, nk_utf8_buf, sizeof(nk_utf8_buf));
        }
    }

    // 원본 CP949 감지 - 문자열 전체 스캔
    for (int i = 0; i < len - 1; i++) {
        unsigned char b0 = (unsigned char)text[i];
        if (b0 >= 0xB0 && b0 <= 0xC8) {
            unsigned char b1 = (unsigned char)text[i + 1];
            if (b1 >= 0xA1 && b1 <= 0xFE) {
                nk_conversion_count++;
                return convert_cp949_to_utf8(text, len, nk_utf8_buf, sizeof(nk_utf8_buf));
            }
        }
    }

    // 감지 안 됨 - 그래도 비ASCII가 있으면 로그 남기기
    if (nk_debug_log_count < MAX_NK_DEBUG_LOG + 10) {
        FILE* log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            fprintf(log, "[NK Unhandled] len=%d, first_non_ascii=%d\n",
                    len, first_non_ascii);
            fclose(log);
        }
    }

    return 0;  // 변환 불필요
}

// 원본 함수 주소 (첫 명령어 다음)
static void* nk_original_func_after_prologue = NULL;

// 원본 프롤로그 명령어
static uint32_t nk_original_instr = 0;

/**
 * nk_draw_text 래퍼 함수
 *
 * 호출 규약:
 * - x0: cmd_buffer
 * - x1: text (변환 대상)
 * - x2: len (변환 대상)
 * - x3: font
 * - x4, x5: colors
 * - v0-v3: rect (SIMD, 보존 필요)
 *
 * 이 함수는 naked로 작성하여 레지스터를 보존
 */
__attribute__((naked))
void my_nk_draw_text_wrapper(void) {
    __asm__ volatile (
        // === 프롤로그: 레지스터 보존 ===
        // SIMD와 정수 레지스터 모두 보존
        "stp x29, x30, [sp, #-0x60]!\n"
        "stp x0, x1, [sp, #0x10]\n"
        "stp x2, x3, [sp, #0x20]\n"
        "stp x4, x5, [sp, #0x30]\n"
        "stp d0, d1, [sp, #0x40]\n"  // v0, v1
        "stp d2, d3, [sp, #0x50]\n"  // v2, v3

        // === 디버깅: 호출 카운터 증가 ===
        "adrp x9, _nk_wrapper_call_count@PAGE\n"
        "add x9, x9, _nk_wrapper_call_count@PAGEOFF\n"
        "ldr w10, [x9]\n"
        "add w10, w10, #1\n"
        "str w10, [x9]\n"

        // === C 함수 호출: nk_process_text(text, len) ===
        // x0 = text (현재 x1)
        // x1 = len (현재 x2)
        "mov x0, x1\n"               // x0 = text
        "mov w1, w2\n"               // x1 = len

        "bl _nk_process_text\n"

        // 반환값 확인: w0 = 변환된 길이 (0이면 변환 안 함)
        "cbz w0, 2f\n"

        // === 변환됨: nk_utf8_buf 사용 ===
        // x1 = nk_utf8_buf, x2 = 변환된 길이
        "adrp x1, _nk_utf8_buf@PAGE\n"
        "add x1, x1, _nk_utf8_buf@PAGEOFF\n"
        "mov w2, w0\n"               // len = utf8_len

        // 나머지 레지스터 복원
        "ldp x0, x9, [sp, #0x10]\n"  // x0 복원, x1은 변환된 버퍼
        "ldr x3, [sp, #0x28]\n"      // x3 복원
        "ldp x4, x5, [sp, #0x30]\n"  // x4, x5 복원
        "ldp d0, d1, [sp, #0x40]\n"  // v0, v1 복원
        "ldp d2, d3, [sp, #0x50]\n"  // v2, v3 복원
        "b 3f\n"

    "2:\n"
        // === 변환 없이 원본 호출 ===
        "ldp x0, x1, [sp, #0x10]\n"
        "ldp x2, x3, [sp, #0x20]\n"
        "ldp x4, x5, [sp, #0x30]\n"
        "ldp d0, d1, [sp, #0x40]\n"
        "ldp d2, d3, [sp, #0x50]\n"

    "3:\n"
        // === 원본 함수 호출 준비 ===
        "ldp x29, x30, [sp], #0x60\n"

        // 원본 프롤로그 실행: stp d11, d10, [sp, #-0x80]!
        "stp d11, d10, [sp, #-0x80]!\n"

        // 원본 함수 본문으로 점프 (첫 명령어 다음)
        "adrp x9, _nk_original_func_after_prologue@PAGE\n"
        "add x9, x9, _nk_original_func_after_prologue@PAGEOFF\n"
        "ldr x9, [x9]\n"
        "br x9\n"
    );
}

// ============================================================================
// Phase 3: TextOut 훅 (입력 인코딩 확인용)
// ============================================================================

static void my_TextOut(CAurFont* self, const char* text, int param) {
    if (textout_log_count < MAX_TEXTOUT_LOG && text && text[0]) {
        FILE* log = fopen("/tmp/nwn_korean.log", "a");
        if (log) {
            // 입력 바이트 출력 (최대 32바이트)
            fprintf(log, "[TextOut #%d] text=%p param=%d\n", textout_log_count, text, param);
            fprintf(log, "  Bytes: ");
            int len = 0;
            for (int i = 0; text[i] && i < 32; i++) {
                fprintf(log, "%02X ", (uint8_t)text[i]);
                len++;
            }
            fprintf(log, "\n");

            // 인코딩 추측
            uint8_t b0 = (uint8_t)text[0];
            uint8_t b1 = text[1] ? (uint8_t)text[1] : 0;

            if (b0 >= 0xB0 && b0 <= 0xC8 && b1 >= 0xA1 && b1 <= 0xFE) {
                fprintf(log, "  Encoding: CP949 (Korean lead byte detected)\n");
            } else if (b0 >= 0xE0 && b0 <= 0xEF) {
                fprintf(log, "  Encoding: UTF-8 (3-byte sequence)\n");
            } else if (b0 >= 0xC0 && b0 <= 0xDF) {
                fprintf(log, "  Encoding: UTF-8 (2-byte sequence)\n");
            } else if (b0 < 0x80) {
                fprintf(log, "  Encoding: ASCII\n");
            } else {
                fprintf(log, "  Encoding: Unknown (0x%02X)\n", b0);
            }

            fclose(log);
            textout_log_count++;
        }
    }

    // 원본 함수 호출
    if (original_textout) {
        original_textout(self, text, param);
    }
}

// ============================================================================
// 초기화
// ============================================================================

__attribute__((constructor))
static void init_korean_hook(void) {
    FILE* log = fopen("/tmp/nwn_korean.log", "w");
    if (log) fprintf(log, "[NWN Korean Hook] Initializing (bake hook only)...\n");
    if (log) fprintf(log, "Note: ldrb patch is applied by apply_korean_patch.py\n");

    // nwmain 찾기
    nwmain_base = find_nwmain_base();
    if (!nwmain_base) {
        if (log) { fprintf(log, "ERROR: nwmain not found\n"); fclose(log); }
        return;
    }
    if (log) fprintf(log, "nwmain base: %p\n", nwmain_base);

    // =========================================
    // Phase 2: 폰트 베이크 후킹
    // =========================================
    bake_ptr_global = (void**)((uintptr_t)nwmain_base + ARM64_BAKE_PTR_OFFSET);
    if (log) fprintf(log, "Bake ptr location: %p\n", bake_ptr_global);

    void* current_bake = *bake_ptr_global;
    if (log) fprintf(log, "Current bake fn: %p\n", current_bake);

    if (current_bake != NULL && (uintptr_t)current_bake > 0x100000000) {
        original_bake = (AurGetTTFTexture_fn)current_bake;
        *bake_ptr_global = (void*)my_AurGetTTFTexture;
        bake_hook_active = 1;
        if (log) fprintf(log, "Phase 2: Bake hook ACTIVE (immediate)\n");
    } else {
        if (log) fprintf(log, "Phase 2: Bake hook DEFERRED - starting poll thread\n");
        // 지연 훅킹 스레드 시작
        bake_thread_running = 1;
        if (pthread_create(&bake_hook_thread, NULL, bake_hook_thread_func, NULL) != 0) {
            if (log) fprintf(log, "ERROR: Failed to create bake hook thread\n");
            bake_thread_running = 0;
        }
    }

    // =========================================
    // Phase 3.5: Decode 함수 GOT 설정 (비활성화)
    // 주의: 이 코드가 텍스트 출력을 깨뜨림
    // =========================================
    if (log) fprintf(log, "Phase 3.5: DISABLED (GOT patch causes text corruption)\n");

    // =========================================
    // Phase 4: Nuklear 한글 지원
    // =========================================

    // 4.1: Locale을 3 (Korean)으로 강제 설정
    // 이렇게 하면 nk_sdl_refresh_config에서 korean_glyph_ranges를 사용
    #define ARM64_LOCALE_OFFSET  0x10114ca88  // Encoding::g_defaultLocale

    // Locale 변수는 __DATA 섹션에 있어서 직접 쓰기 가능
    // 단, 실제 오프셋은 arm64 슬라이스 기준이므로 베이스 주소에서 계산
    // 0x10114ca88은 이미지 베이스 0x100000000 기준
    uint32_t* locale_ptr = (uint32_t*)((uintptr_t)nwmain_base + (ARM64_LOCALE_OFFSET - 0x100000000));

    if (log) {
        fprintf(log, "Phase 4.1: Locale ptr at %p, current value: %u\n", locale_ptr, *locale_ptr);
    }

    // Locale을 3 (Korean)으로 설정
    *locale_ptr = 3;

    if (log) {
        fprintf(log, "Phase 4.1: Locale set to 3 (Korean) for Nuklear glyph ranges\n");
    }

    // 4.1.5: nk_sdl_refresh_config 호출하여 폰트 아틀라스 재빌드
    // dylib 로드 시점에는 아직 SDL/NK가 초기화되지 않았을 수 있으므로
    // 지연 호출이 필요할 수 있음
    #define ARM64_NK_SDL_REFRESH_CONFIG_OFFSET  0xb5affc  // nk_sdl_refresh_config 함수

    typedef void (*nk_sdl_refresh_config_fn)(void);
    nk_sdl_refresh_config_fn refresh_config = (nk_sdl_refresh_config_fn)(
        (uintptr_t)nwmain_base + ARM64_NK_SDL_REFRESH_CONFIG_OFFSET
    );

    if (log) {
        fprintf(log, "Phase 4.1.5: nk_sdl_refresh_config at %p\n", (void*)refresh_config);
        fprintf(log, "Phase 4.1.5: Will be called when NK is ready (deferred)\n");
    }

    // 주의: constructor 시점에는 NK가 초기화되지 않았으므로
    // 여기서 직접 호출하면 크래시할 수 있음
    // 대신 첫 번째 nk_draw_text 호출 시 refresh를 트리거

    // 4.2: nk_draw_text 후킹
    // __DATA 섹션의 빈 공간에 함수 포인터 설정
    #define ARM64_NK_HOOK_PTR_OFFSET  0x115b218  // __DATA.__data 섹션 끝의 패딩

    void* nk_draw_text_addr = (void*)((uintptr_t)nwmain_base + ARM64_NK_DRAW_TEXT_OFFSET);
    nk_original_func_after_prologue = (void*)((uintptr_t)nk_draw_text_addr + 4);

    // 함수 포인터 설정 (__DATA 섹션 - 쓰기 가능)
    void** nk_hook_ptr = (void**)((uintptr_t)nwmain_base + ARM64_NK_HOOK_PTR_OFFSET);

    if (log) {
        fprintf(log, "Phase 4: nk_draw_text at %p\n", nk_draw_text_addr);
        fprintf(log, "Phase 4: wrapper at %p\n", (void*)my_nk_draw_text_wrapper);
        fprintf(log, "Phase 4: hook ptr at %p (offset 0x%x, __DATA section)\n", nk_hook_ptr, ARM64_NK_HOOK_PTR_OFFSET);
        fprintf(log, "Phase 4: return to %p (after prologue)\n", nk_original_func_after_prologue);
    }

    // 함수 포인터 설정
    *nk_hook_ptr = (void*)my_nk_draw_text_wrapper;
    nk_hook_active = 1;

    // 설정 확인
    void* written_ptr = *nk_hook_ptr;
    if (log) {
        fprintf(log, "Phase 4: hook ptr written = %p (expected %p)\n",
                written_ptr, (void*)my_nk_draw_text_wrapper);
        if (written_ptr == (void*)my_nk_draw_text_wrapper) {
            fprintf(log, "Phase 4: nk_draw_text hook ACTIVE\n");
        } else {
            fprintf(log, "Phase 4: WARNING - hook ptr write FAILED!\n");
        }
    }

    // 완료
    if (log) {
        fprintf(log, "\n=== Korean Hook Ready ===\n");
        fprintf(log, "Glyph range: 0-255 (base) + 256-%d (Korean)\n", GLYPH_BASE_INDEX + HANGUL_GLYPH_COUNT - 1);
        fprintf(log, "Mode: Bake hook + Trampoline + Nuklear hook\n");
        fprintf(log, "Input encoding: CP949 confirmed\n");
        fprintf(log, "Nuklear: CP949->UTF-8 conversion enabled\n");
        fclose(log);
    }
}

__attribute__((destructor))
static void cleanup_korean_hook(void) {
    // Phase 2 복원
    if (bake_hook_active && bake_ptr_global && original_bake) {
        *bake_ptr_global = (void*)original_bake;
    }

    if (korean_chars) {
        free(korean_chars);
    }
}
