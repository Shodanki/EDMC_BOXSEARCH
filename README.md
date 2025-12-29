# EDMC Sphere Survey Plugin (SHBOXSEARCH)

Systematic Sphere/Box Survey Plugin for Elite Dangerous via ED Market Connector.

**Version:** 3.0.7  
**Date:** 2025-12-25  
**License:** MIT

## Features

- **Multi-API Support**: EDSM, Spansh, EDGIS, EDDiscovery DB, manual JSON import
- **Intelligent Routing**: Prefers shortest jumps, considers jump range
- **Progress Tracking**: Complete tracking of visited systems with persistence
- **Theme Adaptation**: Automatically adapts to ED Market Connector theme
- **Return to Start**: Navigation back to starting system after completion
- **Clipboard Integration**: Automatic copying of next target
- **Duplicate Prevention**: Robust dual-ID system (ID64 + Name)

## Installation

### Prerequisites

- Elite Dangerous
- [ED Market Connector](https://github.com/EDCD/EDMarketConnector) (EDMC)
- Python 3.7+ (usually installed with EDMC)
- Requests library (for API access)

### Step 1: Create Plugin Folder

Windows:
```
C:\Users\[YOUR_NAME]\AppData\Local\EDMarketConnector\plugins\SHBOXSEARCH\
```

Linux/Mac:
```
~/.local/share/EDMarketConnector/plugins/SHBOXSEARCH/
```

### Step 2: Copy Files

Copy the following files to the SHBOXSEARCH folder:
- `load.py` (main plugin)
- Optional: `neareststars.json` (local system database)
- Optional: `combine_jsons.py` (utility script for multiple JSON files)

### Step 3: Restart EDMC

1. Close EDMC completely
2. Restart EDMC
3. Log should show: "loading plugin SHBOXSEARCH"

## Quick Start

### 1. Start Survey

1. Fly to your starting system in Elite Dangerous
2. In EDMC: Click **"Detect"** button
3. Set radius (default: 50 ly)
4. Click **"Start"** button

### 2. Perform Survey

1. Next target appears in UI
2. With Auto-Copy enabled: System name is already in clipboard
3. In Elite: Open Galaxy Map → Paste → Jump to target
4. After FSD jump: Plugin updates automatically
5. Perform scan → Next target is loaded

### 3. End Survey

- **On completion**: Plugin automatically returns to starting system
- **Manual**: Click **"Stop"** button
- **Pause**: Survey status is saved, can resume on next start

## Configuration

### EDMC Settings → EDMC_SphereSurvey

#### Basic Settings

- **Enable plugin**: Activate/deactivate plugin
- **Debug logging**: Detailed logs for troubleshooting
- **Default radius (ly)**: Default search radius (1-200 ly)
- **Max jump range (ly)**: Maximum jump range of your ship

#### Data Sources

**Preferred data source:**
- `auto` (recommended): Automatic selection of best available source
- `local_json`: Use only local JSON file
- `edd`: Use EDDiscovery database
- `edsm`: Use only EDSM API

**Local JSON file:** Path to local system database (e.g., neareststars.json)

#### Behavior

- **Auto-copy next target to clipboard**: Automatically copy next target
- **Prefer shortest jumps from current position**: Prioritize shortest jumps

## Advanced Usage

### Combining Multiple JSON Files

The plugin supports three JSON formats:
1. `neareststars.json` (EDDiscovery)
2. `galacticmapping.json` (Galactic Mapping)
3. `gecmapping.json` (GEC Mapping)

#### Using the Utility Script

1. Copy all JSON files to the plugin folder
2. In `combine_jsons.py`, adjust the `PLUGIN_DIR` path
3. Run script:
   ```
   python combine_jsons.py
   ```
4. Creates combined `neareststars.json` with backup

#### Manual Combining

Example neareststars.json format:
```json
{
  "System": {
    "Name": "Combined Database",
    "X": 0.0,
    "Y": 0.0,
    "Z": 0.0
  },
  "Nearest": [
    {
      "Name": "Sol",
      "X": 0.0,
      "Y": 0.0,
      "Z": 0.0
    },
    {
      "Name": "Alpha Centauri",
      "X": 3.03,
      "Y": -0.09,
      "Z": 3.15
    }
  ]
}
```

### API Priorities

The plugin automatically selects the best available API:

1. **Local JSON** (highest priority when configured)
   - Instant response
   - Available offline
   - Limited to imported systems

2. **EDDiscovery DB**
   - Very comprehensive database
   - Local access
   - Requires EDDiscovery installation

3. **EDGIS**
   - Best coverage for remote regions
   - Fast API
   - Publicly available

4. **EDSM**
   - Reliable and established
   - Good coverage of known regions
   - With cube-tiling fallback

5. **Spansh**
   - Alternative API
   - Good data quality

### Track Progress

The UI displays:
- **Current System**: Current system
- **Next Target**: Next system to visit
- **Distance**: Distance to target
- **Progress**: Visited/Remaining systems
- **Survey Info**: Starting system and radius

Progress is saved in `survey_state.json` and survives EDMC restarts.

## Troubleshooting

### Plugin Doesn't Load

**Symptom:** No SHBOXSEARCH entries in log

**Solution:**
1. Check folder name: Must be `SHBOXSEARCH`
2. Check file name: Must be `load.py`
3. Delete `__pycache__` folder if exists
4. Restart EDMC

### Current System Not Detected

**Symptom:** "Current: Unknown" in UI

**Solution:**
1. Perform a hyperspace jump in Elite
2. Click "Detect" button
3. Enable debug logging and check log
4. Check journal files (should contain Location/FSDJump events)

### No Systems Found

**Symptom:** "No systems found" when starting

**Solutions:**

1. **API Issues:**
   - Check internet connection
   - Fly to inhabited system (e.g., Sol, Shinrarta Dezhra)
   - Increase radius

2. **Local JSON:**
   - Does file exist and is valid JSON?
   - Is path correct in Settings?
   - Check format (see above)

3. **EDDiscovery DB:**
   - Is EDDiscovery installed?
   - Is database current?

### Settings Tab Won't Open

**Symptom:** Error when opening Settings

**Solution:**
1. Delete `__pycache__`
2. Ensure version 3.0.7 is installed
3. Completely restart EDMC

### Theme Doesn't Match

**Symptom:** Plugin looks different from EDMC

**Solution:**
1. EDMC Settings → Appearance
2. Switch theme (e.g., Default → Dark → Default)
3. Plugin should adapt

## Performance Tips

### Large Surveys (>100 Systems)

- **Use Local JSON**: Much faster than API queries
- **EDDiscovery DB**: Good balance between speed and coverage
- **Limit radius**: 50-100 ly for optimal performance

### Sparsely Populated Regions

- **Increase radius**: More chances to find systems
- **Prefer EDSM**: Best coverage for fringe/outer regions
- **Combine multiple sources**: Local JSON + API

### Jump Optimization

- **Enable "Prefer shortest jumps"**: Better coverage
- **Set max jump range correctly**: Prevents unreachable targets
- **Avoid neutron highway**: Plugin doesn't optimize for boosts

## Known Limitations

1. **Large radii (>200 ly)**: EDSM cube-tiling can become slow
2. **Unknown systems**: API databases don't contain all systems
3. **Carrier jumps**: Treated like normal jumps
4. **Multi-commander**: Separate state per commander

## Logs and Debugging

### Enable Debug Mode

1. EDMC Settings → EDMC_SphereSurvey
2. Enable "Debug logging"
3. Restart EDMC

### Find Log File

Windows:
```
%TEMP%\EDMarketConnector.log
```

Linux/Mac:
```
~/.local/share/EDMarketConnector/EDMarketConnector.log
```

### Important Log Entries

```
# Plugin loaded
loading plugin SHBOXSEARCH
Plugin started v3.0.7

# System detected
Location update: [System name] @ (x, y, z)
Current system from monitor: [System name]

# Survey started
Survey started: X systems from [Source]
Next target: [System name] (X.XX ly)

# System visited
Marking visited: [System name]
Progress: X/Y visited, Z pending
```

## Development

### Structure

```
SHBOXSEARCH/
├── load.py              # Main plugin (EDMC entry point)
├── combine_jsons.py     # JSON combiner (optional)
├── neareststars.json    # Local database (optional)
├── survey_state.json    # Progress (auto-created)
└── README.md            # This file
```

### Important Functions

- `plugin_start3()`: Plugin initialization
- `plugin_app()`: UI creation
- `journal_entry()`: Journal event processing
- `dashboard_entry()`: Dashboard updates
- `plugin_prefs()`: Settings UI

### Extending API Integration

Add new data source:

```python
class MyCustomSource(SystemDataSource):
    def is_available(self) -> bool:
        # Check availability
        return True
    
    def get_systems_near(self, x, y, z, radius, system_name=None):
        # Query systems
        return [SystemNode(...), ...]
    
    def get_name(self) -> str:
        return "My Custom Source"
    
    def get_priority(self) -> int:
        return 50  # Lower = higher priority
```

## Changelog

### Version 3.0.7 (2025-12-25)

- Multi-API support with intelligent prioritization
- Robust progress tracking (dual-ID system)
- Complete theme support
- Intelligent routing (shortest jumps)
- Return-to-start feature
- Clipboard integration with retry
- Comprehensive error handling
- Thread-safe implementation

### Previous Versions

- 1.4.1: Basic functionality, limited APIs
- 1.0.0: Initial version

## Support

### Reporting Issues

When reporting issues, please provide:

1. **EDMC Version**: EDMC → Help → About
2. **Plugin Version**: In log or Settings
3. **Operating System**: Windows/Linux/Mac
4. **Error Description**: What happens, what should happen
5. **Log Excerpt**: With debug logging enabled
6. **Configuration**: Settings screenshot

### Community

- Elite Dangerous Community
- EDMC GitHub: https://github.com/EDCD/EDMarketConnector
- EDSM: https://www.edsm.net

## License

MIT License © 2025

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Credits

- **Elite Dangerous**: © Frontier Developments
- **EDMC**: ED Market Connector Development Team
- **EDSM**: Elite Dangerous Star Map
- **Spansh**: Spansh Tools
- **EDGIS**: Elite Dangerous Galactic Information System
- **EDDiscovery**: EDDiscovery Development Team

---

**Fly safe, Commander! o7**
