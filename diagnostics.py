#!/usr/bin/env python3
"""
SHBOXSEARCH Plugin Diagnostics
Run this script to check your setup and diagnose issues
"""
import json
import os
import sys
from pathlib import Path

def print_header(text):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)

def check_json_file(filepath):
    """Check if JSON file is valid and show stats."""
    print(f"\nChecking: {filepath}")
    
    if not os.path.exists(filepath):
        print("  ❌ File does not exist!")
        return False
    
    print(f"  ✅ File exists ({os.path.getsize(filepath)} bytes)")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        print("  ✅ Valid JSON format")
    except Exception as e:
        print(f"  ❌ Invalid JSON: {e}")
        return False
    
    # Check structure
    if not isinstance(data, dict):
        print(f"  ❌ Root is not a dict, it's: {type(data)}")
        return False
    
    print(f"  ✅ Root is dict with keys: {list(data.keys())}")
    
    if 'System' in data:
        sys_data = data['System']
        if all(k in sys_data for k in ['Name', 'X', 'Y', 'Z']):
            print(f"  ✅ System center: {sys_data['Name']} at ({sys_data['X']:.2f}, {sys_data['Y']:.2f}, {sys_data['Z']:.2f})")
        else:
            print(f"  ⚠️  System data incomplete: {list(sys_data.keys())}")
    
    if 'Nearest' in data:
        systems = data['Nearest']
        if not isinstance(systems, list):
            print(f"  ❌ 'Nearest' is not a list, it's: {type(systems)}")
            return False
        
        print(f"  ✅ Contains {len(systems)} systems")
        
        # Check first few systems
        valid_systems = 0
        for i, sys in enumerate(systems[:5]):
            if all(k in sys for k in ['Name', 'X', 'Y', 'Z']):
                valid_systems += 1
                if i == 0:
                    print(f"     Example: {sys['Name']} at ({sys['X']:.2f}, {sys['Y']:.2f}, {sys['Z']:.2f})")
        
        print(f"  ✅ First 5 systems have valid structure: {valid_systems}/5")
        
        # Calculate bounds
        if systems:
            x_coords = [s['X'] for s in systems if 'X' in s]
            y_coords = [s['Y'] for s in systems if 'Y' in s]
            z_coords = [s['Z'] for s in systems if 'Z' in s]
            
            if x_coords and y_coords and z_coords:
                print(f"\n  📊 Database bounds:")
                print(f"     X: {min(x_coords):.2f} to {max(x_coords):.2f}")
                print(f"     Y: {min(y_coords):.2f} to {max(y_coords):.2f}")
                print(f"     Z: {min(z_coords):.2f} to {max(z_coords):.2f}")
                
                # Calculate center
                center_x = (min(x_coords) + max(x_coords)) / 2
                center_y = (min(y_coords) + max(y_coords)) / 2
                center_z = (min(z_coords) + max(z_coords)) / 2
                print(f"     Center: ({center_x:.2f}, {center_y:.2f}, {center_z:.2f})")
                
                # Calculate max distance from center
                import math
                max_dist = 0
                for s in systems[:100]:  # Sample first 100
                    if all(k in s for k in ['X', 'Y', 'Z']):
                        dx = s['X'] - center_x
                        dy = s['Y'] - center_y
                        dz = s['Z'] - center_z
                        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                        max_dist = max(max_dist, dist)
                print(f"     Approx radius: {max_dist:.2f} ly")
    
    return True

def test_search_from_coords(filepath, test_x, test_y, test_z, radius):
    """Test searching systems from specific coordinates."""
    print(f"\n🔍 Testing search from ({test_x:.2f}, {test_y:.2f}, {test_z:.2f}) with radius {radius} ly")
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ❌ Failed to load JSON: {e}")
        return
    
    systems = data.get('Nearest', [])
    if not systems:
        print("  ❌ No systems in database")
        return
    
    import math
    found = []
    for sys in systems:
        if all(k in sys for k in ['Name', 'X', 'Y', 'Z']):
            dx = sys['X'] - test_x
            dy = sys['Y'] - test_y
            dz = sys['Z'] - test_z
            dist = math.sqrt(dx*dx + dy*dy + dz*dz)
            
            if dist <= radius:
                found.append((sys['Name'], dist))
    
    found.sort(key=lambda x: x[1])
    
    if found:
        print(f"  ✅ Found {len(found)} systems!")
        print(f"\n  Closest 5 systems:")
        for name, dist in found[:5]:
            print(f"     {name:40s} {dist:8.2f} ly")
    else:
        print(f"  ❌ No systems found in radius {radius} ly")
        
        # Find closest system
        closest_dist = float('inf')
        closest_sys = None
        for sys in systems:
            if all(k in sys for k in ['Name', 'X', 'Y', 'Z']):
                dx = sys['X'] - test_x
                dy = sys['Y'] - test_y
                dz = sys['Z'] - test_z
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                if dist < closest_dist:
                    closest_dist = dist
                    closest_sys = sys['Name']
        
        if closest_sys:
            print(f"  ℹ️  Closest system: {closest_sys} at {closest_dist:.2f} ly")
            print(f"  ℹ️  Try increasing radius to at least {closest_dist * 1.1:.0f} ly")

