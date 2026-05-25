export function initExportPage(ctx) {
  const { api, store, toast } = ctx;

  const checklist = document.getElementById("export-checklist");
  const exportBtn = document.getElementById("export-btn");
  const exportStatus = document.getElementById("export-status");

  function renderChecklist() {
    const s = store.state;
    const items = [
      {
        key: "camera",
        label: "Камера (CAMERA_URL)",
        ok: !!s.camera_url,
        required: true,
        hint: s.camera_url || "Не вказано",
      },
      {
        key: "bev",
        label: "BEV калібрування (SRC_POINTS + BEV_WIDTH/HEIGHT)",
        ok: !!s.bev,
        required: true,
        hint: s.bev ? `${s.bev.width}×${s.bev.height}, точок: ${s.bev.src_points.length}` : "Не виконано",
      },
      {
        key: "parking",
        label: "Маска парковки (assets/parking_mask.png)",
        ok: !!s.has_parking_mask,
        required: false,
        hint: s.has_parking_mask ? "Збережено" : "Опціонально — без маски бекенд буде використовувати дефолт",
      },
      {
        key: "orientation",
        label: "Маска орієнтації (assets/orientation_zones.png)",
        ok: !!s.has_orientation_mask,
        required: false,
        hint: s.has_orientation_mask ? "Збережено" : "Опціонально",
      },
      {
        key: "map",
        label: "Карта парковки (assets/parking_map.svg)",
        ok: (s.map_shapes_count || 0) > 0,
        required: false,
        hint: (s.map_shapes_count || 0) > 0
          ? `${s.map_shapes_count} полігон(ів)`
          : "Опціонально — для візуалізації у фронтенді",
      },
    ];

    checklist.innerHTML = "";
    items.forEach((it) => {
      const row = document.createElement("div");
      const klass = it.ok ? "ok" : it.required ? "miss" : "opt";
      row.className = `export-row ${klass}`;
      const mark = it.ok ? "✓" : it.required ? "✗" : "—";
      row.innerHTML = `
        <span class="mark">${mark}</span>
        <span class="export-row-label"><b>${it.label}</b> · <span class="muted small">${it.hint}</span></span>
      `;
      checklist.appendChild(row);
    });

    const requiredMissing = items.filter((it) => it.required && !it.ok);
    exportBtn.disabled = requiredMissing.length > 0;
    if (requiredMissing.length > 0) {
      exportStatus.textContent = `Бракує обовʼязкових кроків: ${requiredMissing.map((i) => i.label).join(", ")}`;
      exportStatus.className = "status inline err";
    } else {
      exportStatus.textContent = "Готово до експорту";
      exportStatus.className = "status inline ok";
    }
  }

  exportBtn.addEventListener("click", async () => {
    exportBtn.disabled = true;
    exportStatus.textContent = "Готую ZIP...";
    exportStatus.className = "status inline";
    try {
      const blob = await api.exportZip();
      const a = document.createElement("a");
      const url = URL.createObjectURL(blob);
      a.href = url;
      a.download = "parking_config.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 500);
      exportStatus.textContent = "ZIP завантажено";
      exportStatus.className = "status inline ok";
      toast("Експорт готовий", "ok");
    } catch (e) {
      exportStatus.textContent = `Помилка: ${e.message}`;
      exportStatus.className = "status inline err";
    } finally {
      exportBtn.disabled = false;
    }
  });

  store.subscribe(() => {
    const page = document.getElementById("page-export");
    if (page && !page.classList.contains("hidden")) renderChecklist();
  });

  return {
    show: () => renderChecklist(),
    onReset: () => { exportStatus.textContent = ""; renderChecklist(); },
  };
}
