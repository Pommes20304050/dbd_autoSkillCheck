# Chapter 9 — Frontend Errors

This chapter catalogues every browser-side failure mode in the dbd_autoSkillCheck Flask UI. The frontend is a single-page app composed of `dbd/web/static/app.js` (~2.4k lines), `dbd/web/templates/index.html` (~465 lines) and `dbd/web/static/style.css` (~1.2k lines). It talks to the Flask backend exclusively through short-lived JSON `fetch()` calls against `/api/*` and one MJPEG-style polling pattern against `/api/live-frame` and `/api/last-hit-frame`. There is no WebSocket, no service worker, no offline cache, no module loader and no framework — every error class below is a consequence of that hand-rolled architecture.

The errors are grouped roughly by source: bootstrap and `/api/init`, polling loops (`/api/status`, `/api/perf`, `/api/preflight`), preview / live-frame, DOM and i18n, browser-environment quirks (localStorage, autofill, throttling) and visual / a11y problems. The numbering is stable so other chapters can cross-reference (e.g. backend chapter 4 references `E.UI.014` for the in-flight guard that masks server slowness).

---

## E.UI.001 — `/api/init` failure leaves UI in zombie state
**Trigger:** First call inside `init()` throws (server offline, 503, 500, network blip, DNS).
**Where:** `app.js:1189-1194`
**What it means (plain English):** The very first server round-trip on page load failed. The function returns immediately after toasting the error.
**Symptoms:** A red "Failed to initialize" toast with sticky TTL (`ttl=0`). Sidebar stays at "—". RUN button is enabled but clicking it cannot succeed because `cfg.model` is `null`. No preflight banner ever appears. No status polling starts.
**Root cause(s):** `init()` aborts with `return` instead of scheduling a retry; `statusPollTimer` and `preflightPollTimer` are only started after the `await api("/api/init")` line.
**How to fix:**
1. Wrap `/api/init` in an exponential-backoff retry (250 ms → 5 s, capped).
2. Show a "Retry" button inside the toast that re-invokes `init()`.
3. Continue to render the static shell so the user sees something other than "—".
**Prevention / hardening:** Treat `init()` as resumable; isolate the network call behind a `bootstrap()` helper that the rest of the UI subscribes to.
**Related:** E.UI.002, E.UI.003, E.BE.* (backend startup races).

## E.UI.002 — `/api/init` returns malformed JSON
**Trigger:** Reverse-proxy injects an HTML error page; Flask returns plain text 500; gzipped truncation.
**Where:** `app.js:1127-1128` (`try { body = await res.json(); } catch { /* empty */ }`)
**What it means (plain English):** Body parsing silently swallows the JSON syntax error and returns `null`.
**Symptoms:** `initData` becomes `null`, then `initData.models` throws `TypeError: Cannot read properties of null` on line 1196. Console has an uncaught exception; UI freezes mid-init.
**Root cause(s):** The empty `catch` block discards the parser error without bubbling.
**How to fix:**
1. Re-throw a `BadResponseError` when JSON parsing fails AND `res.ok` is true.
2. Toast the parser error with the first 200 bytes of the body for diagnosis.
**Prevention / hardening:** Always assert `body !== null` before dereferencing in callers.
**Related:** E.UI.001.

## E.UI.003 — `/api/init` returns 503 (worker still booting)
**Trigger:** User reloads while ONNX Runtime is still importing.
**Where:** `app.js:1129-1131`
**What it means (plain English):** `api()` throws `Error("HTTP 503")`. Same path as offline.
**Symptoms:** Toast says "Failed to initialize: HTTP 503". User has to reload manually.
**Root cause(s):** No retry strategy distinguishes transient (503) from terminal (404) errors.
**How to fix:**
1. Add retry-on-503 with backoff inside `api()` (max 5 attempts).
2. Show a "Server is starting..." spinner instead of an error toast for 503.
**Prevention / hardening:** Backend should always return a stable 200 from `/api/init` once Flask is up, even if subsystems are still loading (use feature flags in the payload).
**Related:** E.UI.001.

## E.UI.004 — `/api/status` slow response stalls the poller
**Trigger:** Backend lock contention or blocking screen-capture call holds `/api/status` for >500 ms.
**Where:** `app.js:1524-1533` (`pollStatusInflight` guard)
**What it means (plain English):** The in-flight guard stops a queue from forming, but it also masks backend slowness — the user sees no telemetry update for as long as the server stalls.
**Symptoms:** FPS counter freezes; status pill stuck on stale value; no "ERROR" toast even if worker died, because the status simply never refreshes.
**Root cause(s):** The guard is unconditional — there is no timeout, no "stale-since" indicator, no fallback display.
**How to fix:**
1. Add an `AbortController` with a 4 s timeout per `/api/status` call.
2. If a request times out, render the status pill as "STALE" with a tooltip showing how long ago the last successful poll was.
3. Increase polling interval (back-off) after 3 consecutive failures.
**Prevention / hardening:** Surface backend latency in the UI rather than hiding it.
**Related:** E.UI.005, E.UI.014.

## E.UI.005 — `/api/status` permanent failure: silent black hole
**Trigger:** Backend route raises 500 indefinitely (e.g. perf subsystem deadlock).
**Where:** `app.js:1532-1533` (`catch (e) { pollStatusInflight = false; return; }`)
**What it means (plain English):** Errors are swallowed; the `setInterval` keeps firing every 500 ms forever.
**Symptoms:** No toast, no console output, no banner. UI looks alive but is fully detached from server state.
**Root cause(s):** Empty catch with no error counter, no toast, no logger.
**How to fix:**
1. Count consecutive failures; after N=10 failures show a sticky "Lost connection to server" toast.
2. Log failures to `console.warn` so they're visible in DevTools.
**Prevention / hardening:** Add a heartbeat indicator dot in the topbar that turns red when `/api/status` last failed.
**Related:** E.UI.004, E.UI.027.

