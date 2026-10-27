// Item list views (cards, equipment, mercenaries, sleeves, other) with filters.
import { api, artUrl, esc, navigate, obtainDot, ownedBadge, queryString, state, thresholdPips, SHARDS } from "./util.js";
import { adminOn, confirmGrant } from "./admin.js";
import { openDetail } from "./detail.js";
import { renderCard } from "./card.js";

export const LIST_VIEWS = {
  cards: {
    kind: "card", title: "Cards",
    filters: ["q", "text", "set", "type", "rarity", "faction", "cost", "shard", "pve", "source", "obtainable", "owned", "alternates"],
    sorts: ["set", "name", "cost", "rarity"],
  },
  equipment: {
    kind: "equipment", title: "Equipment",
    filters: ["q", "text", "set", "subtype", "rarity", "source", "obtainable", "owned"],
    sorts: ["name", "rarity", "set"],
  },
  mercenaries: {
    kind: "mercenary", title: "Mercenaries",
    filters: ["q", "text", "rarity", "source", "obtainable", "owned"],
    sorts: ["name", "rarity"],
  },
  sleeves: {
    kind: "sleeve", title: "Sleeves",
    filters: ["q", "source", "obtainable", "owned"],
    sorts: ["name"],
  },
  other: {
    kind: null, title: "Other items", all: true,
    kinds: ["gameboard", "coin", "gem", "pack", "starter", "chest", "stardust", "ticket", "vip", "currency"],
    filters: ["kind", "q", "source", "obtainable", "owned"],
    sorts: ["name", "set"],
  },
};

const PAGE_SIZE = 60;
const KIND_LABEL = {
  gameboard: "Battleboards", coin: "Coins", gem: "Gems", pack: "Booster packs",
  starter: "Starter decks", chest: "Chests & promo packs", stardust: "Stardust",
  ticket: "Tickets", vip: "VIP", currency: "Currencies",
};

let current = { items: [], view: null, params: null };   // for prev/next in the detail modal
let refocusSearch = false;                               // typing re-renders the view

function options(values, selected, empty = "Any") {
  return (empty === null ? "" : `<option value="">${empty}</option>`) + values.map(v => {
    const [val, label] = Array.isArray(v) ? v : [v, v];
    return `<option value="${esc(val)}"${String(val) === selected ? " selected" : ""}>${esc(label)}</option>`;
  }).join("");
}

function select(name, label, values, params, empty) {
  return `<label class="f"><span>${label}</span><select name="${name}">${options(values, params[name] || "", empty)}</select></label>`;
}

function filterBar(cfg, kind, params) {
  const m = state.meta;
  const parts = [];
  for (const f of cfg.filters) {
    switch (f) {
      case "kind":
        parts.push(select("kind", "Type", cfg.kinds.map(k => [k, KIND_LABEL[k] || k]), params, null));
        break;
      case "q":
        parts.push(`<label class="f grow"><span>Search</span><input type="search" name="q" value="${esc(params.q || "")}" placeholder="Name…" autocomplete="off"></label>`);
        break;
      case "text":
        parts.push(`<label class="f check"><input type="checkbox" name="text" value="1"${params.text ? " checked" : ""}><span>also in text</span></label>`);
        break;
      case "set": {
        const sets = m.sets.filter(s => s.kind === kind)
          .sort((a, b) => (a.set_no ?? 99) - (b.set_no ?? 99) || a.name.localeCompare(b.name))
          .map(s => [s.name, `${s.name} (${s.total})`]);
        parts.push(select("set", "Set", sets, params));
        break;
      }
      case "type": parts.push(select("type", "Type", m.card_types, params)); break;
      case "rarity": parts.push(select("rarity", "Rarity", m.rarities, params)); break;
      case "faction": parts.push(select("faction", "Faction", m.factions.filter(f => f !== "None"), params)); break;
      case "subtype": parts.push(select("subtype", "Slot", m.equipment_slots, params)); break;
      case "cost":
        parts.push(select("cost", "Cost", ["0", "1", "2", "3", "4", "5", "6", ["7+", "7+"]], params));
        break;
      case "shard": {
        const sel = (params.shard || "").split(",");
        parts.push(`<div class="f"><span>Shards</span><div class="shards">` +
          [...SHARDS, "Colorless"].map(s => `<button type="button" data-shard="${s}" class="pip-btn pip-${s.toLowerCase()}${sel.includes(s) ? " on" : ""}" title="${s}"></button>`).join("") +
          `</div></div>`);
        break;
      }
      case "pve": parts.push(select("pve", "Mode", [["0", "PvP cards"], ["1", "PvE cards"]], params)); break;
      case "source":
        parts.push(select("source", "Source", m.source_categories.filter(c => c.category !== "Not Collectible").map(c => c.category), params));
        break;
      case "obtainable":
        parts.push(select("obtainable", "On this server", [["yes", "Obtainable"], ["unknown", "Unclear"], ["no", "Not obtainable"]], params));
        break;
      case "owned":
        parts.push(state.account
          ? select("owned", "Collection", [["owned", "Owned"], ["missing", "Missing"], ["incomplete", "Incomplete playset"]], params, "All")
          : `<label class="f"><span>Collection</span><select disabled title="Select an account first"><option>No account</option></select></label>`);
        break;
      case "alternates":
        parts.push(`<label class="f check"><input type="checkbox" name="noalt" value="1"${params.noalt ? " checked" : ""}><span>hide alternate art</span></label>`);
        break;
    }
  }
  parts.push(`<label class="f"><span>Sort</span><select name="sort">${options(cfg.sorts.map(s => [s, s[0].toUpperCase() + s.slice(1)]), params.sort || cfg.sorts[0], null)}</select></label>`);
  parts.push(`<div class="f"><span>View</span><div class="seg"><button type="button" data-layout="grid" class="${params.layout === "list" ? "" : "on"}">Grid</button><button type="button" data-layout="list" class="${params.layout === "list" ? "on" : ""}">List</button></div></div>`);
  parts.push(`<button type="button" class="reset" data-reset>Reset</button>`);
  return `<form class="filters" autocomplete="off">${parts.join("")}</form>`;
}

