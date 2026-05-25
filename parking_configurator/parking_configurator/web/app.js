import * as api from "/static/lib/api.js";
import { initCameraPage } from "/static/pages/camera.js";
import { initBevPage } from "/static/pages/bev.js";
import { initMaskPage } from "/static/pages/mask.js";
import { initMapPage } from "/static/pages/map.js";
import { initExportPage } from "/static/pages/export.js";

const STEP_PAGES = [
  "camera",
  "bev",
  "mask-parking",
  "mask-orientation",
  "map",
  "export",
];

const Store = {
  state: null,
  listeners: new Set(),
  subscribe(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  },
  set(state) {
    this.state = state;
    this.listeners.forEach((fn) => {
      try { fn(state); } catch (e) { console.error(e); }
    });
  },
  async refresh() {
    const s = await api.fetchState();
    this.set(s);
    return s;
  },
};

function toast(message, kind = "info", ttlMs = 3500) {
  const container = document.getElementById("toast-container");
  const node = document.createElement("div");
  node.className = `toast ${kind}`;
  node.textContent = message;
  container.appendChild(node);
  setTimeout(() => node.remove(), ttlMs);
}

function isStepEnabled(step, state) {
  if (!state) return false;
  switch (step) {
    case "camera": return true;
    case "bev": return !!state.has_frame;
    case "mask-parking": return !!state.bev;
    case "mask-orientation": return !!state.bev;
    case "map": return !!state.bev;
    case "export": return true;
    default: return false;
  }
}

function isStepDone(step, state) {
  if (!state) return false;
  switch (step) {
    case "camera": return !!state.has_frame;
    case "bev": return !!state.bev;
    case "mask-parking": return !!state.has_parking_mask;
    case "mask-orientation": return !!state.has_orientation_mask;
    case "map": return (state.map_shapes_count || 0) > 0;
    case "export": return false;
    default: return false;
  }
}

const Sidebar = {
  current: null,
  init() {
    document.querySelectorAll(".step").forEach((btn) => {
      btn.addEventListener("click", () => {
        const page = btn.dataset.page;
        const step = btn.dataset.step;
        if (!isStepEnabled(step, Store.state)) {
          toast("Спочатку завершіть попередній крок", "warn");
          return;
        }
        showPage(page);
      });
    });
  },
  render(state) {
    document.querySelectorAll(".step").forEach((btn) => {
      const step = btn.dataset.step;
      const enabled = isStepEnabled(step, state);
      const done = isStepDone(step, state);
      btn.disabled = !enabled;
      btn.classList.toggle("done", done);
      btn.classList.toggle("active", btn.dataset.page === this.current);
    });
    document.getElementById("resume-banner").classList.toggle(
      "hidden", !state.resumed,
    );
  },
  setActive(page) {
    this.current = page;
    this.render(Store.state);
  },
};

const Pages = {};
function showPage(name) {
  document.querySelectorAll(".page").forEach((el) => {
    const matches = el.id === `page-${name}`;
    el.classList.toggle("hidden", !matches);
  });
  Sidebar.setActive(name);
  const page = Pages[name];
  if (page && typeof page.show === "function") page.show();
  history.replaceState({}, "", `#${name}`);
}

async function initApp() {
  Sidebar.init();

  document.getElementById("reset-btn").addEventListener("click", async () => {
    if (!confirm("Скинути всю сесію? Усі введені дані буде видалено.")) return;
    try {
      await api.resetSession();
      await Store.refresh();
      Object.values(Pages).forEach((p) => p.onReset && p.onReset());
      showPage("camera");
      toast("Сесію скинуто", "ok");
    } catch (e) {
      toast(`Помилка: ${e.message}`, "err");
    }
  });

  document.getElementById("start-fresh-btn").addEventListener("click", async () => {
    if (!confirm("Очистити збережену сесію і почати з нуля?")) return;
    try {
      await api.resetSession();
      await Store.refresh();
      Object.values(Pages).forEach((p) => p.onReset && p.onReset());
      showPage("camera");
      toast("Старт з чистого аркуша", "ok");
    } catch (e) {
      toast(`Помилка: ${e.message}`, "err");
    }
  });

  await Store.refresh();

  const ctx = { api, store: Store, toast };
  Pages.camera = initCameraPage(ctx);
  Pages.bev = initBevPage(ctx);
  Pages["mask-parking"] = initMaskPage(ctx, "parking");
  Pages["mask-orientation"] = initMaskPage(ctx, "orientation");
  Pages.map = initMapPage(ctx);
  Pages.export = initExportPage(ctx);

  Store.subscribe((s) => Sidebar.render(s));
  Sidebar.render(Store.state);

  const hashPage = window.location.hash.slice(1);
  const initial = STEP_PAGES.includes(hashPage) && isStepEnabled(hashPage, Store.state)
    ? hashPage
    : "camera";
  showPage(initial);
}

window.addEventListener(
  "wheel",
  (ev) => {
    if (ev.ctrlKey) ev.preventDefault();
  },
  { passive: false },
);
window.addEventListener("keydown", (ev) => {
  if (ev.ctrlKey && (ev.key === "+" || ev.key === "=" || ev.key === "-" || ev.key === "0")) {
    ev.preventDefault();
  }
});

initApp().catch((e) => {
  console.error(e);
  toast(`Помилка ініціалізації: ${e.message}`, "err", 8000);
});
