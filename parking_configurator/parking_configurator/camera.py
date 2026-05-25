from __future__ import annotations

import urllib.parse
from typing import Optional

import cv2
import numpy as np


VENDOR_TEMPLATES = {
    "hikvision": {
        "label": "Hikvision",
        "default_port": 554,
        "path": "/Streaming/Channels/{channel}01",
        "channel_label": "Channel (1, 2, ...)",
    },
    "dahua": {
        "label": "Dahua / Imou / Lorex",
        "default_port": 554,
        "path": "/cam/realmonitor?channel={channel}&subtype=0",
        "channel_label": "Channel (1, 2, ...)",
    },
    "axis": {
        "label": "Axis",
        "default_port": 554,
        "path": "/axis-media/media.amp",
        "channel_label": None,
    },
    "reolink": {
        "label": "Reolink",
        "default_port": 554,
        "path": "/h264Preview_0{channel}_main",
        "channel_label": "Channel (1, 2, ...)",
    },
    "tplink": {
        "label": "TP-Link Tapo",
        "default_port": 554,
        "path": "/stream{channel}",
        "channel_label": "Stream (1=main, 2=sub)",
    },
    "onvif": {
        "label": "Generic ONVIF",
        "default_port": 554,
        "path": "/onvif{channel}",
        "channel_label": "Channel (1, 2, ...)",
    },
    "custom": {
        "label": "Custom path",
        "default_port": 554,
        "path": "/{custom_path}",
        "channel_label": None,
    },
}


def vendor_options() -> list[dict]:
    return [
        {
            "id": key,
            "label": data["label"],
            "default_port": data["default_port"],
            "channel_label": data["channel_label"],
            "supports_custom_path": key == "custom",
        }
        for key, data in VENDOR_TEMPLATES.items()
    ]


def build_url(
    vendor: str,
    ip: str,
    port: int | str,
    user: str,
    password: str,
    channel: int | str = 1,
    custom_path: str = "",
) -> str:
    if vendor not in VENDOR_TEMPLATES:
        raise ValueError(f"Unknown vendor: {vendor}")
    user_e = urllib.parse.quote(user or "", safe="")
    pwd_e = urllib.parse.quote(password or "", safe="")
    path_template = VENDOR_TEMPLATES[vendor]["path"]
    custom_path = (custom_path or "").lstrip("/")
    path = path_template.format(channel=channel, custom_path=custom_path)
    auth = f"{user_e}:{pwd_e}@" if user or password else ""
    return f"rtsp://{auth}{ip}:{port}{path}"


def _open_capture(url: str) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    return cap


def test_connection(url: str) -> tuple[bool, Optional[str]]:
    cap = _open_capture(url)
    try:
        if not cap.isOpened():
            return False, "Cannot open stream (check URL, credentials, firewall)"
        ok, frame = cap.read()
        if not ok or frame is None:
            return False, "Connected but no frames received (try transport=tcp or different channel)"
        return True, None
    finally:
        cap.release()


def capture_frame(url: str, warmup: int = 5) -> np.ndarray:
    cap = _open_capture(url)
    try:
        if not cap.isOpened():
            raise RuntimeError("Cannot open stream (check URL, credentials, firewall)")
        last: Optional[np.ndarray] = None
        for _ in range(max(1, warmup)):
            ok, frame = cap.read()
            if ok and frame is not None:
                last = frame
        if last is None:
            raise RuntimeError("Connected but no frames received")
        return last.copy()
    finally:
        cap.release()


def encode_png(frame: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError("Failed to encode PNG")
    return bytes(buf.tobytes())
