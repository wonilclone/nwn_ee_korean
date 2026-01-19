#!/usr/bin/env python3
"""CSV to TLK converter for BioWare's TLK files (NWN, KOTOR series)

NWN:EE 한글 패치 호환:
- --reference 옵션으로 원본 TLK의 플래그/사운드 정보 유지
- 언어 ID를 0으로 설정 (원본과 동일)
- 누락된 텍스트는 원본에서 가져옴
"""

import struct
import csv
import sys
from pathlib import Path
from typing import List, Optional, Dict


class CSVToTLKConverter:
    def __init__(self, csv_path: Path, encoding: str = 'auto',
                 reference_tlk: Optional[Path] = None, language_id: int = 0,
                 debug_mode: bool = False):
        self.csv_path = csv_path
        self.entries = []
        self.encoding = encoding
        self.reference_tlk = reference_tlk
        self.language_id = language_id
        self.debug_mode = debug_mode  # 검수 모드: 텍스트 앞에 [StrRef] 추가
        self.reference_entries = {}  # 원본 TLK 엔트리 캐시
        self.reference_texts = {}    # 원본 TLK 텍스트 캐시
        
    def load_csv(self) -> None:
        """Load CSV file and parse entries"""
        with open(self.csv_path, 'r', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            
            # Verify required columns exist
            required_columns = ['StrRef', 'Text', 'SoundRef', 'VolumeVariance', 'PitchVariance']
            if not all(col in reader.fieldnames for col in required_columns):
                raise ValueError(f"CSV must contain columns: {required_columns}")
            
            for row in reader:
                try:
                    entry = {
                        'strref': int(row['StrRef']),
                        'text': row['Text'] or '',  # Handle empty text
                        'sound_ref': row['SoundRef'] or '',
                        'volume_variance': int(row['VolumeVariance'] or '0'),
                        'pitch_variance': int(row['PitchVariance'] or '0')
                    }
                    self.entries.append(entry)
                except ValueError as e:
                    print(f"Warning: Skipping invalid row {reader.line_num}: {e}")

        # Create entry lookup by StrRef
        entry_dict = {entry['strref']: entry for entry in self.entries}

        # Find max StrRef to determine array size
        max_strref = max(entry_dict.keys()) if entry_dict else 0

        # Build complete entry array with gaps filled
        self.entries = []
        for strref in range(max_strref + 1):
            if strref in entry_dict:
                self.entries.append(entry_dict[strref])
            else:
                # Fill gap with empty entry
                self.entries.append({
                    'strref': strref,
                    'text': '',
                    'sound_ref': '',
                    'volume_variance': 0,
                    'pitch_variance': 0
                })

        print(f"Loaded {len(entry_dict)} entries from CSV (max StrRef: {max_strref})")
        print(f"Created TLK array with {len(self.entries)} entries (including {len(self.entries) - len(entry_dict)} gap entries)")

    def load_reference_tlk(self) -> None:
        """원본 TLK 파일에서 엔트리 정보 로드"""
        if not self.reference_tlk or not self.reference_tlk.exists():
            return

        print(f"Loading reference TLK: {self.reference_tlk}")

        with open(self.reference_tlk, 'rb') as f:
            # 헤더 읽기
            signature = f.read(4)
            version = f.read(4)
            lang_id = struct.unpack('<I', f.read(4))[0]
            string_count = struct.unpack('<I', f.read(4))[0]
            string_entries_offset = struct.unpack('<I', f.read(4))[0]

            print(f"  Reference TLK: {string_count} strings, language ID: {lang_id}")

            # 모든 엔트리 읽기
            for i in range(string_count):
                entry_offset = 20 + (i * 40)
                f.seek(entry_offset)

                flags = struct.unpack('<I', f.read(4))[0]
                sound_resref = f.read(16).rstrip(b'\x00').decode('ascii', errors='replace')
                volume_var = struct.unpack('<I', f.read(4))[0]
                pitch_var = struct.unpack('<I', f.read(4))[0]
                str_offset = struct.unpack('<I', f.read(4))[0]
                str_size = struct.unpack('<I', f.read(4))[0]
                sound_length = struct.unpack('<f', f.read(4))[0]

                self.reference_entries[i] = {
                    'flags': flags,
                    'sound_resref': sound_resref,
                    'volume_var': volume_var,
                    'pitch_var': pitch_var,
                    'sound_length': sound_length,
                }

                # 텍스트 읽기 (원본 텍스트 백업용)
                if flags & 0x01 and str_size > 0:
                    f.seek(string_entries_offset + str_offset)
                    text_bytes = f.read(str_size)
                    try:
                        self.reference_texts[i] = text_bytes.decode('cp1252')
                    except:
                        try:
                            self.reference_texts[i] = text_bytes.decode('utf-8')
                        except:
                            self.reference_texts[i] = text_bytes.decode('latin-1', errors='replace')

            # 언어 ID를 원본과 동일하게 (명시적으로 지정하지 않은 경우)
            if self.language_id == 0:
                self.language_id = lang_id

        print(f"  Loaded {len(self.reference_entries)} reference entries")
        print(f"  Loaded {len(self.reference_texts)} reference texts")

    def write_tlk(self, output_path: Path) -> None:
        """Write TLK file"""
        # 원본 TLK가 있으면 로드
        if self.reference_tlk:
            self.load_reference_tlk()

        # 원본 TLK가 있으면 문자열 개수를 원본과 맞춤
        if self.reference_entries:
            ref_count = max(self.reference_entries.keys()) + 1
            if ref_count > len(self.entries):
                print(f"Extending entry count from {len(self.entries)} to {ref_count} (matching reference)")
                for strref in range(len(self.entries), ref_count):
                    self.entries.append({
                        'strref': strref,
                        'text': '',
                        'sound_ref': '',
                        'volume_variance': 0,
                        'pitch_variance': 0
                    })

        with open(output_path, 'wb') as f:
            # Write header
            f.write(b'TLK ')  # Signature
            f.write(b'V3.0')  # Version

            # Language ID (0 for NWN:EE compatibility)
            f.write(struct.pack('<I', self.language_id))

            # String count (total array size including gaps)
            string_count = len(self.entries)
            f.write(struct.pack('<I', string_count))

            # Calculate string data offset
            # Header: 20 bytes + (40 bytes per entry)
            string_data_offset = 20 + (string_count * 40)
            f.write(struct.pack('<I', string_data_offset))

            # Prepare string data and write entries
            string_data = bytearray()
            current_offset = 0
            fallback_count = 0

            for i, entry in enumerate(self.entries):
                strref = entry['strref']

                # 텍스트 결정: CSV 텍스트 > 원본 텍스트
                text = entry['text']
                if not text and strref in self.reference_texts:
                    text = self.reference_texts[strref]
                    fallback_count += 1

                # 검수 모드: 텍스트 앞에 [StrRef] 추가
                if self.debug_mode and text:
                    text = f"[{strref}]{text}"

                # Encode text to bytes with proper encoding
                text_bytes = self._encode_text(text)

                # 원본 TLK에서 플래그/사운드 정보 가져오기
                if strref in self.reference_entries:
                    ref = self.reference_entries[strref]
                    # 원본 플래그 유지 (TEXT_PRESENT는 텍스트 유무에 따라 조정)
                    flags = ref['flags']
                    if text:
                        flags |= 0x01  # TEXT_PRESENT 설정
                    else:
                        flags &= ~0x01  # TEXT_PRESENT 해제

                    sound_ref = ref['sound_resref']
                    volume_var = ref['volume_var']
                    pitch_var = ref['pitch_var']
                    sound_length = ref['sound_length']
                else:
                    # 원본 정보 없으면 CSV에서 가져옴
                    flags = 0x01 if text else 0x00
                    sound_ref = entry['sound_ref']
                    volume_var = entry['volume_variance']
                    pitch_var = entry['pitch_variance']
                    sound_length = 0.0

                # Write entry (40 bytes)
                f.write(struct.pack('<I', flags))

                # Sound reference (16 bytes, padded with null bytes)
                sound_ref_bytes = sound_ref.encode('ascii', errors='ignore')[:16]
                sound_ref_bytes += b'\x00' * (16 - len(sound_ref_bytes))
                f.write(sound_ref_bytes)

                # Volume and pitch variance
                f.write(struct.pack('<I', volume_var))
                f.write(struct.pack('<I', pitch_var))

                # String offset and length
                f.write(struct.pack('<I', current_offset))
                f.write(struct.pack('<I', len(text_bytes)))

                # Sound length
                f.write(struct.pack('<f', sound_length))

                # Add to string data
                string_data.extend(text_bytes)
                current_offset += len(text_bytes)

            # Write string data section
            f.write(string_data)

        print(f"Successfully wrote TLK file: {output_path}")
        print(f"Written {len(self.entries)} string entries")
        if fallback_count > 0:
            print(f"Used {fallback_count} fallback texts from reference TLK")
    
    def _encode_text(self, text: str) -> bytes:
        """Encode text with proper encoding"""
        if not text:
            return b''  # 빈 텍스트는 빈 바이트열 반환
            
        # Convert literal '\n' strings to actual newline characters
        text = text.replace('\\n', '\n')
            
        if self.encoding == 'auto':
            # Check if text contains Korean characters
            korean_chars = any('\uac00' <= char <= '\ud7af' for char in text)
            
            if korean_chars:
                # Use CP949 (EUC-KR) for Korean text
                try:
                    # Replace characters not supported by CP949
                    text_fixed = text.replace('—', '-')  # Replace em dash with regular dash
                    text_fixed = text_fixed.replace('–', '-')  # Replace en dash with regular dash
                    text_fixed = text_fixed.replace('\u00a0', ' ')  # Replace non-breaking space with regular space
                    return text_fixed.encode('cp949')
                except UnicodeEncodeError as e:
                    print(f"Warning: Cannot encode Korean text with CP949: {e}")
                    print(f"Text: {text[:50]}")
                    return text.encode('utf-8', errors='replace')
            else:
                # For non-Korean text, try CP1252 first (NWN native encoding)
                try:
                    return text.encode('cp1252')
                except UnicodeEncodeError:
                    pass

                # Fallback to UTF-8 with replacement
                return text.encode('utf-8', errors='replace')
        else:
            try:
                return text.encode(self.encoding)
            except (UnicodeEncodeError, LookupError):
                print(f"Warning: Cannot encode with {self.encoding}, using UTF-8")
                return text.encode('utf-8', errors='replace')


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='CSV to TLK converter for BioWare games (NWN, KOTOR)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # 기본 변환
  python csv_to_tlk.py dialog.csv

  # 원본 TLK 참조하여 변환 (NWN:EE 한글 패치용)
  python csv_to_tlk.py dialog.csv -r /path/to/original/dialog.tlk

  # 출력 파일 지정
  python csv_to_tlk.py dialog.csv -o output.tlk

  # 인코딩 지정
  python csv_to_tlk.py dialog.csv -e cp949
        '''
    )

    parser.add_argument('csv_file', help='Input CSV file')
    parser.add_argument('-o', '--output', help='Output TLK file (default: same name with .tlk)')
    parser.add_argument('-e', '--encoding', default='auto',
                        choices=['auto', 'utf-8', 'windows-1252', 'latin-1', 'cp949', 'euc-kr', 'shift-jis'],
                        help='Text encoding (default: auto)')
    parser.add_argument('-r', '--reference',
                        default='/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights/lang/en/data/dialog.tlk',
                        help='Reference TLK file for flags/sound info (default: NWN:EE English dialog.tlk)')
    parser.add_argument('--no-reference', action='store_true',
                        help='Do not use reference TLK file')
    parser.add_argument('-l', '--language-id', type=int, default=0,
                        help='Language ID (default: 0, use reference TLK value if available)')
    parser.add_argument('-d', '--debug', action='store_true',
                        help='Debug/검수 mode: prepend [StrRef] to each text (e.g., [21]안녕하세요)')

    args = parser.parse_args()

    input_path = Path(args.csv_file)
    output_path = Path(args.output) if args.output else input_path.with_suffix('.tlk')
    reference_tlk = None if args.no_reference else (Path(args.reference) if args.reference else None)

    if not input_path.exists():
        print(f"Error: File {input_path} not found")
        sys.exit(1)

    if not input_path.suffix.lower() == '.csv':
        print(f"Warning: File {input_path} doesn't have .csv extension")

    if reference_tlk and not reference_tlk.exists():
        print(f"Error: Reference TLK file {reference_tlk} not found")
        sys.exit(1)

    try:
        converter = CSVToTLKConverter(
            input_path,
            encoding=args.encoding,
            reference_tlk=reference_tlk,
            language_id=args.language_id,
            debug_mode=args.debug
        )
        converter.load_csv()
        converter.write_tlk(output_path)

        if args.debug:
            print(f"\n⚠️  검수 모드로 빌드됨: 모든 텍스트 앞에 [StrRef]가 추가됨")

        print(f"\nSuccessfully converted {input_path} to {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()