function cardTile(item) {
  return `<a class="cardtile${item.owned === 0 ? " missing" : ""}" href="#" data-guid="${item.guid}" title="${esc(item.name)}">
    ${renderCard(item)}
    <div class="cap2">${obtainDot(item.obtainable)}<span class="set">${esc(item.set_name || "")}</span>${item.is_alternate ? '<span class="tag">AA</span>' : ""}${ownedBadge(item)}</div>
  </a>`;
}

function tile(item) {
  if (item.kind === "card") return cardTile(item);
  const rarity = (item.rarity || "").toLowerCase();
  const cost = item.cost !== null && item.cost !== undefined && item.kind === "card" ? `<span class="cost">${item.cost}</span>` : "";
  const stats = item.kind === "card" && /Troop/.test(item.type) ? `<span class="stats">${item.attack}/${item.defense}</span>` : "";
  return `<a class="tile kind-${item.kind} r-${rarity}${item.owned === 0 ? " missing" : ""}" href="#" data-guid="${item.guid}">
    <div class="art"><img loading="lazy" src="${artUrl(item.icon)}" alt="">${cost}${stats}${ownedBadge(item)}</div>
    <div class="cap">
      <div class="name">${obtainDot(item.obtainable)}${esc(item.name)}</div>
      <div class="sub"><span class="thr">${thresholdPips(item.threshold)}</span>${esc(item.subtype && item.kind !== "card" ? item.subtype : item.set_name || "")}${item.is_alternate ? ' <span class="tag">AA</span>' : ""}</div>
    </div>
  </a>`;
}

function row(item) {
  return `<tr data-guid="${item.guid}" class="r-${(item.rarity || "").toLowerCase()}${item.owned === 0 ? " missing" : ""}">
    <td><img loading="lazy" src="${artUrl(item.icon)}" alt=""></td>
    <td class="name">${obtainDot(item.obtainable)}${esc(item.name)}${item.is_alternate ? ' <span class="tag">AA</span>' : ""}</td>
    <td>${item.kind === "card" ? (item.cost ?? "") : ""}</td>
    <td class="thr">${thresholdPips(item.threshold)}</td>
    <td>${esc(item.kind === "card" ? item.type : item.subtype || item.kind)}</td>
    <td class="rar">${esc(item.rarity || "")}</td>
    <td>${esc(item.set_name || "")}</td>
    <td>${ownedBadge(item)}</td>
  </tr>`;
}

function pager(total, page) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (pages === 1) return "";
  const btn = (p, label = p) => `<button type="button" data-page="${p}"${p === page ? ' class="on"' : ""}${p < 1 || p > pages ? " disabled" : ""}>${label}</button>`;
  const nums = [...new Set([1, page - 2, page - 1, page, page + 1, page + 2, pages])].filter(p => p >= 1 && p <= pages).sort((a, b) => a - b);
  let out = btn(page - 1, "‹");
  nums.forEach((p, i) => { if (i && p - nums[i - 1] > 1) out += "<span>…</span>"; out += btn(p); });
  return `<div class="pager">${out}${btn(page + 1, "›")}</div>`;
}

