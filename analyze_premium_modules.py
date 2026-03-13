#!/usr/bin/env python3
"""
Analyze NWN:EE premium module files.
- Parse ERF format (.mod/.nwm/.hak) to list resources
- Parse GFF format (module.ifo) to extract hak list
- Count .dlg files in each archive
"""

import struct
import os
import sys
from pathlib import Path
from collections import defaultdict

NWN_BASE = Path("/Users/mac/Library/Application Support/Steam/steamapps/common/Neverwinter Nights")
DATA_DIR = NWN_BASE / "data"
MOD_DIR = DATA_DIR / "mod"
NWM_DIR = DATA_DIR / "nwm"
HAK_DIR = DATA_DIR / "hk"

# NWN resource type IDs
RES_TYPES = {
    0x0001: ".bmp",
    0x0003: ".tga",
    0x0004: ".wav",
    0x0006: ".plt",
    0x0007: ".ini",
    0x000A: ".txt",
    0x07D2: ".mdl",
    0x07D9: ".nss",
    0x07DA: ".ncs",
    0x07DB: ".mod",  # actually area (are)
    0x07DC: ".are",
    0x07DD: ".set",
    0x07DE: ".ifo",
    0x07DF: ".bic",
    0x07E0: ".wok",
    0x07E1: ".2da",
    0x07E6: ".txi",
    0x07E7: ".git",
    0x07E9: ".uti",
    0x07EA: ".utc",
    0x07EB: ".dlg",
    0x07EC: ".itp",
    0x07ED: ".utt",
    0x07EE: ".dds",
    0x07EF: ".uts",
    0x07F0: ".ltr",
    0x07F1: ".gff",
    0x07F2: ".fac",
    0x07F4: ".ute",
    0x07F5: ".utd",
    0x07F6: ".utp",
    0x07F7: ".dft",
    0x07F8: ".gic",
    0x07F9: ".gui",
    0x07FE: ".utm",
    0x07FF: ".dwk",
    0x0800: ".pwk",
    0x0803: ".jrl",
    0x0804: ".sav",
    0x0805: ".utw",
    0x0808: ".ssf",
    0x080C: ".ndb",
    0x080D: ".ptm",
    0x080E: ".ptt",
    0x0BB8: ".lyt",
    0x0BB9: ".vis",
    0x0BBA: ".rim",  # actually .rim
    0x0BBB: ".pth",
    0x0BBC: ".lip",
    0x270D: ".tpc",
    0x270C: ".ids",
    0x270E: ".mdx",
    0x2712: ".wal",
}

DLG_TYPE = 0x07EB
IFO_TYPE = 0x07DE


def read_erf_entries(filepath):
    """Read ERF/MOD/HAK/NWM file and return list of (resref, res_type) tuples."""
    entries = []
    try:
        with open(filepath, 'rb') as f:
            # Read header
            file_type = f.read(4).decode('ascii', errors='replace').strip()
            file_version = f.read(4).decode('ascii', errors='replace').strip()

            # Localized string count (4), localized string size (4), entry count (4)
            loc_str_count = struct.unpack('<I', f.read(4))[0]
            loc_str_size = struct.unpack('<I', f.read(4))[0]
            entry_count = struct.unpack('<I', f.read(4))[0]

            # Offset to localized strings (4), offset to key list (4), offset to resource list (4)
            off_loc_str = struct.unpack('<I', f.read(4))[0]
            off_key_list = struct.unpack('<I', f.read(4))[0]
            off_res_list = struct.unpack('<I', f.read(4))[0]

            # Skip rest of header (build year, build day, description strref, padding)
            # Total header = 160 bytes, we've read 40 so far
            f.read(160 - 40)

            # Read key list
            f.seek(off_key_list)
            for i in range(entry_count):
                # ResRef: 16 bytes (null-terminated string)
                resref_raw = f.read(16)
                resref = resref_raw.split(b'\x00')[0].decode('ascii', errors='replace').lower()

                # ResID: 4 bytes
                res_id = struct.unpack('<I', f.read(4))[0]

                # ResType: 2 bytes
                res_type = struct.unpack('<H', f.read(2))[0]

                # Unused: 2 bytes
                f.read(2)

                entries.append((resref, res_type, res_id))

            # Read resource list (offsets and sizes)
            f.seek(off_res_list)
            res_list = []
            for i in range(entry_count):
                offset = struct.unpack('<I', f.read(4))[0]
                size = struct.unpack('<I', f.read(4))[0]
                res_list.append((offset, size))

            # Combine entries with their offsets/sizes
            full_entries = []
            for i, (resref, res_type, res_id) in enumerate(entries):
                offset, size = res_list[i]
                full_entries.append((resref, res_type, res_id, offset, size))

            return file_type, file_version, full_entries
    except Exception as e:
        print(f"  ERROR reading {filepath}: {e}")
        return None, None, []


