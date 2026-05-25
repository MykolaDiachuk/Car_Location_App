from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional


class Session:
    def __init__(self, cache_dir: Path, fresh: bool = False) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.state_path = self.cache_dir / "session.json"
        self.frame_path = self.cache_dir / "frame.png"
        self.parking_mask_path = self.cache_dir / "parking_mask.png"
        self.orientation_mask_path = self.cache_dir / "orientation_mask.png"

        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self._resumed = False

        if fresh:
            self._clean_cache()

        self.state = self._default_state()
        if not fresh and self.state_path.exists():
            self._load_from_disk()

    @staticmethod
    def _default_state() -> dict:
        return {
            "camera_url": None,
            "has_frame": False,
            "bev": None,
            "has_parking_mask": False,
            "has_orientation_mask": False,
            "map_shapes": [],
        }

    @property
    def resumed(self) -> bool:
        return self._resumed

    def public_state(self) -> dict:
        with self._lock:
            return {
                "camera_url": self.state["camera_url"],
                "has_frame": self.state["has_frame"],
                "bev": self.state["bev"],
                "has_parking_mask": self.state["has_parking_mask"],
                "has_orientation_mask": self.state["has_orientation_mask"],
                "map_shapes_count": len(self.state["map_shapes"]),
                "resumed": self._resumed,
            }

    def set_camera_url(self, url: str) -> None:
        with self._lock:
            self.state["camera_url"] = url
            self._schedule_save()

    def set_frame(self, png_bytes: bytes) -> None:
        with self._lock:
            self.frame_path.write_bytes(png_bytes)
            self.state["has_frame"] = True
            self._invalidate_below("frame")
            self._schedule_save()

    def get_frame(self) -> Optional[bytes]:
        with self._lock:
            if self.frame_path.exists():
                return self.frame_path.read_bytes()
            return None

    def set_bev(self, src_points: list, width: int, height: int) -> None:
        with self._lock:
            self.state["bev"] = {
                "src_points": src_points,
                "width": int(width),
                "height": int(height),
            }
            self._invalidate_below("bev")
            self._schedule_save()

    def get_bev(self) -> Optional[dict]:
        with self._lock:
            return self.state["bev"]

    def set_mask(self, kind: str, png_bytes: bytes) -> None:
        path = self._mask_path(kind)
        with self._lock:
            path.write_bytes(png_bytes)
            self.state[f"has_{kind}_mask"] = True
            self._schedule_save()

    def get_mask(self, kind: str) -> Optional[bytes]:
        path = self._mask_path(kind)
        with self._lock:
            if path.exists():
                return path.read_bytes()
            return None

    def clear_mask(self, kind: str) -> None:
        path = self._mask_path(kind)
        with self._lock:
            if path.exists():
                path.unlink()
            self.state[f"has_{kind}_mask"] = False
            self._schedule_save()

    def set_map(self, shapes: list) -> None:
        with self._lock:
            self.state["map_shapes"] = list(shapes)
            self._schedule_save()

    def get_map_shapes(self) -> list:
        with self._lock:
            return list(self.state["map_shapes"])

    def get_camera_url(self) -> Optional[str]:
        with self._lock:
            return self.state["camera_url"]

    def reset(self) -> None:
        with self._lock:
            self._clean_cache()
            self.state = self._default_state()
            self._resumed = False
            self._schedule_save()

    def invalidate(self, step: str) -> None:
        with self._lock:
            self._invalidate_below(step)
            self._schedule_save()

    def flush(self) -> None:
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            self._save_now()

    def _mask_path(self, kind: str) -> Path:
        if kind == "parking":
            return self.parking_mask_path
        if kind == "orientation":
            return self.orientation_mask_path
        raise ValueError(f"unknown mask kind: {kind}")

    def _invalidate_below(self, step: str) -> None:
        if step == "frame":
            self.state["bev"] = None
            self._drop_masks_and_map()
        elif step == "bev":
            self._drop_masks_and_map()

    def _drop_masks_and_map(self) -> None:
        self.state["has_parking_mask"] = False
        self.state["has_orientation_mask"] = False
        self.state["map_shapes"] = []
        for p in (self.parking_mask_path, self.orientation_mask_path):
            if p.exists():
                p.unlink()

    def _clean_cache(self) -> None:
        for p in (
            self.frame_path,
            self.parking_mask_path,
            self.orientation_mask_path,
            self.state_path,
        ):
            if p.exists():
                p.unlink()

    def _schedule_save(self) -> None:
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.5, self._save_now)
        self._save_timer.daemon = True
        self._save_timer.start()

    def _save_now(self) -> None:
        with self._lock:
            tmp = self.state_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)

    def _load_from_disk(self) -> None:
        try:
            loaded = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        merged = self._default_state()
        for key in merged:
            if key in loaded:
                merged[key] = loaded[key]
        if merged["has_frame"] and not self.frame_path.exists():
            merged["has_frame"] = False
            merged["bev"] = None
            merged["has_parking_mask"] = False
            merged["has_orientation_mask"] = False
            merged["map_shapes"] = []
        if merged["has_parking_mask"] and not self.parking_mask_path.exists():
            merged["has_parking_mask"] = False
        if merged["has_orientation_mask"] and not self.orientation_mask_path.exists():
            merged["has_orientation_mask"] = False
        self.state = merged
        self._resumed = any(
            [
                self.state["camera_url"],
                self.state["has_frame"],
                self.state["bev"],
                self.state["has_parking_mask"],
                self.state["has_orientation_mask"],
                self.state["map_shapes"],
            ]
        )
