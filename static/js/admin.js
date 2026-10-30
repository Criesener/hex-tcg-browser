// Admin mode (./run.sh --admin): grant items to the selected account.
// Every grant is a dry run first, confirmed in an inline panel.
// HEX Revival accounts ("rev:..." ids) get their save files written instead
// of the server DB, for fewer item kinds, and not when everything is unlocked.
import { esc, post, state } from "./util.js";

const account = () => state.accounts.find(a => a.id === state.account);
const isRevival = () => state.account.startsWith("rev:");

export const adminOn = () => Boolean(state.meta?.admin && state.account && !account()?.unlock_all);

const INVENTORY_KINDS = new Set(["equipment", "mercenary", "sleeve", "gameboard", "coin", "gem", "pack", "starter", "chest"]);
const REVIVAL_KINDS = new Set(["equipment", "mercenary", "sleeve", "pack"]);

export function grantable(item) {
  if (item.kind === "card") return Boolean(item.collectible);
  return (isRevival() ? REVIVAL_KINDS : INVENTORY_KINDS).has(item.kind);
}

function accountName() {
  return account()?.name || state.account;
}

export function toast(message, cls = "") {
  const el = document.createElement("div");
  el.className = `toast ${cls}`;
  el.textContent = message;
  document.body.append(el);
  setTimeout(() => el.remove(), 6000);
}

/**
 * Show the grant plan for request ({items} and/or {query}) in box and grant on
 * confirmation. Fires "hex:granted" on window afterwards so views reload.
 */
export async function confirmGrant(box, request) {
  const body = { account: state.account, ...request };
  box.hidden = false;
  box.innerHTML = `<p class="loading">Checking…</p>`;
  let plan;
  try {
    plan = await post("/api/admin/grant", { ...body, dry_run: true });
  } catch (e) {
    box.innerHTML = `<p class="error">${esc(e.message)}</p>`;
    return;
  }
  if (!plan.entries) {
    box.innerHTML = `<p class="hint">Nothing to grant: the account already owns everything here.</p>`;
    return;
  }
  const what = [plan.cards && `${plan.cards} card cop${plan.cards === 1 ? "y" : "ies"}`,
                plan.items && `${plan.items} item${plan.items === 1 ? "" : "s"}`].filter(Boolean).join(" and ");
  const more = plan.entries > plan.sample.length ? `<li>… and ${plan.entries - plan.sample.length} more</li>` : "";
  box.innerHTML = `
    <p>Grant <strong>${what}</strong> (${plan.entries} entr${plan.entries === 1 ? "y" : "ies"}) to <strong>${esc(accountName())}</strong>:</p>
    <ul>${plan.sample.map(s => `<li>${esc(s)}</li>`).join("")}${more}</ul>
    ${plan.target === "revival"
      ? plan.server_running
        ? `<p class="warn">${esc(plan.server_running)}. Quit the game first, otherwise it would overwrite the change on its next save.</p>`
        : `<p class="hint">The game is closed. collection.txt and inventory.txt are backed up before writing.</p>`
      : plan.server_running
        ? `<p class="warn">The hex-server is running (${esc(plan.server_running)}). Stop it first with <code>./server/hex-server.sh stop</code>, otherwise it would overwrite the change.</p>`
        : `<p class="hint">The hex-server is stopped. hconnect.db is backed up before writing.</p>`}
    <div class="adminbtns">
      <button type="button" class="primary" data-admin="go"${plan.server_running ? " disabled" : ""}>Grant</button>
      <button type="button" data-admin="recheck">Check again</button>
      <button type="button" data-admin="cancel">Cancel</button>
    </div>`;
  box.onclick = async e => {
    const action = e.target.closest("[data-admin]")?.dataset.admin;
    if (action === "cancel") { box.hidden = true; box.innerHTML = ""; }
    if (action === "recheck") confirmGrant(box, request);
    if (action !== "go") return;
    box.querySelectorAll("button").forEach(b => { b.disabled = true; });
    try {
      const res = await post("/api/admin/grant", body);
      toast(`Granted ${what} to ${accountName()}. Backup: ${res.backup.split("/").pop()}`, "ok");
      window.dispatchEvent(new Event("hex:granted"));
    } catch (err) {
      box.insertAdjacentHTML("beforeend", `<p class="error">${esc(err.message)}</p>`);
      box.querySelector('[data-admin="recheck"]').disabled = false;
      box.querySelector('[data-admin="cancel"]').disabled = false;
    }
  };
}
