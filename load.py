# EDMC_SphereSurvey - Systematisches Sphere/Box Survey Plugin für Elite Dangerous
# Version 3.0.7
# MIT License © 2025
#
# Features:
# - Multi-API Support: EDSM, Spansh, EDGIS, EDDiscovery DB, Manueller JSON Import
# - Automatische API-Auswahl basierend auf Verfügbarkeit und Datenqualität
# - Intelligentes Routing: Kürzeste Sprünge bevorzugt, Sprungreichweite berücksichtigt
# - Vollständiges Progress-Tracking mit Persistierung
# - Theme-bewusstes UI (passt sich an ED Market Connector Theme an)
# - Rückkehr zum Start-System nach Abschluss
# - Vermeidung doppelter System-Besuche
# - Clipboard-Integration für schnelles Kopieren des nächsten Ziels

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import tkinter as tk
from tkinter import ttk, filedialog

# EDMC public API imports
import myNotebook as nb
from config import appname, config
from theme import theme
from ttkHyperlinkLabel import HyperlinkLabel

# Logging setup
import logging
plugin_name = os.path.basename(os.path.dirname(__file__))
logger = logging.getLogger(f"{appname}.{plugin_name}")
if not logger.hasHandlers():
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d:%(funcName)s: %(message)s"
    )
    formatter.default_time_format = "%Y-%m-%d %H:%M:%S"
    formatter.default_msec_format = "%s.%03d"
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ============================================================================
# Version & Constants
# ============================================================================
VERSION = "3.0.7"
VERSION_DATE = "2025-12-25"

STATE_FILE = os.path.join(os.path.dirname(__file__), "survey_state.json")

# API Endpoints
EDSM_BASE = "https://www.edsm.net"
EDSM_SPHERE = "/api-v1/sphere-systems"
EDSM_CUBE = "/api-v1/cube-systems"
EDSM_SYSTEM = "/api-v1/system"

SPANSH_BASE = "https://spansh.co.uk"
SPANSH_NEAREST = "/api/nearest"

EDGIS_BASE = "https://edgis.elitedangereuse.fr/api"
EDGIS_NEARBY = "/systems/nearby"

# Config keys
CFG_ENABLED = f"{plugin_name}_enabled"
CFG_DEBUG = f"{plugin_name}_debug"
CFG_RADIUS = f"{plugin_name}_radius"
CFG_JUMP_RANGE = f"{plugin_name}_jump_range"
CFG_DATA_SOURCE = f"{plugin_name}_data_source"
CFG_LOCAL_PATH = f"{plugin_name}_local_path"
CFG_AUTOCOPY = f"{plugin_name}_autocopy"
CFG_PREFER_SHORT_JUMPS = f"{plugin_name}_prefer_short"

# ============================================================================
# Data Structures
# ============================================================================

@dataclass
class SystemNode:
    """Represents a star system."""
    name: str
    id64: Optional[int]
    x: float
    y: float
    z: float
    distance: float  # from start system
    
    def __hash__(self):
        return hash((self.name, self.id64))
    
    def __eq__(self, other):
        if not isinstance(other, SystemNode):
            return False
        if self.id64 and other.id64:
            return self.id64 == other.id64
        return self.name == other.name

@dataclass
class SurveyState:
    """Persistent survey state."""
    active: bool = False
    start_system: Optional[str] = None
    start_coords: Optional[Tuple[float, float, float]] = None
    radius_ly: float = 50.0
    max_jump_ly: Optional[float] = None
    prefer_short_jumps: bool = True
    
    # Survey progress
    pending_systems: List[SystemNode] = field(default_factory=list)
    visited_ids: Set[int] = field(default_factory=set)
    visited_names: Set[str] = field(default_factory=set)
    all_systems: Dict[str, SystemNode] = field(default_factory=dict)
    
    # Metadata
    started_ts: Optional[float] = None
    data_source_used: Optional[str] = None
    
    def reset(self) -> None:
        """Reset survey state."""
        self.active = False
        self.start_system = None
        self.start_coords = None
        self.pending_systems.clear()
        self.visited_ids.clear()
        self.visited_names.clear()
        self.all_systems.clear()
        self.started_ts = None
        self.data_source_used = None

# ============================================================================
# API Abstraction
# ============================================================================

class SystemDataSource(ABC):
    """Abstract base class for system data sources."""
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this data source is available."""
        pass
    
    @abstractmethod
    def get_systems_near(
        self,
        x: float,
        y: float,
        z: float,
        radius: float,
        system_name: Optional[str] = None
    ) -> Optional[List[SystemNode]]:
        """Get systems near coordinates."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get human-readable name of this source."""
        pass
    
    @abstractmethod
    def get_priority(self) -> int:
        """Get priority (lower = higher priority)."""
        pass


