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
