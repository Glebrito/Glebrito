// ==UserScript==
// @name         Colih — Atualizar Supabase (Hourglass)
// @namespace    glebrito-colih
// @version      1.0.1
// @description  Um botão no Hourglass envia o export MM ao painel local Colih (127.0.0.1).
// @match        https://app.hourglass-app.com/*
// @run-at       document-end
// @grant        none
// ==/UserScript==

(function colihHourglassUserscript() {
  "use strict";

  if (window.__colihHourglassBoot) return;
  window.__colihHourglassBoot = true;

  const FROM = "2025-04-01";
  const TO = "2026-12-31";
  const LGROUP = 43741;
  const COLIH_IMPORT = "http://127.0.0.1:8765/import-json";
  const PANEL_HINT =
    "Painel offline. Execute scripts\\iniciar-painel.bat ou: python -m colih_hourglass serve --env-file scripts\\hourglass.env";

  const UI_ID = "colih-hg-root";

  function ensureStyles() {
    if (document.getElementById("colih-hg-style")) return;
    const style = document.createElement("style");
    style.id = "colih-hg-style";
    style.textContent = `
      #${UI_ID} {
        all: initial;
        font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
        position: fixed;
        z-index: 2147483646;
        right: 18px;
        bottom: 18px;
        display: flex;
        flex-direction: column;
        align-items: flex-end;
        gap: 10px;
        pointer-events: none;
      }
      #${UI_ID} * { box-sizing: border-box; pointer-events: auto; }
      #colih-hg-btn {
        border: none;
        border-radius: 999px;
        padding: 12px 20px;
        font-size: 15px;
        font-weight: 650;
        color: #fff;
        background: linear-gradient(135deg, #2563eb, #1d4ed8);
        box-shadow: 0 8px 24px rgba(37, 99, 235, 0.45);
        cursor: pointer;
        transition: transform 0.15s ease, opacity 0.15s ease;
      }
      #colih-hg-btn:hover:not(:disabled) { transform: translateY(-1px); }
      #colih-hg-btn:disabled { opacity: 0.72; cursor: wait; }
      #colih-hg-btn .colih-spin {
        display: inline-block;
        width: 1em;
        height: 1em;
        margin-right: 0.45em;
        vertical-align: -0.15em;
        border: 2px solid rgba(255,255,255,0.35);
        border-top-color: #fff;
        border-radius: 50%;
        animation: colih-spin 0.7s linear infinite;
      }
      @keyframes colih-spin { to { transform: rotate(360deg); } }
      #colih-hg-toast {
        max-width: min(22rem, calc(100vw - 2rem));
        padding: 10px 14px;
        border-radius: 10px;
        font-size: 13px;
        line-height: 1.45;
        color: #111;
        background: #fff;
        border: 1px solid #e5e7eb;
        box-shadow: 0 10px 30px rgba(0,0,0,0.12);
        display: none;
      }
      #colih-hg-toast.ok { border-color: #86efac; background: #f0fdf4; }
      #colih-hg-toast.err { border-color: #fecaca; background: #fef2f2; }
      #colih-hg-toast.show { display: block; }
    `;
    document.head.appendChild(style);
  }

  function mountUi() {
    if (document.getElementById(UI_ID)) {
      window.__colihHourglassUi = true;
      return true;
    }
    const parent = document.body;
    if (!parent) return false;

    ensureStyles();
    const root = document.createElement("div");
    root.id = UI_ID;
    root.setAttribute("aria-live", "polite");
    root.innerHTML =
      '<div id="colih-hg-toast" role="status"></div>' +
      '<button type="button" id="colih-hg-btn">Atualizar Supabase</button>';
    parent.appendChild(root);

    const btn = root.querySelector("#colih-hg-btn");
    const toast = root.querySelector("#colih-hg-toast");
    btn.addEventListener("click", () => runUpdate(btn, toast));
    window.__colihHourglassUi = true;
    return true;
  }

  function watchForSpaRemoval() {
    if (!document.body || window.__colihHourglassSpaWatch) return;
    window.__colihHourglassSpaWatch = true;
    const obs = new MutationObserver(() => {
      if (!document.getElementById(UI_ID)) mountUi();
    });
    obs.observe(document.body, { childList: true });
  }

  function scheduleMountWithRetries() {
    const delays = [0, 1000, 3000];
    let step = 0;

    function attempt() {
      if (mountUi()) {
        watchForSpaRemoval();
        return;
      }
      step += 1;
      if (step < delays.length) {
        setTimeout(attempt, delays[step]);
      }
    }

    setTimeout(attempt, delays[0]);
  }

  function showToast(el, text, kind) {
    el.textContent = text;
    el.className = kind === "ok" ? "ok show" : kind === "err" ? "err show" : "show";
  }

  function hideToast(el) {
    el.className = "";
    el.textContent = "";
  }

  async function fetchHourglassPayload() {
    const xsrf = document.cookie.match(/X-Hourglass-XSRF-Token=([^;]+)/)?.[1];
    if (!xsrf) {
      throw new Error("Faça login no Hourglass e recarregue a página.");
    }

    const hdrs = {
      "X-Hourglass-XSRF-Token": xsrf,
      Accept: "application/json",
    };
    const postHdrs = { ...hdrs, "Content-Type": "application/json" };
    const range = `${FROM}_${TO}`;
    const base = "/api/v0.2";

    async function fetchUsersDirectory() {
      try {
        const r = await fetch(`${base}/scheduling/users?lgroup=${LGROUP}`, {
          method: "POST",
          headers: postHdrs,
          credentials: "include",
          body: "{}",
        });
        if (r.ok) return r.json();
      } catch (e) {
        console.warn("Colih: POST scheduling/users falhou", e);
      }
      try {
        const r2 = await fetch(`${base}/fsreport/startup`, {
          headers: hdrs,
          credentials: "include",
        });
        if (r2.ok) return r2.json();
      } catch (e) {
        console.warn("Colih: GET fsreport/startup falhou", e);
      }
      return null;
    }

    const [meetings, schedules, events, privileges, users] = await Promise.all([
      fetch(`${base}/scheduling/mm/meeting/${range}?lgroup=${LGROUP}&no_subs=true`, {
        headers: hdrs,
        credentials: "include",
      }).then((r) => {
        if (!r.ok) throw new Error(`meeting HTTP ${r.status}`);
        return r.json();
      }),
      fetch(`${base}/scheduling/mm/schedule/${range}?lgroup=${LGROUP}`, {
        headers: hdrs,
        credentials: "include",
      }).then((r) => {
        if (!r.ok) throw new Error(`schedule HTTP ${r.status}`);
        return r.json();
      }),
      fetch(`${base}/scheduling/events/${range}?lgroup=${LGROUP}`, {
        headers: hdrs,
        credentials: "include",
      }).then((r) => (r.ok ? r.json() : [])),
      fetch(`${base}/scheduling/users/privileges?lgroup=${LGROUP}`, {
        headers: hdrs,
        credentials: "include",
      }).then((r) => {
        if (!r.ok) throw new Error(`privileges HTTP ${r.status}`);
        return r.json();
      }),
      fetchUsersDirectory(),
    ]);

    return {
      meta: {
        from: FROM,
        to: TO,
        lgroup: LGROUP,
        fetched_at: new Date().toISOString(),
        source: "hourglass-colih-userscript.js",
      },
      meetings,
      schedules,
      events,
      privileges,
      users,
    };
  }

  async function postToColih(payload) {
    const r = await fetch(COLIH_IMPORT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const info = await r.json().catch(() => ({}));
    if (!r.ok) {
      const msg = info.error || info.message || `HTTP ${r.status}`;
      throw new Error(msg);
    }
    return info;
  }

  function isLikelyOfflineError(err) {
    const m = String(err && err.message ? err.message : err).toLowerCase();
    return (
      m.includes("failed to fetch") ||
      m.includes("networkerror") ||
      m.includes("load failed") ||
      m.includes("connection refused")
    );
  }

  async function runUpdate(btn, toast) {
    hideToast(toast);
    const idleLabel = "Atualizar Supabase";
    btn.disabled = true;
    btn.innerHTML = '<span class="colih-spin" aria-hidden="true"></span>Atualizando…';
    showToast(toast, "Buscando dados no Hourglass…", "info");

    try {
      const payload = await fetchHourglassPayload();
      if (!payload.users) {
        throw new Error(
          "Hourglass não devolveu o cadastro (users). Recarregue a página, confira o login e tente de novo.",
        );
      }
      showToast(toast, "Enviando ao painel Colih…", "info");
      const info = await postToColih(payload);
      const stats = info.result && info.result.stats ? JSON.stringify(info.result.stats) : "";
      showToast(
        toast,
        info.message || "Importado no Colih." + (stats ? " " + stats : ""),
        "ok",
      );
    } catch (err) {
      console.error("Colih Hourglass", err);
      if (isLikelyOfflineError(err)) {
        showToast(toast, PANEL_HINT, "err");
      } else {
        showToast(toast, String(err.message || err), "err");
      }
    } finally {
      btn.disabled = false;
      btn.textContent = idleLabel;
    }
  }

  scheduleMountWithRetries();
})();
