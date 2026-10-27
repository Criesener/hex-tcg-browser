// Collection dashboard and deck list for the selected account.
import { api, artUrl, esc, hashFor, obtainDot, queryString, state, thresholdPips } from "./util.js";

const KIND_VIEW = { card: "cards", equipment: "equipment", mercenary: "mercenaries", sleeve: "sleeves" };
const KIND_LABEL = { card: "Cards", equipment: "Equipment", mercenary: "Mercenaries", sleeve: "Sleeves",
                     gameboard: "Battleboards", coin: "Coins", gem: "Gems" };

function listLink(kind, params) {
  const view = KIND_VIEW[kind] || "other";
  return hashFor(view, view === "other" ? { kind, ...params } : params);
}

const COLLECTIBLE = "card,equipment,mercenary,sleeve,gameboard,coin,gem";

function csvLink(params, label = "CSV") {
  const q = queryString({ kind: COLLECTIBLE, owned: "missing", account: state.account, sort: "set", ...params });
  return `<a class="csv" href="/api/items.csv?${q}" download title="Download as CSV">${label}</a>`;
}

function bar(part, total, cls = "") {
  const pct = total ? Math.round((part / total) * 100) : 0;
  return `<div class="bar ${cls}" title="${part} / ${total}"><div style="width:${pct}%"></div><span>${pct}%</span></div>`;
}

function needAccount(main, title) {
  main.innerHTML = `<section><h1>${title}</h1><p class="empty">Select an account in the top right to see its collection.</p></section>`;
}

export async function renderCollection(main, isCurrent = () => true) {
  if (!state.account) return needAccount(main, "Collection");
  main.innerHTML = `<section><h1>Collection</h1><p class="loading">Loading…</p></section>`;
  let s;
  try {
    s = await api(`/api/accounts/${encodeURIComponent(state.account)}/summary`);
  } catch (e) {
    if (!isCurrent()) return;
    main.innerHTML = `<section><h1>Collection</h1><p class="error">${esc(e.message)}</p></section>`;
    return;
  }
  if (!isCurrent()) return;
  const a = s.account;
  const champs = a.champions.filter(c => !c.deleted).map(c => `${esc(c.name)} (Lv ${c.level})`).join(", ") || "none";
  const dust = Object.entries(s.stardust).map(([r, n]) => `<span>${esc(r)} ${n}</span>`).join("");
  const kinds = Object.entries(s.by_kind).sort((x, y) => y[1].total - x[1].total);
  const missingRows = ["obtainable", "unknown", "historical"].map(key => {
    const label = { obtainable: "Obtainable on this server", unknown: "Unclear", historical: "Historical only (Kickstarter, ladder, events…)" }[key];
    const dot = { obtainable: "yes", unknown: "unknown", historical: "no" }[key];
    const cells = Object.entries(s.missing[key]).sort((x, y) => y[1] - x[1]).map(([kind, n]) =>
      `<a href="${listLink(kind, { owned: "missing", obtainable: dot })}">${n} ${KIND_LABEL[kind] || kind}</a>`).join(" · ");
    return `<tr><th>${obtainDot(dot)}${label}</th><td>${cells || "—"}</td><td>${cells ? csvLink({ obtainable: dot }) : ""}</td></tr>`;
  }).join("");

  main.innerHTML = `<section class="collection">
    <h1>Collection · ${esc(a.name)}</h1>
    <div class="cards-row">
      <div class="stat"><b>${a.gold.toLocaleString()}</b><span>Gold</span></div>
      <div class="stat"><b>${a.platinum.toLocaleString()}</b><span>Platinum</span></div>
      <div class="stat"><b>${a.distinct_cards}</b><span>distinct cards</span></div>
      <div class="stat"><b>${a.card_copies}</b><span>card copies</span></div>
      <div class="stat wide"><b>${champs}</b><span>Champions</span></div>
      <div class="stat wide"><b class="dust">${dust || "—"}</b><span>Stardust</span></div>
    </div>
    ${s.discrepancies.length ? `<p class="warn">Server data mismatch: for ${s.discrepancies.length} card(s) the <code>collections</code> table lists more copies than exist as card instances. Counts here follow the card instances, which is what the game client receives.</p>` : ""}

    <h2>Completion by type</h2>
    <table class="progress">
      <thead><tr><th></th><th>Owned</th><th></th><th>Complete playsets</th></tr></thead>
      <tbody>${kinds.map(([kind, b]) => `<tr>
        <th><a href="${listLink(kind, {})}">${KIND_LABEL[kind] || kind}</a></th>
        <td>${b.owned} / ${b.total}</td><td>${bar(b.owned, b.total)}</td>
        <td>${kind === "card" ? `${b.complete} / ${b.total}` : ""}</td></tr>`).join("")}</tbody>
    </table>

    <h2>Missing items <small>${csvLink({}, "Download full list (CSV)")}</small></h2>
    <table class="missing"><tbody>${missingRows}</tbody></table>

    <h2>Card sets</h2>
    <table class="progress">
      <thead><tr><th>Set</th><th>Owned</th><th></th><th>Playsets</th><th></th><th></th></tr></thead>
      <tbody>${s.by_set.map(x => `<tr>
        <th><a href="${hashFor("cards", { set: x.set_name })}">${esc(x.set_name)}</a></th>
        <td>${x.owned} / ${x.total}</td><td>${bar(x.owned, x.total)}</td>
        <td>${x.complete} / ${x.total}</td><td>${bar(x.complete, x.total, "alt")}</td>
        <td><a href="${hashFor("cards", { set: x.set_name, owned: "missing" })}">missing</a> · ${csvLink({ kind: "card", set: x.set_name })}</td></tr>`).join("")}</tbody>
    </table>

    <h2>By source</h2>
    <table class="progress">
      <thead><tr><th>Source</th><th>Owned</th><th></th><th></th></tr></thead>
      <tbody>${Object.entries(s.by_source).filter(([c]) => c !== "Not Collectible").map(([cat, b]) => `<tr>
        <th>${esc(cat)}</th><td>${b.owned} / ${b.total}</td><td>${bar(b.owned, b.total)}</td>
        <td><a href="${hashFor("cards", { source: cat, owned: "missing" })}">cards</a> ·
            <a href="${hashFor("equipment", { source: cat, owned: "missing" })}">equipment</a> ·
            <a href="${hashFor("sleeves", { source: cat, owned: "missing" })}">sleeves</a> ·
            <a href="${hashFor("mercenaries", { source: cat, owned: "missing" })}">mercs</a></td></tr>`).join("")}</tbody>
    </table>
  </section>`;
}

