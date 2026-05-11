# Selene PSS — Blender addon

Blender addon for importing photometric stereo scans produced by the Selene PSS scanner.
Builds a displaced mesh from a 32-bit float depth map and applies albedo, normal and alpha textures.

Developed at [Factum Arte / Factum Foundation](https://www.factumfoundation.org).

## Requirements

- Blender 4.1 or newer (drag-and-drop requires 4.1+)
- Depth map must be a **32-bit float grayscale TIFF** with values in metres

## Installation

1. Download `pss_importer_addon.py`
2. Blender → Edit → Preferences → Add-ons → Install → select the file
3. Enable **Selene PSS**
4. Open the N-panel in the 3D viewport (key `N`) → tab **PSS**

## Usage

### Images
| Slot | Format | Required |
|------|--------|----------|
| Depth | 32-bit float TIFF (metres) | Yes |
| Albedo | 16-bit RGB TIFF | No |
| Normal map | 16-bit RGB TIFF | No |
| Alpha | 8-bit PNG | No |

Files can be assigned with the folder button or by **drag-and-dropping onto the 3D viewport**.
Dropped files fill the first empty slot in order: depth → albedo → normal → alpha.

### Object size

| Mode | Description |
|------|-------------|
| W / H | Enter real-world width and height in cm |
| DPI | Size calculated automatically from image pixel dimensions and scanner DPI |

### Geometry quality

| Setting | Subdivision factor | Use |
|---------|--------------------|-----|
| Low | n=64 | Preview |
| Medium | n=32 | General use |
| High | n=16 | Final quality |
| Ultra | n=8 | Maximum detail (slow) |

**Geometry Quality only changes mesh density.** It does not reduce the size of
the depth, albedo, normal or alpha textures, which are always loaded at full
resolution.

## Large scans

Blender can freeze or crash on very large recordings (above ~16 384 px per side
or files larger than ~500 MB). The most common limits are GPU texture size and
RAM pressure during depth-map conversion, neither of which the addon can lift.

If the panel shows a large-file warning, downsample the inputs **before**
importing them. ImageMagick is the simplest tool:

```
magick depth.tif   -resize 8192x8192 depth_8k.tif
magick albedo.tif  -resize 8192x8192 albedo_8k.tif
magick normal.tif  -resize 8192x8192 normal_8k.tif
```

Downsample depth, albedo and normal with the same target size so they stay
aligned. The Z range is preserved automatically — the addon reads it from the
depth values themselves, not from pixel dimensions.

For physical size, **the safe option is W/H mode**: enter the real-world
width and height in cm manually, exactly as you would for the original scan.
If you prefer DPI mode, the DPI value must be rescaled to match the new pixel
count:

```
DPI_downsampled = DPI_original × (new_px / old_px)
```

Example: original 25 000 px at 600 DPI downsampled to 8 192 px →
DPI_downsampled = 600 × (8192 / 25000) ≈ 197.

## Repository layout

```
.
├── scripts/
│   ├── blender/
│   │   ├── pss_importer_addon.py   ← main addon (install this)
│   │   └── pss_importer_v1.2.py   ← legacy script reference
│   └── convert/
│       ├── convert_alpha.bat
│       └── convert_depth.bat
└── docs/
    └── PSS_Importer_Addon_QuickStart.pdf
```

The `data/` directory (local scan datasets) is excluded from version control via `.gitignore`.

## License

MIT
