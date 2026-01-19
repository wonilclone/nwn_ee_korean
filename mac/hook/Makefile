# NWN:EE CP949 Korean Support Hook
# macOS Universal Binary Build

CC = clang
CFLAGS = -Wall -O2 -fPIC
LDFLAGS = -dynamiclib -framework CoreFoundation

# 소스 파일
SRCS = nwn_korean_hook.c
TARGET = nwn_korean_hook.dylib

# 아키텍처별 타겟
TARGET_X64 = nwn_korean_hook_x64.dylib
TARGET_ARM = nwn_korean_hook_arm.dylib

.PHONY: all clean x64 arm universal test

# 기본 빌드: arm64 only (ARM64 inline assembly 사용)
all: arm
	cp $(TARGET_ARM) $(TARGET)
	@echo "Built: $(TARGET) (arm64 only)"

# x86_64 빌드
x64: $(TARGET_X64)

$(TARGET_X64): $(SRCS)
	$(CC) $(CFLAGS) -arch x86_64 $(LDFLAGS) -o $@ $^

# arm64 빌드
arm: $(TARGET_ARM)

$(TARGET_ARM): $(SRCS)
	$(CC) $(CFLAGS) -arch arm64 $(LDFLAGS) -o $@ $^

# Universal Binary - 현재 arm64만 지원 (x64는 inline asm 호환성 문제)
universal: arm
	cp $(TARGET_ARM) $(TARGET)
	@echo "Built: $(TARGET) (arm64 only)"

# 테스트 (권한 문제로 실패할 수 있음)
test: universal
	@echo "Testing hook injection..."
	@echo "Note: May fail due to SIP restrictions"
	DYLD_INSERT_LIBRARIES=./$(TARGET) /bin/echo "Hook loaded successfully"

clean:
	rm -f $(TARGET) $(TARGET_X64) $(TARGET_ARM)

# 디버그 빌드
debug: CFLAGS += -g -DDEBUG
debug: universal

# NWN 실행 (직접 실행 방식)
# Steam 경로 수정 필요
NWN_PATH = "/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/bin/macos/nwmain.app/Contents/MacOS/nwmain"

run: universal
	@echo "Launching NWN:EE with CP949 hook..."
	@echo "Note: May require SIP disabled or binary re-signing"
	DYLD_INSERT_LIBRARIES=./$(TARGET) $(NWN_PATH) || echo "Failed - check SIP status"

# 코드 서명 제거 (SIP 우회용)
unsign:
	@echo "Removing code signature from nwmain..."
	@echo "WARNING: This modifies the game binary!"
	codesign --remove-signature $(NWN_PATH) || echo "Failed - may need sudo"

# 도움말
help:
	@echo "NWN:EE CP949 Korean Support Hook"
	@echo ""
	@echo "Targets:"
	@echo "  all/universal - Build universal binary (x64 + arm64)"
	@echo "  x64           - Build x86_64 only"
	@echo "  arm           - Build arm64 only"
	@echo "  test          - Test hook loading"
	@echo "  run           - Launch NWN with hook"
	@echo "  unsign        - Remove code signature (for SIP bypass)"
	@echo "  clean         - Remove built files"
	@echo ""
	@echo "Usage:"
	@echo "  1. make"
	@echo "  2. DYLD_INSERT_LIBRARIES=./$(TARGET) /path/to/nwmain"