## E.UI.006 — `/api/perf` failure suppressed
**Trigger:** psutil or nvidia-smi raises; route returns 500 or stalls.
**Where:** `app.js:2052-2057` (`catch { pollPerfInflight = false; return; }`)
**What it means (plain English):** Same anti-pattern as E.UI.005 — silent swallow, no UI signal.
**Symptoms:** Performance Monitor card stays frozen on the last good values; CPU/GPU bars stuck; user assumes telemetry is fresh.
**Root cause(s):** No timestamp, no staleness indicator, no error toast.
**How to fix:**
1. Surface staleness: grey out perf bars after 3 missed polls.
2. Show last-success timestamp in the card subtitle.
**Prevention / hardening:** Same as E.UI.005.
**Related:** E.UI.005, E.UI.024.

## E.UI.007 — `/api/preview` returns 500 (capture init failure)
**Trigger:** mss/bettercam fails to enumerate; chosen monitor index out of range; DXGI handle dropped during alt-tab.
**Where:** `app.js:1445-1459` — `img.onerror` triggers when the image element gets a non-image response.
**What it means (plain English):** Browser sees a 500 instead of a JPEG, fires the `error` event on `<img>`.
**Symptoms:** Empty placeholder card with text "Preview failed — pick another monitor or library" (`card.feed.emptyAlt`). No toast — just the inline placeholder.
**Root cause(s):** `img.onerror` is the only error channel; the error body (which might say "monitor 3 not found") is never read.
**How to fix:**
1. Replace `<img src="...">` with `fetch()` → check status → set `URL.createObjectURL(blob)` → release with `URL.revokeObjectURL`.
2. On non-OK responses, parse JSON error and show toast with reason.
**Prevention / hardening:** Always tee error context to the user; "Preview failed" alone gives them no actionable hint.
**Related:** E.UI.026 (cache busting), E.UI.029.

## E.UI.008 — `/api/preflight` failure leaves stale advice
**Trigger:** Preflight route 500s (e.g. transient `pkg_resources` import error after a `pip install`).
**Where:** `app.js:1669-1673` (`catch { return; // probe failed (503) — leave previous banner state alone }`)
**What it means (plain English):** Failure is intentionally swallowed; previous banner stays.
**Symptoms:** User installs the missing package but the "package missing" banner does not clear, because the only refresh path is the next 30 s tick — and if that one fails too, nothing updates until success.
**Root cause(s):** No retry-on-failure with a shorter interval; banner has no "checking..." state.
**How to fix:**
1. On preflight fetch failure, retry once after 2 s.
2. Add a refresh icon to the banner that re-runs `pollPreflight()` on click.
**Prevention / hardening:** Display "last checked: HH:MM:SS" inside the banner.
**Related:** E.UI.001, E.UI.020.

## E.UI.009 — No WebSocket — every page is a polling cluster
**Trigger:** N/A (architectural).
**Where:** Whole `app.js` — uses `setInterval` at 500 ms (`/api/status`), 600 ms (`/api/perf`), 30 s (`/api/preflight`), 250 ms (`/api/live-frame`).
**What it means (plain English):** The browser hammers Flask with ~5 requests/second per open tab, even when nothing is happening.
**Symptoms:** Battery drain; mobile thermal throttling; reverse-proxy log floods; backlog under network jitter.
**Root cause(s):** No socket/SSE channel. No reconnection logic exists because no sockets exist.
**How to fix:**
1. Add `/api/events` Server-Sent Events stream with status + perf + preflight events.
2. Fall back to polling if SSE connect fails 3× in a row.
**Prevention / hardening:** Document polling intervals; pause polling when `document.hidden` is true.
**Related:** E.UI.030, E.UI.014.