class EDSMSource(SystemDataSource):
    """EDSM API - Reliable public API."""
    
    def __init__(self):
        try:
            import requests
            self._session = requests.Session()
            self._session.headers.update({
                'User-Agent': 'EDMC-SphereSurvey/3.0.1',
                'Accept': 'application/json'
            })
        except ImportError:
            self._session = None
    
    def is_available(self) -> bool:
        return self._session is not None
    
    def get_systems_near(self, x: float, y: float, z: float, radius: float, system_name: Optional[str] = None) -> Optional[List[SystemNode]]:
        try:
            # Try sphere query with coordinates (more reliable than by name)
            systems = self._query_sphere_coords(x, y, z, radius)
            
            # Fallback to cube query if sphere fails
            if not systems:
                logger.info("EDSM sphere query failed, trying cube tiling")
                systems = self._query_cube_tiled(x, y, z, radius)
            
            return systems
        except Exception as e:
            logger.error(f"EDSM query failed: {e}", exc_info=True)
            return None
    
    def _query_sphere_coords(self, x: float, y: float, z: float, radius: float) -> Optional[List[SystemNode]]:
        """Query EDSM sphere by coordinates."""
        try:
            url = f"{EDSM_BASE}{EDSM_SPHERE}"
            params = {
                'x': x,
                'y': y,
                'z': z,
                'radius': radius,
                'showCoordinates': 1
            }
            
            logger.info(f"EDSM Sphere Query: {url} with radius {radius}")
            
            response = self._session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # EDSM returns dict with error if no systems found or parameters invalid
            if isinstance(data, dict):
                if 'error' in data or 'msg' in data:
                    logger.warning(f"EDSM API message: {data.get('error') or data.get('msg')}")
                    return None
                # Sometimes dict with 'systems' key
                if 'systems' in data:
                    data = data['systems']
                else:
                    logger.warning(f"EDSM returned dict without 'systems' key: {list(data.keys())}")
                    return None
            
            if not isinstance(data, list):
                logger.warning(f"EDSM data is not a list: {type(data)}")
                return None
            
            systems = []
            for sys in data:
                if not isinstance(sys, dict) or 'coords' not in sys:
                    continue
                
                try:
                    sx = float(sys['coords']['x'])
                    sy = float(sys['coords']['y'])
                    sz = float(sys['coords']['z'])
                    
                    dx = sx - x
                    dy = sy - y
                    dz = sz - z
                    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                    
                    systems.append(SystemNode(
                        name=sys['name'],
                        id64=sys.get('id64'),
                        x=sx,
                        y=sy,
                        z=sz,
                        distance=dist
                    ))
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug(f"Skipping invalid system: {e}")
                    continue
            
            systems.sort(key=lambda s: s.distance)
            logger.info(f"EDSM sphere returned {len(systems)} systems")
            return systems if systems else None
            
        except Exception as e:
            logger.error(f"EDSM sphere query failed: {e}")
            return None
    
    def _query_cube_tiled(self, x: float, y: float, z: float, radius: float) -> Optional[List[SystemNode]]:
        """Query EDSM using cube tiling to cover the sphere."""
        try:
            # Use larger cube size and more tiles for better coverage
            cube_size = 200  # EDSM max is 200
            tiles_needed = max(1, int(math.ceil(radius / 80)))  # More overlap
            
            all_systems = []
            seen_ids = set()
            seen_names = set()
            
            logger.info(f"EDSM Cube Tiling: {tiles_needed}x{tiles_needed}x{tiles_needed} tiles, cube size {cube_size}")
            
            tile_count = 0
            for tx in range(-tiles_needed, tiles_needed + 1):
                for ty in range(-tiles_needed, tiles_needed + 1):
                    for tz in range(-tiles_needed, tiles_needed + 1):
                        cx = x + tx * 80  # 80ly spacing for overlap
                        cy = y + ty * 80
                        cz = z + tz * 80
                        
                        url = f"{EDSM_BASE}{EDSM_CUBE}"
                        params = {'x': cx, 'y': cy, 'z': cz, 'size': cube_size, 'showCoordinates': 1}
                        
                        try:
                            response = self._session.get(url, params=params, timeout=15)
                            if response.status_code != 200:
                                logger.debug(f"Tile ({tx},{ty},{tz}) returned {response.status_code}")
                                continue
                            
                            data = response.json()
                            
                            # Handle dict response
                            if isinstance(data, dict):
                                if 'systems' in data:
                                    data = data['systems']
                                else:
                                    continue
                            
                            if not isinstance(data, list):
                                continue
                            
                            tile_systems = 0
                            for sys in data:
                                if not isinstance(sys, dict) or 'coords' not in sys:
                                    continue
                                
                                sys_id = sys.get('id64')
                                sys_name = sys.get('name', '')
                                
                                # Deduplicate by ID or name
                                if sys_id and sys_id in seen_ids:
                                    continue
                                if sys_name in seen_names:
                                    continue
                                
                                if sys_id:
                                    seen_ids.add(sys_id)
                                if sys_name:
                                    seen_names.add(sys_name)
                                
                                try:
                                    sx = float(sys['coords']['x'])
                                    sy = float(sys['coords']['y'])
                                    sz = float(sys['coords']['z'])
                                    
                                    dx = sx - x
                                    dy = sy - y
                                    dz = sz - z
                                    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                                    
                                    if dist <= radius:
                                        all_systems.append(SystemNode(
                                            name=sys_name,
                                            id64=sys_id,
                                            x=sx,
                                            y=sy,
                                            z=sz,
                                            distance=dist
                                        ))
                                        tile_systems += 1
                                except (KeyError, ValueError, TypeError):
                                    continue
                            
                            tile_count += 1
                            if tile_systems > 0:
                                logger.debug(f"Tile ({tx},{ty},{tz}) added {tile_systems} systems")
                                    
                        except Exception as e:
                            logger.debug(f"Cube tile ({tx},{ty},{tz}) failed: {e}")
                            continue
            
            all_systems.sort(key=lambda s: s.distance)
            logger.info(f"EDSM cube tiling: queried {tile_count} tiles, returned {len(all_systems)} systems")
            return all_systems if all_systems else None
            
        except Exception as e:
            logger.error(f"EDSM cube tiling failed: {e}")
            return None
    
    def get_name(self) -> str:
        return "EDSM"
    
    def get_priority(self) -> int:
        return 2


