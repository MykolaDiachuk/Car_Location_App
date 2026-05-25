# 🚗 Parking Analysis System

**Intelligent parking analysis using YOLOv11 and computer vision**

Automatically detects occupied and free parking spots on unstructured parking lots (without markings) using camera feed.

---

## 🎯 Features

- **Unstructured parking** — works with chaotic parking without lane markings
- **Perspective correction** — Bird's Eye View transformation from angled camera
- **Custom parking masks** — supports complex shapes (flowerbeds, exits, irregular boundaries)
- **Orientation zones** — parallel and perpendicular parking spots
- **Realtime monitoring** — RTSP camera support

### Technologies
- **YOLOv11** (Ultralytics) — vehicle detection
- **OpenCV** — video processing, perspective transformation
- **NumPy** — computations
- **Matplotlib** — visualization

---

## 📁 Project Structure

```
Car_Location_Project/
├── config.py                    # Configuration (transform points, car dimensions)
├── main.py                      # Batch analysis entry point
├── realtime_camera_fixed.py     # Realtime RTSP monitoring
├── requirements.txt
├── README.md
│
├── parking/                     # Core package
│   ├── __init__.py
│   ├── detector.py              # YOLOv11 vehicle detector
│   ├── transformer.py           # Perspective transformation (BEV)
│   ├── analyzer.py              # Free spot analysis
│   └── pipeline.py              # Unified processing pipeline
│
├── assets/                      # Masks and calibration files
│   ├── parking_mask.png         # Allowed parking zones (white=allowed)
│   └── orientation_zones.png    # Orientation zones (green=parallel, blue=perpendicular)
│
├── input/                       # Input video/images
│   └── ...
│
├── output/                      # Analysis results (gitignored)
│   └── ...
│
├── tools/                       # Calibration utilities (standalone)
│   ├── find_bev_points.py       # Interactive point selection
│   ├── generate_bev.py          # Generate BEV from image
│   ├── edit_parking_mask.py     # Parking mask editor
│   ├── edit_orientation_zones.py # Orientation zones editor
│   └── ...
│
└── yolo11n.pt                   # YOLO model (gitignored)
```

---

## 🚀 Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Prepare input

```bash
# Place your video in input/
cp your_video.mp4 input/parking_video.mp4
```

### 3. Configure transform points

```bash
python tools/find_bev_points.py input/frame.png
```
- Click **4 points** (corners of parking area): TL → TR → BR → BL
- Press **SPACE** for preview
- Press **S** to save
- Copy result to `config.py`

### 4. Create parking mask

```bash
python tools/edit_parking_mask.py
```
- **LMB** — draw white (allowed zone)
- **RMB** — draw black (forbidden zone)
- Save as `assets/parking_mask.png`

### 5. Run analysis

```bash
# Batch analysis
python main.py

# With specific file
python main.py input/my_video.mp4
python main.py input/frame.png

# Realtime from RTSP camera
python realtime_camera_fixed.py
```

---

## 📊 Output

After running, you'll get:

1. **Matplotlib window** with 4 panels:
   - Original frame
   - YOLO detections
   - Bird's Eye View
   - Analysis (red=occupied, green=free)

2. **Files in `output/`**:
   - `01_original.jpg`
   - `02_detections.jpg`
   - `03_bev.jpg`
   - `04_analysis.jpg`
   - `report_[timestamp].png`

---

## ⚙️ Configuration

Edit `config.py`:

```python
class ParkingConfig:
    # Transform points (corners on original image)
    SRC_POINTS = np.float32([
        [-172, -86],    # Top-Left
        [2062, 414],    # Top-Right
        [3040, 1079],   # Bottom-Right
        [746, 1258]     # Bottom-Left
    ])

    # BEV dimensions
    BEV_WIDTH = 1200
    BEV_HEIGHT = 800

    # Car size in BEV (pixels)
    CAR_WIDTH = 150
    CAR_HEIGHT = 80

    # YOLO settings
    MODEL_PATH = "yolo11n.pt"
    CONF_THRESHOLD = 0.3
```

---

## 🛠️ Tools

| Tool | Purpose |
|------|---------|
| `tools/find_bev_points.py` | Interactive BEV point selection |
| `tools/generate_bev.py` | Generate BEV preview from image |
| `tools/edit_parking_mask.py` | Edit parking allowed zones |
| `tools/edit_orientation_zones.py` | Edit orientation zones |

---

## 🐛 Troubleshooting

**Problem: Green squares overlap**
→ Increase `CAR_WIDTH`/`CAR_HEIGHT` in config.py

**Problem: BEV is distorted**
→ Re-select `SRC_POINTS` using `tools/find_bev_points.py`

**Problem: YOLO misses some cars**
→ Lower `CONF_THRESHOLD` (e.g., 0.3 → 0.2)

**Problem: Algorithm marks flowerbeds as free**
→ Edit `assets/parking_mask.png` — paint forbidden areas black

---

## 📄 License

MIT License. Free for educational and commercial use.

---

**Technologies:** Python 3.12+, YOLOv11, OpenCV, NumPy, Matplotlib
