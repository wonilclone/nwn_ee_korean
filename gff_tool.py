#!/usr/bin/env python3
"""
GFF (Generic File Format) parser and writer for NWN:EE.
Supports reading, modifying, and writing GFF files (.bic, .dlg, .utc, .uti, etc.)
"""

import struct
import sys
import argparse
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Union


# GFF field type constants
BYTE = 0
CHAR = 1
WORD = 2
SHORT = 3
DWORD = 4
INT = 5
DWORD64 = 6
INT64 = 7
FLOAT = 8
DOUBLE = 9
CEXOSTRING = 10
RESREF = 11
CEXOLOCSTRING = 12
VOID = 13
STRUCT = 14
LIST = 15

TYPE_NAMES = {
    BYTE: 'BYTE', CHAR: 'CHAR', WORD: 'WORD', SHORT: 'SHORT',
    DWORD: 'DWORD', INT: 'INT', DWORD64: 'DWORD64', INT64: 'INT64',
    FLOAT: 'FLOAT', DOUBLE: 'DOUBLE', CEXOSTRING: 'CExoString',
    RESREF: 'ResRef', CEXOLOCSTRING: 'CExoLocString', VOID: 'VOID',
    STRUCT: 'Struct', LIST: 'List',
}

# Types where value fits in the 4-byte data field (no field_data offset needed)
SIMPLE_TYPES = {BYTE, CHAR, WORD, SHORT, DWORD, INT, FLOAT}


class CExoLocString:
    """Localized string with optional TLK reference and language-specific substrings."""

    def __init__(self, strref: int = -1, substrings: Optional[dict] = None):
        self.strref = strref
        self.substrings = substrings or {}  # lang_id -> text

    def __repr__(self):
        parts = []
        if self.strref != -1:
            parts.append(f'strref={self.strref}')
        for lang_id, text in sorted(self.substrings.items()):
            parts.append(f'lang{lang_id}="{text}"')
        return f'CExoLocString({", ".join(parts)})'

    def get_text(self, lang_id: int = 0) -> str:
        return self.substrings.get(lang_id, '')

    def set_text(self, text: str, lang_id: int = 0):
        self.substrings[lang_id] = text


class GffStruct:
    """A GFF struct containing named fields."""

    def __init__(self, type_id: int = 0xFFFFFFFF):
        self.type_id = type_id
        self.fields: OrderedDict[str, tuple] = OrderedDict()  # label -> (field_type, value)

    def __getitem__(self, label: str):
        return self.fields[label][1]

    def __setitem__(self, label: str, value):
        if label in self.fields:
            field_type = self.fields[label][0]
            self.fields[label] = (field_type, value)
        else:
            raise KeyError(f"Field '{label}' not found. Use set_field() to add new fields.")

    def __contains__(self, label: str):
        return label in self.fields

    def get_type(self, label: str) -> int:
        return self.fields[label][0]

    def set_field(self, label: str, field_type: int, value):
        self.fields[label] = (field_type, value)