def read_resource_data(filepath, offset, size):
    """Read raw resource data from an ERF file."""
    with open(filepath, 'rb') as f:
        f.seek(offset)
        return f.read(size)


def parse_gff_for_haklist(data):
    """Parse a GFF binary (module.ifo) and extract Mod_HakList entries."""
    if len(data) < 56:
        return []

    # GFF Header
    file_type = data[0:4].decode('ascii', errors='replace')
    file_version = data[4:8].decode('ascii', errors='replace')

    struct_offset = struct.unpack_from('<I', data, 8)[0]
    struct_count = struct.unpack_from('<I', data, 12)[0]
    field_offset = struct.unpack_from('<I', data, 16)[0]
    field_count = struct.unpack_from('<I', data, 20)[0]
    label_offset = struct.unpack_from('<I', data, 24)[0]
    label_count = struct.unpack_from('<I', data, 28)[0]
    field_data_offset = struct.unpack_from('<I', data, 32)[0]
    field_data_count = struct.unpack_from('<I', data, 36)[0]
    field_indices_offset = struct.unpack_from('<I', data, 40)[0]
    field_indices_count = struct.unpack_from('<I', data, 44)[0]
    list_indices_offset = struct.unpack_from('<I', data, 48)[0]
    list_indices_count = struct.unpack_from('<I', data, 52)[0]

    # Read all labels
    labels = []
    for i in range(label_count):
        off = label_offset + i * 16
        label = data[off:off+16].split(b'\x00')[0].decode('ascii', errors='replace')
        labels.append(label)

    # Read all structs
    structs = []
    for i in range(struct_count):
        off = struct_offset + i * 12
        s_type = struct.unpack_from('<I', data, off)[0]
        s_data_or_offset = struct.unpack_from('<I', data, off + 4)[0]
        s_field_count = struct.unpack_from('<I', data, off + 8)[0]
        structs.append((s_type, s_data_or_offset, s_field_count))

    # GFF field types
    GFF_LIST = 15
    GFF_STRUCT = 14
    GFF_CEXOSTRING = 10
    GFF_CEXOLOCSTRING = 12
    GFF_RESREF = 11

    # Read all fields
    fields = []
    for i in range(field_count):
        off = field_offset + i * 12
        f_type = struct.unpack_from('<I', data, off)[0]
        f_label_idx = struct.unpack_from('<I', data, off + 4)[0]
        f_data = struct.unpack_from('<I', data, off + 8)[0]
        fields.append((f_type, f_label_idx, f_data))

    def get_struct_fields(struct_idx):
        """Get field indices for a struct."""
        s_type, s_data_or_offset, s_field_count = structs[struct_idx]
        if s_field_count == 1:
            return [s_data_or_offset]
        else:
            result = []
            for j in range(s_field_count):
                off = field_indices_offset + s_data_or_offset + j * 4
                fidx = struct.unpack_from('<I', data, off)[0]
                result.append(fidx)
            return result

    def get_list_items(list_offset):
        """Get struct indices from a list."""
        off = list_indices_offset + list_offset
        size = struct.unpack_from('<I', data, off)[0]
        items = []
        for j in range(size):
            sidx = struct.unpack_from('<I', data, off + 4 + j * 4)[0]
            items.append(sidx)
        return items

    def read_cexostring(field_data_off):
        """Read a CExoString from field data block."""
        off = field_data_offset + field_data_off
        str_len = struct.unpack_from('<I', data, off)[0]
        return data[off+4:off+4+str_len].decode('ascii', errors='replace')

    def read_resref(field_data_off):
        """Read a ResRef from field data block."""
        off = field_data_offset + field_data_off
        str_len = struct.unpack_from('<B', data, off)[0]
        return data[off+1:off+1+str_len].decode('ascii', errors='replace')

    # Parse top-level struct (struct 0)
    hak_list = []
    custom_tlk = None
    mod_name = None

    top_fields = get_struct_fields(0)
    for fidx in top_fields:
        f_type, f_label_idx, f_data = fields[fidx]
        label = labels[f_label_idx] if f_label_idx < len(labels) else "?"

        if label == "Mod_HakList" and f_type == GFF_LIST:
            # This is a list of structs, each containing "Mod_HakName"
            list_items = get_list_items(f_data)
            for struct_idx in list_items:
                sub_fields = get_struct_fields(struct_idx)
                for sf_idx in sub_fields:
                    sf_type, sf_label_idx, sf_data = fields[sf_idx]
                    sf_label = labels[sf_label_idx] if sf_label_idx < len(labels) else "?"
                    if sf_label in ("Mod_Hak", "Mod_HakName") and sf_type == GFF_CEXOSTRING:
                        hak_name = read_cexostring(sf_data)
                        hak_list.append(hak_name)
                    elif sf_label in ("Mod_Hak", "Mod_HakName") and sf_type == GFF_RESREF:
                        hak_name = read_resref(sf_data)
                        hak_list.append(hak_name)

        elif label == "Mod_CustomTlk" and f_type == GFF_CEXOSTRING:
            custom_tlk = read_cexostring(f_data)
        elif label == "Mod_CustomTlk" and f_type == GFF_RESREF:
            custom_tlk = read_resref(f_data)

    return hak_list, custom_tlk


