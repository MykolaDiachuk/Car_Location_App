"""System resource monitoring with in-memory history ring buffer."""

import platform
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import psutil


HISTORY_MAX_POINTS = 300  # ~5 min at 1s interval


@dataclass
class SystemMetrics:
    timestamp: float
    cpu_percent: float
    cpu_per_core: list[float]
    ram_used_mb: float
    ram_total_mb: float
    ram_percent: float
    swap_used_mb: float
    swap_total_mb: float
    disk_used_gb: float
    disk_total_gb: float
    disk_percent: float
    net_sent_mb: float
    net_recv_mb: float
    cpu_temp: float | None
    uptime_seconds: float
    load_avg: list[float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": self.cpu_percent,
            "cpu_per_core": self.cpu_per_core,
            "ram_used_mb": round(self.ram_used_mb, 1),
            "ram_total_mb": round(self.ram_total_mb, 1),
            "ram_percent": self.ram_percent,
            "swap_used_mb": round(self.swap_used_mb, 1),
            "swap_total_mb": round(self.swap_total_mb, 1),
            "disk_used_gb": round(self.disk_used_gb, 2),
            "disk_total_gb": round(self.disk_total_gb, 2),
            "disk_percent": self.disk_percent,
            "net_sent_mb": round(self.net_sent_mb, 2),
            "net_recv_mb": round(self.net_recv_mb, 2),
            "cpu_temp": self.cpu_temp,
            "uptime_seconds": round(self.uptime_seconds, 0),
            "load_avg": self.load_avg,
        }


@dataclass
class StatsCollector:
    history: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=HISTORY_MAX_POINTS))
    _boot_time: float = field(default_factory=psutil.boot_time)
    _prev_net: Any = field(default=None)
    _prev_net_time: float = field(default=0.0)

    def collect(self) -> dict[str, Any]:
        now = time.time()

        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        net_sent_mb = net.bytes_sent / (1024 * 1024)
        net_recv_mb = net.bytes_recv / (1024 * 1024)

        cpu_temp = self._get_cpu_temp()
        uptime = now - self._boot_time

        try:
            load_avg = list(psutil.getloadavg())
        except (AttributeError, OSError):
            load_avg = [cpu_percent / 100.0, 0.0, 0.0]

        metrics = SystemMetrics(
            timestamp=now,
            cpu_percent=cpu_percent,
            cpu_per_core=cpu_per_core,
            ram_used_mb=mem.used / (1024 * 1024),
            ram_total_mb=mem.total / (1024 * 1024),
            ram_percent=mem.percent,
            swap_used_mb=swap.used / (1024 * 1024),
            swap_total_mb=swap.total / (1024 * 1024),
            disk_used_gb=disk.used / (1024 ** 3),
            disk_total_gb=disk.total / (1024 ** 3),
            disk_percent=disk.percent,
            net_sent_mb=net_sent_mb,
            net_recv_mb=net_recv_mb,
            cpu_temp=cpu_temp,
            uptime_seconds=uptime,
            load_avg=load_avg,
        )

        data = metrics.to_dict()
        self.history.append(data)
        return data

    def get_server_info(self) -> dict[str, Any]:
        return {
            "hostname": platform.node(),
            "os": f"{platform.system()} {platform.release()}",
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "cpu_count_logical": psutil.cpu_count(logical=True),
            "cpu_count_physical": psutil.cpu_count(logical=False),
            "ram_total_mb": round(psutil.virtual_memory().total / (1024 * 1024), 1),
        }

    def get_history(self) -> list[dict[str, Any]]:
        return list(self.history)

    @staticmethod
    def _get_cpu_temp() -> float | None:
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None
            for key in ("cpu_thermal", "coretemp", "cpu-thermal", "k10temp"):
                if key in temps and temps[key]:
                    return temps[key][0].current
            first = next(iter(temps.values()), None)
            if first:
                return first[0].current
        except (AttributeError, OSError):
            pass
        return None


collector = StatsCollector()