class EDDiscoverySource(SystemDataSource):
    """EDDiscovery local database."""
    
    def __init__(self):
        self.db_path = None
        self._check_paths()
    
    def _check_paths(self):
        possible_paths = [
            os.path.expandvars(r"%APPDATA%\EDDiscovery\EDDUser.sqlite"),
            os.path.expandvars(r"%LOCALAPPDATA%\EDDiscovery\EDDUser.sqlite"),
            # Try alternative table names
            os.path.expandvars(r"%APPDATA%\EDDiscovery\Systems.sqlite"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                self.db_path = path
                logger.info(f"Found EDDiscovery DB at: {path}")
                break
    
    def is_available(self) -> bool:
        if not self.db_path:
            return False
        
        # Test if we can actually query the database
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Try to find the correct table name
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            
            logger.info(f"EDDiscovery DB tables: {tables}")
            
            # Check for known table names
            if any(t in ['SystemList', 'Systems', 'EdsmSystems'] for t in tables):
                return True
            return False
        except Exception as e:
            logger.error(f"EDDiscovery DB test failed: {e}")
            return False
    
    def get_systems_near(self, x: float, y: float, z: float, radius: float, system_name: Optional[str] = None) -> Optional[List[SystemNode]]:
        if not self.is_available():
            logger.info("EDDiscovery DB not available, skipping")
            return None
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Try different table names
            table_name = None
            for name in ['SystemList', 'Systems', 'EdsmSystems', 'system']:
                try:
                    cursor.execute(f"SELECT * FROM {name} LIMIT 1")
                    table_name = name
                    logger.info(f"Using EDDiscovery table: {name}")
                    break
                except:
                    continue
            
            if not table_name:
                conn.close()
                logger.error("No suitable table found in EDDiscovery DB")
                return None
            
            # Query with bounding box
            query = f"""
            SELECT name, x, y, z, id
            FROM {table_name}
            WHERE 
                x BETWEEN ? AND ? AND
                y BETWEEN ? AND ? AND
                z BETWEEN ? AND ?
            LIMIT 1000
            """
            
            cursor.execute(query, (
                x - radius, x + radius,
                y - radius, y + radius,
                z - radius, z + radius
            ))
            
            systems = []
            for row in cursor.fetchall():
                name, sx, sy, sz, sys_id = row
                dx = sx - x
                dy = sy - y
                dz = sz - z
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                
                if dist <= radius:
                    systems.append(SystemNode(
                        name=name,
                        id64=sys_id,
                        x=sx,
                        y=sy,
                        z=sz,
                        distance=dist
                    ))
            
            conn.close()
            systems.sort(key=lambda s: s.distance)
            logger.info(f"EDDiscovery DB returned {len(systems)} systems")
            return systems if systems else None
        except Exception as e:
            logger.error(f"EDDiscovery query failed: {e}")
            return None
    
    def get_name(self) -> str:
        return "EDDiscovery"
    
    def get_priority(self) -> int:
        return 0  # Local DB has highest priority


class LocalJSONSource(SystemDataSource):
    """Local JSON file (EDDiscovery export)."""
    
    def __init__(self, file_path: Optional[str] = None):
        self.file_path = file_path
        self._data = None
        if file_path:
            self._load_file()
    
    def set_file(self, path: str):
        self.file_path = path
        self._load_file()
    
    def _load_file(self):
        if not self.file_path or not os.path.exists(self.file_path):
            self._data = None
            return
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                self._data = json.load(f)
            logger.info(f"Loaded local JSON: {self.file_path}")
        except Exception as e:
            logger.error(f"Failed to load JSON: {e}")
            self._data = None
    
    def is_available(self) -> bool:
        return self._data is not None
    
    def get_systems_near(self, x: float, y: float, z: float, radius: float, system_name: Optional[str] = None) -> Optional[List[SystemNode]]:
        if not self.is_available():
            return None
        
        try:
            raw_systems = self._data.get('Nearest', [])
            systems = []
            
            for sys in raw_systems:
                if not all(k in sys for k in ['Name', 'X', 'Y', 'Z']):
                    continue
                
                dx = sys['X'] - x
                dy = sys['Y'] - y
                dz = sys['Z'] - z
                dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                
                if dist <= radius:
                    systems.append(SystemNode(
                        name=sys['Name'],
                        id64=None,  # Will be filled from journal
                        x=sys['X'],
                        y=sys['Y'],
                        z=sys['Z'],
                        distance=dist
                    ))
            
            systems.sort(key=lambda s: s.distance)
            logger.info(f"Local JSON returned {len(systems)} systems")
            return systems if systems else None
        except Exception as e:
            logger.error(f"Local JSON processing failed: {e}")
            return None
    
    def get_name(self) -> str:
        return "Local JSON"
    
    def get_priority(self) -> int:
        return 0  # Highest priority when available


class DataSourceManager:
    """Manages multiple data sources with automatic fallback."""
    
    def __init__(self):
        self.sources: Dict[str, SystemDataSource] = {
            'local_json': LocalJSONSource(),
            'edd': EDDiscoverySource(),
            'edsm': EDSMSource(),
        }
    
    def set_local_file(self, path: str):
        self.sources['local_json'].set_file(path)
    
    def get_best_source(self, prefer_source: Optional[str] = None) -> Optional[SystemDataSource]:
        """Get best available source."""
        # If preference specified and available, use it
        if prefer_source and prefer_source in self.sources:
            source = self.sources[prefer_source]
            if source.is_available():
                logger.info(f"Using preferred source: {source.get_name()}")
                return source
            else:
                logger.warning(f"Preferred source {prefer_source} not available")
        
        # Otherwise, use best available by priority
        available = [(s.get_priority(), name, s) for name, s in self.sources.items() if s.is_available()]
        if not available:
            logger.error("No data sources available!")
            return None
        
        available.sort()
        logger.info(f"Available sources: {[(name, s.get_name()) for _, name, s in available]}")
        
        return available[0][2]
    
    def get_systems_near(self, x: float, y: float, z: float, radius: float, 
                        system_name: Optional[str] = None,
                        prefer_source: Optional[str] = None) -> Tuple[Optional[List[SystemNode]], Optional[str]]:
        """Get systems from best available source with automatic fallback."""
        
        # Build list of sources to try
        sources_to_try = []
        
        # If preference specified, try it first
        if prefer_source and prefer_source in self.sources:
            source = self.sources[prefer_source]
            if source.is_available():
                sources_to_try.append((prefer_source, source))
        
        # Add all other available sources by priority
        available = [(s.get_priority(), name, s) for name, s in self.sources.items() 
                    if s.is_available() and name != prefer_source]
        available.sort()
        sources_to_try.extend([(name, s) for _, name, s in available])
        
        if not sources_to_try:
            logger.error("No data sources available to try")
            return None, None
        
        # Try each source until one succeeds
        for source_name, source in sources_to_try:
            logger.info(f"Trying data source: {source.get_name()}")
            
            try:
                systems = source.get_systems_near(x, y, z, radius, system_name)
                
                if systems and len(systems) > 0:
                    logger.info(f"SUCCESS: {source.get_name()} returned {len(systems)} systems")
                    return systems, source.get_name()
                else:
                    logger.warning(f"EMPTY: {source.get_name()} returned no systems")
            except Exception as e:
                logger.error(f"ERROR: {source.get_name()} failed: {e}")
                continue
        
        # All sources failed
        logger.error("All data sources failed or returned no results")
        return None, None

# ============================================================================
# Global State
# ============================================================================

_state = SurveyState()
_data_manager = DataSourceManager()
_current_system: Optional[str] = None
_current_system_id: Optional[int] = None
_current_coords: Optional[Tuple[float, float, float]] = None
_current_max_jump: Optional[float] = None

# UI Widgets
_root_frame: Optional[tk.Frame] = None
_status_var: Optional[tk.StringVar] = None
_target_var: Optional[tk.StringVar] = None
_progress_var: Optional[tk.StringVar] = None
_source_status_var: Optional[tk.StringVar] = None

# ============================================================================
# Helper Functions
# ============================================================================

def _get_config_bool(key: str, default: bool = False) -> bool:
    """Get boolean config value with fallback for older EDMC versions."""
    try:
        if hasattr(config, 'get_bool'):
            return config.get_bool(key)
        else:
            val = config.get(key)
            if val is None:
                return default
            return bool(val)
    except:
        return default


def _get_config_int(key: str, default: int = 0) -> int:
    """Get integer config value with fallback."""
    try:
        if hasattr(config, 'get_int'):
            return config.get_int(key)
        else:
            val = config.get(key)
            if val is None:
                return default
            return int(val)
    except:
        return default


def _get_config_str(key: str, default: str = '') -> str:
    """Get string config value with fallback."""
    try:
        if hasattr(config, 'get_str'):
            return config.get_str(key)
        else:
            val = config.get(key)
            return str(val) if val is not None else default
    except:
        return default

# ============================================================================
# State Persistence
# ============================================================================

def _save_state():
    """Save state to disk."""
    try:
        data = {
            'active': _state.active,
            'start_system': _state.start_system,
            'start_coords': list(_state.start_coords) if _state.start_coords else None,
            'radius_ly': _state.radius_ly,
            'max_jump_ly': _state.max_jump_ly,
            'prefer_short_jumps': _state.prefer_short_jumps,
            'pending_systems': [
                {
                    'name': s.name,
                    'id64': s.id64,
                    'x': s.x,
                    'y': s.y,
                    'z': s.z,
                    'distance': s.distance
                } for s in _state.pending_systems
            ],
            'visited_ids': list(_state.visited_ids),
            'visited_names': list(_state.visited_names),
            'all_systems': {
                name: {
                    'name': s.name,
                    'id64': s.id64,
                    'x': s.x,
                    'y': s.y,
                    'z': s.z,
                    'distance': s.distance
                } for name, s in _state.all_systems.items()
            },
            'started_ts': _state.started_ts,
            'data_source_used': _state.data_source_used
        }
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        logger.debug("State saved")
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def _load_state():
    """Load state from disk."""
    if not os.path.exists(STATE_FILE):
        return
    
    try:
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        _state.active = data.get('active', False)
        _state.start_system = data.get('start_system')
        coords = data.get('start_coords')
        _state.start_coords = tuple(coords) if coords else None
        _state.radius_ly = data.get('radius_ly', 50.0)
        _state.max_jump_ly = data.get('max_jump_ly')
        _state.prefer_short_jumps = data.get('prefer_short_jumps', True)
        
        _state.pending_systems = [
            SystemNode(**s) for s in data.get('pending_systems', [])
        ]
        _state.visited_ids = set(data.get('visited_ids', []))
        _state.visited_names = set(data.get('visited_names', []))
        _state.all_systems = {
            name: SystemNode(**s) for name, s in data.get('all_systems', {}).items()
        }
        _state.started_ts = data.get('started_ts')
        _state.data_source_used = data.get('data_source_used')
        
        logger.info(f"State loaded: {len(_state.pending_systems)} pending, {len(_state.visited_names)} visited")
    except Exception as e:
        logger.error(f"Failed to load state: {e}")

# ============================================================================
# Current Location Detection
# ============================================================================

def _update_current_location_from_monitor():
    """Update current location from EDMC monitor state."""
    global _current_system, _current_system_id, _current_coords
    
    try:
        from monitor import monitor
        state = monitor.state
        
        if not state:
            logger.debug("Monitor state is empty")
            return False
        
        system_name = state.get('SystemName') or state.get('StarSystem')
        system_id = state.get('SystemAddress')
        coords = state.get('StarPos')
        
        changed = False
        
        if system_name and system_name != _current_system:
            _current_system = system_name
            changed = True
            logger.info(f"Current system from monitor: {system_name}")
        
        if system_id and system_id != _current_system_id:
            _current_system_id = system_id
            changed = True
            logger.info(f"Current system ID from monitor: {system_id}")
        
        if coords and len(coords) >= 3:
            new_coords = tuple(coords[:3])
            if new_coords != _current_coords:
                _current_coords = new_coords
                changed = True
                logger.info(f"Current coords from monitor: {_current_coords}")
        
        return changed
        
    except Exception as e:
        logger.error(f"Failed to update from monitor: {e}")
        return False

# ============================================================================
# Survey Logic
# ============================================================================

def _get_next_target() -> Optional[SystemNode]:
    """Get next system to visit, preferring shortest jumps if configured."""
    if not _state.pending_systems or not _current_coords:
        return None
    
    if _state.prefer_short_jumps and _current_coords:
        # Find nearest unvisited system from current position
        cx, cy, cz = _current_coords
        
        def dist_from_current(sys: SystemNode) -> float:
            dx = sys.x - cx
            dy = sys.y - cy
            dz = sys.z - cz
            return math.sqrt(dx*dx + dy*dy + dz*dz)
        
        # Filter by jump range if available
        candidates = _state.pending_systems
        if _state.max_jump_ly:
            candidates = [s for s in candidates if dist_from_current(s) <= _state.max_jump_ly]
        
        if not candidates:
            # No reachable systems, take closest even if out of range
            candidates = _state.pending_systems
        
        # Sort by distance from current position
        candidates.sort(key=dist_from_current)
        return candidates[0] if candidates else None
    else:
        # Take next from queue (sorted by distance from start)
        return _state.pending_systems[0] if _state.pending_systems else None


def _mark_visited(system_name: str, system_id: Optional[int] = None):
    """Mark a system as visited."""
    if system_id:
        _state.visited_ids.add(system_id)
    _state.visited_names.add(system_name)
    
    # Remove from pending
    _state.pending_systems = [s for s in _state.pending_systems 
                              if s.name != system_name and (not system_id or s.id64 != system_id)]
    
    # Update UI
    if _root_frame:
        _root_frame.after(0, _refresh_ui)
    
    _save_state()
    logger.info(f"Marked visited: {system_name} (ID: {system_id})")


def _copy_to_clipboard(text: str):
    """Copy text to clipboard."""
    try:
        if not _root_frame:
            logger.error("Cannot copy to clipboard: _root_frame is None")
            return
        
        _root_frame.clipboard_clear()
        _root_frame.clipboard_append(text)
        _root_frame.update()
        logger.info(f"✓ Copied to clipboard: {text}")
    except Exception as e:
        logger.error(f"Clipboard copy failed: {e}", exc_info=True)


def _start_survey():
    """Start a new survey."""
    global _current_system, _current_coords
    
    # Try to get current location from monitor
    _update_current_location_from_monitor()
    
    if not _current_system or not _current_coords:
        logger.error("Cannot start: no current system")
        if _status_var:
            _status_var.set("Error: No current system detected")
            _status_var.set("Error: Start Elite Dangerous first")
        return
    
    # Get config
    radius = config.get_int(CFG_RADIUS) if hasattr(config, 'get_int') else int(config.get(CFG_RADIUS) or 50)
    prefer_source = config.get_str(CFG_DATA_SOURCE) if hasattr(config, 'get_str') else config.get(CFG_DATA_SOURCE)
    
    # Reset state
    _state.reset()
    _state.active = True
    _state.start_system = _current_system
    _state.start_coords = _current_coords
    _state.radius_ly = radius
    _state.max_jump_ly = _current_max_jump
    _state.prefer_short_jumps = config.get_bool(CFG_PREFER_SHORT_JUMPS) if hasattr(config, 'get_bool') else bool(config.get(CFG_PREFER_SHORT_JUMPS))
    _state.started_ts = time.time()
    
    # Query systems in background thread
    def query_systems():
        x, y, z = _current_coords
        systems, source_name = _data_manager.get_systems_near(x, y, z, radius, _current_system, prefer_source)
        
        if not systems:
            logger.error("No systems found")
            if _status_var:
                _root_frame.after(0, lambda: _status_var.set("Error: No systems found"))
            _state.reset()
            return
        
        # Store all systems
        _state.all_systems = {s.name: s for s in systems}
        _state.pending_systems = list(systems)
        _state.data_source_used = source_name
        
        # Mark start system as visited
        _state.visited_names.add(_current_system)
        if _current_system_id:
            _state.visited_ids.add(_current_system_id)
        
        _state.pending_systems = [s for s in _state.pending_systems if s.name != _current_system]
        
        _save_state()
        
        # Update UI and copy first target
        if _root_frame:
            _root_frame.after(0, _refresh_ui)
            target = _get_next_target()
            autocopy_enabled = _get_config_bool(CFG_AUTOCOPY, True)
            logger.info(f"Auto-copy enabled: {autocopy_enabled}, Target: {target.name if target else None}")
            if target and autocopy_enabled:
                logger.info(f"Scheduling clipboard copy for: {target.name}")
                _root_frame.after(0, lambda: _copy_to_clipboard(target.name))
        
        logger.info(f"Survey started: {len(systems)} systems from {source_name}")
    
    thread = threading.Thread(target=query_systems, daemon=True)
    thread.start()
    
    if _status_var:
        _status_var.set("Loading systems...")


def _stop_survey():
    """Stop current survey."""
    _state.active = False
    _save_state()
    _refresh_ui()
    logger.info("Survey stopped")


def _reset_survey():
    """Reset survey state."""
    _state.reset()
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
    _refresh_ui()
    logger.info("Survey reset")


def _return_to_start():
    """Queue return to start system."""
    if not _state.start_system:
        return
    
    if _current_system == _state.start_system:
        logger.info("Already at start system")
        if _status_var:
            _status_var.set("Already at start system")
        return
    
    # Copy start system name to clipboard
    _copy_to_clipboard(_state.start_system)
    if _status_var:
        _status_var.set(f"Return to: {_state.start_system}")
    logger.info(f"Returning to start: {_state.start_system}")

# ============================================================================
# UI Functions
# ============================================================================

def _refresh_ui():
    """Update all UI elements."""
    if not _root_frame:
        return
    
    try:
        # Status
        if _status_var:
            if _state.active:
                _status_var.set("Survey Active")
            else:
                _status_var.set("Inactive")
        
        # Target
        if _target_var:
            target = _get_next_target()
            if target:
                _target_var.set(target.name)
            elif _state.active and not _state.pending_systems:
                _target_var.set("Survey Complete!")
            else:
                _target_var.set("-")
        
        # Progress
        if _progress_var:
            if _state.all_systems:
                total = len(_state.all_systems)
                visited = len(_state.visited_names)
                pending = len(_state.pending_systems)
                _progress_var.set(f"{visited}/{total} visited, {pending} pending")
            else:
                _progress_var.set("-")
        
        # Source status
        if _source_status_var:
            if _state.data_source_used:
                _source_status_var.set(f"Source: {_state.data_source_used}")
            else:
                _source_status_var.set("No data source")
    except Exception as e:
        logger.error(f"UI refresh failed: {e}")

# ============================================================================
# EDMC Plugin Interface
# ============================================================================

def plugin_start3(plugin_dir: str) -> str:
    """Plugin initialization."""
    global PLUGIN_DIR, STATE_PATH, _data_manager
    PLUGIN_DIR = plugin_dir
    STATE_PATH = STATE_FILE
    
    # Set defaults on first run
    if config.get(CFG_ENABLED) is None:
        config.set(CFG_ENABLED, True)
    if config.get(CFG_AUTOCOPY) is None:
        config.set(CFG_AUTOCOPY, True)
    if config.get(CFG_PREFER_SHORT_JUMPS) is None:
        config.set(CFG_PREFER_SHORT_JUMPS, True)
    if config.get(CFG_RADIUS) is None:
        config.set(CFG_RADIUS, 50)
    
    # Auto-load neareststars.json from plugin folder if present
    auto_json = os.path.join(plugin_dir, 'neareststars.json')
    if os.path.exists(auto_json):
        logger.info(f"Auto-loading neareststars.json from plugin folder")
        local_source = _data_manager.sources.get('local_json')
        if local_source:
            local_source.set_file(auto_json)
            # Save to config so it appears in settings
            config.set(CFG_LOCAL_PATH, auto_json)
    
    _load_state()
    logger.info(f"Plugin started v{VERSION}")
    return f"EDMC_SphereSurvey v{VERSION}"


def plugin_stop():
    """Plugin shutdown."""
    _save_state()
    logger.info("Plugin stopped")


def plugin_app(parent: tk.Frame) -> tk.Frame:
    """Create main UI frame."""
    global _root_frame, _status_var, _target_var, _progress_var, _source_status_var
    
    _root_frame = tk.Frame(parent)
    _root_frame.columnconfigure(1, weight=1)
    
    row = 0
    
    # Title
    tk.Label(_root_frame, text="Sphere Survey:").grid(row=row, column=0, sticky=tk.W)
    _status_var = tk.StringVar(value="Inactive")
    tk.Label(_root_frame, textvariable=_status_var).grid(row=row, column=1, sticky=tk.W)
    row += 1
    
    # Current system display
    tk.Label(_root_frame, text="Current:").grid(row=row, column=0, sticky=tk.W)
    current_var = tk.StringVar(value=_current_system or "Unknown")
    tk.Label(_root_frame, textvariable=current_var).grid(row=row, column=1, sticky=tk.W)
    _root_frame.current_var = current_var  # Store for updates
    row += 1
    
    # Next target
    tk.Label(_root_frame, text="Next target:").grid(row=row, column=0, sticky=tk.W)
    _target_var = tk.StringVar(value="-")
    tk.Label(_root_frame, textvariable=_target_var).grid(row=row, column=1, sticky=tk.W)
    row += 1
    
    # Progress
    tk.Label(_root_frame, text="Progress:").grid(row=row, column=0, sticky=tk.W)
    _progress_var = tk.StringVar(value="-")
    tk.Label(_root_frame, textvariable=_progress_var).grid(row=row, column=1, sticky=tk.W)
    row += 1
    
    # Source status
    _source_status_var = tk.StringVar(value="No data source")
    tk.Label(_root_frame, textvariable=_source_status_var, foreground="gray").grid(
        row=row, column=0, columnspan=2, sticky=tk.W
    )
    row += 1
    
    # Buttons
    btn_frame = tk.Frame(_root_frame)
    btn_frame.grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=5)
    
    def detect_system():
        """Manually detect current system."""
        if _update_current_location_from_monitor():
            if _root_frame.current_var:
                _root_frame.current_var.set(_current_system or "Unknown")
            if _status_var:
                _status_var.set(f"Detected: {_current_system}")
        else:
            if _status_var:
                _status_var.set("Cannot detect system - Start Elite!")
    
    tk.Button(btn_frame, text="Detect", command=detect_system).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text="Start", command=_start_survey).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text="Stop", command=_stop_survey).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text="Reset", command=_reset_survey).pack(side=tk.LEFT, padx=2)
    tk.Button(btn_frame, text="Return", command=_return_to_start).pack(side=tk.LEFT, padx=2)
    
    theme.update(_root_frame)
    
    # Initial detection
    _update_current_location_from_monitor()
    if _root_frame.current_var:
        _root_frame.current_var.set(_current_system or "Unknown")
    
    _refresh_ui()
    
    return _root_frame


