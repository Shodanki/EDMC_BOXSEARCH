# -*- coding: utf-8 -*-
# Derived from EDTS (https://bitbucket.org/Esvandiary/edts),
# Copyright (c) 2016, Andy Martin. BSD 3-Clause licence - see LICENSE.txt.
# SPDX-License-Identifier: BSD-3-Clause
"""Sector names computed with EDTS's algorithm - origin in SOURCE.md."""

from .pgnames import (BASE_COORDS, GALAXY_ORIGIN, SECTOR_SIZE, HARegion,  # noqa: F401
                      format_sector_name, ha_region, ha_region_at,
                      ha_regions_near, is_valid_sector_name, sector_fragments,
                      sector_index, sector_name)