export async function renderList(main, view, params, isCurrent = () => true) {
  const cfg = LIST_VIEWS[view];
  const kind = cfg.kind || params.kind || cfg.kinds[0];
  const page = Math.max(1, parseInt(params.page || "1", 10));
  main.innerHTML = `<section class="list-view">
      <h1>${esc(cfg.title)}${cfg.kind ? "" : ` · ${esc(KIND_LABEL[kind] || kind)}`}</h1>
      ${filterBar(cfg, kind, params)}
      <div class="summary" id="summary">Loading…</div>
      <div class="adminbox" id="adminbox" hidden></div>
      <div id="results"></div>
    </section>`;
  bindFilters(main, view, params);

  // the filters as API parameters (shared by the list, CSV export and grant)
  const query = {
    kind, q: params.q, text: params.text ? "true" : "", set: params.set, type: params.type,
    rarity: params.rarity, faction: params.faction, subtype: params.subtype, cost: params.cost,
    shard: params.shard, pve: params.pve, source: params.source, obtainable: params.obtainable,
    owned: state.account ? params.owned : "", account: state.account,
    alternates: params.noalt ? "false" : "", all: cfg.all ? "true" : "",
    sort: params.sort || cfg.sorts[0],
  };
  let data;
  try {
    data = await api("/api/items", { ...query, page, page_size: PAGE_SIZE });
  } catch (e) {
    if (!isCurrent()) return;
    main.querySelector("#summary").innerHTML = `<span class="error">${esc(e.message)}</span>`;
    return;
  }
  if (!isCurrent()) return;   // a newer render replaced this view
  current = { items: data.items, view, params };
  const from = data.total ? (page - 1) * PAGE_SIZE + 1 : 0;
  main.querySelector("#summary").innerHTML =
    `${data.total} ${data.total === 1 ? "item" : "items"}${data.total ? ` · showing ${from}–${from + data.items.length - 1}` : ""}` +
    `<span class="legend">${obtainDot("yes")} obtainable here ${obtainDot("unknown")} unclear ${obtainDot("no")} historical only</span>` +
    `<span class="actions">${data.total ? `<a href="/api/items.csv?${queryString(query)}" download>Export CSV</a>` : ""}` +
    `${adminOn() && data.total ? `<button type="button" data-grant-list title="Fill up every item of this list to a full playset">Grant missing…</button>` : ""}</span>`;
  main.querySelector("[data-grant-list]")?.addEventListener("click", () => {
    const { owned, ...filters } = query;   // the server fills up all incomplete items
    confirmGrant(main.querySelector("#adminbox"), { query: filters });
  });
  const results = main.querySelector("#results");
  if (!data.items.length) {
    results.innerHTML = `<p class="empty">Nothing matches these filters.</p>`;
  } else if (params.layout === "list") {
    results.innerHTML = `<table class="items"><thead><tr><th></th><th>Name</th><th>Cost</th><th>Shards</th><th>Type</th><th>Rarity</th><th>Set</th><th>Owned</th></tr></thead>
      <tbody>${data.items.map(row).join("")}</tbody></table>${pager(data.total, page)}`;
  } else {
    results.innerHTML = `<div class="grid grid-${kind}">${data.items.map(tile).join("")}</div>${pager(data.total, page)}`;
  }
  results.addEventListener("click", e => {
    const el = e.target.closest("[data-guid]");
    if (el) {
      e.preventDefault();
      navigate(view, { ...params, item: el.dataset.guid });
    }
    const pg = e.target.closest("[data-page]");
    if (pg && !pg.disabled) {
      navigate(view, { ...params, page: pg.dataset.page, item: "" });
      window.scrollTo(0, 0);
    }
  });
  if (params.item) openDetail(params.item);
}

function bindFilters(main, view, params) {
  const form = main.querySelector("form.filters");
  const base = () => ({ layout: params.layout, sort: params.sort, kind: params.kind });
  const collect = () => {
    const p = { ...base() };
    for (const el of form.elements) {
      if (!el.name || el.disabled) continue;
      if (el.type === "checkbox") { if (el.checked) p[el.name] = "1"; }
      else if (el.value) p[el.name] = el.value;
    }
    const shards = [...form.querySelectorAll("[data-shard].on")].map(b => b.dataset.shard);
    if (shards.length) p.shard = shards.join(",");
    return p;
  };
  form.addEventListener("change", e => {
    if (e.target.name === "q") return;
    navigate(view, collect());
  });
  let timer;
  form.addEventListener("input", e => {
    if (e.target.name !== "q") return;
    clearTimeout(timer);
    timer = setTimeout(() => { refocusSearch = true; navigate(view, collect(), true); }, 300);
  });
  form.addEventListener("submit", e => e.preventDefault());
  form.addEventListener("click", e => {
    const shard = e.target.closest("[data-shard]");
    if (shard) { shard.classList.toggle("on"); navigate(view, collect()); }
    const lay = e.target.closest("[data-layout]");
    if (lay) navigate(view, { ...params, layout: lay.dataset.layout === "list" ? "list" : "", item: "" });
    if (e.target.closest("[data-reset]")) navigate(view, { layout: params.layout, kind: params.kind });
  });
  // keep the caret in the search box after re-rendering
  const q = form.querySelector('input[name="q"]');
  if (q && refocusSearch) {
    q.focus();
    q.setSelectionRange(q.value.length, q.value.length);
  }
  refocusSearch = false;
}

export function neighbours(guid) {
  const i = current.items.findIndex(x => x.guid === guid);
  return {
    prev: i > 0 ? current.items[i - 1].guid : null,
    next: i >= 0 && i < current.items.length - 1 ? current.items[i + 1].guid : null,
    view: current.view, params: current.params,
  };
}
