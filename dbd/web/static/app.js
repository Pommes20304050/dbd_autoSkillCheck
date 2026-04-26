/* ══════════════════════════════════════════════════════════════════
   DBD Auto Skill Check — Flask UI
   ══════════════════════════════════════════════════════════════════ */

(() => {
  // ─── i18n dictionary (en, de, fr, es, ru) ─────────────────────
  const I18N = {
    en: {
      "topbar.title": "Auto Skill Check",
      "topbar.sub": "AI-powered great-skill-check detection & auto-press",
      "topbar.gpuNa": "GPU N/A",
      "sidebar.system": "System",
      "sidebar.menu": "Menu",
      "sidebar.status": "Status",
      "sidebar.provider": "Provider",
      "sidebar.avgFps": "Avg FPS",
      "sidebar.hits": "Hits",
      "sidebar.run": "▶ RUN",
      "sidebar.stop": "■ STOP",
      "sidebar.copy": "MANUTEAA / DBD_ASC<br />FLASK UI · v1",
      "nav.open": "Open",
      "nav.perf": "Performance Monitor",
      "nav.info": "Info",
      "nav.settings": "Settings",
      "status.idle": "IDLE",
      "status.running": "RUNNING",
      "status.starting": "STARTING",
      "status.stopping": "STOPPING",
      "status.error": "ERROR",
      "page.open.title": "Auto Skill Check",
      "page.open.sub": "AI-powered great-skill-check detection & auto-press",
      "page.perf.title": "Performance Monitor",
      "page.perf.sub": "Live CPU & GPU telemetry",
      "page.info.title": "Environment Info",
      "page.info.sub": "Python, CUDA, drivers, packages",
      "page.settings.title": "Settings",
      "page.settings.sub": "Language and tool preferences",
      "card.settings.title": "Inference Settings",
      "card.settings.sub": "Configure once, then RUN. Changes apply on next start.",
      "settings.aiModel": "AI Model",
      "settings.aiModelHint": "Drop ONNX or TensorRT files into <code>models/</code>.",
      "settings.device": "Device",
      "settings.deviceHintGpuMissing": "GPU runtime missing.",
      "settings.deviceHintGpuOk": "Will run inference on your GPU.",
      "settings.deviceHintGpuRequires": "GPU requires PyTorch + CUDA / DirectML / TensorRT.",
      "settings.screenLib": "Screen Lib",
      "settings.screenLibHint": "bettercam is faster but Windows-only and optional.",
      "settings.monitor": "Monitor",
      "settings.monitorHint": "Center 224×224 of the chosen monitor is sampled.",
      "settings.ante": "Ante-frontier hit delay",
      "settings.cpu": "CPU workload",
      "settings.cpuHint": "Adapts to your CPU. Higher = more throughput, more load.",
      "cpu.threads": "threads",
      "cpu.threadsPinned": "threads · pinned to P-Cores",
      "cpu.detected": "Detected",
      "cpu.hybridDetected": "Hybrid Intel CPU detected",
      "cpu.locked": "locking inference to P-Cores only.",
      "cpu.locked2": "Mixing E-Cores in would slow each forward pass — slow E-threads finish later than P-threads on every batch.",
      "cpu.typicalGain": "Typical gain: <strong>~2× faster</strong> than using all {all} threads.",
      "cpu.tip": "Tip",
      "cpu.tipBody": "on hybrid Intel CPUs (12th gen+), the {p} P-Cores preset is typically ~2× faster than the {all}-thread \"Max\" preset — even using all cores is slower because the E-cores hold back the P-cores during each inference step.",
      "cpu.nonHybrid": "Higher = more throughput, more load. (No hybrid CPU detected — P-Cores preset only matters for Intel 12th gen+.)",
      "cpu.deviceCpuSummary": "{n} of {total} threads",
      "cpu.deviceCpuHint": "Detected {total}-core CPU. Higher = more throughput, more load.",
      "modal.title": "Are you sure? Slower than P-Cores",
      "modal.line1": "On your <strong>{cpu}</strong> ({pe}), running",
      "modal.threadsUnpinned": "unpinned threads",
      "modal.slower": "is typically <strong>~2× slower</strong> than the",
      "modal.preset": "(P-Cores) preset",
      "modal.explain": "E-Cores run inference much slower per thread than P-Cores. When mixed in the same forward pass, the slow E-threads hold back the P-threads and drag total throughput down.",
      "modal.benchref": "Reference benchmark on i9-14900K (ONNX): 8 P-Cores → 980 fps · all 32 threads → 525 fps.",
      "modal.useAnyway": "Use anyway",
      "modal.keep": "Keep",
      "toast.hybridTitle": "Hybrid CPU optimization",
      "toast.hybridBody": "Your CPU has fast P-Cores and slower E-Cores. The {p}t ★ preset locks inference to P-Cores only — typically ~2× faster than running on all {all} threads.",
      "toast.systemDetected": "System detected",
      "toast.cpuLineHybrid": "{summary} (hybrid Intel — P-Cores preset enabled)",
      "toast.cpuLine": "{summary} · {os}",
      "toast.gpuLineOk": "GPU: {summary}",
      "toast.gpuLineNa": "GPU: not available",
      "toast.running": "Inference running",
      "toast.runningGpu": "Provider: {provider}",
      "toast.runningCpu": "{used}/{total} CPU threads · {provider}",
      "toast.stopped": "Stopped",
      "toast.stoppedBody": "Inference loop ended cleanly.",
      "toast.errInfer": "Inference error",
      "toast.errStart": "Could not start",
      "toast.errStop": "Could not stop",
      "toast.errInit": "Failed to initialize",
      "toast.errModels": "No model files found",
      "toast.errModelsBody": "Drop ONNX or TensorRT files into {folder}/",
      "toast.errMonitors": "Failed to list monitors",
      "toast.fpsDanger": "FPS critically low",
      "toast.fpsWarn": "FPS warning",
      "toast.fpsCapSet": "Game cap set to {cap} fps",
      "toast.fpsCapSetBody": "Restart Dead by Daylight to apply (the game only reads this file at startup).",
      "toast.fpsCapErr": "Could not write FPS cap",
      "mini.avgFps": "Average FPS",
      "mini.hitsTotal": "Hits Total",
      "mini.gameCap": "Game FPS Cap",
      "card.feed.title": "Live Monitor Feed",
      "card.feed.sub": "Center 224×224 the model sees",
      "card.feed.empty": "Press RUN or pick a monitor to preview",
      "card.feed.emptyAlt": "Preview failed — pick another monitor or library",
      "card.feed.fps": "{fps} FPS",
      "card.donut.title": "Last Skill Check",
      "card.donut.subEmpty": "No hit yet",
      "card.donut.label": "CONFIDENCE",
      "card.lasthit.title": "Last Hit Frame",
      "card.lasthit.sub": "Captured frame the model fired SPACE on",
      "card.lasthit.empty": "No hit yet",
      "ante.hint": "Pre-press delay for ante-frontier (early-edge) hits. Lower = react sooner; higher = wait deeper into the great-zone.",
      "ante.guide": "0–10 ms: aggressive (lower is risky if the model fires on noise) · 15–25 ms: balanced (default) · 30–50 ms: safer.",
      "perf.gpu": "GPU",
      "perf.gpuNa": "GPU · not available",
      "perf.cpu": "CPU",
      "perf.cpuNa": "CPU · not available",
      "perf.psutilMissing": "psutil not installed.",
      "perf.nvidiaSmiMissing": "No NVIDIA GPU detected (nvidia-smi missing).",
      "perf.utilization": "Utilization",
      "perf.totalUtil": "Total Utilization",
      "perf.power": "Power",
      "perf.temperature": "Temperature",
      "perf.vram": "VRAM",
      "perf.fan": "Fan",
      "perf.memUtil": "Memory Util",
      "perf.perCore": "Per-core Utilization",
      "perf.lhmHint": 'CPU temp/power are unavailable. Install &amp; run <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> with WMI provider enabled to see them here.',
      "perf.chartTitle": "Performance Monitor",
      "perf.chartSub": "Real-time GPU + detection metrics",
      "perf.chartFps": "FPS",
      "perf.chartGpu": "GPU %",
      "perf.chartVram": "VRAM",
      "perf.chartTemp": "Temp",
      "settings.lang": "Language",
      "settings.langDesc": "Interface language — saved in your browser.",
      "settings.fpsCap": "Game FPS Cap",
      "settings.fpsCapHint": "Writes <code>FrameRateLimit</code> in DBD's <code>GameUserSettings.ini</code>. <strong>Restart Dead by Daylight</strong> for it to take effect — the game only reads this file at startup.",
      "settings.fpsCapNoIni": "INI not found. Launch DBD once so it generates GameUserSettings.ini, then reload.",
      "settings.fpsCapStatusSet": "Set to {cap} fps · restart DBD to apply.",
      "settings.fpsCapStatusRecommended": "Recommended: {rec} fps (★) — your tool can't keep up with {cur}.",
      "settings.fpsCapStatusCurrent": "Currently capped at {cur} fps.",
      "info.envTitle": "Environment",
      "info.envSub": "Python · OS · drivers · CUDA toolkit",
      "info.pkgTitle": "Python Packages",
      "info.pkgSub": "Installed dependencies for the inference pipeline",
      "info.aboutTitle": "About",
      "info.aboutSub": "Open-source · Flask UI for Manuteaa/dbd_autoSkillCheck",
      "info.python": "Python",
      "info.executable": "Interpreter path",
      "info.os": "Operating System",
      "info.gpu": "GPU",
      "info.driver": "NVIDIA Driver",
      "info.cudaRuntime": "CUDA (driver)",
      "info.cudaToolkit": "CUDA Toolkit (nvcc)",
      "info.cudaHome": "CUDA_PATH",
      "info.torch": "PyTorch",
      "info.torchCuda": "PyTorch CUDA",
      "info.notInstalled": "not installed",
      "info.notDetected": "not detected",
      "info.installed": "installed",
      "info.missing": "missing",
      "info.required": "required",
      "info.optional": "optional",
      "info.loading": "Loading…",
      "about.p1": 'Drop-in Flask UI for <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">Manuteaa/dbd_autoSkillCheck</a>. The default Gradio app (<code>app.py</code>) is untouched — run <code>python app_flask.py</code> for this UI instead.',
      "about.p2": "Hardware-adaptive CPU presets, hybrid-CPU P-Cores pinning, GPU performance monitor (NVIDIA only via <code>nvidia-smi</code>), and a live FPS advisor that compares the rolling tool FPS to the game's <code>FrameRateLimit</code>.",
      "about.p3": 'CPU temperature / power readings require <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> to be installed and running (its WMI namespace is queried).',
      "footer.note": 'Open-source · drop-in alternative to <code>app.py</code> (Gradio). Source: <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">github.com/Manuteaa/dbd_autoSkillCheck</a>',
    },

    de: {
      "topbar.title": "Auto Skill Check",
      "topbar.sub": "KI-gestützte Great-Skill-Check-Erkennung & automatischer Tastendruck",
      "topbar.gpuNa": "GPU n.v.",
      "sidebar.system": "System",
      "sidebar.menu": "Menü",
      "sidebar.status": "Status",
      "sidebar.provider": "Provider",
      "sidebar.avgFps": "Ø-FPS",
      "sidebar.hits": "Treffer",
      "sidebar.run": "▶ START",
      "sidebar.stop": "■ STOP",
      "sidebar.copy": "MANUTEAA / DBD_ASC<br />FLASK UI · v1",
      "nav.open": "Hauptseite",
      "nav.perf": "Performance-Monitor",
      "nav.info": "Info",
      "nav.settings": "Einstellungen",
      "status.idle": "BEREIT",
      "status.running": "LÄUFT",
      "status.starting": "STARTET",
      "status.stopping": "STOPPT",
      "status.error": "FEHLER",
      "page.open.title": "Auto Skill Check",
      "page.open.sub": "KI-gestützte Erkennung & automatischer Tastendruck",
      "page.perf.title": "Performance-Monitor",
      "page.perf.sub": "Live CPU- & GPU-Telemetrie",
      "page.info.title": "System-Info",
      "page.info.sub": "Python, CUDA, Treiber, Pakete",
      "page.settings.title": "Einstellungen",
      "page.settings.sub": "Sprache und Tool-Voreinstellungen",
      "card.settings.title": "Inferenz-Einstellungen",
      "card.settings.sub": "Einmal konfigurieren, dann START. Änderungen werden beim nächsten Start übernommen.",
      "settings.aiModel": "KI-Modell",
      "settings.aiModelHint": "Lege ONNX- oder TensorRT-Dateien in <code>models/</code> ab.",
      "settings.device": "Gerät",
      "settings.deviceHintGpuMissing": "GPU-Runtime fehlt.",
      "settings.deviceHintGpuOk": "Inferenz läuft auf deiner GPU.",
      "settings.deviceHintGpuRequires": "GPU benötigt PyTorch + CUDA / DirectML / TensorRT.",
      "settings.screenLib": "Bildschirm-Lib",
      "settings.screenLibHint": "bettercam ist schneller, aber nur unter Windows verfügbar (optional).",
      "settings.monitor": "Monitor",
      "settings.monitorHint": "Es wird das mittige 224×224-Feld des gewählten Monitors abgegriffen.",
      "settings.ante": "Ante-frontier-Verzögerung",
      "settings.cpu": "CPU-Last",
      "settings.cpuHint": "Passt sich deiner CPU an. Mehr = mehr Durchsatz, mehr Last.",
      "cpu.threads": "Threads",
      "cpu.threadsPinned": "Threads · auf P-Cores fixiert",
      "cpu.detected": "Erkannt",
      "cpu.hybridDetected": "Hybride Intel-CPU erkannt",
      "cpu.locked": "Inferenz wird ausschließlich auf P-Cores ausgeführt.",
      "cpu.locked2": "Mischbetrieb mit E-Cores würde jeden Forward-Pass verlangsamen — die E-Threads beenden ihre Arbeit pro Batch später als die P-Threads.",
      "cpu.typicalGain": "Typischer Vorteil: <strong>~2× schneller</strong> als mit allen {all} Threads.",
      "cpu.tip": "Tipp",
      "cpu.tipBody": "bei hybriden Intel-CPUs (ab 12. Gen.) ist das {p}-Preset typischerweise ~2× schneller als der {all}-Thread-Max-Modus — sogar alle Kerne zu nutzen ist langsamer, weil die E-Cores die P-Cores in jedem Inferenzschritt ausbremsen.",
      "cpu.nonHybrid": "Mehr = mehr Durchsatz, mehr Last. (Keine Hybrid-CPU erkannt — das P-Cores-Preset ist nur für Intel ab 12. Gen. relevant.)",
      "cpu.deviceCpuSummary": "{n} von {total} Threads",
      "cpu.deviceCpuHint": "Erkannt: {total}-Kern-CPU. Mehr = mehr Durchsatz, mehr Last.",
      "modal.title": "Wirklich? Langsamer als P-Cores",
      "modal.line1": "Auf deiner <strong>{cpu}</strong> ({pe}) sind",
      "modal.threadsUnpinned": "unfixierte Threads",
      "modal.slower": "typischerweise <strong>~2× langsamer</strong> als das",
      "modal.preset": "(P-Cores)-Preset",
      "modal.explain": "E-Cores sind pro Thread deutlich langsamer als P-Cores bei Inferenz. Im selben Forward-Pass halten sie die P-Threads auf und drücken den Gesamt-Durchsatz.",
      "modal.benchref": "Referenz-Benchmark auf i9-14900K (ONNX): 8 P-Cores → 980 fps · alle 32 Threads → 525 fps.",
      "modal.useAnyway": "Trotzdem nutzen",
      "modal.keep": "Behalten",
      "toast.hybridTitle": "Hybrid-CPU-Optimierung",
      "toast.hybridBody": "Deine CPU hat schnelle P-Cores und langsamere E-Cores. Das {p}t ★ Preset fixiert die Inferenz nur auf die P-Cores — typischerweise ~2× schneller als alle {all} Threads.",
      "toast.systemDetected": "System erkannt",
      "toast.cpuLineHybrid": "{summary} (hybride Intel-CPU — P-Cores-Preset aktiviert)",
      "toast.cpuLine": "{summary} · {os}",
      "toast.gpuLineOk": "GPU: {summary}",
      "toast.gpuLineNa": "GPU: nicht verfügbar",
      "toast.running": "Inferenz läuft",
      "toast.runningGpu": "Provider: {provider}",
      "toast.runningCpu": "{used}/{total} CPU-Threads · {provider}",
      "toast.stopped": "Gestoppt",
      "toast.stoppedBody": "Inferenz-Loop sauber beendet.",
      "toast.errInfer": "Inferenz-Fehler",
      "toast.errStart": "Start fehlgeschlagen",
      "toast.errStop": "Stopp fehlgeschlagen",
      "toast.errInit": "Initialisierung fehlgeschlagen",
      "toast.errModels": "Keine Modelldateien gefunden",
      "toast.errModelsBody": "Lege ONNX- oder TensorRT-Dateien in {folder}/ ab",
      "toast.errMonitors": "Monitor-Liste fehlgeschlagen",
      "toast.fpsDanger": "FPS kritisch niedrig",
      "toast.fpsWarn": "FPS-Warnung",
      "toast.fpsCapSet": "Spiel-Cap auf {cap} fps gesetzt",
      "toast.fpsCapSetBody": "Dead by Daylight neu starten, damit es übernommen wird (das Spiel liest die Datei nur beim Start).",
      "toast.fpsCapErr": "FPS-Cap konnte nicht geschrieben werden",
      "mini.avgFps": "Ø-FPS",
      "mini.hitsTotal": "Treffer gesamt",
      "mini.gameCap": "Spiel-FPS-Limit",
      "card.feed.title": "Live-Monitor-Feed",
      "card.feed.sub": "Mittiger 224×224-Ausschnitt, den das Modell sieht",
      "card.feed.empty": "START drücken oder Monitor wählen für Vorschau",
      "card.feed.emptyAlt": "Vorschau fehlgeschlagen — anderen Monitor oder Library wählen",
      "card.feed.fps": "{fps} FPS",
      "card.donut.title": "Letzter Skill-Check",
      "card.donut.subEmpty": "Noch kein Treffer",
      "card.donut.label": "KONFIDENZ",
      "card.lasthit.title": "Letzter-Treffer-Frame",
      "card.lasthit.sub": "Aufgenommener Frame, bei dem das Modell SPACE ausgelöst hat",
      "card.lasthit.empty": "Noch kein Treffer",
      "ante.hint": "Vorabverzögerung für ante-frontier-Treffer (frühe Kante). Niedriger = früher reagieren; höher = tiefer in die Great-Zone hineinwarten.",
      "ante.guide": "0–10 ms: aggressiv · 15–25 ms: ausgewogen (Standard) · 30–50 ms: sicherer.",
      "perf.gpu": "GPU",
      "perf.gpuNa": "GPU · nicht verfügbar",
      "perf.cpu": "CPU",
      "perf.cpuNa": "CPU · nicht verfügbar",
      "perf.psutilMissing": "psutil ist nicht installiert.",
      "perf.nvidiaSmiMissing": "Keine NVIDIA-GPU erkannt (nvidia-smi fehlt).",
      "perf.utilization": "Auslastung",
      "perf.totalUtil": "Gesamt-Auslastung",
      "perf.power": "Leistung",
      "perf.temperature": "Temperatur",
      "perf.vram": "VRAM",
      "perf.fan": "Lüfter",
      "perf.memUtil": "Speicher-Auslastung",
      "perf.perCore": "Pro-Kern-Auslastung",
      "perf.lhmHint": 'CPU-Temp/-Leistung sind nicht verfügbar. Installiere &amp; starte <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> mit aktiviertem WMI-Provider, um diese Werte hier zu sehen.',
      "perf.chartTitle": "Performance Monitor",
      "perf.chartSub": "Echtzeit-GPU- und Detection-Metriken",
      "perf.chartFps": "FPS",
      "perf.chartGpu": "GPU %",
      "perf.chartVram": "VRAM",
      "perf.chartTemp": "Temp",
      "settings.lang": "Sprache",
      "settings.langDesc": "Sprache der Benutzeroberfläche — wird im Browser gespeichert.",
      "settings.fpsCap": "Spiel-FPS-Limit",
      "settings.fpsCapHint": "Schreibt <code>FrameRateLimit</code> in die <code>GameUserSettings.ini</code> von DBD. <strong>Dead by Daylight muss neu gestartet werden</strong> — das Spiel liest die Datei nur beim Start.",
      "settings.fpsCapNoIni": "INI nicht gefunden. Starte DBD einmal, damit es GameUserSettings.ini erzeugt, dann neu laden.",
      "settings.fpsCapStatusSet": "Auf {cap} fps gesetzt · DBD neu starten zum Übernehmen.",
      "settings.fpsCapStatusRecommended": "Empfohlen: {rec} fps (★) — dein Tool kommt nicht auf {cur} mit.",
      "settings.fpsCapStatusCurrent": "Aktuell auf {cur} fps begrenzt.",
      "info.envTitle": "Umgebung",
      "info.envSub": "Python · OS · Treiber · CUDA-Toolkit",
      "info.pkgTitle": "Python-Pakete",
      "info.pkgSub": "Installierte Abhängigkeiten der Inferenz-Pipeline",
      "info.aboutTitle": "Über",
      "info.aboutSub": "Open Source · Flask-UI für Manuteaa/dbd_autoSkillCheck",
      "info.python": "Python",
      "info.executable": "Interpreter-Pfad",
      "info.os": "Betriebssystem",
      "info.gpu": "GPU",
      "info.driver": "NVIDIA-Treiber",
      "info.cudaRuntime": "CUDA (Treiber)",
      "info.cudaToolkit": "CUDA-Toolkit (nvcc)",
      "info.cudaHome": "CUDA_PATH",
      "info.torch": "PyTorch",
      "info.torchCuda": "PyTorch CUDA",
      "info.notInstalled": "nicht installiert",
      "info.notDetected": "nicht erkannt",
      "info.installed": "installiert",
      "info.missing": "fehlt",
      "info.required": "erforderlich",
      "info.optional": "optional",
      "info.loading": "Lädt…",
      "about.p1": 'Drop-in Flask-UI für <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">Manuteaa/dbd_autoSkillCheck</a>. Die Standard-Gradio-App (<code>app.py</code>) bleibt unangetastet — starte stattdessen <code>python app_flask.py</code> für diese UI.',
      "about.p2": "Hardware-adaptive CPU-Presets, P-Cores-Pinning für hybride CPUs, GPU-Performance-Monitor (nur NVIDIA via <code>nvidia-smi</code>) und ein Live-FPS-Advisor, der die mittlere Tool-FPS mit dem <code>FrameRateLimit</code> des Spiels vergleicht.",
      "about.p3": 'CPU-Temperatur/-Leistung benötigt <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a>, installiert und gestartet (der WMI-Namespace wird abgefragt).',
      "footer.note": 'Open Source · Drop-in-Alternative zu <code>app.py</code> (Gradio). Quellcode: <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">github.com/Manuteaa/dbd_autoSkillCheck</a>',
    },

    fr: {
      "topbar.title": "Auto Skill Check",
      "topbar.sub": "Détection IA des great-skill-checks & pression auto",
      "topbar.gpuNa": "GPU N/D",
      "sidebar.system": "Système",
      "sidebar.menu": "Menu",
      "sidebar.status": "Statut",
      "sidebar.provider": "Provider",
      "sidebar.avgFps": "FPS moy.",
      "sidebar.hits": "Hits",
      "sidebar.run": "▶ DÉMARRER",
      "sidebar.stop": "■ STOP",
      "sidebar.copy": "MANUTEAA / DBD_ASC<br />FLASK UI · v1",
      "nav.open": "Accueil",
      "nav.perf": "Moniteur de performance",
      "nav.info": "Infos",
      "nav.settings": "Paramètres",
      "status.idle": "INACTIF",
      "status.running": "EN COURS",
      "status.starting": "DÉMARRAGE",
      "status.stopping": "ARRÊT",
      "status.error": "ERREUR",
      "page.open.title": "Auto Skill Check",
      "page.open.sub": "Détection IA & pression automatique",
      "page.perf.title": "Moniteur de performance",
      "page.perf.sub": "Télémétrie CPU & GPU en direct",
      "page.info.title": "Informations système",
      "page.info.sub": "Python, CUDA, pilotes, paquets",
      "page.settings.title": "Paramètres",
      "page.settings.sub": "Langue et préférences de l'outil",
      "card.settings.title": "Paramètres d'inférence",
      "card.settings.sub": "Configurer une fois puis DÉMARRER. Modifications appliquées au prochain démarrage.",
      "settings.aiModel": "Modèle IA",
      "settings.aiModelHint": "Place les fichiers ONNX ou TensorRT dans <code>models/</code>.",
      "settings.device": "Périphérique",
      "settings.deviceHintGpuMissing": "Runtime GPU manquant.",
      "settings.deviceHintGpuOk": "L'inférence tourne sur ton GPU.",
      "settings.deviceHintGpuRequires": "GPU requiert PyTorch + CUDA / DirectML / TensorRT.",
      "settings.screenLib": "Lib. d'écran",
      "settings.screenLibHint": "bettercam est plus rapide mais Windows seulement (optionnel).",
      "settings.monitor": "Moniteur",
      "settings.monitorHint": "Le centre 224×224 du moniteur choisi est échantillonné.",
      "settings.ante": "Délai ante-frontier",
      "settings.cpu": "Charge CPU",
      "settings.cpuHint": "S'adapte à ton CPU. Plus = plus de débit, plus de charge.",
      "cpu.threads": "threads",
      "cpu.threadsPinned": "threads · épinglés sur P-Cores",
      "cpu.detected": "Détecté",
      "cpu.hybridDetected": "CPU Intel hybride détecté",
      "cpu.locked": "inférence verrouillée sur les P-Cores uniquement.",
      "cpu.locked2": "Mélanger les E-Cores ralentirait chaque forward pass — les E-threads finissent plus tard que les P-threads à chaque batch.",
      "cpu.typicalGain": "Gain typique : <strong>~2× plus rapide</strong> qu'avec les {all} threads.",
      "cpu.tip": "Astuce",
      "cpu.tipBody": "sur les CPU Intel hybrides (12e gen+), le préréglage {p} P-Cores est typiquement ~2× plus rapide que le mode {all}-threads — utiliser tous les cœurs est plus lent car les E-cores freinent les P-cores à chaque étape d'inférence.",
      "cpu.nonHybrid": "Plus = plus de débit, plus de charge. (Pas de CPU hybride détecté — préréglage P-Cores pertinent uniquement Intel 12e gen+.)",
      "cpu.deviceCpuSummary": "{n} sur {total} threads",
      "cpu.deviceCpuHint": "CPU détecté à {total} cœurs. Plus = plus de débit, plus de charge.",
      "modal.title": "Sûr ? Plus lent que les P-Cores",
      "modal.line1": "Sur ton <strong>{cpu}</strong> ({pe}), exécuter",
      "modal.threadsUnpinned": "threads non-épinglés",
      "modal.slower": "est typiquement <strong>~2× plus lent</strong> que le",
      "modal.preset": "préréglage (P-Cores)",
      "modal.explain": "Les E-Cores tournent l'inférence bien plus lentement par thread que les P-Cores. Mélangés dans le même forward pass, les E-threads freinent les P-threads et tirent le débit total vers le bas.",
      "modal.benchref": "Référence i9-14900K (ONNX) : 8 P-Cores → 980 fps · 32 threads → 525 fps.",
      "modal.useAnyway": "Utiliser quand même",
      "modal.keep": "Garder",
      "toast.hybridTitle": "Optimisation CPU hybride",
      "toast.hybridBody": "Ton CPU a des P-Cores rapides et des E-Cores lents. Le préréglage {p}t ★ verrouille l'inférence sur les P-Cores uniquement — typiquement ~2× plus rapide que sur les {all} threads.",
      "toast.systemDetected": "Système détecté",
      "toast.cpuLineHybrid": "{summary} (Intel hybride — préréglage P-Cores activé)",
      "toast.cpuLine": "{summary} · {os}",
      "toast.gpuLineOk": "GPU : {summary}",
      "toast.gpuLineNa": "GPU : non disponible",
      "toast.running": "Inférence en cours",
      "toast.runningGpu": "Provider : {provider}",
      "toast.runningCpu": "{used}/{total} threads CPU · {provider}",
      "toast.stopped": "Arrêté",
      "toast.stoppedBody": "Boucle d'inférence arrêtée proprement.",
      "toast.errInfer": "Erreur d'inférence",
      "toast.errStart": "Impossible de démarrer",
      "toast.errStop": "Impossible d'arrêter",
      "toast.errInit": "Échec de l'initialisation",
      "toast.errModels": "Aucun fichier de modèle",
      "toast.errModelsBody": "Place les fichiers ONNX ou TensorRT dans {folder}/",
      "toast.errMonitors": "Échec liste moniteurs",
      "toast.fpsDanger": "FPS critiquement bas",
      "toast.fpsWarn": "Avertissement FPS",
      "toast.fpsCapSet": "Cap du jeu réglé sur {cap} fps",
      "toast.fpsCapSetBody": "Redémarre Dead by Daylight pour appliquer (le jeu lit ce fichier seulement au démarrage).",
      "toast.fpsCapErr": "Impossible d'écrire le cap FPS",
      "mini.avgFps": "FPS moyens",
      "mini.hitsTotal": "Total Hits",
      "mini.gameCap": "Cap FPS du jeu",
      "card.feed.title": "Flux moniteur en direct",
      "card.feed.sub": "Centre 224×224 vu par le modèle",
      "card.feed.empty": "Appuie sur DÉMARRER ou choisis un moniteur",
      "card.feed.emptyAlt": "Aperçu échoué — choisis un autre moniteur ou lib",
      "card.feed.fps": "{fps} FPS",
      "card.donut.title": "Dernier Skill Check",
      "card.donut.subEmpty": "Aucun hit",
      "card.donut.label": "CONFIANCE",
      "card.lasthit.title": "Image du dernier hit",
      "card.lasthit.sub": "Image capturée où le modèle a appuyé sur ESPACE",
      "card.lasthit.empty": "Aucun hit",
      "ante.hint": "Délai pré-pression pour les hits ante-frontier (bord précoce). Plus bas = réagir plus tôt ; plus haut = attendre plus profondément dans la great-zone.",
      "ante.guide": "0–10 ms : agressif · 15–25 ms : équilibré (défaut) · 30–50 ms : plus sûr.",
      "perf.gpu": "GPU",
      "perf.gpuNa": "GPU · non disponible",
      "perf.cpu": "CPU",
      "perf.cpuNa": "CPU · non disponible",
      "perf.psutilMissing": "psutil n'est pas installé.",
      "perf.nvidiaSmiMissing": "Aucun GPU NVIDIA détecté (nvidia-smi manquant).",
      "perf.utilization": "Utilisation",
      "perf.totalUtil": "Utilisation totale",
      "perf.power": "Puissance",
      "perf.temperature": "Température",
      "perf.vram": "VRAM",
      "perf.fan": "Ventilateur",
      "perf.memUtil": "Util. mémoire",
      "perf.perCore": "Utilisation par cœur",
      "perf.lhmHint": 'Temp/Puissance CPU indisponibles. Installe &amp; lance <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> avec WMI activé pour les voir ici.',
      "perf.chartTitle": "Moniteur de performance",
      "perf.chartSub": "Métriques GPU + détection en temps réel",
      "perf.chartFps": "FPS",
      "perf.chartGpu": "GPU %",
      "perf.chartVram": "VRAM",
      "perf.chartTemp": "Temp",
      "settings.lang": "Langue",
      "settings.langDesc": "Langue de l'interface — sauvegardée dans ton navigateur.",
      "settings.fpsCap": "Cap FPS du jeu",
      "settings.fpsCapHint": "Écrit <code>FrameRateLimit</code> dans <code>GameUserSettings.ini</code> de DBD. <strong>Redémarre Dead by Daylight</strong> pour appliquer — le jeu lit ce fichier seulement au démarrage.",
      "settings.fpsCapNoIni": "INI introuvable. Lance DBD une fois pour qu'il génère GameUserSettings.ini, puis recharge.",
      "settings.fpsCapStatusSet": "Réglé sur {cap} fps · redémarre DBD pour appliquer.",
      "settings.fpsCapStatusRecommended": "Recommandé : {rec} fps (★) — l'outil ne suit pas {cur}.",
      "settings.fpsCapStatusCurrent": "Actuellement plafonné à {cur} fps.",
      "info.envTitle": "Environnement",
      "info.envSub": "Python · OS · pilotes · CUDA toolkit",
      "info.pkgTitle": "Paquets Python",
      "info.pkgSub": "Dépendances installées du pipeline d'inférence",
      "info.aboutTitle": "À propos",
      "info.aboutSub": "Open-source · UI Flask pour Manuteaa/dbd_autoSkillCheck",
      "info.python": "Python",
      "info.executable": "Chemin interpréteur",
      "info.os": "Système d'exploitation",
      "info.gpu": "GPU",
      "info.driver": "Pilote NVIDIA",
      "info.cudaRuntime": "CUDA (pilote)",
      "info.cudaToolkit": "CUDA Toolkit (nvcc)",
      "info.cudaHome": "CUDA_PATH",
      "info.torch": "PyTorch",
      "info.torchCuda": "PyTorch CUDA",
      "info.notInstalled": "non installé",
      "info.notDetected": "non détecté",
      "info.installed": "installé",
      "info.missing": "manquant",
      "info.required": "requis",
      "info.optional": "optionnel",
      "info.loading": "Chargement…",
      "about.p1": 'UI Flask drop-in pour <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">Manuteaa/dbd_autoSkillCheck</a>. L\'app Gradio par défaut (<code>app.py</code>) reste intacte — lance <code>python app_flask.py</code> pour cette UI.',
      "about.p2": "Préréglages CPU adaptatifs, épinglage P-Cores pour CPU hybrides, moniteur GPU (NVIDIA via <code>nvidia-smi</code>), et conseiller FPS en direct comparant la moyenne mobile de l'outil au <code>FrameRateLimit</code> du jeu.",
      "about.p3": 'Lectures température/puissance CPU nécessitent <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> installé et lancé (son namespace WMI est requêté).',
      "footer.note": 'Open-source · alternative drop-in à <code>app.py</code> (Gradio). Source : <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">github.com/Manuteaa/dbd_autoSkillCheck</a>',
    },

    es: {
      "topbar.title": "Auto Skill Check",
      "topbar.sub": "Detección IA de great-skill-checks y pulsación automática",
      "topbar.gpuNa": "GPU N/D",
      "sidebar.system": "Sistema",
      "sidebar.menu": "Menú",
      "sidebar.status": "Estado",
      "sidebar.provider": "Proveedor",
      "sidebar.avgFps": "FPS prom.",
      "sidebar.hits": "Aciertos",
      "sidebar.run": "▶ INICIAR",
      "sidebar.stop": "■ DETENER",
      "sidebar.copy": "MANUTEAA / DBD_ASC<br />FLASK UI · v1",
      "nav.open": "Inicio",
      "nav.perf": "Monitor de rendimiento",
      "nav.info": "Info",
      "nav.settings": "Ajustes",
      "status.idle": "INACTIVO",
      "status.running": "EN EJECUCIÓN",
      "status.starting": "INICIANDO",
      "status.stopping": "DETENIENDO",
      "status.error": "ERROR",
      "page.open.title": "Auto Skill Check",
      "page.open.sub": "Detección IA y pulsación automática",
      "page.perf.title": "Monitor de rendimiento",
      "page.perf.sub": "Telemetría en vivo CPU y GPU",
      "page.info.title": "Información del sistema",
      "page.info.sub": "Python, CUDA, drivers, paquetes",
      "page.settings.title": "Ajustes",
      "page.settings.sub": "Idioma y preferencias",
      "card.settings.title": "Ajustes de inferencia",
      "card.settings.sub": "Configura una vez, luego INICIAR. Los cambios se aplican al próximo inicio.",
      "settings.aiModel": "Modelo IA",
      "settings.aiModelHint": "Coloca archivos ONNX o TensorRT en <code>models/</code>.",
      "settings.device": "Dispositivo",
      "settings.deviceHintGpuMissing": "Runtime GPU faltante.",
      "settings.deviceHintGpuOk": "La inferencia correrá en tu GPU.",
      "settings.deviceHintGpuRequires": "GPU requiere PyTorch + CUDA / DirectML / TensorRT.",
      "settings.screenLib": "Lib. de pantalla",
      "settings.screenLibHint": "bettercam es más rápido pero solo Windows (opcional).",
      "settings.monitor": "Monitor",
      "settings.monitorHint": "Se muestrea el centro 224×224 del monitor elegido.",
      "settings.ante": "Retraso ante-frontier",
      "settings.cpu": "Carga CPU",
      "settings.cpuHint": "Se adapta a tu CPU. Más = más rendimiento, más carga.",
      "cpu.threads": "hilos",
      "cpu.threadsPinned": "hilos · fijados en P-Cores",
      "cpu.detected": "Detectado",
      "cpu.hybridDetected": "CPU Intel híbrida detectada",
      "cpu.locked": "inferencia bloqueada en P-Cores únicamente.",
      "cpu.locked2": "Mezclar E-Cores ralentizaría cada forward pass — los E-threads terminan más tarde que los P-threads en cada batch.",
      "cpu.typicalGain": "Ganancia típica: <strong>~2× más rápido</strong> que con los {all} hilos.",
      "cpu.tip": "Consejo",
      "cpu.tipBody": "en CPUs Intel híbridas (12.ª gen+), el preset {p} P-Cores suele ser ~2× más rápido que el preset {all}-hilos — usar todos los núcleos es más lento porque los E-cores frenan a los P-cores en cada paso.",
      "cpu.nonHybrid": "Más = más rendimiento, más carga. (Sin CPU híbrida — preset P-Cores solo importa en Intel 12.ª gen+.)",
      "cpu.deviceCpuSummary": "{n} de {total} hilos",
      "cpu.deviceCpuHint": "CPU de {total} núcleos detectada. Más = más rendimiento, más carga.",
      "modal.title": "¿Seguro? Más lento que P-Cores",
      "modal.line1": "En tu <strong>{cpu}</strong> ({pe}), correr",
      "modal.threadsUnpinned": "hilos sin fijar",
      "modal.slower": "es típicamente <strong>~2× más lento</strong> que el",
      "modal.preset": "preset (P-Cores)",
      "modal.explain": "Los E-Cores corren la inferencia mucho más lento por hilo que los P-Cores. Mezclados en el mismo forward pass, los E-threads frenan a los P-threads y bajan el rendimiento total.",
      "modal.benchref": "Benchmark de referencia i9-14900K (ONNX): 8 P-Cores → 980 fps · 32 hilos → 525 fps.",
      "modal.useAnyway": "Usar igualmente",
      "modal.keep": "Mantener",
      "toast.hybridTitle": "Optimización CPU híbrida",
      "toast.hybridBody": "Tu CPU tiene P-Cores rápidos y E-Cores lentos. El preset {p}t ★ fija la inferencia solo en P-Cores — típicamente ~2× más rápido que con los {all} hilos.",
      "toast.systemDetected": "Sistema detectado",
      "toast.cpuLineHybrid": "{summary} (Intel híbrida — preset P-Cores activado)",
      "toast.cpuLine": "{summary} · {os}",
      "toast.gpuLineOk": "GPU: {summary}",
      "toast.gpuLineNa": "GPU: no disponible",
      "toast.running": "Inferencia en ejecución",
      "toast.runningGpu": "Proveedor: {provider}",
      "toast.runningCpu": "{used}/{total} hilos CPU · {provider}",
      "toast.stopped": "Detenido",
      "toast.stoppedBody": "Bucle de inferencia terminado limpiamente.",
      "toast.errInfer": "Error de inferencia",
      "toast.errStart": "No se pudo iniciar",
      "toast.errStop": "No se pudo detener",
      "toast.errInit": "Fallo en la inicialización",
      "toast.errModels": "Sin archivos de modelo",
      "toast.errModelsBody": "Coloca archivos ONNX o TensorRT en {folder}/",
      "toast.errMonitors": "Fallo al listar monitores",
      "toast.fpsDanger": "FPS críticamente bajos",
      "toast.fpsWarn": "Aviso FPS",
      "toast.fpsCapSet": "Tope del juego: {cap} fps",
      "toast.fpsCapSetBody": "Reinicia Dead by Daylight para aplicar (el juego solo lee este archivo al iniciar).",
      "toast.fpsCapErr": "No se pudo escribir el tope FPS",
      "mini.avgFps": "FPS promedio",
      "mini.hitsTotal": "Aciertos totales",
      "mini.gameCap": "Tope FPS del juego",
      "card.feed.title": "Feed del monitor en vivo",
      "card.feed.sub": "Centro 224×224 que ve el modelo",
      "card.feed.empty": "Pulsa INICIAR o elige un monitor",
      "card.feed.emptyAlt": "Vista previa fallida — elige otro monitor o lib",
      "card.feed.fps": "{fps} FPS",
      "card.donut.title": "Último Skill Check",
      "card.donut.subEmpty": "Aún sin aciertos",
      "card.donut.label": "CONFIANZA",
      "card.lasthit.title": "Último frame de acierto",
      "card.lasthit.sub": "Frame capturado donde el modelo pulsó ESPACIO",
      "card.lasthit.empty": "Aún sin aciertos",
      "ante.hint": "Retraso de pulsación para hits ante-frontier (borde temprano). Menor = reaccionar antes; mayor = esperar más adentro de la great-zone.",
      "ante.guide": "0–10 ms: agresivo · 15–25 ms: equilibrado (defecto) · 30–50 ms: más seguro.",
      "perf.gpu": "GPU",
      "perf.gpuNa": "GPU · no disponible",
      "perf.cpu": "CPU",
      "perf.cpuNa": "CPU · no disponible",
      "perf.psutilMissing": "psutil no instalado.",
      "perf.nvidiaSmiMissing": "Sin GPU NVIDIA (falta nvidia-smi).",
      "perf.utilization": "Utilización",
      "perf.totalUtil": "Utilización total",
      "perf.power": "Potencia",
      "perf.temperature": "Temperatura",
      "perf.vram": "VRAM",
      "perf.fan": "Ventilador",
      "perf.memUtil": "Util. memoria",
      "perf.perCore": "Utilización por núcleo",
      "perf.lhmHint": 'Temp/Potencia CPU no disponibles. Instala &amp; ejecuta <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> con WMI activado para verlas aquí.',
      "perf.chartTitle": "Monitor de rendimiento",
      "perf.chartSub": "Métricas GPU + detección en tiempo real",
      "perf.chartFps": "FPS",
      "perf.chartGpu": "GPU %",
      "perf.chartVram": "VRAM",
      "perf.chartTemp": "Temp",
      "settings.lang": "Idioma",
      "settings.langDesc": "Idioma de la interfaz — guardado en tu navegador.",
      "settings.fpsCap": "Tope FPS del juego",
      "settings.fpsCapHint": "Escribe <code>FrameRateLimit</code> en <code>GameUserSettings.ini</code> de DBD. <strong>Reinicia Dead by Daylight</strong> para aplicar — el juego solo lee este archivo al iniciar.",
      "settings.fpsCapNoIni": "INI no encontrado. Inicia DBD una vez para generar GameUserSettings.ini, luego recarga.",
      "settings.fpsCapStatusSet": "Fijado en {cap} fps · reinicia DBD para aplicar.",
      "settings.fpsCapStatusRecommended": "Recomendado: {rec} fps (★) — la herramienta no llega a {cur}.",
      "settings.fpsCapStatusCurrent": "Actualmente limitado a {cur} fps.",
      "info.envTitle": "Entorno",
      "info.envSub": "Python · SO · drivers · CUDA toolkit",
      "info.pkgTitle": "Paquetes Python",
      "info.pkgSub": "Dependencias instaladas del pipeline de inferencia",
      "info.aboutTitle": "Acerca de",
      "info.aboutSub": "Open-source · UI Flask para Manuteaa/dbd_autoSkillCheck",
      "info.python": "Python",
      "info.executable": "Ruta del intérprete",
      "info.os": "Sistema operativo",
      "info.gpu": "GPU",
      "info.driver": "Driver NVIDIA",
      "info.cudaRuntime": "CUDA (driver)",
      "info.cudaToolkit": "CUDA Toolkit (nvcc)",
      "info.cudaHome": "CUDA_PATH",
      "info.torch": "PyTorch",
      "info.torchCuda": "PyTorch CUDA",
      "info.notInstalled": "no instalado",
      "info.notDetected": "no detectado",
      "info.installed": "instalado",
      "info.missing": "falta",
      "info.required": "requerido",
      "info.optional": "opcional",
      "info.loading": "Cargando…",
      "about.p1": 'UI Flask drop-in para <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">Manuteaa/dbd_autoSkillCheck</a>. La app Gradio por defecto (<code>app.py</code>) queda intacta — ejecuta <code>python app_flask.py</code> para esta UI.',
      "about.p2": "Presets CPU adaptativos, fijado P-Cores en CPUs híbridas, monitor GPU (solo NVIDIA vía <code>nvidia-smi</code>) y advisor FPS en vivo que compara el FPS medio del tool con el <code>FrameRateLimit</code> del juego.",
      "about.p3": 'Las lecturas de temperatura/potencia CPU requieren <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> instalado y en ejecución (se consulta su namespace WMI).',
      "footer.note": 'Open-source · alternativa drop-in a <code>app.py</code> (Gradio). Fuente: <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">github.com/Manuteaa/dbd_autoSkillCheck</a>',
    },

    ru: {
      "topbar.title": "Auto Skill Check",
      "topbar.sub": "ИИ-детекция great-skill-check и автонажатие",
      "topbar.gpuNa": "GPU н/д",
      "sidebar.system": "Система",
      "sidebar.menu": "Меню",
      "sidebar.status": "Статус",
      "sidebar.provider": "Провайдер",
      "sidebar.avgFps": "Сред. FPS",
      "sidebar.hits": "Хиты",
      "sidebar.run": "▶ ЗАПУСК",
      "sidebar.stop": "■ СТОП",
      "sidebar.copy": "MANUTEAA / DBD_ASC<br />FLASK UI · v1",
      "nav.open": "Главная",
      "nav.perf": "Монитор производительности",
      "nav.info": "Инфо",
      "nav.settings": "Настройки",
      "status.idle": "ОЖИДАНИЕ",
      "status.running": "РАБОТАЕТ",
      "status.starting": "ЗАПУСК",
      "status.stopping": "ОСТАНОВКА",
      "status.error": "ОШИБКА",
      "page.open.title": "Auto Skill Check",
      "page.open.sub": "ИИ-детекция и автонажатие",
      "page.perf.title": "Монитор производительности",
      "page.perf.sub": "CPU и GPU телеметрия в реальном времени",
      "page.info.title": "Информация о системе",
      "page.info.sub": "Python, CUDA, драйверы, пакеты",
      "page.settings.title": "Настройки",
      "page.settings.sub": "Язык и параметры инструмента",
      "card.settings.title": "Параметры инференса",
      "card.settings.sub": "Настройте один раз, затем ЗАПУСК. Изменения применяются при следующем запуске.",
      "settings.aiModel": "Модель ИИ",
      "settings.aiModelHint": "Поместите ONNX или TensorRT файлы в <code>models/</code>.",
      "settings.device": "Устройство",
      "settings.deviceHintGpuMissing": "Среда GPU отсутствует.",
      "settings.deviceHintGpuOk": "Инференс будет работать на вашем GPU.",
      "settings.deviceHintGpuRequires": "GPU требует PyTorch + CUDA / DirectML / TensorRT.",
      "settings.screenLib": "Библиотека экрана",
      "settings.screenLibHint": "bettercam быстрее, но только Windows (опционально).",
      "settings.monitor": "Монитор",
      "settings.monitorHint": "Сэмплируется центральный участок 224×224 выбранного монитора.",
      "settings.ante": "Задержка ante-frontier",
      "settings.cpu": "Нагрузка CPU",
      "settings.cpuHint": "Подстраивается под ваш CPU. Больше = выше пропускная, выше нагрузка.",
      "cpu.threads": "потоков",
      "cpu.threadsPinned": "потоков · закреплены на P-ядрах",
      "cpu.detected": "Обнаружено",
      "cpu.hybridDetected": "Обнаружен гибридный Intel CPU",
      "cpu.locked": "инференс закреплён только на P-ядрах.",
      "cpu.locked2": "Смешивание E-ядер замедлит каждый forward pass — медленные E-потоки заканчивают позже P-потоков на каждом батче.",
      "cpu.typicalGain": "Типичный выигрыш: <strong>~2× быстрее</strong>, чем со всеми {all} потоками.",
      "cpu.tip": "Совет",
      "cpu.tipBody": "на гибридных Intel CPU (12-е поколение+) пресет {p} P-Cores обычно ~2× быстрее, чем {all}-поточный «Max» — даже использование всех ядер медленнее, потому что E-ядра тормозят P-ядра на каждом шаге инференса.",
      "cpu.nonHybrid": "Больше = выше пропускная, выше нагрузка. (Гибридный CPU не обнаружен — пресет P-Cores актуален только для Intel 12-го поколения+.)",
      "cpu.deviceCpuSummary": "{n} из {total} потоков",
      "cpu.deviceCpuHint": "Обнаружен CPU с {total} ядрами. Больше = выше пропускная, выше нагрузка.",
      "modal.title": "Уверены? Медленнее, чем P-Cores",
      "modal.line1": "На вашем <strong>{cpu}</strong> ({pe}) запуск",
      "modal.threadsUnpinned": "незакреплённых потоков",
      "modal.slower": "обычно <strong>~2× медленнее</strong>, чем",
      "modal.preset": "пресет (P-Cores)",
      "modal.explain": "E-ядра выполняют инференс намного медленнее на поток, чем P-ядра. Смешанные в одном forward pass, медленные E-потоки тормозят P-потоки и снижают общую пропускную способность.",
      "modal.benchref": "Эталонный бенчмарк i9-14900K (ONNX): 8 P-Cores → 980 fps · 32 потока → 525 fps.",
      "modal.useAnyway": "Всё равно использовать",
      "modal.keep": "Оставить",
      "toast.hybridTitle": "Оптимизация гибридного CPU",
      "toast.hybridBody": "Ваш CPU имеет быстрые P-ядра и медленные E-ядра. Пресет {p}t ★ закрепляет инференс только на P-ядрах — обычно ~2× быстрее, чем со всеми {all} потоками.",
      "toast.systemDetected": "Система обнаружена",
      "toast.cpuLineHybrid": "{summary} (гибридный Intel — пресет P-Cores включён)",
      "toast.cpuLine": "{summary} · {os}",
      "toast.gpuLineOk": "GPU: {summary}",
      "toast.gpuLineNa": "GPU: недоступно",
      "toast.running": "Инференс работает",
      "toast.runningGpu": "Провайдер: {provider}",
      "toast.runningCpu": "{used}/{total} CPU потоков · {provider}",
      "toast.stopped": "Остановлено",
      "toast.stoppedBody": "Цикл инференса корректно завершён.",
      "toast.errInfer": "Ошибка инференса",
      "toast.errStart": "Не удалось запустить",
      "toast.errStop": "Не удалось остановить",
      "toast.errInit": "Ошибка инициализации",
      "toast.errModels": "Файлы моделей не найдены",
      "toast.errModelsBody": "Поместите ONNX или TensorRT файлы в {folder}/",
      "toast.errMonitors": "Не удалось получить список мониторов",
      "toast.fpsDanger": "FPS критически низкий",
      "toast.fpsWarn": "Предупреждение FPS",
      "toast.fpsCapSet": "Лимит игры: {cap} fps",
      "toast.fpsCapSetBody": "Перезапустите Dead by Daylight, чтобы применить (игра читает файл только при запуске).",
      "toast.fpsCapErr": "Не удалось записать FPS-лимит",
      "mini.avgFps": "Средний FPS",
      "mini.hitsTotal": "Всего хитов",
      "mini.gameCap": "FPS-лимит игры",
      "card.feed.title": "Live-фид монитора",
      "card.feed.sub": "Центральная область 224×224, которую видит модель",
      "card.feed.empty": "Нажмите ЗАПУСК или выберите монитор",
      "card.feed.emptyAlt": "Превью не удалось — выберите другой монитор или библиотеку",
      "card.feed.fps": "{fps} FPS",
      "card.donut.title": "Последний Skill Check",
      "card.donut.subEmpty": "Хитов пока нет",
      "card.donut.label": "УВЕРЕННОСТЬ",
      "card.lasthit.title": "Кадр последнего хита",
      "card.lasthit.sub": "Захваченный кадр, по которому модель нажала ПРОБЕЛ",
      "card.lasthit.empty": "Хитов пока нет",
      "ante.hint": "Предзадержка нажатия для ante-frontier-хитов (раннего края). Меньше = реагировать раньше; больше = ждать глубже в great-zone.",
      "ante.guide": "0–10 мс: агрессивно · 15–25 мс: сбалансировано (по умолч.) · 30–50 мс: безопаснее.",
      "perf.gpu": "GPU",
      "perf.gpuNa": "GPU · недоступно",
      "perf.cpu": "CPU",
      "perf.cpuNa": "CPU · недоступно",
      "perf.psutilMissing": "psutil не установлен.",
      "perf.nvidiaSmiMissing": "NVIDIA GPU не обнаружен (нет nvidia-smi).",
      "perf.utilization": "Загрузка",
      "perf.totalUtil": "Общая загрузка",
      "perf.power": "Мощность",
      "perf.temperature": "Температура",
      "perf.vram": "VRAM",
      "perf.fan": "Вентилятор",
      "perf.memUtil": "Загрузка памяти",
      "perf.perCore": "Загрузка по ядрам",
      "perf.lhmHint": 'Темп/мощность CPU недоступны. Установите и запустите <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> с активным WMI-провайдером, чтобы увидеть их здесь.',
      "perf.chartTitle": "Монитор производительности",
      "perf.chartSub": "GPU и детекция в реальном времени",
      "perf.chartFps": "FPS",
      "perf.chartGpu": "GPU %",
      "perf.chartVram": "VRAM",
      "perf.chartTemp": "Темп",
      "settings.lang": "Язык",
      "settings.langDesc": "Язык интерфейса — сохраняется в браузере.",
      "settings.fpsCap": "FPS-лимит игры",
      "settings.fpsCapHint": "Записывает <code>FrameRateLimit</code> в <code>GameUserSettings.ini</code> DBD. <strong>Перезапустите Dead by Daylight</strong>, чтобы применить — игра читает файл только при запуске.",
      "settings.fpsCapNoIni": "INI не найден. Запустите DBD один раз, чтобы создать GameUserSettings.ini, затем перезагрузите.",
      "settings.fpsCapStatusSet": "Установлено {cap} fps · перезапустите DBD для применения.",
      "settings.fpsCapStatusRecommended": "Рекомендуется: {rec} fps (★) — инструмент не успевает за {cur}.",
      "settings.fpsCapStatusCurrent": "Сейчас ограничено {cur} fps.",
      "info.envTitle": "Окружение",
      "info.envSub": "Python · ОС · драйверы · CUDA toolkit",
      "info.pkgTitle": "Python-пакеты",
      "info.pkgSub": "Установленные зависимости пайплайна инференса",
      "info.aboutTitle": "О программе",
      "info.aboutSub": "Open-source · Flask UI для Manuteaa/dbd_autoSkillCheck",
      "info.python": "Python",
      "info.executable": "Путь к интерпретатору",
      "info.os": "Операционная система",
      "info.gpu": "GPU",
      "info.driver": "Драйвер NVIDIA",
      "info.cudaRuntime": "CUDA (драйвер)",
      "info.cudaToolkit": "CUDA Toolkit (nvcc)",
      "info.cudaHome": "CUDA_PATH",
      "info.torch": "PyTorch",
      "info.torchCuda": "PyTorch CUDA",
      "info.notInstalled": "не установлено",
      "info.notDetected": "не обнаружено",
      "info.installed": "установлено",
      "info.missing": "отсутствует",
      "info.required": "обязательно",
      "info.optional": "опционально",
      "info.loading": "Загрузка…",
      "about.p1": 'Drop-in Flask UI для <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">Manuteaa/dbd_autoSkillCheck</a>. Стандартное Gradio-приложение (<code>app.py</code>) не трогается — для этого UI запустите <code>python app_flask.py</code>.',
      "about.p2": "Адаптивные пресеты CPU, закрепление на P-ядрах для гибридных CPU, монитор GPU (только NVIDIA через <code>nvidia-smi</code>) и live FPS-advisor, сравнивающий средний FPS инструмента с <code>FrameRateLimit</code> игры.",
      "about.p3": 'Чтение температуры/мощности CPU требует <a href="https://github.com/LibreHardwareMonitor/LibreHardwareMonitor" target="_blank" rel="noopener">LibreHardwareMonitor</a> установленным и запущенным (запрашивается его WMI-namespace).',
      "footer.note": 'Open-source · drop-in альтернатива <code>app.py</code> (Gradio). Источник: <a href="https://github.com/Manuteaa/dbd_autoSkillCheck" target="_blank" rel="noopener">github.com/Manuteaa/dbd_autoSkillCheck</a>',
    },
  };

  const STORED_LANG = localStorage.getItem("dbdasc_lang");
  let LANG = STORED_LANG && I18N[STORED_LANG] ? STORED_LANG : "en";
  const HAS_LANG_PREF = !!(STORED_LANG && I18N[STORED_LANG]);

  function t(key, vars) {
    const dict = I18N[LANG] || I18N.en;
    let s = dict[key] ?? I18N.en[key] ?? key;
    if (vars) {
      for (const [k, v] of Object.entries(vars)) {
        s = s.replaceAll(`{${k}}`, String(v));
      }
    }
    return s;
  }

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
    cpu_affinity_mask: 0,
  };
  let initData = null;
  let prevAdvisorSeverity = null;
  let lastHitTimestamp = null;
  let livePollTimer = null;
  let statusPollTimer = null;
  let infoLoaded = false;
  let pCoreWarnAcknowledged = false;
  let lastSnapStatus = "idle";
  let lastSnapAdvice = null;

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
    // First-run language picker. Blocks the rest of init until the user picks
    // one — that way every subsequent string in the UI is rendered in the
    // chosen language from the very first paint.
    if (!HAS_LANG_PREF) await showFirstRunLangPicker();

    try {
      initData = await api("/api/init");
    } catch (e) {
      toast("error", t("toast.errInit"), e.message, 0);
      return;
    }

    if (!initData.models || initData.models.length === 0) {
      toast("error", t("toast.errModels"),
        t("toast.errModelsBody", { folder: initData.models_folder }), 0);
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
          ? t("settings.deviceHintGpuOk")
          : (sys.gpu_unavailable_reason || t("settings.deviceHintGpuMissing"));
      } else {
        const n = cfg.nb_cpu_threads;
        sumEl.textContent = t("cpu.deviceCpuSummary", { n, total: cpu.cores });
        hintEl.textContent = t("cpu.deviceCpuHint", { total: cpu.cores });
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

    // ── CPU presets ──
    const cpuPresets = initData.cpu_presets;
    cfg.nb_cpu_threads = initData.default_cpu_threads;
    const defaultPreset = cpuPresets.find(p => p.threads === cfg.nb_cpu_threads);
    cfg.cpu_affinity_mask = defaultPreset?.affinity_mask || 0;

    const cpuItems = cpuPresets.map(p => {
      const alreadyHasCount = /^\d+t/.test(p.label);
      return {
        label: alreadyHasCount ? p.label : `${p.label} · ${p.threads}t`,
        value: `${p.threads}|${p.affinity_mask}`,
        threads: p.threads,
        affinity_mask: p.affinity_mask,
      };
    });
    const initialCpuValue = `${cfg.nb_cpu_threads}|${cfg.cpu_affinity_mask}`;

    renderSeg($("cfg-cpu"), cpuItems, initialCpuValue, async (_v, item) => {
      const isUnpinnedHybridOversize =
        cpu.is_hybrid && !item.affinity_mask && item.threads > (cpu.p_physical || 0);

      if (isUnpinnedHybridOversize && !pCoreWarnAcknowledged) {
        const cpuLabel = cpu.short_name || `${cpu.cores} threads`;
        const peSplit = `${cpu.p_physical}P+${cpu.e_threads || 0}E`;
        const ok = await showConfirm({
          title: t("modal.title"),
          body: `
            ${t("modal.line1", { cpu: cpuLabel, pe: peSplit })}
            <code>${item.threads} ${t("modal.threadsUnpinned")}</code>
            ${t("modal.slower")}
            <code>${cpu.p_physical}t ★</code> ${t("modal.preset")}.<br><br>
            ${t("modal.explain")}<br><br>
            <em>${t("modal.benchref")}</em>
          `,
          confirmLabel: t("modal.useAnyway"),
          cancelLabel: `${t("modal.keep")} ${cpu.p_physical}t ★`,
        });
        if (!ok) {
          const stripBtns = $("cfg-cpu").querySelectorAll(".seg-btn");
          stripBtns.forEach(b => b.classList.remove("active"));
          const prev = Array.from(stripBtns).find(b =>
            b.dataset.value === `${cfg.nb_cpu_threads}|${cfg.cpu_affinity_mask}`
          );
          if (prev) prev.classList.add("active");
          return;
        }
        pCoreWarnAcknowledged = true;
      }

      cfg.nb_cpu_threads = item.threads;
      cfg.cpu_affinity_mask = item.affinity_mask;
      updateCpuSummary();
      updateDeviceSummary();
    });

    function updateCpuSummary() {
      const isPinned = cfg.cpu_affinity_mask > 0;
      $("cfg-cpu-summary").textContent =
        isPinned
          ? `${cfg.nb_cpu_threads} ${t("cpu.threadsPinned")}`
          : `${cfg.nb_cpu_threads} / ${cpu.cores} ${t("cpu.threads")}`;

      const summary = cpu.cpu_summary || `${cpu.cores}-core CPU`;
      const baseHint = `${t("cpu.detected")}: ${summary}.`;
      const hintEl = $("cfg-cpu-hint");
      if (cpu.is_hybrid) {
        const pStar = `<code>${cpu.p_physical}t ★</code>`;
        hintEl.innerHTML = isPinned
          ? `${baseHint} <strong>${t("cpu.hybridDetected")}</strong> — ${t("cpu.locked")}
             ${t("cpu.locked2")} ${t("cpu.typicalGain", { all: cpu.cores })}`
          : `${baseHint} <strong>${t("cpu.tip")}:</strong> ${t("cpu.tipBody", { p: pStar, all: cpu.cores })}`;
      } else {
        hintEl.textContent = `${baseHint} ${t("cpu.nonHybrid")}`;
      }
    }
    initData.__updateCpuSummary = updateCpuSummary;
    initData.__updateDeviceSummary = updateDeviceSummary;
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
    function applyAnteHints() {
      $("cfg-ante-hint").textContent = t("ante.hint");
      $("cfg-ante-guide").textContent = t("ante.guide");
    }
    applyAnteHints();
    initData.__applyAnteHints = applyAnteHints;

    $("ms-gamefps").textContent = "—";

    // ── Topbar hardware chips ──
    $("cpu-name").textContent = shortCpuName(cpu);
    $("cpu-chip").title = `CPU · ${cpu.cpu_summary || cpu.cores + ' threads'}`;
    if (gpuAvailable) {
      $("gpu-name").textContent = shortGpuName(gpuSummary);
      $("gpu-chip").title = `GPU · ${gpuSummary}`;
    } else {
      $("gpu-name").textContent = t("topbar.gpuNa");
      $("gpu-chip").classList.add("unavailable");
      $("gpu-chip").title = sys.gpu_unavailable_reason || "No GPU runtime detected";
    }

    // ── Sidebar nav routing ──
    initSidebarNav();
    initCpuCoresGrid(cpu);
    initLanguagePicker();
    refreshFpsCapControl();
    initPerfChart();
    applyI18n();
    startPerfPoll();

    // ── Buttons ──
    $("btn-run").addEventListener("click", onRun);
    $("btn-stop").addEventListener("click", onStop);
    $("advisor-close").addEventListener("click", () => {
      $("advisor").classList.add("advisor-hidden");
    });

    refreshPreview();

    // ── Boot toast ──
    const cpuLine = cpu.is_hybrid
      ? t("toast.cpuLineHybrid", { summary: cpu.cpu_summary })
      : t("toast.cpuLine", { summary: cpu.cpu_summary || `${cpu.cores} cores`, os: cpu.platform || "unknown OS" });
    const gpuLine = gpuAvailable
      ? t("toast.gpuLineOk", { summary: gpuSummary })
      : t("toast.gpuLineNa");
    toast("info", t("toast.systemDetected"), `${cpuLine}\n${gpuLine}`);

    if (cpu.is_hybrid) {
      toast("info", t("toast.hybridTitle"),
        t("toast.hybridBody", { p: cpu.p_physical, all: cpu.cores }),
        12000);
    }

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
      toast("error", t("toast.errMonitors"), e.message);
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
      $("feed-empty").textContent = t("card.feed.emptyAlt");
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
        cpu_affinity_mask: cfg.cpu_affinity_mask,
      });
      await api("/api/start", { method: "POST", body });
      $("btn-stop").disabled = false;
      startLivePoll();
    } catch (e) {
      toast("error", t("toast.errStart"), e.message, 0);
      $("btn-run").disabled = false;
    }
  }

  async function onStop() {
    $("btn-stop").disabled = true;
    try {
      await api("/api/stop", { method: "POST" });
      stopLivePoll();
    } catch (e) {
      toast("error", t("toast.errStop"), e.message);
    }
    $("btn-run").disabled = false;
  }

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

    lastSnapStatus = snap.status;
    lastSnapAdvice = snap.fps_advice;

    if (snap.status !== lastStatus) {
      onStatusTransition(lastStatus, snap.status, snap);
      lastStatus = snap.status;
    }
    if (snap.error && snap.error !== lastError) {
      toast("error", t("toast.errInfer"), snap.error, 0);
      lastError = snap.error;
    } else if (!snap.error) {
      lastError = null;
    }

    // Sidebar (uses avg fps, since user requested avg-only display)
    const avgFps = snap.tool_fps_avg ?? snap.tool_fps ?? 0;
    pushChartSample("fps", snap.status === "running" ? avgFps : 0);
    $("sb-status").textContent = t(`status.${snap.status}`) || snap.status;
    $("sb-status").style.color = colorForStatus(snap.status);
    $("sb-provider").textContent = snap.provider || "—";
    $("sb-fps").textContent = avgFps.toFixed(1);
    $("sb-hits").textContent = snap.hit_count || 0;

    $("status-pill").textContent = t(`status.${snap.status}`) || snap.status.toUpperCase();
    $("status-fps").textContent = snap.status === "running" ? `${avgFps.toFixed(1)}` : "—";
    const dot = $("status-dot");
    dot.classList.remove("running", "error", "starting");
    if (snap.status === "running") dot.classList.add("running");
    else if (snap.status === "error") dot.classList.add("error");
    else if (snap.status === "starting" || snap.status === "stopping") dot.classList.add("starting");

    // Mini stats — Avg FPS, Hits Total, Game FPS Cap (Hits/min removed per user)
    $("ms-fps").textContent = avgFps.toFixed(1);
    $("ms-hits").textContent = snap.hit_count || 0;
    setBar("ms-fps-bar", Math.min(100, avgFps / 1.2)); // 120 = 100% bar
    setBar("ms-hits-bar", Math.min(100, (snap.hit_count || 0) * 5));

    $("feed-fps-chip").textContent = `${(snap.tool_fps || 0).toFixed(1)} FPS`;

    renderAdvisor(snap.fps_advice);

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
        ? t("toast.runningGpu", { provider })
        : t("toast.runningCpu", { used: cfg.nb_cpu_threads, total: cores, provider });
      toast("success", t("toast.running"), detail);
    }
    if (to === "idle" && from === "running") {
      toast("info", t("toast.stopped"), t("toast.stoppedBody"));
    }
  }

  function renderAdvisor(advice) {
    const banner = $("advisor");
    if (!advice) return;

    if (typeof advice.game_fps_cap === "number" && advice.game_fps_cap > 0) {
      $("ms-gamefps").textContent = advice.game_fps_cap.toFixed(0);
      // 120 fps = 100% of the bar (user explicitly requested)
      setBar("ms-gamefps-bar", Math.min(100, (advice.game_fps_cap / 120) * 100));
    } else if (advice.game_fps_cap === 0) {
      $("ms-gamefps").textContent = "∞";
      setBar("ms-gamefps-bar", 100);
    } else {
      $("ms-gamefps").textContent = "—";
      setBar("ms-gamefps-bar", 0);
    }

    const sev = advice.severity;
    banner.classList.remove("severity-info", "severity-warn", "severity-danger", "advisor-hidden");

    if (sev === "ok") {
      banner.classList.add("advisor-hidden");
    } else {
      banner.classList.add(`severity-${sev}`);
      $("advisor-icon").textContent = sev === "danger" ? "⚠" : (sev === "warn" ? "⚠" : "ℹ");
      $("advisor-msg").textContent = advice.message || "";
      $("advisor-rec").textContent = advice.recommendation || "";
      $("advisor-rec").style.display = advice.recommendation ? "" : "none";
    }

    if (sev !== prevAdvisorSeverity) {
      if (sev === "danger") {
        toast("error", t("toast.fpsDanger"),
              advice.message + (advice.recommendation ? " " + advice.recommendation : ""), 12000);
      } else if (sev === "warn" && prevAdvisorSeverity !== "danger") {
        toast("warn", t("toast.fpsWarn"),
              advice.message + (advice.recommendation ? " " + advice.recommendation : ""), 10000);
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

  // ─── Confirm modal ─────────────────────────────────────────────
  function showConfirm({ title, body, confirmLabel = "Use anyway", cancelLabel = "Cancel" }) {
    return new Promise(resolve => {
      const overlay = $("modal-overlay");
      $("modal-title").textContent = title;
      $("modal-body").innerHTML = body;
      $("modal-confirm").textContent = confirmLabel;
      $("modal-cancel").textContent = cancelLabel;
      overlay.hidden = false;

      const cleanup = (val) => {
        overlay.hidden = true;
        $("modal-confirm").removeEventListener("click", onConfirm);
        $("modal-cancel").removeEventListener("click", onCancel);
        overlay.removeEventListener("click", onBackdrop);
        document.removeEventListener("keydown", onKey);
        resolve(val);
      };
      const onConfirm = () => cleanup(true);
      const onCancel  = () => cleanup(false);
      const onBackdrop = (e) => { if (e.target === overlay) cleanup(false); };
      const onKey = (e) => {
        if (e.key === "Escape") cleanup(false);
        if (e.key === "Enter")  cleanup(true);
      };
      $("modal-confirm").addEventListener("click", onConfirm);
      $("modal-cancel").addEventListener("click", onCancel);
      overlay.addEventListener("click", onBackdrop);
      document.addEventListener("keydown", onKey);
    });
  }

  // ─── Hardware name shorteners ─────────────────────────────────
  function shortCpuName(cpu) {
    return cpu.short_name || cpu.name || `${cpu.cores}T CPU`;
  }
  function shortGpuName(summary) {
    if (!summary) return "GPU";
    const m = summary.match(/(RTX|GTX|Radeon|Arc|Quadro|Tesla)[\s\w]*$/i);
    if (m) return m[0].trim();
    return summary.replace(/^.+?·\s*/, "").replace(/^NVIDIA\s+GeForce\s+/i, "").trim();
  }

  // ─── Sidebar nav (page switcher) ──────────────────────────────
  function initSidebarNav() {
    document.querySelectorAll(".nav-item").forEach(item => {
      item.addEventListener("click", () => {
        const target = item.dataset.page;
        document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
        item.classList.add("active");
        document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
        const targetPage = document.querySelector(`.page[data-page-id="${target}"]`);
        if (targetPage) targetPage.classList.add("active");
        updateTopbarForPage(target);
        if (target === "info" && !infoLoaded) loadInfoPage();
        if (target === "perf" && typeof drawChart === "function") {
          // Canvas was display:none — draw once it has dimensions.
          requestAnimationFrame(drawChart);
        }
      });
    });
  }

  function updateTopbarForPage(page) {
    const titles = {
      open: ["page.open.title", "page.open.sub"],
      perf: ["page.perf.title", "page.perf.sub"],
      info: ["page.info.title", "page.info.sub"],
      settings: ["page.settings.title", "page.settings.sub"],
    };
    const [tk, sk] = titles[page] || titles.open;
    $("topbar-title").textContent = t(tk);
    $("topbar-sub").textContent = t(sk);
  }

  // ─── First-run language picker ────────────────────────────────
  // Shown exactly once, on the very first launch (no `dbdasc_lang` in
  // localStorage). Returns a Promise that resolves after the user has
  // made a choice — init() awaits this so every later string renders
  // in the chosen language from the start.
  function showFirstRunLangPicker() {
    return new Promise((resolve) => {
      const overlay = $("lang-modal");
      if (!overlay) { resolve(); return; }
      overlay.hidden = false;

      const onPick = (ev) => {
        const btn = ev.target.closest(".lang-btn");
        if (!btn) return;
        const lang = btn.dataset.lang;
        if (!I18N[lang]) return;
        LANG = lang;
        localStorage.setItem("dbdasc_lang", lang);
        document.documentElement.lang = lang;
        overlay.hidden = true;
        overlay.removeEventListener("click", onPick);
        resolve();
      };
      overlay.addEventListener("click", onPick);
    });
  }

  // ─── Language picker ──────────────────────────────────────────
  function initLanguagePicker() {
    const langEl = $("cfg-lang");
    if (!langEl) return;
    renderSeg(langEl,
      [
        { label: "EN", value: "en" },
        { label: "DE", value: "de" },
        { label: "FR", value: "fr" },
        { label: "ES", value: "es" },
        { label: "RU", value: "ru" },
      ],
      LANG,
      (v) => {
        LANG = v;
        localStorage.setItem("dbdasc_lang", v);
        applyI18n();
        document.documentElement.lang = v;
      }
    );
  }

  // ─── Game FPS cap segmented control ──────────────────────────
  async function refreshFpsCapControl() {
    const segEl = $("cfg-fpscap");
    if (!segEl) return;
    let advice = null;
    try { advice = await api("/api/fps-advice"); } catch { /* offline */ }

    const caps = (advice && advice.standard_caps) || [30, 60, 90, 120];
    const current = advice && advice.game_fps_cap;
    const recommended = advice && advice.recommended_cap;
    const status = $("cfg-fpscap-status");

    if (advice && advice.ini_status !== "ok") {
      segEl.innerHTML = `<div class="seg-disabled-hint">${t("settings.fpsCapNoIni")}</div>`;
      if (status) status.textContent = `(${advice.ini_status})`;
      return;
    }

    const items = caps.map(c => ({
      label: `${c} fps${c === recommended ? " ★" : ""}`,
      value: c,
    }));
    const currentValue = current && Math.abs(current - Math.round(current)) < 0.5
      ? Math.round(current) : null;

    renderSeg(segEl, items, currentValue, async (v) => {
      try {
        await api("/api/set-fps-cap", {
          method: "POST",
          body: JSON.stringify({ cap: v }),
        });
        toast("success", t("toast.fpsCapSet", { cap: v }),
          t("toast.fpsCapSetBody"), 9000);
        if (status) status.textContent = t("settings.fpsCapStatusSet", { cap: v });
        refreshFpsCapControl();
      } catch (e) {
        toast("error", t("toast.fpsCapErr"), e.message, 0);
      }
    });

    if (status) {
      if (recommended && recommended !== currentValue) {
        status.textContent = t("settings.fpsCapStatusRecommended", {
          rec: recommended,
          cur: current ? current.toFixed(0) : "?",
        });
      } else if (current) {
        status.textContent = t("settings.fpsCapStatusCurrent", {
          cur: current.toFixed(0),
        });
      } else {
        status.textContent = "";
      }
    }
  }

  // ─── Apply current language to all data-i18n / data-i18n-html nodes ───
  function applyI18n() {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-html]").forEach(el => {
      el.innerHTML = t(el.dataset.i18nHtml);
    });
    if (initData) {
      initData.__updateCpuSummary && initData.__updateCpuSummary();
      initData.__updateDeviceSummary && initData.__updateDeviceSummary();
      initData.__applyAnteHints && initData.__applyAnteHints();
    }
    // Re-render dynamic strings that aren't tagged
    updateTopbarForPage(getActivePageId());
    refreshFpsCapControl();
    // Re-render perf hints with translated language
    if (lastPerfSnap) {
      renderGpuPerf(lastPerfSnap.gpu);
      renderCpuPerf(lastPerfSnap.cpu);
    }
    // Re-render info page if loaded
    if (infoLoaded && lastInfoSnap) renderInfoPage(lastInfoSnap);
    // Re-draw chart so the metric label picks up the new language
    if (typeof drawChart === "function") drawChart();
  }

  function getActivePageId() {
    const active = document.querySelector(".page.active");
    return active ? active.dataset.pageId : "open";
  }

  // ─── CPU per-core grid ─────────────────────────────────────────
  let cpuCoreEls = [];
  function initCpuCoresGrid(cpu) {
    const container = $("cpu-cores");
    container.innerHTML = "";
    cpuCoreEls = [];
    const total = cpu.cores || 0;
    const pCount = cpu.p_threads || 0;
    for (let i = 0; i < total; i++) {
      const cell = document.createElement("div");
      cell.className = "cpu-core";
      if (cpu.is_hybrid && i < pCount) cell.classList.add("p-core");
      else if (cpu.is_hybrid) cell.classList.add("e-core");
      const fill = document.createElement("div");
      fill.className = "cpu-core-fill";
      fill.style.height = "0%";
      const lbl = document.createElement("div");
      lbl.className = "cpu-core-label";
      lbl.textContent = i;
      cell.appendChild(fill);
      cell.appendChild(lbl);
      container.appendChild(cell);
      cpuCoreEls.push(fill);
    }
  }

  // ─── Performance Monitor poll ──────────────────────────────────
  let perfPollTimer = null;
  let lastPerfSnap = null;
  function startPerfPoll() {
    pollPerf();
    perfPollTimer = setInterval(pollPerf, 600);
  }
  async function pollPerf() {
    let snap;
    try { snap = await api("/api/perf"); }
    catch { return; }
    lastPerfSnap = snap;
    renderGpuPerf(snap.gpu);
    renderCpuPerf(snap.cpu);
    pushPerfChartSamples(snap);
  }

  function fmt(v, suffix = "", digits = 0) {
    if (v == null || isNaN(v)) return "—";
    return `${v.toFixed(digits)}${suffix}`;
  }

  function renderGpuPerf(g) {
    if (!g || !g.available) {
      $("perf-gpu-name").textContent = t("perf.gpuNa");
      $("perf-gpu-hint").textContent = (g && g.reason) || t("perf.nvidiaSmiMissing");
      $("gpu-pct").textContent = "—";
      return;
    }
    const utilTopbar = g.util_gpu_pct ?? 0;
    $("gpu-pct").textContent = `${utilTopbar.toFixed(0)}%`;
    $("perf-gpu-name").textContent = g.name || "GPU";
    $("perf-gpu-clocks").textContent =
      `${fmt(g.clock_gr_mhz, " MHz core", 0)} · ${fmt(g.clock_mem_mhz, " MHz mem", 0)}`;

    const util = g.util_gpu_pct ?? 0;
    $("perf-gpu-util").textContent = fmt(util, " %", 0);
    setBar("perf-gpu-util-bar", util);

    const power = g.power_w ?? 0;
    const limit = g.power_limit_w || 1;
    $("perf-gpu-power").textContent = `${fmt(power, " W", 1)} / ${fmt(limit, " W", 0)}`;
    setBar("perf-gpu-power-bar", (power / limit) * 100);

    const temp = g.temp_c ?? 0;
    $("perf-gpu-temp").textContent = fmt(temp, " °C", 0);
    setBar("perf-gpu-temp-bar", Math.min(100, (temp / 90) * 100));

    const memUsed = g.mem_used_mib ?? 0;
    const memTotal = g.mem_total_mib || 1;
    $("perf-gpu-mem").textContent =
      `${(memUsed / 1024).toFixed(1)} / ${(memTotal / 1024).toFixed(1)} GB`;
    setBar("perf-gpu-mem-bar", (memUsed / memTotal) * 100);

    $("perf-gpu-fan").textContent = fmt(g.fan_pct, " %", 0);
    $("perf-gpu-memutil").textContent = fmt(g.util_mem_pct, " %", 0);
    $("perf-gpu-hint").textContent = "";
  }

  function renderCpuPerf(c) {
    const hintEl = $("perf-cpu-hint");
    if (!c || !c.available) {
      $("perf-cpu-name").textContent = t("perf.cpuNa");
      hintEl.innerHTML = "";
      hintEl.textContent = (c && c.reason) || t("perf.psutilMissing");
      $("cpu-pct").textContent = "—";
      return;
    }
    const utilTopbar = c.util_pct ?? 0;
    $("cpu-pct").textContent = `${utilTopbar.toFixed(0)}%`;
    const sys = initData?.system?.cpu;
    $("perf-cpu-name").textContent = sys?.cpu_summary || "CPU";
    $("perf-cpu-freq").textContent =
      `${fmt(c.freq_mhz, " MHz", 0)}${c.freq_max_mhz ? " / " + c.freq_max_mhz.toFixed(0) + " MHz" : ""}`;

    const util = c.util_pct ?? 0;
    $("perf-cpu-util").textContent = fmt(util, " %", 1);
    setBar("perf-cpu-util-bar", util);

    if (c.power_w != null) {
      $("perf-cpu-power").textContent = fmt(c.power_w, " W", 1);
      setBar("perf-cpu-power-bar", Math.min(100, (c.power_w / 200) * 100));
    } else {
      $("perf-cpu-power").textContent = "—";
      setBar("perf-cpu-power-bar", 0);
    }

    if (c.temp_c != null) {
      $("perf-cpu-temp").textContent = fmt(c.temp_c, " °C", 0);
      setBar("perf-cpu-temp-bar", Math.min(100, (c.temp_c / 100) * 100));
    } else {
      $("perf-cpu-temp").textContent = "—";
      setBar("perf-cpu-temp-bar", 0);
    }

    if (Array.isArray(c.util_per_core)) {
      c.util_per_core.forEach((pct, i) => {
        const el = cpuCoreEls[i];
        if (!el) return;
        el.style.height = `${Math.max(0, Math.min(100, pct))}%`;
      });
    }

    // CPU temp/power UX: when LHM isn't running, show a clearer
    // explanatory hint with a link instead of silent dashes.
    if (c.temp_c == null && c.power_w == null) {
      hintEl.innerHTML = t("perf.lhmHint");
    } else {
      hintEl.textContent = "";
    }
  }

  // ─── Big chart card (SUV-style switchable line chart) ──────────
  const CHART_HISTORY = 60;
  const chartData = {
    fps:  new Array(CHART_HISTORY).fill(0),
    gpu:  new Array(CHART_HISTORY).fill(0),
    vram: new Array(CHART_HISTORY).fill(0),
    temp: new Array(CHART_HISTORY).fill(0),
  };
  let activeMetric = "fps";

  const CHART_LABELS = {
    fps:  () => t("perf.chartFps"),
    gpu:  () => t("perf.chartGpu"),
    vram: () => t("perf.chartVram"),
    temp: () => t("perf.chartTemp"),
  };

  function metricMax(metric, data) {
    if (metric === "fps")  return Math.max(100, ...data, 1);
    if (metric === "gpu")  return 100;
    if (metric === "vram") return 100;
    if (metric === "temp") return 100;
    return 100;
  }

  function metricUnit(metric) {
    if (metric === "fps")  return "";
    if (metric === "gpu")  return "%";
    if (metric === "vram") return "%";
    if (metric === "temp") return "°C";
    return "";
  }

  function pushChartSample(metric, value) {
    const arr = chartData[metric];
    if (!arr) return;
    arr.shift();
    arr.push(Number.isFinite(value) ? value : 0);
    if (metric === activeMetric) drawChart();
  }

  function pushPerfChartSamples(snap) {
    const g = snap?.gpu;
    if (!g || !g.available) {
      pushChartSample("gpu", 0);
      pushChartSample("vram", 0);
      pushChartSample("temp", 0);
      return;
    }
    pushChartSample("gpu", g.util_gpu_pct ?? 0);
    const memPct = (g.mem_total_mib && g.mem_used_mib != null)
      ? (g.mem_used_mib / g.mem_total_mib) * 100 : 0;
    pushChartSample("vram", memPct);
    pushChartSample("temp", g.temp_c ?? 0);
  }

  function setActiveMetric(metric) {
    if (!chartData[metric]) return;
    activeMetric = metric;
    document.querySelectorAll(".chart-tab").forEach(b => {
      b.classList.toggle("active", b.dataset.metric === metric);
    });
    drawChart();
  }

  function initPerfChart() {
    document.querySelectorAll(".chart-tab").forEach(b => {
      b.addEventListener("click", () => setActiveMetric(b.dataset.metric));
    });
    window.addEventListener("resize", drawChart);
    drawChart();
  }

  function drawChart() {
    const canvas = $("mainChart");
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;

    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const w = rect.width, h = rect.height;
    ctx.clearRect(0, 0, w, h);

    const data = chartData[activeMetric];
    const max = metricMax(activeMetric, data);
    const unit = metricUnit(activeMetric);
    const last = data[data.length - 1] || 0;

    // Update floating labels
    const maxEl = $("chartMaxLabel");
    const bigEl = $("chartBigValue");
    const subEl = $("chartBigLabel");
    if (maxEl) maxEl.textContent = Math.round(max);
    if (bigEl) bigEl.textContent = activeMetric === "fps" ? last.toFixed(1) : Math.round(last) + (unit ? "" : "");
    if (subEl) subEl.textContent = (CHART_LABELS[activeMetric]?.() || activeMetric) + (unit && activeMetric !== "gpu" && activeMetric !== "vram" ? "" : "");

    // Grid lines
    ctx.strokeStyle = "rgba(255,255,255,0.04)";
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i++) {
      const y = (h / 5) * i;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    // Y-axis tick labels
    ctx.fillStyle = "rgba(138,143,154,0.7)";
    ctx.font = "10px 'JetBrains Mono', monospace";
    ctx.textAlign = "left";
    for (let i = 0; i <= 4; i++) {
      const v = max - (max / 4) * i;
      ctx.fillText(Math.round(v), 4, (h / 4) * i + 10);
    }

    // Filled area under the line
    const step = w / (data.length - 1);
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    grad.addColorStop(0, "rgba(255, 140, 0, 0.35)");
    grad.addColorStop(1, "rgba(255, 140, 0, 0)");
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(0, h);
    data.forEach((v, i) => ctx.lineTo(i * step, h - (v / max) * h));
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fill();

    // Glowing line
    ctx.strokeStyle = "#ff8c00";
    ctx.lineWidth = 2.5;
    ctx.shadowColor = "rgba(255,140,0,0.6)";
    ctx.shadowBlur = 10;
    ctx.beginPath();
    data.forEach((v, i) => {
      const x = i * step, y = h - (v / max) * h;
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Current point marker
    const lx = (data.length - 1) * step;
    const ly = h - (last / max) * h;
    ctx.fillStyle = "#ff8c00";
    ctx.beginPath();
    ctx.arc(lx, ly, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#000";
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // ─── Info page ─────────────────────────────────────────────────
  let lastInfoSnap = null;
  async function loadInfoPage() {
    $("info-env").innerHTML = `<div class="info-row"><span class="info-row-key">${t("info.loading")}</span></div>`;
    $("info-packages").innerHTML = "";
    try {
      const data = await api("/api/info");
      lastInfoSnap = data;
      infoLoaded = true;
      renderInfoPage(data);
    } catch (e) {
      $("info-env").innerHTML = `<div class="info-row"><span class="info-row-key">Error</span><span class="info-row-val red">${e.message}</span></div>`;
    }
  }

  function _row(key, val, valClass = "") {
    return `<div class="info-row">
      <span class="info-row-key">${key}</span>
      <span class="info-row-val ${valClass}">${val == null || val === "" ? "—" : escapeHtml(String(val))}</span>
    </div>`;
  }
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  }

  function renderInfoPage(data) {
    const env = $("info-env");
    const py = data.python || {};
    const os = data.os || {};
    const nv = data.nvidia || {};
    const ck = data.cuda_toolkit || {};
    const pt = data.torch || {};

    let html = "";
    html += _row(t("info.python"), `${py.version || "—"} (${py.implementation || ""} ${py.bits || ""})`.trim());
    html += _row(t("info.executable"), py.executable || "—", "muted");
    html += _row(t("info.os"), `${os.system || ""} ${os.release || ""} (${os.machine || ""})`.trim());
    html += _row(t("info.gpu"), nv.available ? (nv.gpu_name || "NVIDIA GPU") : t("info.notDetected"),
      nv.available ? "green" : "muted");
    html += _row(t("info.driver"), nv.driver || t("info.notDetected"), nv.driver ? "green" : "muted");
    html += _row(t("info.cudaRuntime"), nv.cuda_runtime || t("info.notDetected"),
      nv.cuda_runtime ? "green" : "muted");
    html += _row(t("info.cudaToolkit"), ck.version || t("info.notInstalled"),
      ck.version ? "green" : "muted");
    if (ck.home) html += _row(t("info.cudaHome"), ck.home, "muted");
    if (pt.installed) {
      html += _row(t("info.torch"), pt.version || "—", "green");
      const cudaText = pt.cuda_built
        ? `${pt.cuda_version || ""} (${pt.cuda_available ? "✓ CUDA" : "✗ no CUDA"})`.trim()
        : t("info.notInstalled");
      html += _row(t("info.torchCuda"), cudaText, pt.cuda_available ? "green" : (pt.cuda_built ? "amber" : "muted"));
    } else {
      html += _row(t("info.torch"), t("info.notInstalled"), "muted");
    }
    env.innerHTML = html;

    // Packages
    const tbl = $("info-packages");
    tbl.innerHTML = "";
    (data.packages || []).forEach(p => {
      const row = document.createElement("div");
      row.className = "pkg-row";
      const verCls = p.installed ? "installed" : (p.optional ? "optional-missing" : "missing");
      const badgeCls = p.optional ? "optional" : "required";
      const badgeLabel = p.optional ? t("info.optional") : t("info.required");
      row.innerHTML = `
        <div class="pkg-row-name">
          <div class="pkg-row-display">${escapeHtml(p.display_name)} <span style="opacity:.5;font-weight:500">· ${escapeHtml(p.dist)}</span></div>
          <div class="pkg-row-role">${escapeHtml(p.role)}</div>
        </div>
        <div class="pkg-row-version ${verCls}">
          ${p.installed ? escapeHtml(p.version || "?") : t(p.optional ? "info.notInstalled" : "info.missing")}
        </div>
        <div class="pkg-badge ${badgeCls}">${badgeLabel}</div>
      `;
      tbl.appendChild(row);
    });
  }

  // ─── Boot ──────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    document.documentElement.lang = LANG;
    init();
  });
})();