export async function renderDecks(main, params, isCurrent = () => true) {
  if (!state.account) return needAccount(main, "Decks");
  main.innerHTML = `<section><h1>Decks</h1><p class="loading">Loading…</p></section>`;
  let decks;
  try {
    decks = await api(`/api/accounts/${encodeURIComponent(state.account)}/decks`);
  } catch (e) {
    if (!isCurrent()) return;
    main.innerHTML = `<section><h1>Decks</h1><p class="error">${esc(e.message)}</p></section>`;
    return;
  }
  if (!isCurrent()) return;
  const extras = d => ["pvp_champion", "sleeve", "gameboard", "coin"].filter(k => d[k]).map(k =>
    `<a href="#" class="mini" data-item="${d[k].guid}"><img src="${artUrl(d[k].icon)}" alt=""><span>${esc(d[k].name || k)}</span></a>`).join("");
  main.innerHTML = `<section class="decks"><h1>Decks</h1>
    ${decks.length ? "" : `<p class="empty">This account has no decks.</p>`}
    ${decks.map(d => `<article class="deck">
      <header><h2>${esc(d.name)}</h2>
        <span>${d.card_count} cards${d.missing_cards ? ` · <b class="miss">${d.missing_cards} missing</b>` : " · complete"}${d.last_saved ? ` · saved ${esc(d.last_saved)}` : ""}</span></header>
      <div class="minis">${extras(d)}</div>
      <table class="decklist"><tbody>${d.cards.map(c => `
        <tr class="${c.owned < c.qty ? "short" : ""}" data-item="${c.guid}">
          <td class="qty">${c.qty}×</td><td class="cost">${c.cost ?? ""}</td>
          <td class="thr">${thresholdPips(c.threshold)}</td>
          <td class="name">${esc(c.name || c.guid)}</td><td>${esc(c.type || "")}</td>
          <td class="own">${c.owned < c.qty ? `owned ${c.owned}` : ""}</td></tr>`).join("")}</tbody></table>
    </article>`).join("")}
  </section>`;
  main.querySelector("section.decks").addEventListener("click", e => {
    const el = e.target.closest("[data-item]");
    if (!el) return;
    e.preventDefault();
    location.hash = hashFor("decks", { ...params, item: el.dataset.item });
  });
}