def analyze_erf_file(filepath, label=None):
    """Analyze an ERF file and return stats."""
    if label is None:
        label = filepath.name

    file_type, file_version, entries = read_erf_entries(filepath)
    if file_type is None:
        return None

    total = len(entries)
    dlg_count = sum(1 for _, rt, _, _, _ in entries if rt == DLG_TYPE)

    # Count by type
    type_counts = defaultdict(int)
    for resref, rt, _, _, _ in entries:
        ext = RES_TYPES.get(rt, f".unknown_{rt:#06x}")
        type_counts[ext] += 1

    # Check for module.ifo
    hak_list = []
    custom_tlk = None
    ifo_entries = [(resref, rt, rid, off, sz) for resref, rt, rid, off, sz in entries if rt == IFO_TYPE]
    if ifo_entries:
        resref, rt, rid, off, sz = ifo_entries[0]
        ifo_data = read_resource_data(filepath, off, sz)
        hak_list, custom_tlk = parse_gff_for_haklist(ifo_data)

    return {
        'file': str(filepath),
        'label': label,
        'file_type': file_type,
        'total_resources': total,
        'dlg_count': dlg_count,
        'type_counts': dict(type_counts),
        'hak_list': hak_list,
        'custom_tlk': custom_tlk,
    }


def main():
    print("=" * 80)
    print("NWN:EE FILE ANALYSIS")
    print("=" * 80)

    # Premium module names to look for
    premium_keywords = {
        'daggerford': 'Darkness over Daggerford',
        'tyrants': 'Tyrants of the Moonsea',
        'moonsea': 'Tyrants of the Moonsea',
        'wyvern': 'Wyvern Crown of Cormyr',
        'pirates': 'Pirates of the Sword Coast',
        'infinite': 'Infinite Dungeons',
        'furiae': 'Dark Dreams of Furiae',
    }

    # ==========================================
    # 1. List all .mod files
    # ==========================================
    print("\n" + "=" * 80)
    print("1. .MOD FILES (data/mod/)")
    print("=" * 80)

    mod_files = sorted(MOD_DIR.glob("*.mod"))
    for f in mod_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name:50s} ({size_mb:.1f} MB)")
    print(f"  Total: {len(mod_files)} .mod files")

    # ==========================================
    # 2. List all .nwm files
    # ==========================================
    print("\n" + "=" * 80)
    print("2. .NWM FILES (data/nwm/)")
    print("=" * 80)

    nwm_files = sorted(NWM_DIR.glob("*.nwm"))
    for f in nwm_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name:60s} ({size_mb:.1f} MB)")
    print(f"  Total: {len(nwm_files)} .nwm files")

    # ==========================================
    # 3. List all .hak files
    # ==========================================
    print("\n" + "=" * 80)
    print("3. .HAK FILES (data/hk/)")
    print("=" * 80)

    hak_files = sorted(HAK_DIR.glob("*.hak"))
    for f in hak_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"  {f.name:50s} ({size_mb:.1f} MB)")
    print(f"  Total: {len(hak_files)} .hak files")

    # ==========================================
    # 4. Analyze premium modules
    # ==========================================
    print("\n" + "=" * 80)
    print("4. PREMIUM MODULE ANALYSIS")
    print("=" * 80)

    premium_nwm = [
        f for f in nwm_files
        if any(kw in f.name.lower() for kw in premium_keywords)
    ]

    all_referenced_haks = set()
    module_results = []

    for f in premium_nwm:
        print(f"\n--- Analyzing: {f.name} ---")
        result = analyze_erf_file(f)
        if result:
            module_results.append(result)
            print(f"  File type: {result['file_type']}")
            print(f"  Total resources: {result['total_resources']}")
            print(f"  .dlg files: {result['dlg_count']}")

            # Top resource types
            sorted_types = sorted(result['type_counts'].items(), key=lambda x: -x[1])
            print(f"  Resource types (top 10):")
            for ext, count in sorted_types[:10]:
                print(f"    {ext:20s}: {count}")

            if result['hak_list']:
                print(f"  Referenced .hak files ({len(result['hak_list'])}):")
                for hak in result['hak_list']:
                    print(f"    - {hak}")
                    all_referenced_haks.add(hak.lower())
            else:
                print(f"  Referenced .hak files: (none)")

            if result['custom_tlk']:
                print(f"  Custom TLK: {result['custom_tlk']}")

    # ==========================================
    # 5. Also analyze OC and expansion .nwm files
    # ==========================================
    print("\n" + "=" * 80)
    print("5. OC & EXPANSION MODULE ANALYSIS (for reference)")
    print("=" * 80)

    oc_nwm = [f for f in nwm_files if f not in premium_nwm]
    for f in oc_nwm:
        print(f"\n--- Analyzing: {f.name} ---")
        result = analyze_erf_file(f)
        if result:
            print(f"  Total resources: {result['total_resources']}")
            print(f"  .dlg files: {result['dlg_count']}")
            if result['hak_list']:
                print(f"  Referenced .hak files: {result['hak_list']}")

    # ==========================================
    # 6. Also analyze .mod files
    # ==========================================
    print("\n" + "=" * 80)
    print("6. .MOD FILE ANALYSIS")
    print("=" * 80)

    for f in mod_files:
        print(f"\n--- Analyzing: {f.name} ---")
        result = analyze_erf_file(f)
        if result:
            print(f"  Total resources: {result['total_resources']}")
            print(f"  .dlg files: {result['dlg_count']}")
            if result['hak_list']:
                print(f"  Referenced .hak files: {result['hak_list']}")
                for hak in result['hak_list']:
                    all_referenced_haks.add(hak.lower())

    # ==========================================
    # 7. Analyze ALL .hak files for .dlg counts
    # ==========================================
    print("\n" + "=" * 80)
    print("7. HAK FILE ANALYSIS (all .hak files)")
    print("=" * 80)

    hak_results = []
    for f in hak_files:
        result = analyze_erf_file(f)
        if result:
            hak_results.append(result)
            hak_base = f.stem.lower()
            referenced = " [REFERENCED]" if hak_base in all_referenced_haks else ""
            if result['dlg_count'] > 0 or referenced:
                print(f"\n  {f.name}{referenced}")
                print(f"    Total resources: {result['total_resources']}")
                print(f"    .dlg files: {result['dlg_count']}")
                if result['dlg_count'] > 0:
                    sorted_types = sorted(result['type_counts'].items(), key=lambda x: -x[1])
                    print(f"    Resource types (top 5):")
                    for ext, count in sorted_types[:5]:
                        print(f"      {ext:20s}: {count}")
            elif result['total_resources'] == 0:
                print(f"\n  {f.name}{referenced}")
                print(f"    (empty - 0 resources)")
            else:
                # Only show name + total for non-referenced haks with no dlgs
                pass  # skip non-relevant haks without dlgs

    # Print haks with no dlgs that are referenced
    print("\n  Referenced .hak files with 0 .dlg files:")
    for r in hak_results:
        hak_base = Path(r['file']).stem.lower()
        if hak_base in all_referenced_haks and r['dlg_count'] == 0:
            print(f"    {Path(r['file']).name}: {r['total_resources']} total resources, 0 .dlg")

    # ==========================================
    # 8. SUMMARY
    # ==========================================
    print("\n" + "=" * 80)
    print("8. SUMMARY")
    print("=" * 80)

    print("\nPremium Modules:")
    print(f"  {'Module':<60s} {'Total':>8s} {'DLGs':>8s} {'Haks':>5s}")
    print(f"  {'-'*60} {'-'*8} {'-'*8} {'-'*5}")

    total_premium_dlg = 0
    for r in module_results:
        name = Path(r['file']).stem
        print(f"  {name:<60s} {r['total_resources']:>8d} {r['dlg_count']:>8d} {len(r['hak_list']):>5d}")
        total_premium_dlg += r['dlg_count']

    print(f"\n  Total .dlg in premium modules: {total_premium_dlg}")

    # Count dlg in referenced haks
    total_hak_dlg = 0
    print("\nReferenced .hak files with .dlg:")
    print(f"  {'Hak File':<50s} {'Total':>8s} {'DLGs':>8s}")
    print(f"  {'-'*50} {'-'*8} {'-'*8}")
    for r in hak_results:
        hak_base = Path(r['file']).stem.lower()
        if hak_base in all_referenced_haks and r['dlg_count'] > 0:
            print(f"  {Path(r['file']).name:<50s} {r['total_resources']:>8d} {r['dlg_count']:>8d}")
            total_hak_dlg += r['dlg_count']

    if total_hak_dlg == 0:
        print("  (no referenced .hak files contain .dlg files)")
    else:
        print(f"\n  Total .dlg in referenced haks: {total_hak_dlg}")

    print(f"\n  GRAND TOTAL .dlg (premium modules + their haks): {total_premium_dlg + total_hak_dlg}")

    # Also show all referenced haks
    print("\nAll referenced .hak files across all modules:")
    for hak in sorted(all_referenced_haks):
        hak_file = HAK_DIR / f"{hak}.hak"
        exists = "EXISTS" if hak_file.exists() else "MISSING"
        print(f"  {hak}.hak - {exists}")


if __name__ == '__main__':
    main()
