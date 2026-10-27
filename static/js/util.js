// Shared helpers: API access, routing state, HTML formatting.

function storedAccount() {
  try { return localStorage.getItem("hexbrowser.account") || ""; } catch { return ""; }
}

export const state = {
  meta: null,
  accounts: [],
  account: storedAccount(),
  renderSeq: 0,
};

/** Start a view render; the returned check is false once a newer render began. */
export function beginRender() {
  const seq = ++state.renderSeq;
  return () => seq === state.renderSeq;
}

export async function api(path, params = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== null && v !== undefined && v !== false) url.searchParams.set(k, v);
  }
  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* not json */ }
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.json();
}

// ---- routing: #!/view?key=value
export function parseHash() {
  const raw = location.hash.replace(/^#!?\/?/, "");
  const [path, query = ""] = raw.split("?");
  return { view: path || "cards", params: Object.fromEntries(new URLSearchParams(query)) };
}

export function hashFor(view, params) {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null));
  const s = q.toString();
  return `#!/${view}${s ? "?" + s : ""}`;
}

/** Update the URL; replace=true for typing so history is not flooded. */
export function navigate(view, params, replace = false) {
  const h = hashFor(view, params);
  if (h === location.hash) return;
  if (replace) {
    history.replaceState(null, "", h);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    location.hash = h;
  }
}

// ---- formatting
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

export const SHARDS = ["Blood", "Diamond", "Ruby", "Sapphire", "Wild"];

export function thresholdPips(threshold) {
  if (!threshold) return "";
  return Object.entries(threshold).map(([color, n]) =>
    `<span class="pip pip-${esc(color.toLowerCase())}" title="${esc(color)}">${n > 1 ? n : ""}</span>`
  ).join("");
}

export const SWORD = `<svg viewBox="0 0 24 24"><path d="M14.5 3 21 3 21 9.5 11 19.5 8.5 17 18.5 7 17 5.5 7 15.5 4.5 13Z M5 16l3 3-2.5 2.5L3 19Z" fill="currentColor"/></svg>`;
export const SHIELD = `<svg viewBox="0 0 24 24"><path d="M12 2 20 5v6c0 5-3.5 9-8 11-4.5-2-8-6-8-11V5Z" fill="currentColor"/></svg>`;

const TOKEN_ICONS = {
  ATK: `<span class="tok-icon" title="Attack">${SWORD}</span>`,
  DEF: `<span class="tok-icon" title="Defense">${SHIELD}</span>`,
  ARROWR: "→",
  ACT: `<span class="tok-icon act" title="Activate">↻</span>`,
};

/** Card/game text: keeps <b>/<i>, turns <p> into line breaks and [TOKENS] into icons or chips. */
export function gameText(text) {
  let s = esc(text);
  s = s.replace(/&lt;p&gt;/gi, "<br>").replace(/&lt;(\/?)(b|i)&gt;/gi, "<$1$2>");
  s = s.replace(/\[([A-Z0-9 +\-\/]+)\]/g, (m, tok) => {
    const shard = SHARDS.find(x => x.toUpperCase() === tok);
    if (shard) return `<span class="pip pip-${shard.toLowerCase()}" title="${shard}"></span>`;
    if (TOKEN_ICONS[tok]) return TOKEN_ICONS[tok];
    if (/^\d+$/.test(tok)) return `<span class="tok-num" title="Cost ${tok}">${tok}</span>`;
    return `<span class="tok">${tok}</span>`;
  });
  return s.replace(/\\n/g, "<br>");
}

export function artUrl(ref, size = "thumb") {
  return ref ? `/art/${ref}?size=${size}` : "/art/none/none";
}

export const OBTAINABLE_LABEL = {
  yes: "Obtainable on this server",
  unknown: "Unclear whether obtainable on this server",
  no: "Not obtainable on this server (historical)",
};

export function ownedBadge(item) {
  if (item.owned === undefined) return "";
  const max = item.max_copies || 1;
  const cls = item.owned === 0 ? "none" : item.owned >= max ? "full" : "partial";
  const label = item.kind === "card" ? `${item.owned}/${max}` : item.owned ? `×${item.owned}` : "0";
  return `<span class="owned owned-${cls}" title="Owned: ${item.owned}">${label}</span>`;
}

export function obtainDot(value) {
  return value ? `<span class="dot dot-${value}" title="${OBTAINABLE_LABEL[value]}"></span>` : "";
}

export async function post(path, body) {
  const res = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `${res.status}: ${res.statusText}`);
  return data;
}

/** Query string for an API URL (empty values dropped, as in api()). */
export function queryString(params) {
  return new URLSearchParams(Object.entries(params).filter(([, v]) => v !== "" && v != null && v !== false)).toString();
}
