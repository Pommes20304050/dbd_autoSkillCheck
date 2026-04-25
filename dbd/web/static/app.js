/* ══════════════════════════════════════════════════════════════════
   DBD Auto Skill Check — Flask UI
   ══════════════════════════════════════════════════════════════════ */

(() => {
  // ─── Toast system ──────────────────────────────────────────────
  const toastEl = document.getElementById("toasts");
  const TOAST_ICON = { success: "✓", warn: "⚠", error: "✕", info: "ℹ" };
  const TOAST_DEFAULT_TTL = 5000;

  function toast(type, title, msg, ttl = TOAST_DEFAULT_TTL) {
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.innerHTML = `
      <div class="toast-icon">${TOAST_ICON[type] || "•"}</div>
      <div class="toast-body">
        <div class="toast-title"></div>
        <div class="toast-msg"></div>
      </div>
      <button class="toast-close" aria-label="close">✕</button>
    `;
    t.querySelector(".toast-title").textContent = title || "";
    t.querySelector(".toast-msg").textContent = msg || "";
    const close = () => {
      t.classList.add("toast-out");
      setTimeout(() => t.remove(), 250);
    };
    t.querySelector(".toast-close").addEventListener("click", close);
    if (ttl > 0) setTimeout(close, ttl);
    toastEl.appendChild(t);
  }

  // ─── API helpers ───────────────────────────────────────────────
  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    let body = null;
    try { body = await res.json(); } catch { /* empty */ }
    if (!res.ok) {
      const err = (body && body.error) || res.statusText || `HTTP ${res.status}`;
      throw new Error(err);
    }
    return body;
  }

  // ─── State ─────────────────────────────────────────────────────
  const cfg = {
    model: null,
    device: "CPU",
    monitoring_lib: "mss",
    monitor_id: null,
    hit_ante: 20,
    nb_cpu_threads: 4,
  };
  let initData = null;
  let prevAdvisorSeverity = null;
  let lastHitTimestamp = null;
  let livePollTimer = null;
  let statusPollTimer = null;

  // ─── Element refs ──────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  // ─── Segmented control builder ─────────────────────────────────
  function renderSeg(container, items, currentValue, onPick, getDisabled = () => false) {
    container.innerHTML = "";
    items.forEach(item => {
      const btn = document.createElement("button");
      btn.className = "seg-btn";
      btn.textContent = item.label;
      btn.dataset.value = item.value;
      if (item.value === currentValue) btn.classList.add("active");
      if (getDisabled(item)) {
        btn.classList.add("seg-btn-disabled");
        btn.disabled = true;
        if (item.disabledReason) btn.title = item.disabledReason;
      }
      btn.addEventListener("click", () => {
        if (btn.disabled) return;
        container.querySelectorAll(".seg-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        onPick(item.value, item);
      });
      container.appendChild(btn);
    });
  }

  // ─── Init flow ─────────────────────────────────────────────────
  async function init() {
    try {
      initData = await api("/api/init");
    } catch (e) {
      toast("error", "Failed to initialize", e.message, 0);
      return;
    }

    if (!initData.models || initData.models.length === 0) {
      toast("error", "No model files found",
        `Drop ONNX or TensorRT files into ${initData.models_folder}/`, 0);
    }

    // ── Models ──
    const modelSel = $("cfg-model");
    modelSel.innerHTML = "";
    initData.models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      modelSel.appendChild(opt);
    });
    if (initData.default_model) {
      modelSel.value = initData.default_model;
      cfg.model = initData.default_model;
    }
    modelSel.addEventListener("change", () => { cfg.model = modelSel.value; });

    // ── Device (CPU/GPU) ──
    const sys = initData.system || {};
    const gpu = sys.gpu || {};
    const cpu = sys.cpu || { cores: 4 };
    const gpuAvailable = sys.gpu_available;
    const gpuSummary = gpu.gpu_summary || "GPU not available";

    cfg.device = initData.default_device || "CPU";

    renderSeg($("cfg-device"),
      [
        { label: "CPU", value: "CPU" },
        { label: "GPU", value: "GPU", disabledReason: sys.gpu_unavailable_reason },
      ],
      cfg.device,
      (v) => { cfg.device = v; updateDeviceSummary(); },
      (item) => item.value === "GPU" && !gpuAvailable
    );

    function updateDeviceSummary() {
      const sumEl = $("cfg-device-summary");
      const hintEl = $("cfg-device-hint");
      if (cfg.device === "GPU") {
        sumEl.textContent = gpuSummary;
        hintEl.textContent = gpuAvailable
          ? "Will run inference on your GPU."
          : (sys.gpu_unavailable_reason || "GPU runtime missing.");
      } else {
        const t = cfg.nb_cpu_threads;
        sumEl.textContent = `${t} of ${cpu.cores} threads`;
        hintEl.textContent = `Detected ${cpu.cores}-core CPU. Higher = more throughput, more load.`;
      }
    }

    // ── Monitoring lib ──
    cfg.monitoring_lib = initData.default_monitoring_lib;
    renderSeg($("cfg-monlib"),
      initData.monitoring_libs.map(v => ({ label: v, value: v })),
      cfg.monitoring_lib,
      async (v) => { cfg.monitoring_lib = v; await refreshMonitors(); }
    );

    // ── Monitors ──
    populateMonitors(initData.monitors);

    // ── CPU presets (adaptive!) ──
    const cpuPresets = initData.cpu_presets;
    cfg.nb_cpu_threads = initData.default_cpu_threads;
    renderSeg($("cfg-cpu"),
      cpuPresets.map(p => ({ label: `${p.label} · ${p.threads}t`, value: p.threads })),
      cfg.nb_cpu_threads,
      (v) => { cfg.nb_cpu_threads = v; updateCpuSummary(); updateDeviceSummary(); }
    );

    function updateCpuSummary() {
      $("cfg-cpu-summary").textContent = `${cfg.nb_cpu_threads} / ${cpu.cores} threads`;
      $("cfg-cpu-hint").textContent = `Detected ${cpu.cores}-core CPU. Higher = more throughput, more load.`;
    }
    updateCpuSummary();
    updateDeviceSummary();

    // ── Hit ante slider ──
    cfg.hit_ante = initData.default_hit_ante;
    const ante = $("cfg-ante");
    ante.value = cfg.hit_ante;
    $("cfg-ante-val").textContent = `${cfg.hit_ante} ms`;
    ante.addEventListener("input", () => {
      cfg.hit_ante = parseInt(ante.value, 10);
      $("cfg-ante-val").textContent = `${cfg.hit_ante} ms`;
    });

    // ── Hardware summary in the gpu mini-stat ──
    $("ms-gamefps").textContent = "—";

    // ── Buttons ──
    $("btn-run").addEventListener("click", onRun);
    $("btn-stop").addEventListener("click", onStop);
    $("advisor-close").addEventListener("click", () => {
      $("advisor").classList.add("advisor-hidden");
    });

    // ── Initial preview for the default monitor ──
    refreshPreview();

    // ── Boot toast ──
    const cpuLine = `${cpu.cores} cores · ${cpu.platform || "unknown OS"}`;
    const gpuLine = gpuAvailable ? `GPU: ${gpuSummary}` : "GPU: not available";
    toast("info", "System detected", `${cpuLine}\n${gpuLine}`);

    // ── Start status polling ──
    pollStatus();
    statusPollTimer = setInterval(pollStatus, 500);
  }

  function populateMonitors(monitors) {
    const sel = $("cfg-monitor");
    sel.innerHTML = "";
    monitors.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m.id;
      opt.textContent = m.label;
      sel.appendChild(opt);
    });
    if (monitors.length > 0) {
      cfg.monitor_id = monitors[0].id;
      sel.value = monitors[0].id;
    }
    sel.addEventListener("change", () => {
      cfg.monitor_id = parseInt(sel.value, 10);
      refreshPreview();
    });
  }

  async function refreshMonitors() {
    try {
      const r = await api(`/api/monitors?monitoring_lib=${encodeURIComponent(cfg.monitoring_lib)}`);
      populateMonitors(r.monitors);
      refreshPreview();
    } catch (e) {
      toast("error", "Failed to list monitors", e.message);
    }
  }

  async function refreshPreview() {
    if (cfg.monitor_id == null) return;
    const url = `/api/preview?monitoring_lib=${encodeURIComponent(cfg.monitoring_lib)}&monitor_id=${cfg.monitor_id}&t=${Date.now()}`;
    const img = $("live-feed");
    img.src = url;
    img.onload = () => {
      $("feed-empty").style.display = "none";
      img.parentElement.classList.add("has-frame");
    };
    img.onerror = () => {
      img.removeAttribute("src");
      $("feed-empty").style.display = "flex";
      $("feed-empty").textContent = "Preview failed — pick another monitor or library";
      img.parentElement.classList.remove("has-frame");
    };
  }

  // ─── Run / Stop ────────────────────────────────────────────────
  async function onRun() {
    $("btn-run").disabled = true;
    try {
      const body = JSON.stringify({
        model: cfg.model,
        device: cfg.device,
        monitoring_lib: cfg.monitoring_lib,
        monitor_id: cfg.monitor_id,
        hit_ante: cfg.hit_ante,
        nb_cpu_threads: cfg.nb_cpu_threads,
      });
      await api("/api/start", { method: "POST", body });
      $("btn-stop").disabled = false;
      // We don't toast success here — the status poll will toast when it sees "running"
      startLivePoll();
    } catch (e) {
      toast("error", "Could not start", e.message, 0);
      $("btn-run").disabled = false;
    }
  }

  async function onStop() {
    $("btn-stop").disabled = true;
    try {
      await api("/api/stop", { method: "POST" });
      stopLivePoll();
    } catch (e) {
      toast("error", "Could not stop", e.message);
    }
    $("btn-run").disabled = false;
  }

  // ─── Live frame poll ───────────────────────────────────────────
  function startLivePoll() {
    if (livePollTimer) return;
    livePollTimer = setInterval(() => {
      const img = $("live-feed");
      img.src = `/api/live-frame?t=${Date.now()}`;
    }, 250);
  }
  function stopLivePoll() {
    if (livePollTimer) clearInterval(livePollTimer);
    livePollTimer = null;
  }

  // ─── Status polling ────────────────────────────────────────────
  let lastStatus = "idle";
  let lastError = null;

  async function pollStatus() {
    let snap;
    try { snap = await api("/api/status"); }
    catch (e) { return; }

    // Top-level state changes
    if (snap.status !== lastStatus) {
      onStatusTransition(lastStatus, snap.status, snap);
      lastStatus = snap.status;
    }
    if (snap.error && snap.error !== lastError) {
      toast("error", "Inference error", snap.error, 0);
      lastError = snap.error;
    } else if (!snap.error) {
      lastError = null;
    }

    // Sidebar + status chip
    $("sb-status").textContent = snap.status;
    $("sb-status").style.color = colorForStatus(snap.status);
    $("sb-provider").textContent = snap.provider || "—";
    $("sb-fps").textContent = (snap.tool_fps || 0).toFixed(1);
    $("sb-hits").textContent = snap.hit_count || 0;
    $("sb-hpm").textContent  = snap.hits_per_minute || 0;

    $("status-pill").textContent = snap.status.toUpperCase();
    $("status-fps").textContent = snap.status === "running" ? `${(snap.tool_fps || 0).toFixed(1)}` : "—";
    const dot = $("status-dot");
    dot.classList.remove("running", "error", "starting");
    if (snap.status === "running") dot.classList.add("running");
    else if (snap.status === "error") dot.classList.add("error");
    else if (snap.status === "starting" || snap.status === "stopping") dot.classList.add("starting");

    // Mini stats
    const fpsAvgOrNow = snap.tool_fps_avg ?? snap.tool_fps ?? 0;
    $("ms-fps").textContent = fpsAvgOrNow.toFixed(1);
    $("ms-hits").textContent = snap.hit_count || 0;
    $("ms-hpm").textContent = snap.hits_per_minute || 0;
    setBar("ms-fps-bar", Math.min(100, fpsAvgOrNow / 1.2)); // ~120fps full bar
    setBar("ms-hits-bar", Math.min(100, (snap.hit_count || 0) * 5));
    setBar("ms-hpm-bar", Math.min(100, (snap.hits_per_minute || 0) * 10));

    $("feed-fps-chip").textContent = `${(snap.tool_fps || 0).toFixed(1)} FPS`;

    // FPS advisor
    renderAdvisor(snap.fps_advice);

    // Last hit
    if (snap.last_hit_at && snap.last_hit_at !== lastHitTimestamp) {
      lastHitTimestamp = snap.last_hit_at;
      const img = $("lasthit-img");
      img.src = `/api/last-hit-frame?t=${Date.now()}`;
      img.onload = () => {
        $("lasthit-empty").style.display = "none";
        img.parentElement.classList.add("has-frame");
      };
      $("lasthit-sub").textContent = snap.last_hit_desc || "—";
      renderDonut(snap.last_hit_probs, snap.last_hit_desc);
    }
  }

  function colorForStatus(s) {
    if (s === "running") return "var(--green)";
    if (s === "error")   return "var(--red)";
    if (s === "starting" || s === "stopping") return "var(--amber)";
    return "var(--orange)";
  }

  function onStatusTransition(from, to, snap) {
    if (to === "running") {
      const cores = (initData?.system?.cpu?.cores) || "?";
      const provider = snap.provider || "?";
      const detail = (cfg.device === "GPU")
        ? `Provider: ${provider}`
        : `${cfg.nb_cpu_threads}/${cores} CPU threads · ${provider}`;
      toast("success", "Inference running", detail);
    }
    if (to === "idle" && from === "running") {
      toast("info", "Stopped", "Inference loop ended cleanly.");
    }
    if (to === "error") {
      // error toast is fired by the lastError check above, with the actual message
    }
  }

  // ─── Advisor banner + transition toasts ────────────────────────
  function renderAdvisor(advice) {
    const banner = $("advisor");
    if (!advice) return;

    // Update Game FPS Cap mini stat
    if (typeof advice.game_fps_cap === "number" && advice.game_fps_cap > 0) {
      $("ms-gamefps").textContent = advice.game_fps_cap.toFixed(0);
      setBar("ms-gamefps-bar", Math.min(100, advice.game_fps_cap / 2.4));
    } else if (advice.game_fps_cap === 0) {
      $("ms-gamefps").textContent = "∞";
    } else {
      $("ms-gamefps").textContent = "—";
    }

    const sev = advice.severity;

    // Reset classes
    banner.classList.remove("severity-info", "severity-warn", "severity-danger", "advisor-hidden");

    if (sev === "ok") {
      banner.classList.add("advisor-hidden");
    } else {
      banner.classList.add(`severity-${sev}`);
      $("advisor-icon").textContent = sev === "danger" ? "⚠" : (sev === "warn" ? "⚠" : "ℹ");
      $("advisor-msg").textContent = advice.message || "";
      $("advisor-rec").textContent = advice.recommendation || "";
      if (!advice.recommendation) $("advisor-rec").style.display = "none";
      else $("advisor-rec").style.display = "";
    }

    // Toast on severity transition (ok→warn, warn→danger, etc.)
    if (sev !== prevAdvisorSeverity) {
      if (sev === "danger") {
        toast("error", "FPS critically low", advice.message + (advice.recommendation ? " " + advice.recommendation : ""), 12000);
      } else if (sev === "warn" && prevAdvisorSeverity !== "danger") {
        toast("warn", "FPS warning", advice.message + (advice.recommendation ? " " + advice.recommendation : ""), 10000);
      }
      prevAdvisorSeverity = sev;
    }
  }

  function setBar(id, pct) {
    const el = $(id);
    if (el) el.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  }

  // ─── Donut ─────────────────────────────────────────────────────
  function renderDonut(probs, desc) {
    if (!probs) return;
    const entries = Object.entries(probs).sort((a, b) => b[1] - a[1]);
    const top = entries[0];
    if (!top) return;

    const pct = top[1];
    const seg = $("donut-seg");
    seg.style.strokeDashoffset = 314 * (1 - pct);
    seg.classList.remove("seg-high", "seg-med", "seg-low");
    if (pct >= 0.85) seg.classList.add("seg-high");
    else if (pct >= 0.6) seg.classList.add("seg-med");
    else seg.classList.add("seg-low");

    $("donut-val").textContent = `${(pct * 100).toFixed(0)}%`;
    $("donut-sub").textContent = desc || top[0];

    const legend = $("donut-legend");
    legend.innerHTML = "";
    entries.slice(0, 5).forEach(([name, p]) => {
      const row = document.createElement("div");
      row.className = "legend-row";
      const dotColor = p >= 0.85 ? "var(--orange)" : (p >= 0.6 ? "var(--amber)" : "var(--text-muted)");
      row.innerHTML = `
        <span class="legend-dot" style="background:${dotColor}"></span>
        <span class="legend-name"></span>
        <span class="legend-pct">${(p * 100).toFixed(1)}%</span>
      `;
      row.querySelector(".legend-name").textContent = name;
      legend.appendChild(row);
    });
  }

  // ─── Boot ──────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", init);
})();
