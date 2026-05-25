from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import camera as camera_mod
from . import transform as transform_mod
from .export import build_zip, export_summary
from .session import Session


_PACKAGE_DIR = Path(__file__).resolve().parent
_WEB_DIR = _PACKAGE_DIR / "web"


def _cache_dir() -> Path:
    override = os.environ.get("PARKING_CONFIGURATOR_CACHE")
    if override:
        return Path(override)
    return Path.cwd() / ".parking_configurator_cache"


_fresh = os.environ.get("PARKING_CONFIGURATOR_FRESH") == "1"
session = Session(_cache_dir(), fresh=_fresh)


app = FastAPI(title="Parking Configurator", docs_url=None, redoc_url=None)


class CameraUrlRequest(BaseModel):
    url: str = Field(..., min_length=1)


class CameraBuildRequest(BaseModel):
    vendor: str
    ip: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)
    user: str = ""
    password: str = ""
    channel: int = 1
    custom_path: str = ""


class BevRequest(BaseModel):
    src_points: list[list[float]]
    width: int = Field(..., ge=400, le=4000)
    height: int = Field(..., ge=400, le=4000)


class MaskSaveRequest(BaseModel):
    type: str
    png_base64: str


class MapShape(BaseModel):
    id: str
    points: list[list[float]]


class MapSaveRequest(BaseModel):
    shapes: list[MapShape]


def _png_response(data: bytes) -> Response:
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/api/state")
def get_state() -> JSONResponse:
    payload = session.public_state()
    payload["vendors"] = camera_mod.vendor_options()
    payload["defaults"] = {"bev_width": 1200, "bev_height": 800}
    return JSONResponse(payload)


@app.post("/api/camera/build")
def build_camera_url(req: CameraBuildRequest) -> JSONResponse:
    try:
        url = camera_mod.build_url(
            vendor=req.vendor,
            ip=req.ip,
            port=req.port,
            user=req.user,
            password=req.password,
            channel=req.channel,
            custom_path=req.custom_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse({"url": url})


@app.post("/api/camera/test")
def camera_test(req: CameraUrlRequest) -> JSONResponse:
    start = time.monotonic()
    ok, err = camera_mod.test_connection(req.url)
    elapsed = round((time.monotonic() - start) * 1000)
    return JSONResponse({"ok": ok, "error": err, "elapsed_ms": elapsed})


@app.post("/api/camera/capture")
def camera_capture(req: CameraUrlRequest) -> Response:
    try:
        frame = camera_mod.capture_frame(req.url)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    png = camera_mod.encode_png(frame)
    session.set_camera_url(req.url)
    session.set_frame(png)
    return _png_response(png)


@app.get("/api/camera/frame")
def camera_frame() -> Response:
    data = session.get_frame()
    if data is None:
        raise HTTPException(status_code=404, detail="No frame captured yet")
    return _png_response(data)


def _decode_frame() -> np.ndarray:
    raw = session.get_frame()
    if raw is None:
        raise HTTPException(status_code=400, detail="No frame in session")
    arr = np.frombuffer(raw, dtype=np.uint8)
    frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status_code=500, detail="Cached frame is corrupt")
    return frame


@app.post("/api/bev/preview")
def bev_preview(req: BevRequest) -> Response:
    frame = _decode_frame()
    try:
        bev = transform_mod.bev_from_frame(
            frame, req.src_points, req.width, req.height
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except cv2.error as exc:
        raise HTTPException(status_code=400, detail=f"Invalid points: {exc}") from exc
    png = camera_mod.encode_png(bev)
    return _png_response(png)


def _normalize_points(points: list[list[float]]) -> list[list[float | int]]:
    out: list[list[float | int]] = []
    for p in points:
        row: list[float | int] = []
        for c in p:
            cf = float(c)
            row.append(int(cf) if cf.is_integer() else cf)
        out.append(row)
    return out


@app.post("/api/bev/save")
def bev_save(req: BevRequest) -> JSONResponse:
    _decode_frame()
    session.set_bev(_normalize_points(req.src_points), req.width, req.height)
    return JSONResponse({"ok": True})


def _check_mask_kind(kind: str) -> None:
    if kind not in ("parking", "orientation"):
        raise HTTPException(status_code=404, detail="Unknown mask kind")


@app.post("/api/mask/save")
def mask_save(req: MaskSaveRequest) -> JSONResponse:
    _check_mask_kind(req.type)
    if session.get_bev() is None:
        raise HTTPException(status_code=400, detail="BEV not calibrated yet")
    try:
        png = base64.b64decode(req.png_base64, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid base64: {exc}") from exc
    session.set_mask(req.type, png)
    return JSONResponse({"ok": True})


@app.post("/api/mask/clear/{kind}")
def mask_clear(kind: str) -> JSONResponse:
    _check_mask_kind(kind)
    session.clear_mask(kind)
    return JSONResponse({"ok": True})


@app.get("/api/mask/{kind}")
def mask_get(kind: str) -> Response:
    _check_mask_kind(kind)
    data = session.get_mask(kind)
    if data is None:
        raise HTTPException(status_code=404, detail=f"No {kind} mask saved")
    return _png_response(data)


@app.post("/api/map/save")
def map_save(req: MapSaveRequest) -> JSONResponse:
    if session.get_bev() is None:
        raise HTTPException(status_code=400, detail="BEV not calibrated yet")
    shapes = [{"id": s.id, "points": s.points} for s in req.shapes]
    session.set_map(shapes)
    return JSONResponse({"ok": True})


@app.get("/api/map")
def map_get() -> JSONResponse:
    bev = session.get_bev()
    return JSONResponse(
        {
            "shapes": session.get_map_shapes(),
            "width": bev["width"] if bev else 1200,
            "height": bev["height"] if bev else 800,
        }
    )


@app.get("/api/export")
def export() -> Response:
    data = build_zip(session)
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=parking_config.zip",
        },
    )


@app.get("/api/export/summary")
def export_summary_endpoint() -> JSONResponse:
    return JSONResponse(export_summary(session))


@app.post("/api/reset")
def reset() -> JSONResponse:
    session.reset()
    return JSONResponse({"ok": True})


@app.post("/api/invalidate/{step}")
def invalidate(step: str) -> JSONResponse:
    if step not in ("frame", "bev"):
        raise HTTPException(status_code=400, detail="step must be frame or bev")
    session.invalidate(step)
    return JSONResponse({"ok": True})


app.mount("/static", StaticFiles(directory=str(_WEB_DIR)), name="static")
