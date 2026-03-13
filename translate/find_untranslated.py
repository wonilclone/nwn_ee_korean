#!/usr/bin/env python3
"""
Find entries in translated CSV files where Korean text is identical to English original.
This indicates entries that were copied without actual translation.

Categorizes findings into:
1. Game dialogue (actual spoken lines needing translation)
2. UI/System strings (menus, errors, settings)
3. Technical/internal strings (script names, waypoints, tags, dev notes)
4. Asset labels (tiles, creatures, items, placeables - short descriptive names)
"""

import csv
import os
import re
from collections import defaultdict

TRANSLATED_DIR = os.path.join(os.path.dirname(__file__), "dialog_translated")
MIN_LENGTH = 10  # Minimum English text length to consider

def is_likely_proper_noun_only(text):
    """Check if text is likely just a proper noun or trivial content."""
    if len(text.strip()) <= MIN_LENGTH:
        return True
    if text.strip().isupper() and len(text.strip()) <= 30:
        return True
    return False

def has_english_words(text):
    """Check if text contains actual English words/sentences."""
    alpha_chars = sum(1 for c in text if c.isalpha())
    return alpha_chars >= 3

def categorize_entry(strref, speaker, text, filename):
    """Categorize an untranslated entry into one of several types."""
    t = text.strip()

    # Technical/internal strings
    if re.match(r'^[A-Za-z0-9_]+$', t) and '_' in t:
        return 'technical_internal'  # Script/tag names like "hx_winter_wolf_rw"
    if t.startswith('ERROR:') or t.startswith('ERROR '):
        return 'error_messages'
    if re.match(r'^(On[A-Z]|Design Build|Copyright)', t):
        return 'technical_internal'
    if re.match(r'^M\d+[A-Z]', t) or re.match(r'^[A-Z]\d+[A-Z]', t):
        return 'technical_internal'  # Internal IDs like M1Q5Cultists
    if t.startswith('---') or t.startswith('IGNORE THIS') or t.startswith('RANDOMIZER'):
        return 'dev_notes'  # Developer notes/separators
    if t.startswith('[') and t.endswith(']'):
        return 'dev_notes'  # Stage directions like [VFX. ARIBETH TURNS...]
    if t.startswith('<<') and t.endswith('>>'):
        return 'dev_notes'
    if 'Cutscene' in t and len(t) < 40:
        return 'technical_internal'
    if re.match(r'^Debug_', t):
        return 'technical_internal'

    # Asset labels (tiles, objects, creatures with structured names)
    if re.match(r'^(Tree|Flag|Window|Balcony|Scaffolding|Arrow|Kelp|Bubbles|Chest|Rope|Dirt|Grass|Gravel|Barn|Farm|Tower|Inn|Temple|Warzone|Ship|Merchant Ship|Weathered Ship|Galleon)', t) and len(t) < 60:
        return 'asset_labels'
    if '(sand)' in t or '(No Ambient Light)' in t:
        return 'asset_labels'
    if re.match(r'^(Shark|Seagull|Ochre Jelly|Sahuagin|Wyvern|Golem|Dragon|Snake|Beholder|Ogre|Satyr|Harat|Rubble|Map |Icon |Stocks|Hay block|Cloud|Market Stall|Shield Rack|Hanging Cage|Hangman)', t) and len(t) < 60:
        return 'asset_labels'
    if re.match(r'.+, (Large|Medium|Small|Male|Female)$', t) and len(t) < 60:
        return 'asset_labels'

    # Sound/music labels
    if re.match(r'^(Draft |Leaf |Bush |Cheers |PM - )', t) and len(t) < 50:
        return 'asset_labels'
    if re.match(r'^(Draft|Leaf|Bush) ', t):
        return 'asset_labels'

    # UI/System strings
    if re.match(r'^(Loading|Saving|Enable|Disable|Show|Hide|Select|Choose|Enter|Specify|Camera|Mouse|Full Screen|Server|Max Players|Player Password|DM Password|Normal |Competitive|Persistent|Search Results)', t):
        return 'ui_system'
    if 'Wizard' in t and len(t) < 30:
        return 'ui_system'
    if re.match(r'^(Plot |Journal |Vault |Auto Detect)', t) and len(t) < 40:
        return 'ui_system'
    if t.endswith(':') and len(t) < 50:
        return 'ui_system'

    # NWN Toolset strings (editor-only, not visible to players)
    toolset_keywords = [
        'Blueprint', 'palette', 'module', 'tileset', 'ResRef', 'compile',
        'instance', 'resource', 'toolbar', 'area wizard', 'tile painting',
        'custom palette', 'sound object', 'clipboard', 'Registry key',
        'Hak File', 'Wave sounds', 'NWScript', 'Build Module',
        'aurora', 'toolset', 'BINK Movie'
    ]
    for kw in toolset_keywords:
        if kw.lower() in t.lower() and len(t) < 200:
            return 'toolset_only'

    # Actual game dialogue/descriptions (spoken lines, narrative text)
    if speaker and speaker not in ('', '?'):
        return 'game_dialogue'

    # Longer prose text is likely game content
    if len(t) > 60 and any(c in t for c in '.!?'):
        return 'game_content'

    # Shorter but still meaningful strings
    if len(t) > 30 and any(c in t for c in '.!?'):
        return 'game_content_short'

    return 'other'


