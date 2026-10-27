// Entry point: account selector and hash router (#!/view?params).
import { api, beginRender, esc, parseHash, state } from "./util.js";
import { LIST_VIEWS, renderList } from "./list.js";
import { closeDetail, openDetail } from "./detail.js";
import { renderCollection, renderDecks } from "./collection.js";

const main = document.getElementById("main");
let lastKey = null;

async function route() {
  const { view, params } = parseHash();
  const { item, ...rest } = params;
  const key = JSON.stringify([view, rest, state.account]);
  for (const a of document.querySelectorAll("#nav a")) a.classList.toggle("on", a.dataset.view === view);

  if (key === lastKey) {           // only the opened item changed
    item ? openDetail(item) : closeDetail();
    return;
  }
  lastKey = key;
  closeDetail();
  const isCurrent = beginRender();
  if (LIST_VIEWS[view]) {
    await renderList(main, view, params, isCurrent);   // opens params.item itself after loading
    return;
  }
  if (view === "collection") await renderCollection(main, isCurrent);
  else if (view === "decks") await renderDecks(main, params, isCurrent);
  else main.innerHTML = `<section><h1>Not found</h1><p class="empty">Unknown page “${esc(view)}”.</p></section>`;
  if (item && isCurrent()) openDetail(item);
}

async function init() {
  const sel = document.getElementById("account");
  try {
    [state.meta, state.accounts] = await Promise.all([api("/api/meta"), api("/api/accounts")]);
  } catch (e) {
    main.innerHTML = `<section><h1>Server error</h1><p class="error">${esc(e.message)}</p></section>`;
    return;
  }
  sel.innerHTML += state.accounts.map(a =>
    `<option value="${esc(a.id)}">${esc(a.name)} (${a.distinct_cards} cards)</option>`).join("");
  if (!state.accounts.some(a => a.id === state.account)) state.account = "";
  sel.value = state.account;
  sel.addEventListener("change", () => {
    state.account = sel.value;
    try { localStorage.setItem("hexbrowser.account", state.account); } catch { /* private mode */ }
    route();
  });
  window.addEventListener("hashchange", route);
  window.addEventListener("hex:granted", () => { lastKey = null; route(); });   // reload owned counts
  if (!location.hash) history.replaceState(null, "", "#!/cards");
  route();
}

init();
