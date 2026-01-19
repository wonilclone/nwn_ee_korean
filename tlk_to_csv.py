#!/usr/bin/env python3
"""TLK to CSV converter for BioWare's TLK files (NWN, KOTOR series)"""

import struct
import csv
import sys
from pathlib import Path
from typing import List, Tuple, Optional


class TLKEntry:
    def __init__(self, strref: int, sound_ref: str, volume_variance: int, 
                 pitch_variance: int, offset: int, length: int, text: str):
        self.strref = strref
        self.sound_ref = sound_ref
        self.volume_variance = volume_variance
        self.pitch_variance = pitch_variance
        self.offset = offset
        self.length = length
        self.text = text


class TLKParser:
    def __init__(self, filepath: Path, encoding: str = 'auto'):
        self.filepath = filepath
        self.entries: List[TLKEntry] = []
        self.encoding = encoding
        
    def parse(self) -> List[TLKEntry]:
        with open(self.filepath, 'rb') as f:
            # Read header
            signature = f.read(4).decode('ascii', errors='ignore')
            version = f.read(4).decode('ascii', errors='ignore')
            
            if signature != 'TLK ':
                raise ValueError(f"Invalid TLK file signature: {signature}")
            
            # Read language ID and string count
            language_id = struct.unpack('<I', f.read(4))[0]
            string_count = struct.unpack('<I', f.read(4))[0]
            
            # Read string data offset
            string_entries_offset = struct.unpack('<I', f.read(4))[0]
            
            print(f"TLK Version: {version.strip()}")
            print(f"Language ID: {language_id}")
            print(f"String Count: {string_count}")
            print(f"String Data Offset: {string_entries_offset}")
            
            # Read string entries
            for i in range(string_count):
                # Each entry is 40 bytes
                flags = struct.unpack('<I', f.read(4))[0]
                sound_ref = f.read(16).decode('ascii', errors='ignore').rstrip('\x00')
                volume_variance = struct.unpack('<I', f.read(4))[0]
                pitch_variance = struct.unpack('<I', f.read(4))[0]
                offset = struct.unpack('<I', f.read(4))[0]
                length = struct.unpack('<I', f.read(4))[0]
                sound_length = struct.unpack('<f', f.read(4))[0]
                
                # Read the actual text from string data section
                current_pos = f.tell()
                f.seek(string_entries_offset + offset)
                text_bytes = f.read(length)
                
                # Decode text with proper encoding detection
                text = self._decode_text(text_bytes)
                
                f.seek(current_pos)
                
                entry = TLKEntry(
                    strref=i,
                    sound_ref=sound_ref,
                    volume_variance=volume_variance,
                    pitch_variance=pitch_variance,
                    offset=offset,
                    length=length,
                    text=text
                )
                
                self.entries.append(entry)
                
        return self.entries
    
    def _decode_text(self, text_bytes: bytes) -> str:
        """Decode text bytes with encoding detection"""
        # Remove null terminator first
        text_bytes = text_bytes.rstrip(b'\x00')
        
        if not text_bytes:
            return ''
        
        if self.encoding == 'auto':
            # Try multiple encodings in order of preference
            encodings = ['utf-8', 'windows-1252', 'latin-1', 'cp949', 'euc-kr', 'shift-jis']
            
            for encoding in encodings:
                try:
                    decoded = text_bytes.decode(encoding)
                    # Check if decoded text looks reasonable (no control chars except common ones)
                    if all(ord(c) >= 32 or c in '\t\n\r' for c in decoded):
                        return decoded
                except (UnicodeDecodeError, UnicodeError):
                    continue
            
            # Fallback to latin-1 which never fails
            return text_bytes.decode('latin-1', errors='replace')
        else:
            try:
                return text_bytes.decode(self.encoding, errors='replace')
            except LookupError:
                print(f"Warning: Unknown encoding {self.encoding}, using latin-1")
                return text_bytes.decode('latin-1', errors='replace')
    
    def to_csv(self, output_path: Path) -> None:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            
            # Write header
            writer.writerow([
                'StrRef', 'Text', 'SoundRef', 'VolumeVariance', 'PitchVariance'
            ])
            
            # Write entries
            for entry in self.entries:
                writer.writerow([
                    entry.strref,
                    entry.text,
                    entry.sound_ref,
                    entry.volume_variance,
                    entry.pitch_variance
                ])


def main():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python tlk_to_csv.py <tlk_file_path> [encoding]")
        print("Encodings: auto (default), utf-8, windows-1252, latin-1, cp949, euc-kr, shift-jis")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    encoding = sys.argv[2] if len(sys.argv) == 3 else 'auto'
    
    if not input_path.exists():
        print(f"Error: File {input_path} not found")
        sys.exit(1)
    
    if not input_path.suffix.lower() == '.tlk':
        print(f"Warning: File {input_path} doesn't have .tlk extension")
    
    # Generate output filename
    output_path = input_path.with_suffix('.csv')
    
    try:
        parser = TLKParser(input_path, encoding)
        entries = parser.parse()
        
        print(f"\nParsed {len(entries)} string entries")
        
        parser.to_csv(output_path)
        
        print(f"Successfully converted {input_path} to {output_path}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()