def plugin_prefs(parent: nb.Notebook, cmdr: str, is_beta: bool) -> Optional[tk.Frame]:
    """Create preferences UI."""
    frame = nb.Frame(parent)
    frame.columnconfigure(1, weight=1)
    
    row = 0
    
    # Title
    nb.Label(frame, text=f"Sphere Survey v{VERSION}").grid(row=row, column=0, columnspan=2, sticky=tk.W)
    row += 1
    
    # Enabled
    enabled_val = _get_config_bool(CFG_ENABLED, True)  # Use helper, default True
    enabled_var = tk.IntVar(value=1 if enabled_val else 0)
    nb.Checkbutton(frame, text="Enable plugin", variable=enabled_var, 
                   command=lambda: config.set(CFG_ENABLED, bool(enabled_var.get()))).grid(
        row=row, column=0, columnspan=2, sticky=tk.W
    )
    row += 1
    
    # Debug
    debug_val = _get_config_bool(CFG_DEBUG, False)  # Use helper, default False
    debug_var = tk.IntVar(value=1 if debug_val else 0)
    nb.Checkbutton(frame, text="Debug logging", variable=debug_var,
                   command=lambda: config.set(CFG_DEBUG, bool(debug_var.get()))).grid(
        row=row, column=0, columnspan=2, sticky=tk.W
    )
    row += 1
    
    # Radius
    nb.Label(frame, text="Default radius (ly):").grid(row=row, column=0, sticky=tk.W)
    radius_var = tk.StringVar(value=str(config.get_int(CFG_RADIUS) if hasattr(config, 'get_int') else config.get(CFG_RADIUS) or 50))
    
    def save_radius(*args):
        try:
            config.set(CFG_RADIUS, int(radius_var.get()))
        except:
            pass
    
    radius_entry = nb.Entry(frame, textvariable=radius_var, width=10)
    radius_entry.grid(row=row, column=1, sticky=tk.W)
    radius_var.trace('w', save_radius)
    row += 1
    
    # Jump range  
    nb.Label(frame, text="Max jump range (ly):").grid(row=row, column=0, sticky=tk.W)
    jump_var = tk.StringVar(value=str(config.get_int(CFG_JUMP_RANGE) if hasattr(config, 'get_int') else config.get(CFG_JUMP_RANGE) or 65))
    
    def save_jump(*args):
        try:
            config.set(CFG_JUMP_RANGE, int(jump_var.get()))
        except:
            pass
    
    jump_entry = nb.Entry(frame, textvariable=jump_var, width=10)
    jump_entry.grid(row=row, column=1, sticky=tk.W)
    jump_var.trace('w', save_jump)
    row += 1
    
    # Data source
    nb.Label(frame, text="Preferred data source:").grid(row=row, column=0, sticky=tk.W)
    source_var = tk.StringVar(value=config.get_str(CFG_DATA_SOURCE) if hasattr(config, 'get_str') else config.get(CFG_DATA_SOURCE) or 'auto')
    
    def save_source(*args):
        config.set(CFG_DATA_SOURCE, source_var.get())
    
    source_combo = ttk.Combobox(frame, textvariable=source_var, values=['auto', 'local_json', 'edd', 'edsm'], width=15, state='readonly')
    source_combo.grid(row=row, column=1, sticky=tk.W)
    source_combo.bind('<<ComboboxSelected>>', save_source)
    row += 1
    
    # Local JSON path
    nb.Label(frame, text="Local JSON file:").grid(row=row, column=0, sticky=tk.W)
    path_var = tk.StringVar(value=config.get_str(CFG_LOCAL_PATH) if hasattr(config, 'get_str') else config.get(CFG_LOCAL_PATH) or '')
    
    def save_path(*args):
        config.set(CFG_LOCAL_PATH, path_var.get())
        if path_var.get():
            _data_manager.set_local_file(path_var.get())
    
    path_entry = nb.Entry(frame, textvariable=path_var, width=30)
    path_entry.grid(row=row, column=1, sticky=tk.EW)
    path_var.trace('w', save_path)
    row += 1
    
    def browse_file():
        path = filedialog.askopenfilename(
            title="Select neareststars.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            path_var.set(path)
    
    nb.Button(frame, text="Browse...", command=browse_file).grid(row=row, column=1, sticky=tk.W)
    row += 1
    
    # Auto-copy
    autocopy_val = _get_config_bool(CFG_AUTOCOPY, True)  # Use helper, default True
    autocopy_var = tk.IntVar(value=1 if autocopy_val else 0)
    nb.Checkbutton(frame, text="Auto-copy next target to clipboard", variable=autocopy_var,
                   command=lambda: config.set(CFG_AUTOCOPY, bool(autocopy_var.get()))).grid(
        row=row, column=0, columnspan=2, sticky=tk.W
    )
    row += 1
    
    # Prefer short jumps
    prefer_val = _get_config_bool(CFG_PREFER_SHORT_JUMPS, True)  # Use helper, default True
    prefer_short_var = tk.IntVar(value=1 if prefer_val else 0)
    nb.Checkbutton(frame, text="Prefer shortest jumps from current position", variable=prefer_short_var,
                   command=lambda: config.set(CFG_PREFER_SHORT_JUMPS, bool(prefer_short_var.get()))).grid(
        row=row, column=0, columnspan=2, sticky=tk.W
    )
    row += 1
    
    theme.update(frame)
    return frame


def prefs_changed(cmdr: str, is_beta: bool) -> None:
    """Save preference changes."""
    try:
        # Config values are stored directly, not via frame reference
        logger.info("Preferences saved")
    except Exception as e:
        logger.error(f"Failed to save preferences: {e}")


def dashboard_entry(cmdr: str, is_beta: bool, entry: dict) -> None:
    """Process dashboard entry (Status.json)."""
    global _current_max_jump
    
    try:
        # Update current location from monitor when dashboard updates
        _update_current_location_from_monitor()
        
        # Update UI with current system
        if _root_frame and hasattr(_root_frame, 'current_var'):
            _root_frame.after(0, lambda: _root_frame.current_var.set(_current_system or "Unknown"))
        
        # Get ship jump range from dashboard
        if 'FuelCapacity' in entry:
            fuel_cap = entry['FuelCapacity'].get('Main', 0)
            if fuel_cap > 0 and _current_max_jump is None:
                _current_max_jump = fuel_cap * 2.0
                logger.info(f"Jump range estimate from dashboard: {_current_max_jump:.2f} ly")
    except Exception as e:
        logger.error(f"Error in dashboard_entry: {e}")


def journal_entry(
    cmdr: str,
    is_beta: bool,
    system: str,
    station: str,
    entry: Dict[str, Any],
    state: Dict[str, Any]
) -> None:
    """Process journal entries."""
    global _current_system, _current_system_id, _current_coords, _current_max_jump
    
    try:
        event = entry.get("event")
        
        # Location events
        if event in ("Location", "FSDJump", "CarrierJump"):
            _current_system = entry.get("StarSystem")
            _current_system_id = entry.get("SystemAddress")
            
            coords = entry.get("StarPos")
            if coords and len(coords) >= 3:
                _current_coords = tuple(coords[:3])
            
            logger.info(f"Location update: {_current_system} @ {_current_coords}")
            
            # Update UI
            if _root_frame and hasattr(_root_frame, 'current_var'):
                _root_frame.after(0, lambda: _root_frame.current_var.set(_current_system or "Unknown"))
            
            # Mark visited if in survey
            if _state.active and _current_system:
                _mark_visited(_current_system, _current_system_id)
                
                # Copy next target to clipboard
                target = _get_next_target()
                autocopy_enabled = _get_config_bool(CFG_AUTOCOPY, True)
                logger.info(f"After jump - Auto-copy: {autocopy_enabled}, Next target: {target.name if target else 'None'}")
                if target and autocopy_enabled:
                    # Delayed copy to handle rapid jumps
                    logger.info(f"Scheduling delayed clipboard copy for: {target.name}")
                    if _root_frame:
                        _root_frame.after(1500, lambda: _copy_to_clipboard(target.name))
            
            if _root_frame:
                _root_frame.after(0, _refresh_ui)
        
        # Ship loadout for jump range
        elif event == "Loadout":
            max_jump = entry.get("MaxJumpRange", 0)
            if max_jump > 0:
                _current_max_jump = max_jump
                logger.info(f"Jump range updated: {max_jump:.2f} ly")
        
    except Exception as e:
        logger.error(f"Error in journal_entry: {e}", exc_info=True)
    
    # Always try to update from monitor as backup
    if not _current_system:
        _update_current_location_from_monitor()
        if _root_frame and hasattr(_root_frame, 'current_var'):
            _root_frame.after(0, lambda: _root_frame.current_var.set(_current_system or "Unknown"))