def main():
    print_header("SHBOXSEARCH Plugin Diagnostics v1.0")
    
    # Detect plugin directory
    if len(sys.argv) > 1:
        plugin_dir = sys.argv[1]
    else:
        # Try common locations
        user_dir = os.path.expanduser("~")
        possible_dirs = [
            os.path.join(user_dir, "AppData", "Local", "EDMarketConnector", "plugins", "SHBOXSEARCH"),
            os.path.join(user_dir, ".local", "share", "EDMarketConnector", "plugins", "SHBOXSEARCH"),
            "SHBOXSEARCH"
        ]
        
        plugin_dir = None
        for d in possible_dirs:
            if os.path.exists(d):
                plugin_dir = d
                break
        
        if not plugin_dir:
            print("\n❌ Could not find plugin directory!")
            print("\nUsage: python diagnostics.py [PLUGIN_DIR]")
            print("\nOr run from plugin directory")
            return 1
    
    print(f"\nPlugin directory: {plugin_dir}")
    
    if not os.path.exists(plugin_dir):
        print(f"  ❌ Directory does not exist!")
        return 1
    
    print(f"  ✅ Directory exists")
    
    # Check load.py
    print_header("Checking Plugin Files")
    
    load_py = os.path.join(plugin_dir, "load.py")
    if os.path.exists(load_py):
        print(f"  ✅ load.py exists ({os.path.getsize(load_py)} bytes)")
        
        # Check version
        try:
            with open(load_py, 'r', encoding='utf-8') as f:
                content = f.read(2000)  # Read first 2000 chars
                if 'VERSION = ' in content:
                    for line in content.split('\n'):
                        if line.startswith('VERSION = '):
                            print(f"     Version: {line.split('=')[1].strip().strip('\"')}")
                            break
        except:
            pass
    else:
        print(f"  ❌ load.py not found!")
    
    # Check JSON files
    print_header("Checking Data Files")
    
    json_files = [
        "neareststars.json",
        "galacticmapping.json",
        "gecmapping.json"
    ]
    
    found_json = []
    for filename in json_files:
        filepath = os.path.join(plugin_dir, filename)
        if check_json_file(filepath):
            found_json.append(filepath)
    
    # Test searches if we have a JSON file
    if found_json:
        print_header("Testing Search Functionality")
        
        json_file = found_json[0]
        
        # Test some common coordinates
        test_cases = [
            (0, 0, 0, 50, "Sol area"),
            (536.4, -123.0, -980.9, 50, "NGC 2232 area (from your JSON)"),
            (207.4, -36.4, -788.2, 50, "Synuefe area (from your logs)"),
        ]
        
        for x, y, z, radius, desc in test_cases:
            print(f"\n--- {desc} ---")
            test_search_from_coords(json_file, x, y, z, radius)
    
    # Check state file
    print_header("Checking State File")
    
    state_file = os.path.join(plugin_dir, "survey_state.json")
    if os.path.exists(state_file):
        print(f"  ✅ survey_state.json exists")
        try:
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            if state.get('active'):
                print(f"  ℹ️  Active survey:")
                print(f"     Start: {state.get('start_system')}")
                print(f"     Radius: {state.get('radius_ly')} ly")
                print(f"     Pending: {len(state.get('pending_systems', []))}")
                print(f"     Visited: {len(state.get('visited_names', []))}")
            else:
                print(f"  ℹ️  No active survey")
        except Exception as e:
            print(f"  ⚠️  Could not read state: {e}")
    else:
        print(f"  ℹ️  No state file (will be created on first survey)")
    
    print_header("Summary")
    print("\nIf you see errors above:")
    print("1. Check that neareststars.json is in the plugin folder")
    print("2. Make sure JSON file is valid (use https://jsonlint.com)")
    print("3. Enable Debug logging in EDMC settings")
    print("4. Start a survey and check EDMarketConnector.log")
    print("\n")
    
    return 0

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