CATEGORY_LABELS = {
    'game_dialogue': '*** GAME DIALOGUE (spoken lines - NEEDS TRANSLATION) ***',
    'game_content': '*** GAME CONTENT (descriptions/narratives - NEEDS TRANSLATION) ***',
    'game_content_short': '*** GAME CONTENT SHORT (may need translation) ***',
    'error_messages': 'Compiler/System Error Messages',
    'ui_system': 'UI/System Strings (menus, settings)',
    'toolset_only': 'Toolset-Only Strings (editor, not visible to players)',
    'dev_notes': 'Developer Notes / Stage Directions',
    'technical_internal': 'Technical/Internal (script names, tags, IDs)',
    'asset_labels': 'Asset Labels (tiles, creatures, objects)',
    'other': 'Other/Uncategorized',
}

CATEGORY_PRIORITY = [
    'game_dialogue',
    'game_content',
    'game_content_short',
    'ui_system',
    'toolset_only',
    'error_messages',
    'dev_notes',
    'asset_labels',
    'technical_internal',
    'other',
]


def analyze_files():
    results_by_file = defaultdict(list)
    results_by_category = defaultdict(list)
    total_entries = 0
    total_translated = 0
    total_empty_ko = 0
    total_identical = 0
    total_flagged = 0

    files = sorted([f for f in os.listdir(TRANSLATED_DIR) if f.endswith('.csv')])

    for filename in files:
        filepath = os.path.join(TRANSLATED_DIR, filename)
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_entries += 1

                    eng_text = row.get('TextEng', '').strip()
                    ko_text = row.get('Text', '').strip()
                    strref = row.get('StrRef', '?')
                    speaker = row.get('SpeakerName', '?')

                    if not eng_text:
                        continue

                    if not ko_text:
                        total_empty_ko += 1
                        continue

                    if eng_text == ko_text:
                        total_identical += 1

                        if is_likely_proper_noun_only(eng_text):
                            continue
                        if not has_english_words(eng_text):
                            continue

                        total_flagged += 1
                        category = categorize_entry(strref, speaker, eng_text, filename)
                        entry = {
                            'strref': strref,
                            'speaker': speaker,
                            'text': eng_text,
                            'length': len(eng_text),
                            'filename': filename,
                        }
                        results_by_file[filename].append(entry)
                        results_by_category[category].append(entry)

        except Exception as e:
            print(f"  ERROR reading {filename}: {e}")

    return results_by_file, results_by_category, total_entries, total_translated, total_empty_ko, total_identical, total_flagged