class GffFile:
    """A complete GFF file that can be parsed, modified, and serialized."""

    def __init__(self):
        self.file_type = 'GFF '
        self.file_version = 'V3.2'
        self.root = GffStruct()

    @classmethod
    def load(cls, path: Union[str, Path]) -> 'GffFile':
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    def save(self, path: Union[str, Path]):
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    @classmethod
    def from_bytes(cls, data: bytes) -> 'GffFile':
        if len(data) < 56:
            raise ValueError("Data too short for GFF header")

        gff = cls()
        gff.file_type = data[0:4].decode('ascii')
        gff.file_version = data[4:8].decode('ascii')

        # Parse header offsets
        struct_offset = struct.unpack_from('<I', data, 8)[0]
        struct_count = struct.unpack_from('<I', data, 12)[0]
        field_offset = struct.unpack_from('<I', data, 16)[0]
        field_count = struct.unpack_from('<I', data, 20)[0]
        label_offset = struct.unpack_from('<I', data, 24)[0]
        label_count = struct.unpack_from('<I', data, 28)[0]
        field_data_offset = struct.unpack_from('<I', data, 32)[0]
        field_data_size = struct.unpack_from('<I', data, 36)[0]
        field_indices_offset = struct.unpack_from('<I', data, 40)[0]
        field_indices_size = struct.unpack_from('<I', data, 44)[0]
        list_indices_offset = struct.unpack_from('<I', data, 48)[0]
        list_indices_size = struct.unpack_from('<I', data, 52)[0]

        # Read raw arrays
        raw_structs = []
        for i in range(struct_count):
            off = struct_offset + i * 12
            s_type = struct.unpack_from('<I', data, off)[0]
            s_data = struct.unpack_from('<I', data, off + 4)[0]
            s_count = struct.unpack_from('<I', data, off + 8)[0]
            raw_structs.append((s_type, s_data, s_count))

        raw_fields = []
        for i in range(field_count):
            off = field_offset + i * 12
            f_type = struct.unpack_from('<I', data, off)[0]
            f_label = struct.unpack_from('<I', data, off + 4)[0]
            f_data = struct.unpack_from('<I', data, off + 8)[0]
            raw_fields.append((f_type, f_label, f_data))

        labels = []
        for i in range(label_count):
            off = label_offset + i * 16
            label = data[off:off + 16].split(b'\x00')[0].decode('ascii', errors='replace')
            labels.append(label)

        def get_field_indices(s_data, s_count):
            if s_count == 1:
                return [s_data]
            indices = []
            for j in range(s_count):
                off = field_indices_offset + s_data + j * 4
                indices.append(struct.unpack_from('<I', data, off)[0])
            return indices

        def get_list_structs(list_off):
            off = list_indices_offset + list_off
            count = struct.unpack_from('<I', data, off)[0]
            return [struct.unpack_from('<I', data, off + 4 + j * 4)[0] for j in range(count)]

        def read_cexostring(fd_off):
            off = field_data_offset + fd_off
            length = struct.unpack_from('<I', data, off)[0]
            return data[off + 4:off + 4 + length].decode('utf-8', errors='replace')

        def read_resref(fd_off):
            off = field_data_offset + fd_off
            length = struct.unpack_from('<B', data, off)[0]
            return data[off + 1:off + 1 + length].decode('ascii', errors='replace')

        def read_cexolocstring(fd_off):
            off = field_data_offset + fd_off
            total_len = struct.unpack_from('<I', data, off)[0]
            strref = struct.unpack_from('<i', data, off + 4)[0]
            substr_count = struct.unpack_from('<I', data, off + 8)[0]
            substrings = {}
            pos = off + 12
            for _ in range(substr_count):
                lang_id = struct.unpack_from('<I', data, pos)[0]
                str_len = struct.unpack_from('<I', data, pos + 4)[0]
                text_bytes = data[pos + 8:pos + 8 + str_len]
                # Try UTF-8 first, fall back to CP949 then CP1252
                for enc in ('utf-8', 'cp949', 'cp1252'):
                    try:
                        text = text_bytes.decode(enc)
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
                else:
                    text = text_bytes.decode('latin-1')
                substrings[lang_id] = text
                pos += 8 + str_len
            return CExoLocString(strref, substrings)

        def read_void(fd_off):
            off = field_data_offset + fd_off
            length = struct.unpack_from('<I', data, off)[0]
            return data[off + 4:off + 4 + length]

        def parse_struct(struct_idx):
            s_type, s_data, s_count = raw_structs[struct_idx]
            gs = GffStruct(s_type)
            if s_count == 0:
                return gs

            field_indices = get_field_indices(s_data, s_count)
            for fidx in field_indices:
                f_type, f_label_idx, f_data = raw_fields[fidx]
                label = labels[f_label_idx] if f_label_idx < len(labels) else f'_unknown_{f_label_idx}'

                if f_type == BYTE:
                    value = f_data & 0xFF
                elif f_type == CHAR:
                    value = struct.unpack('b', struct.pack('B', f_data & 0xFF))[0]
                elif f_type == WORD:
                    value = f_data & 0xFFFF
                elif f_type == SHORT:
                    value = struct.unpack('h', struct.pack('H', f_data & 0xFFFF))[0]
                elif f_type == DWORD:
                    value = f_data
                elif f_type == INT:
                    value = struct.unpack('i', struct.pack('I', f_data))[0]
                elif f_type == FLOAT:
                    value = struct.unpack('f', struct.pack('I', f_data))[0]
                elif f_type == DWORD64:
                    off = field_data_offset + f_data
                    value = struct.unpack_from('<Q', data, off)[0]
                elif f_type == INT64:
                    off = field_data_offset + f_data
                    value = struct.unpack_from('<q', data, off)[0]
                elif f_type == DOUBLE:
                    off = field_data_offset + f_data
                    value = struct.unpack_from('<d', data, off)[0]
                elif f_type == CEXOSTRING:
                    value = read_cexostring(f_data)
                elif f_type == RESREF:
                    value = read_resref(f_data)
                elif f_type == CEXOLOCSTRING:
                    value = read_cexolocstring(f_data)
                elif f_type == VOID:
                    value = read_void(f_data)
                elif f_type == STRUCT:
                    value = parse_struct(f_data)
                elif f_type == LIST:
                    struct_indices = get_list_structs(f_data)
                    value = [parse_struct(si) for si in struct_indices]
                else:
                    value = f_data

                gs.set_field(label, f_type, value)

            return gs

        gff.root = parse_struct(0)
        return gff

    def to_bytes(self) -> bytes:
        """Serialize the GFF tree back to binary format."""
        # Collect all unique labels
        label_set = OrderedDict()

        def collect_labels(gs: GffStruct):
            for label, (ft, val) in gs.fields.items():
                if label not in label_set:
                    label_set[label] = len(label_set)
                if ft == STRUCT and isinstance(val, GffStruct):
                    collect_labels(val)
                elif ft == LIST and isinstance(val, list):
                    for item in val:
                        collect_labels(item)

        collect_labels(self.root)

        # Build sections
        struct_array = bytearray()
        field_array = bytearray()
        field_data = bytearray()
        field_indices = bytearray()
        list_indices = bytearray()

        struct_idx_counter = [0]
        field_idx_counter = [0]

        def reserve_struct():
            idx = struct_idx_counter[0]
            struct_idx_counter[0] += 1
            struct_array.extend(b'\x00' * 12)
            return idx

        def write_struct(idx, s_type, data_or_offset, field_count):
            off = idx * 12
            struct.pack_into('<III', struct_array, off, s_type, data_or_offset, field_count)

        def add_field(f_type, label_idx, f_data):
            idx = field_idx_counter[0]
            field_idx_counter[0] += 1
            field_array.extend(struct.pack('<III', f_type, label_idx, f_data))
            return idx

        def write_field_data_cexostring(text: str) -> int:
            offset = len(field_data)
            encoded = text.encode('utf-8')
            field_data.extend(struct.pack('<I', len(encoded)))
            field_data.extend(encoded)
            return offset

        def write_field_data_resref(text: str) -> int:
            offset = len(field_data)
            encoded = text.encode('ascii', errors='replace')[:16]
            field_data.extend(struct.pack('<B', len(encoded)))
            field_data.extend(encoded)
            return offset

        def write_field_data_cexolocstring(loc: CExoLocString) -> int:
            offset = len(field_data)
            # Build substring data first
            substr_data = bytearray()
            for lang_id in sorted(loc.substrings.keys()):
                text = loc.substrings[lang_id]
                encoded = text.encode('cp949', errors='replace')
                substr_data.extend(struct.pack('<II', lang_id, len(encoded)))
                substr_data.extend(encoded)
            total_len = 8 + len(substr_data)  # strref(4) + count(4) + substrings
            field_data.extend(struct.pack('<I', total_len))
            field_data.extend(struct.pack('<i', loc.strref))
            field_data.extend(struct.pack('<I', len(loc.substrings)))
            field_data.extend(substr_data)
            return offset

        def write_field_data_void(raw: bytes) -> int:
            offset = len(field_data)
            field_data.extend(struct.pack('<I', len(raw)))
            field_data.extend(raw)
            return offset

        def write_field_data_64(fmt: str, value) -> int:
            offset = len(field_data)
            field_data.extend(struct.pack(fmt, value))
            return offset

        def serialize_struct(gs: GffStruct) -> int:
            sidx = reserve_struct()
            field_count = len(gs.fields)

            if field_count == 0:
                write_struct(sidx, gs.type_id, 0, 0)
                return sidx

            field_idxs = []
            for label, (ft, val) in gs.fields.items():
                li = label_set[label]

                if ft in SIMPLE_TYPES:
                    if ft == BYTE:
                        raw = val & 0xFF
                    elif ft == CHAR:
                        raw = struct.unpack('I', struct.pack('i', val if val >= 0 else val))[0] & 0xFF
                    elif ft == WORD:
                        raw = val & 0xFFFF
                    elif ft == SHORT:
                        raw = struct.unpack('I', struct.pack('i', val if val >= 0 else val))[0] & 0xFFFF
                    elif ft == DWORD:
                        raw = val
                    elif ft == INT:
                        raw = struct.unpack('I', struct.pack('i', val))[0]
                    elif ft == FLOAT:
                        raw = struct.unpack('I', struct.pack('f', val))[0]
                    else:
                        raw = val
                    fidx = add_field(ft, li, raw)

                elif ft == DWORD64:
                    fd_off = write_field_data_64('<Q', val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == INT64:
                    fd_off = write_field_data_64('<q', val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == DOUBLE:
                    fd_off = write_field_data_64('<d', val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == CEXOSTRING:
                    fd_off = write_field_data_cexostring(val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == RESREF:
                    fd_off = write_field_data_resref(val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == CEXOLOCSTRING:
                    fd_off = write_field_data_cexolocstring(val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == VOID:
                    fd_off = write_field_data_void(val)
                    fidx = add_field(ft, li, fd_off)
                elif ft == STRUCT:
                    child_sidx = serialize_struct(val)
                    fidx = add_field(ft, li, child_sidx)
                elif ft == LIST:
                    # Serialize all children first (recursive calls may append to list_indices)
                    child_sidxs = [serialize_struct(item) for item in val]
                    # Then write the complete, contiguous list entry
                    list_off = len(list_indices)
                    list_indices.extend(struct.pack('<I', len(val)))
                    for cs in child_sidxs:
                        list_indices.extend(struct.pack('<I', cs))
                    fidx = add_field(ft, li, list_off)
                else:
                    fidx = add_field(ft, li, val)

                field_idxs.append(fidx)

            if field_count == 1:
                write_struct(sidx, gs.type_id, field_idxs[0], 1)
            else:
                fi_offset = len(field_indices)
                for fi in field_idxs:
                    field_indices.extend(struct.pack('<I', fi))
                write_struct(sidx, gs.type_id, fi_offset, field_count)

            return sidx

        serialize_struct(self.root)

        # Build label array
        label_array = bytearray()
        for label in label_set:
            encoded = label.encode('ascii')[:16]
            label_array.extend(encoded.ljust(16, b'\x00'))

        # Build header
        header = bytearray(56)
        header[0:4] = self.file_type.encode('ascii')
        header[4:8] = self.file_version.encode('ascii')

        offset = 56
        struct.pack_into('<II', header, 8, offset, len(struct_array) // 12)
        offset += len(struct_array)
        struct.pack_into('<II', header, 16, offset, len(field_array) // 12)
        offset += len(field_array)
        struct.pack_into('<II', header, 24, offset, len(label_array) // 16)
        offset += len(label_array)
        struct.pack_into('<II', header, 32, offset, len(field_data))
        offset += len(field_data)
        struct.pack_into('<II', header, 40, offset, len(field_indices))
        offset += len(field_indices)
        struct.pack_into('<II', header, 48, offset, len(list_indices))

        return bytes(header) + bytes(struct_array) + bytes(field_array) + bytes(label_array) + bytes(field_data) + bytes(field_indices) + bytes(list_indices)

    def dump(self, max_depth: int = 3):
        """Print a human-readable dump of the GFF tree."""
        def dump_struct(gs: GffStruct, indent: int = 0, depth: int = 0):
            prefix = '  ' * indent
            for label, (ft, val) in gs.fields.items():
                type_name = TYPE_NAMES.get(ft, f'?{ft}')
                if ft == CEXOLOCSTRING:
                    print(f'{prefix}{label} ({type_name}): {val}')
                elif ft == CEXOSTRING:
                    display = val if len(val) <= 80 else val[:77] + '...'
                    print(f'{prefix}{label} ({type_name}): "{display}"')
                elif ft == RESREF:
                    print(f'{prefix}{label} ({type_name}): "{val}"')
                elif ft == VOID:
                    print(f'{prefix}{label} ({type_name}): [{len(val)} bytes]')
                elif ft == STRUCT:
                    print(f'{prefix}{label} ({type_name}, type={val.type_id}):')
                    if depth < max_depth:
                        dump_struct(val, indent + 1, depth + 1)
                    else:
                        print(f'{prefix}  ... ({len(val.fields)} fields)')
                elif ft == LIST:
                    print(f'{prefix}{label} ({type_name}, {len(val)} items):')
                    if depth < max_depth:
                        for i, item in enumerate(val):
                            print(f'{prefix}  [{i}] (type={item.type_id}):')
                            dump_struct(item, indent + 2, depth + 1)
                    else:
                        print(f'{prefix}  ... ({len(val)} structs)')
                elif ft == FLOAT:
                    print(f'{prefix}{label} ({type_name}): {val:.4f}')
                elif ft == DOUBLE:
                    print(f'{prefix}{label} ({type_name}): {val:.6f}')
                else:
                    print(f'{prefix}{label} ({type_name}): {val}')

        print(f'GFF Type: {self.file_type.strip()}, Version: {self.file_version.strip()}')
        print(f'Root struct (type={self.root.type_id}, {len(self.root.fields)} fields):')
        dump_struct(self.root)


def main():
    parser = argparse.ArgumentParser(description='NWN GFF file tool')
    parser.add_argument('input', help='Input GFF file (.bic, .dlg, .utc, etc.)')
    parser.add_argument('--dump', action='store_true', help='Dump GFF structure')
    parser.add_argument('--depth', type=int, default=3, help='Max dump depth (default: 3)')
    parser.add_argument('--set', action='append', metavar='FIELD=VALUE',
                        help='Set CExoLocString field value (e.g. FirstName="래스터")')
    parser.add_argument('-o', '--output', help='Output file path')

    args = parser.parse_args()

    gff = GffFile.load(args.input)

    if args.dump:
        gff.dump(max_depth=args.depth)
        return

    if args.set:
        for assignment in args.set:
            if '=' not in assignment:
                print(f'Error: Invalid --set format: {assignment} (expected FIELD=VALUE)')
                sys.exit(1)
            field_name, value = assignment.split('=', 1)
            # Strip quotes
            value = value.strip('"').strip("'")

            if field_name not in gff.root:
                print(f'Error: Field "{field_name}" not found in root struct')
                sys.exit(1)

            ft = gff.root.get_type(field_name)
            if ft == CEXOLOCSTRING:
                loc = gff.root[field_name]
                old_text = loc.get_text(0)
                loc.set_text(value, 0)
                print(f'{field_name}: "{old_text}" -> "{value}"')
            elif ft == CEXOSTRING:
                old_text = gff.root[field_name]
                gff.root[field_name] = value
                print(f'{field_name}: "{old_text}" -> "{value}"')
            else:
                print(f'Error: Field "{field_name}" is type {TYPE_NAMES.get(ft, ft)}, '
                      f'only CExoLocString and CExoString are supported')
                sys.exit(1)

        output = args.output or args.input
        gff.save(output)
        print(f'Saved to: {output}')


if __name__ == '__main__':
    main()
