#!/usr/bin/env python3
"""
Combine multiple Elite Dangerous JSON files into one neareststars.json
Supports: neareststars.json, galacticmapping.json, gecmapping.json
"""
import json
import os
import shutil
from datetime import datetime

# Configuration
PLUGIN_DIR = r"C:\Users\Shadow\AppData\Local\EDMarketConnector\plugins\SHBOXSEARCH"
INPUT_FILES = ['neareststars.json', 'galacticmapping.json', 'gecmapping.json']
OUTPUT_FILE = 'neareststars.json'
BACKUP_SUFFIX = '.backup'

def load_json_file(filepath):
    """Load and parse a JSON file."""
    if not os.path.exists(filepath):
        return None
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ Error loading {filepath}: {e}")
        return None

def parse_neareststars_format(data, systems):
    """Parse EDDiscovery neareststars.json format."""
    if not isinstance(data, dict) or 'Nearest' not in data:
        return 0
    
    count = 0
    for sys in data.get('Nearest', []):
        if not all(k in sys for k in ['Name', 'X', 'Y', 'Z']):
            continue
        
        name = sys['Name']
        if name not in systems:
            systems[name] = {
                'Name': name,
                'X': float(sys['X']),
                'Y': float(sys['Y']),
                'Z': float(sys['Z'])
            }
            count += 1
    
    return count

def parse_mapping_format(data, systems):
    """Parse galacticmapping.json / gecmapping.json format."""
    if not isinstance(data, list):
        return 0
    
    count = 0
    for entry in data:
        if 'coordinates' not in entry:
            continue
        
        coords = entry['coordinates']
        if len(coords) < 3:
            continue
        
        # Try to get system name
        name = entry.get('galMapSearch') or entry.get('name')
        if not name or name in systems:
            continue
        
        systems[name] = {
            'Name': name,
            'X': float(coords[0]),
            'Y': float(coords[1]),
            'Z': float(coords[2])
        }
        count += 1
    
    return count

def combine_json_files(plugin_dir, input_files, output_file):
    """Combine multiple JSON files into one neareststars.json format."""
    systems = {}
    stats = {}
    
    print("=" * 60)
    print("Elite Dangerous JSON Combiner v1.0")
    print("=" * 60)
    print()
    
    # Load and parse all input files
    for filename in input_files:
        filepath = os.path.join(plugin_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"⚠️  {filename} not found, skipping")
            stats[filename] = 0
            continue
        
        print(f"📁 Loading {filename}...")
        data = load_json_file(filepath)
        
        if data is None:
            stats[filename] = 0
            continue
        
        # Try to parse as neareststars format
        if isinstance(data, dict) and 'Nearest' in data:
            count = parse_neareststars_format(data, systems)
            stats[filename] = count
            print(f"   ✅ Added {count} systems from neareststars format")
        
        # Try to parse as mapping format
        elif isinstance(data, list):
            count = parse_mapping_format(data, systems)
            stats[filename] = count
            print(f"   ✅ Added {count} systems from mapping format")
        
        else:
            print(f"   ❌ Unknown format, skipping")
            stats[filename] = 0
    
    if not systems:
        print()
        print("❌ No systems found in any file!")
        return False
    
    print()
    print(f"📊 Statistics:")
    for filename, count in stats.items():
        if count > 0:
            print(f"   {filename}: {count} systems")
    print(f"   Total unique: {len(systems)} systems")
    
    # Backup existing file
    output_path = os.path.join(plugin_dir, output_file)
    if os.path.exists(output_path):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_path = f"{output_path}.{timestamp}.backup"
        shutil.copy(output_path, backup_path)
        print()
        print(f"💾 Backup created: {os.path.basename(backup_path)}")
    
    # Create combined output
    combined = {
        'System': {
            'Name': 'Combined Database',
            'X': 0.0,
            'Y': 0.0,
            'Z': 0.0
        },
        'Nearest': sorted(systems.values(), key=lambda s: s['Name'])
    }
    
    # Write output file
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)
    
    print()
    print(f"✅ Successfully created: {output_file}")
    print(f"   Location: {output_path}")
    print(f"   Systems: {len(systems)}")
    print()
    print("🚀 Restart EDMC to use the combined database!")
    print()
    
    return True

def main():
    """Main entry point."""
    if not os.path.exists(PLUGIN_DIR):
        print(f"❌ Plugin directory not found: {PLUGIN_DIR}")
        print("   Please update PLUGIN_DIR in the script")
        return 1
    
    success = combine_json_files(PLUGIN_DIR, INPUT_FILES, OUTPUT_FILE)
    return 0 if success else 1

if __name__ == '__main__':
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Cancelled by user")
        exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