## E.UI.010 — `escapeHtml` does not handle backtick or non-string inputs
**Trigger:** Server returns numeric/null/object in a field that gets passed through `escapeHtml`.
**Where:** `app.js:2340-2342`
**What it means (plain English):** `s.replace(...)` throws `TypeError: s.replace is not a function` if `s` is not a string. Backticks (`` ` ``) are not escaped, allowing template-literal injection if the output is later eval'd by an extension.
**Symptoms:** Info page errors out to "Cannot read properties of undefined" on weird inputs.
**Root cause(s):** No `String(s)` coercion at function entry; allowlist regex omits backtick.
**How to fix:**
1. Coerce: `s = String(s == null ? "" : s);` at the top of `escapeHtml`.
2. Add backtick: `{"&":"&amp;",...,"`":"&#96;"}`.
**Prevention / hardening:** Pair with an ESLint rule banning bare innerHTML interpolation of untrusted strings.
**Related:** E.UI.011.

## E.UI.011 — Direct `innerHTML` interpolation surfaces (XSS)
**Trigger:** Backend payload contains user-controlled or attacker-influenced text (e.g. monitor label coming from EDID, package display name, `cpu_summary`).
**Where:** Multiple — non-exhaustive list:
- `app.js:1102-1109` (toast template; values are then re-set via textContent — safe).
- `app.js:1290-1297` (modal body interpolates `cpu.short_name` raw via `cpu: cpuLabel`).
- `app.js:1331-1334` (CPU hint with `t("cpu.tipBody")` — translated text contains raw HTML).
- `app.js:1796-1800` (legend row with raw `dotColor` from a literal — safe, but adjacent untrusted `name` is set via `textContent` only after the fact, so a synchronous mutation could leak).
- `app.js:1992` (`el.innerHTML = t(el.dataset.i18nHtml)` — i18n strings may contain HTML).
- `app.js:2384-2393` (package row interpolates `display_name`, `dist`, `role` via `escapeHtml`, but `verCls` and `badgeCls` are unescaped CSS class names).
**What it means (plain English):** Any of these surfaces could be an XSS sink if backend ever leaks unsanitised input.
**Symptoms:** Cosmetic glitches at best; arbitrary script execution at worst.
**Root cause(s):** Mix of `innerHTML` and `escapeHtml`; some places forget to escape; CSS class values are unchecked.
**How to fix:**
1. Audit every `.innerHTML =` site; convert to `<template>` cloning where possible.
2. Add a CSP header (script-src 'self'; style-src 'self' 'unsafe-inline').
**Prevention / hardening:** Set `Content-Security-Policy` from Flask; never accept HTML in i18n strings (`data-i18n-html` should be deprecated).
**Related:** E.UI.010, E.UI.022.

## E.UI.012 — `localStorage.setItem("dbdasc_lang", ...)` throws when storage is full
**Trigger:** User has hundreds of localStorage keys; quota exceeded.
**Where:** `app.js:1898`, `app.js:1923`.
**What it means (plain English):** `setItem` raises `QuotaExceededError` (DOMException). Uncaught.
**Symptoms:** Language picker click does nothing; console error; subsequent re-renders abort.
**Root cause(s):** No try/catch around `setItem`.
**How to fix:**
1. Wrap each `localStorage.setItem` in `try { ... } catch (e) { console.warn("storage full", e); }`.
2. Fall back to in-memory state when storage is unavailable.
**Prevention / hardening:** Probe `localStorage` availability once at boot and toggle a `STORAGE_OK` flag.
**Related:** E.UI.013.

## E.UI.013 — `localStorage` disabled (private browsing / corporate policy)
**Trigger:** Safari Private mode, Firefox strict mode, locked-down corporate browser.
**Where:** `app.js:1079` (`localStorage.getItem`).
**What it means (plain English):** Some browsers throw `SecurityError` on access; others return null and reject `setItem`.
**Symptoms:** First-run language picker re-appears on every reload; or page hangs at boot.
**Root cause(s):** Code assumes localStorage always works.
**How to fix:**
1. Wrap the read at line 1079 in try/catch.
2. Fall back to a sessionStorage / cookie-based store, or at least a memory shim.
**Prevention / hardening:** Build a `safeStorage` helper that auto-falls back.
**Related:** E.UI.012, E.UI.034.

## E.UI.014 — Status `setInterval` survives the in-flight guard but not stop-the-world
**Trigger:** Browser tab is suspended (background), then resumed; pending `/api/status` was queued by `setInterval` but never fired its callback.
**Where:** `app.js:1413` (`setInterval(pollStatus, 500)`).
**What it means (plain English):** Long suspension can make `setInterval` callbacks pile up on resume; combined with the in-flight guard most are no-ops, but the user-facing status remains stuck on the snapshot from before suspension.
**Symptoms:** Tab returns to foreground showing "RUNNING" even though the worker has long since errored.
**Root cause(s):** No `visibilitychange` handler that resets state on resume.
**How to fix:**
1. Listen for `document.addEventListener("visibilitychange", ...)` and trigger an immediate poll on `visible`.
2. Treat the first poll after resume as a forced full refresh.
**Prevention / hardening:** Tag every snapshot with a server-side timestamp; render relative age.
**Related:** E.UI.030, E.UI.005.

## E.UI.015 — Cross-origin: user opens app under a different host
**Trigger:** User bookmarked `http://192.168.1.5:5000/` then opens `http://localhost:5000/` (or vice versa).
**Where:** All `fetch()` calls — relative paths resolve against `window.location.origin`.
**What it means (plain English):** Relative `/api/*` URLs are fine, but if the user opens the page through a reverse proxy that rewrites paths or drops query strings, requests miss.
**Symptoms:** All API calls 404; init never completes; everything looks broken.
**Root cause(s):** No SCRIPT_NAME / base-href configuration.
**How to fix:**
1. Inject `window.__BASE = "{{ url_for('') }}"` in the Jinja template and prepend to API calls.
2. Set `<base href="...">` from Flask.
**Prevention / hardening:** Document supported deployment topologies.
**Related:** E.UI.016.

## E.UI.016 — Browser autofill conflicts with the segmented controls
**Trigger:** Chrome/Edge "Autofill" sees `<button>` controls inside `<form>` and tries to fill them.
**Where:** `index.html` settings cards — segmented controls are bare `<button>`s inside divs without `autocomplete="off"`.
**What it means (plain English):** Autofill can spuriously fire focus/click on segmented buttons during page load.
**Symptoms:** Sometimes the wrong CPU preset is "active" right after refresh.
**Root cause(s):** Buttons have no `name`/`autocomplete` attributes; some browsers heuristically autofill any focusable element near labels.
**How to fix:**
1. Add `autocomplete="off"` to the form/page wrapper.
2. Use `type="button"` explicitly on every `<button>`.
**Prevention / hardening:** Avoid `<form>` wrappers when controls are app-state, not form-state.
**Related:** none.

## E.UI.017 — Canvas chart drawn with NaN samples
**Trigger:** `pushChartSample` is called with `undefined` / `NaN` from a half-loaded perf snap (e.g. `g.util_gpu_pct` is missing while GPU is "available: false but reachable").
**Where:** `app.js:2196-2202` — guards with `Number.isFinite(value) ? value : 0`, but `metricMax(...)` then computes `Math.max(100, ...data, 1)` where `data` may contain `0` placeholders.
**What it means (plain English):** Lookups still work, but a chart line drops to zero whenever data is briefly missing, producing visual "spikes to floor".
**Symptoms:** GPU%/VRAM/temp chart shows fake dips when perf endpoint hiccups.
**Root cause(s):** Missing-vs-zero conflation. Loss of fidelity.
**How to fix:**
1. Use `null` as the "missing" sentinel.
2. In `drawChart`, break the polyline path at null samples (don't connect across gaps).
**Prevention / hardening:** Track per-metric `lastValid` and render gap markers.
**Related:** E.UI.024, E.UI.006.

## E.UI.018 — Donut SVG when probabilities don't sum to 1
**Trigger:** Backend sends `last_hit_probs` whose values don't sum to 1.0 (e.g. logits not soft-maxed; one class clipped).
**Where:** `app.js:1773-1804` — `renderDonut` only uses `top[1]` (the max) to compute the stroke offset.
**What it means (plain English):** The donut is driven by max probability only; if probs sum to >1, the visual is fine but the legend percentages will exceed 100% in aggregate.
**Symptoms:** Legend rows show e.g. 84.3%, 73.1%, 22.0% — sums to >100% confusing the user.
**Root cause(s):** No normalisation; relies on backend honesty.
**How to fix:**
1. Normalise: divide every value by `entries.reduce((s,[,v])=>s+v, 0)` before rendering.
2. Show a warning marker if sum is < 0.95 or > 1.05.
**Prevention / hardening:** Backend invariant: always softmax before serialising.
**Related:** E.UI.043.

## E.UI.019 — Live-frame img.src cache busting via `?t=Date.now()`
**Trigger:** Flask in debug mode emits 304 instead of 200; or a CDN caches the frame URL.
**Where:** `app.js:1513` (`img.src = "/api/live-frame?t=${Date.now()}";`), `app.js:1447`, `app.js:1580`.
**What it means (plain English):** The cache buster works, but every frame allocates a new resource entry in the browser's network log; on long-running sessions DevTools and the back-forward cache balloon.
**Symptoms:** Memory growth in long sessions; DevTools network tab unusable.
**Root cause(s):** No `Cache-Control: no-store` on backend; client-side workaround creates 4 URLs/sec.
**How to fix:**
1. Send `Cache-Control: no-store, max-age=0` from Flask on `/api/live-frame`.
2. Drop the `?t=` query param.
**Prevention / hardening:** Or switch to MJPEG `multipart/x-mixed-replace` so a single request streams forever.
**Related:** E.UI.026, E.UI.009.

## E.UI.020 — Event listener leaks on language switch
**Trigger:** User clicks language buttons many times.
**Where:** `app.js:1909-1928` — `initLanguagePicker` calls `renderSeg` which adds click handlers; on each language change `applyI18n` does NOT re-init the picker, but `refreshFpsCapControl` is called which does another `renderSeg` cycle (`app.js:1955`).
**What it means (plain English):** Some segmented controls accumulate click handlers across re-renders because `renderSeg` clears `innerHTML` (drops DOM nodes — handlers dropped with them), but the *outer* listeners attached in `applyI18n` and modals (`app.js:1816-1834`) are duplicated if `showConfirm` is called twice without reaching `cleanup`.
**Symptoms:** Confirm modal "Use anyway" eventually fires multiple times per click.
**Root cause(s):** `cleanup` correctly removes listeners on resolve, but if the modal is dismissed by other paths (e.g. page change), listeners remain.
**How to fix:**
1. Use `AbortController` per modal invocation: pass `signal` to all addEventListener calls; abort on cleanup.
**Prevention / hardening:** Centralise modal lifecycle in a class with a `destroy()` method.
**Related:** E.UI.039.

## E.UI.021 — Unhandled promise rejection in `pollStatus` / `pollPerf` / `pollPreflight`
**Trigger:** Inside the `try { ... } finally { pollStatusInflight = false; }` block, a *synchronous* DOM op throws (e.g. `$("status-pill")` is null mid-page-rebuild).
**Where:** `app.js:1534-1591`, `app.js:2058-2065`.
**What it means (plain English):** The outer try is just for cleanup; any DOM error bubbles as an uncaught promise rejection.
**Symptoms:** "Uncaught (in promise) TypeError: Cannot read properties of null" in console; status pill stops updating but polling timer keeps trying.
**Root cause(s):** Lookup helpers like `$()` return null silently; downstream code assumes elements exist.
**How to fix:**
1. Add a `window.addEventListener("unhandledrejection", ...)` that toasts a generic UI error.
2. Add null-checks in DOM update sites or use optional chaining (`$("status-pill")?.textContent = ...`).
**Prevention / hardening:** Run TypeScript or at minimum strict null checks via JSDoc.
**Related:** E.UI.005.

## E.UI.022 — Toast queue overflow
**Trigger:** Many transient errors fire (e.g. perf 500 burst) — each call to `toast()` appends a new node.
**Where:** `app.js:1099-1119`.
**What it means (plain English):** No de-dup, no max queue length. With `ttl=0` toasts (errors), they stay forever.
**Symptoms:** Top of screen fills with stacked red toasts; scrolling impossible; layout breaks.
**Root cause(s):** Append-only design.
**How to fix:**
1. Cap the toast container at 5 visible items; collapse older into a "+3 more" badge.
2. De-dup on `(type, title, msg)` — increment a counter on the existing toast instead of stacking.
**Prevention / hardening:** Fewer `ttl=0` toasts; only critical conditions should be sticky.
**Related:** E.UI.001, E.UI.038.

## E.UI.023 — Language modal blocks `init()` forever if user dismisses it via DevTools
**Trigger:** Power user `display: none`s `#lang-modal` from DevTools instead of clicking a button.
**Where:** `app.js:1186-1187` (`if (!HAS_LANG_PREF) await showFirstRunLangPicker();`).
**What it means (plain English):** `showFirstRunLangPicker()` returns a promise that ONLY resolves on a `.lang-btn` click. There's no Escape key, no timeout, no fallback.
**Symptoms:** Page is blank shell; everything below the language picker await never runs.
**Root cause(s):** No timeout or default selection.
**How to fix:**
1. Add a 30 s timer that resolves with default `"en"` if no choice is made.
2. Add `<button data-lang="en">Skip</button>` as a fallback.
3. On Escape key, resolve with default.
**Prevention / hardening:** Never block `init()` on user input — proceed in default language and let the user change later.
**Related:** E.UI.044.

## E.UI.024 — i18n key missing fallback works, but only one level deep
**Trigger:** A new key was added to `en` but not yet translated to `de`/`fr`/`es`/`ru`.
**Where:** `app.js:1083-1092` (`I18N[LANG] || I18N.en`).
**What it means (plain English):** Falls back to English correctly. But if the key is missing in BOTH the active language AND English, the literal key is shown.
**Symptoms:** UI shows raw "settings.someKey" string.
**Root cause(s):** No build-time validation of key coverage.
**How to fix:**
1. Add a script that diffs `I18N.en` keys against each other locale and fails CI.
2. At runtime, log to console when fallback to key happens.
**Prevention / hardening:** Centralise key registry; lint for unused keys.
**Related:** E.UI.041.

## E.UI.025 — Narrow viewport breaks the segmented controls
**Trigger:** Window narrower than 360 px; mobile portrait.
**Where:** `style.css:828` (`.fps-cap-ctrl .seg-control { min-width: 320px; }`), `style.css:1061-1066` (`min-width: 360px`).
**What it means (plain English):** The segmented controls have a hard min-width that exceeds the viewport.
**Symptoms:** Horizontal scrollbar on the entire page; controls bleed off the right edge.
**Root cause(s):** Min-width was set for desktop without a mobile fallback. Media queries at 760 px exist but only zero out `min-width`, not the inner `seg-btn` widths.
**How to fix:**
1. Add `@media (max-width: 480px)` to make seg-btn `flex: 1 1 auto` and wrap.
2. Audit `min-width: 360px` sites for mobile.
**Prevention / hardening:** Use `clamp()` instead of fixed `min-width`.
**Related:** E.UI.025a, E.UI.040.

## E.UI.026 — Hits/min ticker (legacy) before init
**Trigger:** The old "Hits/min" mini-stat was removed from the user interface but partial code or templates may still reference `ms-hpm`.
**Where:** `app.js:1567` (comment "Hits/min removed per user").
**What it means (plain English):** If any HTML element still references `ms-hpm`, JS silently no-ops because `$()` returns null. But should the element be re-added without wiring the corresponding `setBar` call, it would render as "—" forever.
**Symptoms:** Phantom "—" mini-stat, indicating dead code.
**Root cause(s):** Inconsistent removal.
**How to fix:**
1. Audit `index.html` for `ms-hpm` references.
2. Remove the legacy template fragment if present.
**Prevention / hardening:** Strip dead i18n keys and DOM stubs together.
**Related:** E.UI.024.

## E.UI.027 — Status transition error→idle missing toast
**Trigger:** Worker crashes (status="error"), then user clicks STOP (status="idle"). The transition `error → idle` is not handled.
**Where:** `app.js:1600-1612` — only handles `→ running` and `running → idle`.
**What it means (plain English):** No toast confirms the user that the failed worker was successfully stopped; only the previous `lastError` toast remains.
**Symptoms:** User suspects STOP didn't work because nothing told them otherwise.
**Root cause(s):** Missing transition case.
**How to fix:**
1. Add `if (to === "idle" && from === "error") toast("info", "Stopped after error", "...");`.
**Prevention / hardening:** Use a transition matrix object instead of conditionals.
**Related:** E.UI.005.

## E.UI.028 — Browser tab in background → setInterval throttled to ≤1 Hz
**Trigger:** User switches to another tab.
**Where:** All `setInterval` users (`pollStatus` 500 ms, `pollPerf` 600 ms, live-frame 250 ms).
**What it means (plain English):** Modern browsers clamp background-tab timers to 1 Hz min; on suspended tabs even longer.
**Symptoms:** Returning to the tab shows a stale snapshot; chart line shows a long flat segment.
**Root cause(s):** Inherent browser behavior; nothing in the app compensates.
**How to fix:**
1. Use `Page Visibility API`: pause polling on `hidden`, restart with an immediate refresh on `visible`.
2. Show "stale — last updated Xs ago" badge if interval missed.
**Prevention / hardening:** SSE / WebSocket would not be throttled the same way.
**Related:** E.UI.014, E.UI.009.

## E.UI.029 — Live-feed `img.onload` / `img.onerror` race during monitor switch
**Trigger:** User rapidly clicks between monitors. Multiple `refreshPreview` calls overwrite `img.src`.
**Where:** `app.js:1445-1459`.
**What it means (plain English):** The first request might still be in flight when the second triggers; whichever finishes last wins, but `onload`/`onerror` references are overwritten on every assignment, so the LATE reply may flip an outdated UI state.
**Symptoms:** Picking monitor 2 then quickly monitor 3 may show monitor 2's frame because monitor 3 errored first.
**Root cause(s):** No request id / generation counter.
**How to fix:**
1. Track a `previewGen` integer; capture it in closure; ignore handlers from stale generations.
**Prevention / hardening:** AbortController + fetch(blob) pattern (see E.UI.007).
**Related:** E.UI.007.

## E.UI.030 — `aria-expanded` keyboard nav incomplete
**Trigger:** Keyboard-only user pressing Tab → Enter on the preflight toggle.
**Where:** `index.html:132` (`<button class="preflight-toggle" aria-expanded="false">`); `app.js:1746-1755`.
**What it means (plain English):** `aria-expanded` is set, but there's no `aria-controls` wiring on Enter (added implicitly by the click handler), AND the focus does not move to the first item after expanding.
**Symptoms:** Screen-reader users hear "expanded" but their reading cursor stays on the toggle.
**Root cause(s):** Missing focus management.
**How to fix:**
1. After expanding, call `list.querySelector("li")?.focus()`.
2. Make `<li>` items `tabindex="0"`.
**Prevention / hardening:** Run an axe-core scan in CI.
**Related:** E.UI.031, E.UI.040.

## E.UI.031 — `severity-warn` color contrast on light themes (we are dark-only, but…)
**Trigger:** User overrides browser's "force dark mode off" or applies a custom user stylesheet.
**Where:** `style.css:270`, `style.css:286-288`, `style.css:346`, `style.css:361` — uses `var(--amber)` on the dark surface.
**What it means (plain English):** App is locked dark; if a user CSS or browser setting forces light text, amber-on-light becomes unreadable.
**Symptoms:** Warn banner becomes invisible white-on-white.
**Root cause(s):** No `@media (prefers-color-scheme: light)` fallback; colors are hardcoded.
**How to fix:**
1. Document explicitly that the UI is dark-only; set `color-scheme: dark` on `:root`.
2. Add `prefers-color-scheme: light` overrides for at least banner colors.
**Prevention / hardening:** Pin `<meta name="color-scheme" content="dark">` in `<head>`.
**Related:** E.UI.040.

## E.UI.032 — `/api/start` payload validation client side is too thin
**Trigger:** User has model selected, monitor selected, but `cfg.cpu_affinity_mask` accidentally `undefined` (older state from before the fix).
**Where:** `app.js:1463-1494`.
**What it means (plain English):** Only `cfg.model` and `cfg.monitor_id` are validated; everything else is sent as-is.
**Symptoms:** Backend returns 400 "invalid affinity mask"; user gets a vague error toast with the server message.
**Root cause(s):** Validation is server-side only.
**How to fix:**
1. Validate `nb_cpu_threads` is an int 1..N.
2. Validate `cpu_affinity_mask` is an int and a subset of valid mask.
3. Validate `hit_ante` is between 0 and 100.
**Prevention / hardening:** Define a JSON schema (Zod-style) shared with backend.
**Related:** E.UI.001.

## E.UI.033 — Monitor list staleness after hotplug
**Trigger:** User plugs in/unplugs an external monitor while the app is running.
**Where:** `app.js:1416-1443` — `populateMonitors` is called once at init; only refreshed via `refreshMonitors` if `monitoring_lib` changes.
**What it means (plain English):** A newly plugged monitor isn't shown in the dropdown; an unplugged one stays visible.
**Symptoms:** User selects a monitor that no longer exists → preview fails (E.UI.007).
**Root cause(s):** No periodic refresh; no display-change event listener.
**How to fix:**
1. Add a refresh button next to the dropdown.
2. Listen to `window.matchMedia("(min-resolution: ...)").addEventListener("change", refreshMonitors)` as a heuristic.
3. On preview error, auto-refresh the monitor list.
**Prevention / hardening:** Re-fetch monitors any time the preview fails.
**Related:** E.UI.007.

## E.UI.034 — P-core warn modal acknowledgement reset on language switch
**Trigger:** User picks an unpinned hybrid CPU preset, dismisses the modal with "Use anyway" → `pCoreWarnAcknowledged = true`. Then switches language. Then re-picks the preset.
**Where:** `app.js:1152` (declared once at module scope), `app.js:1281-1311`.
**What it means (plain English):** Actually `pCoreWarnAcknowledged` is module-scoped and survives `applyI18n()` — so this is currently NOT reset. But the *modal body text* is composed at modal-open time using `t(...)` calls. If the user opens the modal, switches language without confirming, and confirms in the new language — they confirmed text they didn't read.
**Symptoms:** Confused users; localisation feels half-broken.
**Root cause(s):** Modal body is not re-rendered when language changes mid-modal.
**How to fix:**
1. Either disable language picker while a modal is open, or close-and-reopen the modal on language change.
**Prevention / hardening:** Track open modals in a registry that gets re-rendered on `applyI18n`.
**Related:** E.UI.020, E.UI.024.

## E.UI.035 — FPS cap segmented control on Linux
**Trigger:** App running on Linux. Backend returns `ini_status="not_windows"` from `/api/fps-advice`.
**Where:** `app.js:1942-1946`.
**What it means (plain English):** The control collapses to a hint; the backend status string is shown raw in parens (e.g. `(not_windows)`).
**Symptoms:** User sees the cryptic `(not_windows)` next to the FPS-cap control.
**Root cause(s):** No translation for `ini_status` values; they're emitted verbatim.
**How to fix:**
1. Map known statuses to i18n keys (`fpsCap.status.notWindows`, etc.).
2. Hide the control entirely on Linux instead of showing a disabled hint.
**Prevention / hardening:** Stable enum for status, never raw.
**Related:** E.UI.036.

## E.UI.036 — FpsCap status text after refresh shows stale value
**Trigger:** User sets a new cap, toast confirms, but `refreshFpsCapControl()` is recursively called inside the click handler.
**Where:** `app.js:1955-1968` (`refreshFpsCapControl();` invoked inside the success branch).
**What it means (plain English):** The recursive call re-reads the `.ini` file via `/api/fps-advice`. If the backend hasn't flushed the write yet (eventual consistency on some FSes), the status text reads the OLD value.
**Symptoms:** Toast says "Set to 90 fps" but the status row still shows "Currently capped at 60".
**Root cause(s):** Race between write-then-read.
**How to fix:**
1. Pass the just-written value to the status update directly instead of round-tripping.
2. Or add a small `setTimeout(refreshFpsCapControl, 250)` to give the FS time.
**Prevention / hardening:** Backend should return the new cap as the response of `/api/set-fps-cap` so the client can update without re-reading.
**Related:** E.UI.035.

## E.UI.037 — Donut sub label undefined when desc and top entry are both falsy
**Trigger:** `last_hit_probs` is `{}` (empty object) but truthy; `entries[0]` is `undefined`.
**Where:** `app.js:1773-1788` — `if (!top) return;` guards top, but `desc` is then used: `$("donut-sub").textContent = desc || top[0];`.
**What it means (plain English):** With the early return on `!top`, the label is safe. But if probs has exactly one entry whose key is empty string, the sub label renders as empty — "" not "—".
**Symptoms:** Donut center label looks broken (blank) when it should be "—" or fallback.
**Root cause(s):** Falsy collision between empty string and "no data".
**How to fix:**
1. Always render `desc || top[0] || "—"` as a triple fallback.
**Prevention / hardening:** Backend should never emit empty class labels.
**Related:** E.UI.018.

## E.UI.038 — Toast multiline body truncates due to `textContent` + CSS
**Trigger:** Boot toast composed with `\n`: `toast("info", t("toast.systemDetected"), `${cpuLine}\n${gpuLine}`);` (`app.js:1404`).
**Where:** `app.js:1110-1111` (`textContent` preserves \n) + CSS `.toast-msg` likely doesn't have `white-space: pre-line`.
**What it means (plain English):** Newlines in the message render as a single space because default CSS collapses whitespace.
**Symptoms:** "CPU summary GPU summary" run together on one line.
**Root cause(s):** CSS doesn't honour `\n`.
**How to fix:**
1. Add `white-space: pre-line;` to `.toast-msg`.
2. Or split into two toasts.
**Prevention / hardening:** Standardise on a `Toast.body = string[]` API and render each line as its own `<div>`.
**Related:** E.UI.022.

## E.UI.039 — Per-core grid not redrawn on tab switch
**Trigger:** User switches from "Performance Monitor" tab back to "Open" then back to "Perf".
**Where:** `app.js:2018-2042` — `initCpuCoresGrid` is called once at init from `init()` (`app.js:1376`); not re-run on tab switch.
**What it means (plain English):** The fill heights stay at whatever they were when the tab was last visible; CSS transitions can produce flicker.
**Symptoms:** Stale fills; first frame on tab return shows last-known values, then jumps.
**Root cause(s):** Per-core grid is populated lazily by `renderCpuPerf`, but only when `pollPerf` fires (every 600 ms). The visible-tab transition happens before that.
**How to fix:**
1. On nav switch to "perf", trigger an immediate `pollPerf()`.
2. Already done for the chart canvas (`requestAnimationFrame(drawChart)`); apply the same to perf data.
**Prevention / hardening:** Add a `onPageEnter("perf", ...)` hook system.
**Related:** E.UI.006.

## E.UI.040 — Nav menu items have no keyboard activation
**Trigger:** User presses Enter while focused on a `.nav-item`.
**Where:** `app.js:1850-1867` — only `click` listener.
**What it means (plain English):** `<button>` elements would auto-fire click on Enter; if these are `<div>`s with `role="button"`, they need explicit keydown handling.
**Symptoms:** Keyboard-only user can't change pages.
**Root cause(s):** Depends on actual element type; unverified without scanning further.
**How to fix:**
1. Confirm `nav-item` is a `<button>`.
2. If a `<div>`, add `tabindex="0"` and a keydown handler for Enter/Space.
**Prevention / hardening:** Use semantic `<button>` for any clickable.
**Related:** E.UI.030.

## E.UI.041 — i18n value containing unknown placeholder leaks `{var}` text
**Trigger:** Translator forgot to update a key after a placeholder rename.
**Where:** `app.js:1086-1090` — `replaceAll` only replaces declared vars; missing ones stay as `{x}`.
**What it means (plain English):** UI shows literal `{cap}` because a translator left it untranslated.
**Symptoms:** Cosmetic but confusing.
**Root cause(s):** No template strict-mode.
**How to fix:**
1. After replacement, regex-search for `\{[a-zA-Z_]+\}` and warn in console.
**Prevention / hardening:** Use ICU MessageFormat with strict variable matching.
**Related:** E.UI.024.

## E.UI.042 — `hit_count` casts to `0` falsely when backend sends `null`
**Trigger:** Backend hasn't initialised counter yet; sends `hit_count: null`.
**Where:** `app.js:1557` (`snap.hit_count || 0`), `app.js:1569`.
**What it means (plain English):** `null || 0` → 0. Correct here, but `0 || 0` → 0 too (doesn't distinguish "unknown" from "zero").
**Symptoms:** UI shows "0 hits" even when status is "starting" and we don't know yet.
**Root cause(s):** Coalesce-vs-fallback semantics.
**How to fix:**
1. Use `??` instead of `||` for numeric defaults: `snap.hit_count ?? 0`.
2. When status is "starting", show "—" instead of 0.
**Prevention / hardening:** Lint rule against `||` for numeric defaults.
**Related:** E.UI.044.

## E.UI.043 — Donut color thresholds are hard-coded
**Trigger:** Backend's confidence distribution shifts (new model, different temperature scale).
**Where:** `app.js:1782-1785` (0.85 / 0.6 cutoffs).
**What it means (plain English):** Color buckets stop being useful if model probabilities cluster differently.
**Symptoms:** All hits show "low confidence" green-warn-color even though the model is very confident.
**Root cause(s):** Magic numbers.
**How to fix:**
1. Read thresholds from `/api/init` config.
2. Make them user-tunable in Settings.
**Prevention / hardening:** Compute thresholds dynamically from a sliding window of recent hits.
**Related:** E.UI.018.

## E.UI.044 — Boot race: `init()` references DOM before `DOMContentLoaded`
**Trigger:** Cached `app.js` loads before the templated `index.html` has parsed (synchronous import order accident).
**Where:** `app.js:2399-2402` — wrapped in `DOMContentLoaded` listener so this is currently safe. But `app.js:1095` (`document.getElementById("toasts")`) runs at IIFE top-level — IF the script tag is moved to `<head>` without `defer`, this returns null.
**What it means (plain English):** The toast container is captured at module load; if the script is loaded before the body, `toastEl === null`.
**Symptoms:** First call to `toast(...)` throws `Cannot read properties of null (reading 'appendChild')`.
**Root cause(s):** Top-level DOM access in IIFE.
**How to fix:**
1. Move `const toastEl = ...` lookup inside `toast()` (resolve lazily).
2. Or ensure `<script>` tag has `defer` attribute.
**Prevention / hardening:** Audit IIFE top-level for any `document.*` calls.
**Related:** E.UI.001.

## E.UI.045 — Sticky `lastError` swallows recurring distinct errors
**Trigger:** Worker emits the same error string twice in quick succession (e.g. "monitor 0 not found" then resolves, then "monitor 0 not found" again 30 s later).
**Where:** `app.js:1543-1548` — `if (snap.error && snap.error !== lastError)`.
**What it means (plain English):** Identical error messages back-to-back are suppressed. If the error briefly clears in between (`lastError = null` reset) the second occurrence DOES toast — but only if the snap had `!snap.error` between the two occurrences.
**Symptoms:** Recurring error condition only toasts the first time per unique-string-burst.
**Root cause(s):** De-dup is by exact string equality.
**How to fix:**
1. De-dup with a 30 s rolling window keyed by error string + a count badge.
**Prevention / hardening:** Backend emits structured error codes, not free text.
**Related:** E.UI.022.

## E.UI.046 — `applyI18n` re-runs heavy work on every language click
**Trigger:** User cycles through languages.
**Where:** `app.js:1986-2011`.
**What it means (plain English):** `applyI18n` re-invokes `refreshFpsCapControl` (which fetches `/api/fps-advice` again), `renderGpuPerf`, `renderCpuPerf`, `renderInfoPage` and `drawChart`. Each click triggers a network round-trip.
**Symptoms:** Network burst on language switch; UI flicker.
**Root cause(s):** No diffing — full re-render.
**How to fix:**
1. Cache last `/api/fps-advice` result and apply translations to it without refetching.
2. Throttle language clicks (debounce 300 ms).
**Prevention / hardening:** Separate i18n re-render from data refresh.
**Related:** E.UI.020.

## E.UI.047 — Chart drawn into a `display:none` canvas yields zero rect
**Trigger:** User opens app with the Performance Monitor tab not active; `initPerfChart` calls `drawChart()` immediately.
**Where:** `app.js:2236-2240` — `drawChart` early-returns if `rect.width < 1`. Safe.
**What it means (plain English):** The early return is correct, but `setActiveMetric` and `pushChartSample` calls during this window throw away samples that never made it to the canvas.
**Symptoms:** Chart appears empty for the first ~600 ms after the user finally navigates to the Perf tab.
**Root cause(s):** No replay of buffered data on first paint.
**How to fix:**
1. On nav switch to "perf", call `drawChart()` after `requestAnimationFrame`.
2. The `chartData` arrays are already populated, so this is mostly cosmetic.
**Prevention / hardening:** Use ResizeObserver instead of `window.resize`.
**Related:** E.UI.039.

## E.UI.048 — `parseInt(sel.value, 10)` returns NaN when monitor list is empty
**Trigger:** No monitors detected.
**Where:** `app.js:1429-1432`.
**What it means (plain English):** If `sel.value === ""`, parseInt returns NaN; `cfg.monitor_id = NaN`. Subsequent `cfg.monitor_id == null` (`app.js:1446`) is FALSE for NaN → preview is requested with `monitor_id=NaN`.
**Symptoms:** `/api/preview?monitor_id=NaN` returns 400; preview shows error placeholder.
**Root cause(s):** `== null` doesn't catch NaN.
**How to fix:**
1. Use `Number.isFinite(cfg.monitor_id)` as the guard.
2. After `populateMonitors`, if `monitors.length === 0`, set `cfg.monitor_id = null` explicitly.
**Prevention / hardening:** Treat all `cfg.*` values as strictly typed.
**Related:** E.UI.033.

## E.UI.049 — Live-poll timer accumulates if `startLivePoll` called twice
**Trigger:** User clicks RUN, then hits the keyboard shortcut, then clicks RUN again rapidly (status briefly "stopping" → race).
**Where:** `app.js:1509-1515`.
**What it means (plain English):** The `if (livePollTimer) return;` guard prevents duplicate timers — correct. But `stopLivePoll` clears the timer without disabling `img.onload` handlers.
**Symptoms:** A pending image load can fire after `stopLivePoll`, re-showing the last frame.
**Root cause(s):** Image events outlive the timer.
**How to fix:**
1. On `stopLivePoll`, also clear `img.src` and remove `onload`/`onerror`.
**Prevention / hardening:** Use a generation counter.
**Related:** E.UI.029.

## E.UI.050 — Unhandled rejection on `set-fps-cap` failure does not restore UI state
**Trigger:** `/api/set-fps-cap` returns 403 (read-only INI file).
**Where:** `app.js:1955-1968` — toasts the error but the segmented button remains "active" (the click handler in `renderSeg` already moved the highlight before awaiting).
**What it means (plain English):** UI shows the new cap as "selected" even though backend rejected the write.
**Symptoms:** User thinks the cap was applied; reload reveals it wasn't.
**Root cause(s):** Optimistic UI without rollback.
**How to fix:**
1. On error, re-call `refreshFpsCapControl()` to repaint the actual current cap.
**Prevention / hardening:** Pessimistic UI (don't change the active class until the await resolves).
**Related:** E.UI.036.

## E.UI.051 — `lastHitTimestamp` comparison fails on backend clock skew
**Trigger:** Backend re-imports model and resets `last_hit_at` to a timestamp earlier than the previous one.
**Where:** `app.js:1577-1587`.
**What it means (plain English):** `snap.last_hit_at !== lastHitTimestamp` is true even if the new timestamp is older — UI re-renders the donut with what may be older data.
**Symptoms:** Donut briefly shows stale hit info; cosmetic only.
**Root cause(s):** Equality-not-monotonic.
**How to fix:**
1. Use `>` comparison: only update if `snap.last_hit_at > lastHitTimestamp`.
**Prevention / hardening:** Backend should send monotonic counters in addition to wall-clock.
**Related:** E.UI.018.

## E.UI.052 — Sticky preflight banner dismissal vanishes on hard reload
**Trigger:** User dismisses warn banner; reloads the page.
**Where:** `preflightDismissedSummary` lives only in JS memory (`app.js:1660`).
**What it means (plain English):** Dismissal does not persist across reloads.
**Symptoms:** Banner re-appears on every refresh — annoying for known-warn states.
**Root cause(s):** No persistence.
**How to fix:**
1. Persist `(severity, hash-of-issues)` in localStorage; only re-show on a different hash or higher severity.
**Prevention / hardening:** Combine with E.UI.013 safeStorage.
**Related:** E.UI.008.

## E.UI.053 — Window resize handler not debounced
**Trigger:** User drags the window edge.
**Where:** `app.js:2232` (`window.addEventListener("resize", drawChart)`).
**What it means (plain English):** Every pixel of resize redraws the canvas (60+ Hz on good hardware).
**Symptoms:** CPU spike during window resize; visible in low-power devices.
**Root cause(s):** No debounce.
**How to fix:**
1. Wrap `drawChart` in `requestAnimationFrame` with a guard, or use `setTimeout`-based debouncer (60 ms).
2. Use ResizeObserver on the canvas's parent for more accurate triggers.
**Prevention / hardening:** Document the redraw budget.
**Related:** E.UI.047.

## E.UI.054 — Preflight 200 with malformed schema
**Trigger:** Backend bug returns `{}` for `/api/preflight` instead of the expected `{summary, issues}`.
**Where:** `app.js:1686-1717`.
**What it means (plain English):** `issues` defaults to `[]` (safe), `sev` is `undefined`. The early return at line 1693 then matches and hides the banner — silently masking a real backend bug.
**Symptoms:** Preflight banner never shown even though backend is broken.
**Root cause(s):** Defensive defaults swallow signal.
**How to fix:**
1. Distinguish "absent advice" from "ok": require explicit `summary === "ok"`.
2. Log a console warning when schema is unexpected.
**Prevention / hardening:** JSON schema validation.
**Related:** E.UI.008.
