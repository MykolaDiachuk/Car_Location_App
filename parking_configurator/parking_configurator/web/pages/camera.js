function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

export function initCameraPage(ctx) {
  const { api, store, toast } = ctx;

  const vendorSelect = document.getElementById("cam-vendor");
  const ipInput = document.getElementById("cam-ip");
  const portInput = document.getElementById("cam-port");
  const userInput = document.getElementById("cam-user");
  const passInput = document.getElementById("cam-pass");
  const channelInput = document.getElementById("cam-channel");
  const customInput = document.getElementById("cam-custom");
  const channelWrap = document.getElementById("cam-channel-wrap");
  const customWrap = document.getElementById("cam-custom-wrap");
  const builderPreview = document.getElementById("cam-builder-preview");
  const builderFs = document.getElementById("cam-builder");
  const manualFs = document.getElementById("cam-manual");
  const manualUrl = document.getElementById("cam-url");
  const testBtn = document.getElementById("cam-test-btn");
  const captureBtn = document.getElementById("cam-capture-btn");
  const statusEl = document.getElementById("cam-status");
  const frameArea = document.getElementById("cam-frame-area");
  const frameInfo = document.getElementById("cam-frame-info");
  const modeRadios = document.querySelectorAll('input[name="cam-mode"]');

  let vendors = [];
  let currentVendor = null;
  let currentBuiltUrl = "";
  let currentFrameBlobUrl = null;

  function setStatus(text, kind = "") {
    statusEl.textContent = text;
    statusEl.className = `status ${kind}`;
  }

  function populateVendors() {
    vendors = store.state.vendors || [];
    vendorSelect.innerHTML = "";
    vendors.forEach((v) => {
      const opt = document.createElement("option");
      opt.value = v.id;
      opt.textContent = v.label;
      vendorSelect.appendChild(opt);
    });
    if (vendors.length > 0) {
      vendorSelect.value = vendors[0].id;
      applyVendor(vendors[0]);
    }
  }

  function applyVendor(v) {
    currentVendor = v;
    portInput.value = v.default_port;
    if (v.channel_label) {
      channelWrap.classList.remove("hidden");
      channelWrap.querySelector("input").previousSibling.textContent = v.channel_label + " ";
    } else {
      channelWrap.classList.add("hidden");
    }
    customWrap.classList.toggle("hidden", !v.supports_custom_path);
    updateBuilderPreview();
  }

  function getMode() {
    return [...modeRadios].find((r) => r.checked).value;
  }

  function setMode(mode) {
    builderFs.classList.toggle("hidden", mode !== "builder");
    manualFs.classList.toggle("hidden", mode !== "manual");
  }

  async function fetchBuiltUrl() {
    if (!currentVendor) return "";
    const params = {
      vendor: currentVendor.id,
      ip: ipInput.value.trim() || "0.0.0.0",
      port: Number(portInput.value) || 554,
      user: userInput.value,
      password: passInput.value,
      channel: Number(channelInput.value) || 1,
      custom_path: customInput.value,
    };
    try {
      const { url } = await api.buildCameraUrl(params);
      return url;
    } catch (e) {
      return "";
    }
  }

  const updateBuilderPreview = debounce(async () => {
    const url = await fetchBuiltUrl();
    currentBuiltUrl = url;
    const masked = url.replace(
      /(rtsp:\/\/[^:]+:)([^@]*)(@)/,
      (_m, a, b, c) => a + (b ? "•".repeat(Math.min(b.length, 8)) : "") + c,
    );
    builderPreview.textContent = masked || "rtsp://…";
  }, 120);

  function getCurrentUrl() {
    return getMode() === "manual"
      ? manualUrl.value.trim()
      : currentBuiltUrl;
  }

  async function displayFrame(blob) {
    if (currentFrameBlobUrl) URL.revokeObjectURL(currentFrameBlobUrl);
    currentFrameBlobUrl = URL.createObjectURL(blob);
    frameArea.innerHTML = "";
    const img = document.createElement("img");
    img.src = currentFrameBlobUrl;
    img.alt = "Captured frame";
    img.addEventListener("load", () => {
      frameInfo.textContent = `${img.naturalWidth}×${img.naturalHeight}`;
    });
    frameArea.appendChild(img);
  }

  async function loadExistingFrame() {
    try {
      const blob = await api.fetchCameraFrame();
      if (blob) await displayFrame(blob);
    } catch (e) {
      // ignore
    }
  }

  modeRadios.forEach((r) => r.addEventListener("change", () => setMode(getMode())));
  vendorSelect.addEventListener("change", () => {
    const v = vendors.find((x) => x.id === vendorSelect.value);
    if (v) applyVendor(v);
  });
  [ipInput, portInput, userInput, passInput, channelInput, customInput].forEach((el) =>
    el.addEventListener("input", updateBuilderPreview),
  );

  testBtn.addEventListener("click", async () => {
    const url = getCurrentUrl();
    if (!url) { setStatus("Введіть URL або заповніть конструктор", "err"); return; }
    testBtn.disabled = true;
    captureBtn.disabled = true;
    setStatus("Перевіряю підключення...");
    try {
      const r = await api.testCameraUrl(url);
      if (r.ok) setStatus(`OK — підключено за ${r.elapsed_ms} мс`, "ok");
      else setStatus(r.error || "Не вдалося підключитися", "err");
    } catch (e) {
      setStatus(`Помилка: ${e.message}`, "err");
    } finally {
      testBtn.disabled = false;
      captureBtn.disabled = false;
    }
  });

  captureBtn.addEventListener("click", async () => {
    const url = getCurrentUrl();
    if (!url) { setStatus("Введіть URL або заповніть конструктор", "err"); return; }
    testBtn.disabled = true;
    captureBtn.disabled = true;
    setStatus("Захоплюю кадр...");
    try {
      const wasFrame = store.state.has_frame;
      const blob = await api.captureCameraFrame(url);
      await displayFrame(blob);
      await store.refresh();
      setStatus("Кадр захоплено. Перейдіть до кроку 2.", "ok");
      if (wasFrame) {
        toast("Новий кадр — BEV/маски/карту скинуто", "warn");
      } else {
        toast("Кадр готовий. Тепер крок 2 (BEV)", "ok");
      }
    } catch (e) {
      setStatus(`Не вдалося: ${e.message}`, "err");
    } finally {
      testBtn.disabled = false;
      captureBtn.disabled = false;
    }
  });

  populateVendors();
  setMode(getMode());
  updateBuilderPreview();

  return {
    show: async () => {
      const url = store.state.camera_url;
      if (url) manualUrl.value = url;
      if (store.state.has_frame && !currentFrameBlobUrl) {
        await loadExistingFrame();
      }
    },
    onReset: () => {
      if (currentFrameBlobUrl) URL.revokeObjectURL(currentFrameBlobUrl);
      currentFrameBlobUrl = null;
      frameArea.innerHTML = '<p class="placeholder">Тут зʼявиться кадр після успішного захоплення</p>';
      frameInfo.textContent = "";
      manualUrl.value = "";
      setStatus("");
    },
  };
}
