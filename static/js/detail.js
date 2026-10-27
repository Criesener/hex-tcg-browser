// Item detail modal (opened via the "item" URL parameter of any view).
import { api, artUrl, esc, gameText, navigate, obtainDot, ownedBadge, parseHash, state, thresholdPips, OBTAINABLE_LABEL } from "./util.js";
import { neighbours } from "./list.js";
import { renderCard } from "./card.js";
import { adminOn, confirmGrant, grantable } from "./admin.js";

const modal = () => document.getElementById("modal");
let shown = null;

const REL_TITLES = {
  versions: "Other versions",
  in_starters: "Included in starter decks",
  starter_cards: "Deck contents",
  upgrades_cards: "Upgrades these cards",
  upgraded_by: "Equipment for this card",
  variant_of: "Equipment version of",
};

function go(guid) {
  const { view, params } = parseHash();
  navigate(view, { ...params, item: guid || "" });
}

export function closeDetail() {
  const m = modal();
  m.hidden = true;
  m.innerHTML = "";
  shown = null;
  document.body.classList.remove("noscroll");
}

function facts(d) {
  const rows = [];
  const add = (k, v) => { if (v !== null && v !== undefined && v !== "") rows.push(`<dt>${k}</dt><dd>${v}</dd>`); };
  if (d.kind === "card") {
    add("Cost", d.cost !== null ? `${d.cost} ${thresholdPips(d.threshold)}` : "");
    if (/Troop/.test(d.type)) add("Attack / Defense", `${d.attack} / ${d.defense}`);
    add("Faction", d.faction !== "None" ? esc(d.faction) : "");
    add("Unique", d.is_unique ? "yes" : "");
  }
  add("Set", esc(d.set_name || ""));
  add("Rarity", esc(d.rarity || ""));
  add("Mode", d.pve ? "PvE" : d.kind === "card" ? "PvP" : "");
  add("Tradeable", d.tradeable ? "yes" : "no");
  const x = d.extra || {};
  add("Modifiers", esc(x.modifiers || ""));
  add("Health", x.health ?? "");
  add("Race", x.race && x.race !== "None" ? esc(x.race) : "");
  add("Deck", esc(x.deck || ""));
  add("Artist", esc(d.artist || ""));
  return `<dl class="facts">${rows.join("")}</dl>`;
}

function sources(d) {
  if (!d.sources.length) return "";
  return `<h3>How to obtain</h3><ul class="sources">` + d.sources.map(s => `
    <li class="src-${s.obtainable}" title="${esc(s.raw_text || "")}">
      ${obtainDot(s.obtainable)}<strong>${esc(s.category)}</strong>${s.detail ? ` — ${esc(s.detail)}` : ""}
      <small>${OBTAINABLE_LABEL[s.obtainable]}</small>
    </li>`).join("") + `</ul>`;
}

function relations(d) {
  return Object.entries(d.relations || {}).map(([k, items]) => `
    <h3>${REL_TITLES[k] || k} <small>(${items.length})</small></h3>
    <div class="minis">${items.map(x => `
      <a href="#" class="mini${x.owned === 0 ? " missing" : ""}" data-goto="${x.guid}" title="${esc(x.name)} · ${esc(x.set_name || x.kind)}">
        <img loading="lazy" src="${artUrl(x.icon)}" alt="">
        <span>${x.qty && x.qty > 1 ? x.qty + "× " : ""}${esc(x.name)}${x.is_alternate ? " (AA)" : ""}</span>
        ${ownedBadge(x)}
      </a>`).join("")}</div>`).join("");
}

function owned(d) {
  if (!d.owned) return state.account ? "" : `<p class="hint">Select an account to see what you own.</p>`;
  const o = d.owned;
  const max = d.max_copies || 1;
  const cls = o.qty === 0 ? "none" : o.qty >= max ? "full" : "partial";
  const ext = o.ext ? ` (${o.ext} extended art)` : "";
  const text = d.kind === "card" ? `${o.qty} of ${max} copies${ext}` : o.qty ? `owned ×${o.qty}` : "not owned";
  return `<p class="owned-line owned-${cls}">Collection: <strong>${text}</strong></p>`;
}