def print_report(results_by_file, results_by_category, total_entries, total_translated, total_empty_ko, total_identical, total_flagged):
    print("=" * 110)
    print("NWN:EE Korean Translation - Untranslated Entry Report")
    print("Entries where Korean text == English text (not actually translated)")
    print("=" * 110)

    print(f"\n{'='*50}")
    print("OVERALL STATISTICS")
    print(f"{'='*50}")
    print(f"Total entries scanned:             {total_entries:>7,}")
    print(f"Translated (eng != ko):            {total_translated:>7,}")
    print(f"Empty Korean text:                 {total_empty_ko:>7,}")
    print(f"Identical (eng == ko):             {total_identical:>7,}")
    print(f"  Short/proper noun (<=10ch):      {total_identical - total_flagged:>7,} (filtered out)")
    print(f"  FLAGGED (>10ch, has letters):     {total_flagged:>7,}")

    # Category summary
    print(f"\n{'='*50}")
    print("BREAKDOWN BY CATEGORY")
    print(f"{'='*50}\n")

    for cat in CATEGORY_PRIORITY:
        entries = results_by_category.get(cat, [])
        if entries:
            label = CATEGORY_LABELS[cat]
            print(f"  {label}: {len(entries):,}")

    # Detailed by category
    print(f"\n{'='*110}")
    print("DETAILED BREAKDOWN BY CATEGORY")
    print(f"{'='*110}")

    for cat in CATEGORY_PRIORITY:
        entries = results_by_category.get(cat, [])
        if not entries:
            continue

        label = CATEGORY_LABELS[cat]
        print(f"\n{'─'*110}")
        print(f"  {label} ({len(entries):,} entries)")
        print(f"{'─'*110}")

        # Group by file within category
        by_file = defaultdict(list)
        for e in entries:
            by_file[e['filename']].append(e)

        for fn in sorted(by_file.keys()):
            file_entries = by_file[fn]
            print(f"\n  [{fn}] ({len(file_entries)} entries)")
            for entry in file_entries[:10]:  # Show up to 10 per file
                text_preview = entry['text'][:100]
                if len(entry['text']) > 100:
                    text_preview += "..."
                speaker_str = f" ({entry['speaker']})" if entry['speaker'] and entry['speaker'] != '?' else ""
                print(f"    StrRef {entry['strref']:>6}{speaker_str}: {text_preview}")
            if len(file_entries) > 10:
                print(f"    ... and {len(file_entries) - 10} more")

    # Summary by file
    print(f"\n{'='*110}")
    print("SUMMARY BY FILE")
    print(f"{'='*110}\n")

    sorted_files = sorted(results_by_file.items(), key=lambda x: len(x[1]), reverse=True)
    print(f"{'File':<45} {'Total':>6}  {'Dialogue':>8}  {'Content':>8}  {'UI/Sys':>8}  {'Other':>8}")
    print("-" * 95)
    for filename, entries in sorted_files:
        n_dialogue = sum(1 for e in entries if categorize_entry(e['strref'], e['speaker'], e['text'], filename) == 'game_dialogue')
        n_content = sum(1 for e in entries if categorize_entry(e['strref'], e['speaker'], e['text'], filename) in ('game_content', 'game_content_short'))
        n_ui = sum(1 for e in entries if categorize_entry(e['strref'], e['speaker'], e['text'], filename) in ('ui_system', 'toolset_only', 'error_messages'))
        n_other = len(entries) - n_dialogue - n_content - n_ui
        print(f"{filename:<45} {len(entries):>6}  {n_dialogue:>8}  {n_content:>8}  {n_ui:>8}  {n_other:>8}")

    # Non-translated.csv files (dialogue files) - these are most actionable
    print(f"\n{'='*110}")
    print("DIALOGUE FILES WITH UNTRANSLATED ENTRIES (excluding translated.csv)")
    print("These are the most actionable items for translation review.")
    print(f"{'='*110}")

    for filename, entries in sorted_files:
        if filename == 'translated.csv':
            continue
        print(f"\n  [{filename}] ({len(entries)} entries)")
        for entry in entries:
            text_preview = entry['text'][:120]
            if len(entry['text']) > 120:
                text_preview += "..."
            speaker_str = f" ({entry['speaker']})" if entry['speaker'] and entry['speaker'] != '?' else ""
            print(f"    StrRef {entry['strref']:>6}{speaker_str}: {text_preview}")


if __name__ == '__main__':
    print("Scanning all CSV files in dialog_translated/...\n")
    results_by_file, results_by_category, total_entries, total_translated, total_empty_ko, total_identical, total_flagged = analyze_files()
    print_report(results_by_file, results_by_category, total_entries, total_translated, total_empty_ko, total_identical, total_flagged)
