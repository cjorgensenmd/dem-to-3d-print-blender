# DEM to 3D Print STL — Blender Addon

A Blender addon that converts Digital Elevation Model (DEM) files into 3D-printable STL terrain tiles, with optional overlay support for buildings, roads, trails, and street labels. Designed for high-RAM systems (64GB+) to handle high-resolution terrain meshes.

![Blender](https://img.shields.io/badge/Blender-3.0%2B-orange) ![License](https://img.shields.io/github/license/cjorgensenmd/dem-to-3d-print-blender) ![GitHub release](https://img.shields.io/github/v/release/cjorgensenmd/dem-to-3d-print-blender) ![GitHub stars](https://img.shields.io/github/stars/cjorgensenmd/dem-to-3d-print-blender)

## Features

- **DEM to STL conversion** — Import GeoTIFF, ASC, HGT, IMG, and other DEM formats and produce watertight, 3D-printable terrain models
- **High subdivision support** — Leverages systems with large amounts of RAM to produce extremely detailed terrain meshes (subdivision levels up to 15)
- **CityJSON building import** — Import LoD0–LoD2 3D buildings from German cadastral (or other) CityJSON data, with roof geometry preserved
- **Shapefile building footprints** — Import 2D building footprints and extrude to configurable height
- **Road & trail overlays** — Import road and trail shapefiles, buffered and shrinkwrapped onto the terrain surface, exported as separate STL files for multi-color/multi-material printing
- **Road labels** — Auto-generate 3D street name labels from shapefile attributes, positioned and oriented along roads
- **Bowtie alignment cutouts** — Triangular registration cutouts on tile edges for aligning adjacent terrain tiles
- **Mounting holes** — Cylindrical holes near tile corners for back-mounting with screws or pins
- **North arrow & filename text** — Debossed compass indicator and DEM filename on the tile bottom for orientation
- **Batch processing** — Process an entire folder of DEM tiles in one run with shared settings
- **Multi-STL export** — Terrain, buildings, roads, trails, and labels exported as separate STL files for multi-material printing
- **Auto flat-bottom cut** — Automatically determines the lowest elevation and cuts a flat base

## Screenshots

*(Add screenshots of the sidebar panel and example output tiles here)*

## Prerequisites

### Software

| Requirement | Version | Notes |
|---|---|---|
| **Blender** | 3.0+ | Tested primarily on 3.x and 4.x |
| **BlenderGIS addon** | Latest | Required for DEM import. Install from [domlysz/BlenderGIS](https://github.com/domlysz/BlenderGIS) |

### Hardware

- **RAM**: 64GB minimum recommended. Higher subdivision levels (12+) can consume 100GB+ of RAM. The addon is specifically optimized for high-RAM workstations.
- **Storage**: Adequate free disk space for large STL files (high-detail tiles can be hundreds of MB each)

### Python Dependencies (bundled with Blender)

The addon uses only Blender's built-in Python modules (`bpy`, `bmesh`, `mathutils`, `json`, `os`, `math`). No additional pip packages are required.

### Optional Data Sources

- **DEM files** — GeoTIFF (`.tif`/`.tiff`), Arc ASCII Grid (`.asc`), SRTM (`.hgt`), ERDAS IMG (`.img`), or USGS DEM (`.dem`)
- **Shapefiles** (`.shp`) — For buildings, roads, and trails. Requires accompanying `.shx`, `.dbf`, and `.prj` files.
- **CityJSON** (`.json`/`.city.json`) — For 3D LoD2 building models (e.g., German state surveying office open data)

## Installation

1. Download `dem_to_3d_print_highram_v65.py`
2. In Blender, go to **Edit → Preferences → Add-ons → Install...**
3. Select the downloaded `.py` file and click **Install Add-on**
4. Enable the addon by checking the box next to **"DEM to 3D Print STL (High-RAM)"**
5. The panel appears in the 3D Viewport sidebar under the **DEM Print** tab (press `N` to open the sidebar)

> **Important:** You must also have the [BlenderGIS](https://github.com/domlysz/BlenderGIS) addon installed and enabled, as it handles the initial DEM raster import.

## Usage

1. Open the **DEM Print** tab in the 3D Viewport sidebar
2. Select your DEM file and output folder
3. Configure print size, subdivision level, and base thickness
4. Optionally enable buildings, roads, trails, alignment cutouts, or mounting holes
5. Click **Process DEM** — the addon will run through all steps and export STL files to your output folder

### Batch Processing

To process multiple DEM tiles at once:

1. Place all DEM files in a single folder
2. Set the **Batch Input Folder** at the bottom of the panel
3. Optionally enable **Include Subfolders**
4. Click **Process All** — each tile is processed with the same settings and exported individually

### Multi-Material Printing

The addon exports terrain, buildings, roads, trails, and labels as separate STL files with a common origin. Import them into your slicer and they will align automatically, allowing you to assign different colors or materials to each layer.

## Processing Pipeline

1. **Import** — DEM loaded via BlenderGIS georaster importer
2. **Subdivide** — Subdivision surface modifier applied for mesh detail
3. **Apply modifiers** — Geometry baked to mesh
4. **Extrude base** — Solid base created below terrain
5. **Cut bottom** — Flat bottom cut at lowest elevation
6. **Buildings** — CityJSON or shapefile buildings added (optional)
7. **Roads** — Road geometry created and shrinkwrapped to terrain (optional)
8. **Trails** — Trail geometry created and shrinkwrapped to terrain (optional)
9. **Text** — Filename and north arrow debossed on bottom
10. **Alignment cutouts** — Bowtie registration features cut into edges (optional)
11. **Mounting holes** — Cylindrical holes cut near corners (optional)
12. **Scale & Export** — Model scaled to target print width and exported as STL

## Configuration Reference

| Parameter | Default | Description |
|---|---|---|
| Output Width | 200mm | Target width of the printed tile |
| Subdivision Levels | 11 | Mesh detail (higher = more RAM) |
| Base Thickness | 7000m | Solid base depth (in source CRS units) |
| Cutout Size | 5mm | Bowtie triangle base width |
| Cutout Depth | 3mm | Depth of alignment cutouts |
| Mounting Hole Diameter | 3mm | Diameter of corner mounting holes |
| Building Height | 12m | Extrusion height for shapefile buildings |
| Road Width | 40m | Buffer width for road lines |

## Known Limitations

- Requires BlenderGIS for DEM import — the addon does not include its own raster reader
- Boolean operations (text deboss, alignment cutouts) can occasionally fail on very complex meshes — the addon uses the EXACT solver to mitigate this
- Very high subdivision levels (13+) may require 128GB+ RAM and take significant processing time
- CityJSON import expects coordinates in the same CRS as the DEM

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- [BlenderGIS](https://github.com/domlysz/BlenderGIS) by domlysz — DEM import functionality
- German state surveying offices for open CityJSON/CityGML building data
