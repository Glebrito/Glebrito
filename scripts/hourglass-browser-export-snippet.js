// Hourglass — exportar mm no navegador (DevTools → Sources → Snippets → New → colar → Run)
// Cópia canônica no Agent Store: scripts/hourglass-browser-export-snippet.js

const FROM = "2025-04-01";
const TO = "2026-12-31";
const LGROUP = 43741;

const xsrf = document.cookie.match(/X-Hourglass-XSRF-Token=([^;]+)/)?.[1];
if (!xsrf) {
  throw new Error("Sem X-Hourglass-XSRF-Token no cookie — faça login e recarregue a página.");
}

const hdrs = {
  "X-Hourglass-XSRF-Token": xsrf,
  Accept: "application/json",
};
const postHdrs = {
  ...hdrs,
  "Content-Type": "application/json",
};
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
    console.warn("POST scheduling/users falhou", e);
  }
  try {
    const r2 = await fetch(`${base}/fsreport/startup`, {
      headers: hdrs,
      credentials: "include",
    });
    if (r2.ok) return r2.json();
  } catch (e) {
    console.warn("GET fsreport/startup falhou", e);
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

const payload = {
  meta: {
    from: FROM,
    to: TO,
    lgroup: LGROUP,
    fetched_at: new Date().toISOString(),
    source: "hourglass-browser-export-snippet.js",
  },
  meetings,
  schedules,
  events,
  privileges,
  users,
};

const blob = new Blob([JSON.stringify(payload, null, 2)], {
  type: "application/json",
});
const a = document.createElement("a");
a.href = URL.createObjectURL(blob);
a.download = "mm-export.json";
a.click();
console.log("Download mm-export.json iniciado", users ? "(com users)" : "(sem users — nomes via privileges/histórico)");