function adminGrant(d) {
  if (!adminOn() || !grantable(d)) return "";
  const missing = Math.max(1, (d.max_copies || 1) - (d.owned?.qty || 0));
  return `<div class="admin-grant">
    <label>Grant <input type="number" name="grant-qty" min="1" max="99" value="${missing}"></label>
    <button type="button" data-grant="${d.guid}">Grant…</button>
    <div class="adminbox" hidden></div>
  </div>`;
}

export async function openDetail(guid) {
  if (shown === guid) return;
  shown = guid;
  const m = modal();
  m.hidden = false;
  document.body.classList.add("noscroll");
  m.innerHTML = `<div class="sheet"><p class="loading">Loading…</p></div>`;
  let d;
  try {
    d = await api(`/api/items/${encodeURIComponent(guid)}`, { account: state.account });
  } catch (e) {
    m.innerHTML = `<div class="sheet"><button class="close" data-close>×</button><p class="error">${esc(e.message)}</p></div>`;
    return;
  }
  if (shown !== guid) return;   // user moved on while loading
  const { view } = parseHash();
  const nb = neighbours(guid);
  const sameList = nb.view === view;
  const img = d.image || d.icon;
  m.innerHTML = `
    <div class="sheet kind-${d.kind} r-${(d.rarity || "").toLowerCase()}">
      <button class="close" data-close title="Close (Esc)">×</button>
      <div class="detail">
        <div class="visual">${d.kind === "card"
          ? `${renderCard(d, { full: true })}${img ? `<a class="artlink" href="${artUrl(img, "full")}" target="_blank" rel="noopener">Full artwork ↗</a>` : ""}`
          : `<img src="${artUrl(img, "full")}" alt="${esc(d.name)}">`}</div>
        <div class="info">
          <h2>${obtainDot(d.obtainable)}${esc(d.name)}${d.is_alternate ? ' <span class="tag">Alternate art</span>' : ""}</h2>
          <p class="typeline">${esc([d.kind === "card" ? d.type?.replace(/\|/g, " · ") : d.type, d.subtype].filter(Boolean).join(" — "))}</p>
          ${owned(d)}
          ${adminGrant(d)}
          ${d.text ? `<div class="gametext">${gameText(d.text)}</div>` : ""}
          ${d.flavor ? `<p class="flavor">${gameText(d.flavor)}</p>` : ""}
          ${facts(d)}
          ${sources(d)}
          ${relations(d)}
        </div>
      </div>
      <div class="navbtns">
        <button data-goto="${sameList && nb.prev || ""}"${sameList && nb.prev ? "" : " disabled"} title="Previous (←)">‹ Previous</button>
        <button data-goto="${sameList && nb.next || ""}"${sameList && nb.next ? "" : " disabled"} title="Next (→)">Next ›</button>
      </div>
    </div>`;
}

// one set of listeners for the lifetime of the page
document.addEventListener("click", e => {
  if (modal().hidden) return;
  if (e.target === modal() || e.target.closest("[data-close]")) { e.preventDefault(); go(""); return; }
  const grant = e.target.closest("[data-grant]");
  if (grant) {
    const box = grant.closest(".admin-grant");
    const qty = parseInt(box.querySelector("[name=grant-qty]").value, 10) || 1;
    confirmGrant(box.querySelector(".adminbox"), { items: [{ guid: grant.dataset.grant, qty }] });
    return;
  }
  const g = e.target.closest("[data-goto]");
  if (g && g.dataset.goto) { e.preventDefault(); go(g.dataset.goto); }
});
document.addEventListener("keydown", e => {
  if (modal().hidden || e.target.closest?.("input, select, textarea")) return;
  if (e.key === "Escape") go("");
  const btns = modal().querySelectorAll(".navbtns [data-goto]");
  if (e.key === "ArrowLeft" && btns[0]?.dataset.goto) go(btns[0].dataset.goto);
  if (e.key === "ArrowRight" && btns[1]?.dataset.goto) go(btns[1].dataset.goto);
});
