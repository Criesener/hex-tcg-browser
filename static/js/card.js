// A card rendered with the game's own card-frame sprites (extract_assets frame):
// each sprite is placed at its box on the card from state.meta.frame
// ([left, top, width, height] as fractions); text and numbers go on top.
// All sizes scale with the card width (container query units).
import { artUrl, esc, gameText, state, SHARDS } from "./util.js";

const TYPE_LABEL = { BasicAction: "Basic Action", QuickAction: "Quick Action" };
const RARITIES = new Set(["common", "uncommon", "rare", "epic", "legendary"]);
const FACTIONS = new Set(["ardent", "underworld"]);
const GEM_STEP = 0.044;            // vertical distance of threshold gems (measured in-game)
const ART = [0.085, 0.08, 0.835, 0.56];   // art window, under the frame bars

function typeLine(item) {
  const types = (item.type || "").split("|").map(t => TYPE_LABEL[t] || t).join(" · ");
  return esc(types.toUpperCase()) + (item.subtype ? ` — ${esc(item.subtype)}` : "");
}

/** Frame color set of the Frames atlas: Blood … Wild, Multi, Artifact, Shardless. */
function frameColor(item) {
  const colors = Object.keys(item.threshold || {}).filter(c => item.threshold[c] > 0);
  if (colors.length > 1) return "multi";
  if (colors.length === 1) return colors[0].toLowerCase();
  return /Artifact/.test(item.type || "") ? "artifact" : "shardless";
}

const pct = v => `${(v * 100).toFixed(2)}%`;
const boxStyle = ([l, t, w, h]) => `left:${pct(l)};top:${pct(t)};width:${pct(w)};height:${pct(h)}`;

/** One frame sprite at its own box (or at box, if given). */
function sprite(name, box, cls = "") {
  box = box || state.meta?.frame?.[name];
  if (!box) return "";
  return `<img class="hc-sp${cls ? " " + cls : ""}" src="/art/frame/${name}?size=full" alt="" style="${boxStyle(box)}">`;
}

/** A sprite centred on another sprite's box, with the given width (height keeps the card's aspect). */
function circleAt(name, onto, width) {
  const b = state.meta?.frame?.[onto];
  if (!b) return "";
  const height = width * 354 / 494;   // card aspect: square on the card
  return sprite(name, [b[0] + b[2] / 2 - width / 2, b[1] + b[3] / 2 - height / 2, width, height]);
}

/**
 * Gem sockets on the rune bar (gembar). Only the count is in the card data;
 * major/minor comes from "Socketable Major/Minor" in the text (majors on top,
 * missing ones count as minor). Measured in-game: a single socket is centred
 * at 37.9% of the card height, a pair at 33.9% / 40.2%; 7.2% of the width wide.
 */
const SOCKET_STEP = 0.063, SOCKET_CENTER = 0.375, SOCKET_W = 0.072;

function sockets(item) {
  const n = Math.min(item.extra?.sockets || 0, 3);
  const bar = state.meta?.frame?.gembar;
  if (!n || !bar) return "";
  const text = item.text || "";
  const majors = (text.match(/socketable major/gi) || []).length;
  const kinds = Array.from({ length: n }, (_, i) => i < majors ? "major" : "minor");
  const h = SOCKET_W * 354 / 494 * 42 / 43;   // sprite is 43x42 px
  const cx = bar[0] + bar[2] / 2;
  return kinds.map((kind, i) => {
    const cy = SOCKET_CENTER + (i - (n - 1) / 2) * SOCKET_STEP;
    return sprite(`gemsocket_${kind}`, [cx - SOCKET_W / 2, cy - h / 2, SOCKET_W, h]);
  }).join("");
}

function gems(threshold) {
  const out = [];
  let k = 0;
  for (const shard of SHARDS) {
    const name = `threshold_${shard.toLowerCase()}`;
    const b = state.meta?.frame?.[name];
    const n = Math.min((threshold || {})[shard] || 0, 10);
    for (let i = 0; i < n && b; i++, k++) {
      out.push(`<img class="hc-sp hc-gem" src="/art/frame/${name}?size=full" alt="${shard}" title="${shard}" style="${boxStyle([b[0], b[1] + k * GEM_STEP, b[2], b[3]])}">`);
    }
  }
  return out.join("");
}

/** Position the art so the game's portrait window [l, t, r, b] fills the art window. */
function artImg(item, full) {
  const src = artUrl(item.icon || item.image, full ? "full" : "thumb");
  const c = item.art_crop;
  if (!c) return `<img class="hc-img fallback" loading="lazy" src="${src}" alt="">`;
  const [l, t, r, b] = c;
  const w = r - l, h = b - t;
  const style = `width:${(100 / w).toFixed(2)}%;height:${(100 / h).toFixed(2)}%;` +
                `left:${(-l / w * 100).toFixed(2)}%;top:${(-t / h * 100).toFixed(2)}%`;
  return `<img class="hc-img" loading="lazy" src="${src}" alt="" style="${style}">`;
}

function plainLength(text) {
  return (text || "").replace(/<[^>]+>|\[[^\]]+\]/g, "x").length;
}

export function renderCard(item, { full = false } = {}) {
  const troop = /Troop/.test(item.type || "");
  const color = frameColor(item);
  const rarity = RARITIES.has((item.rarity || "").toLowerCase()) ? item.rarity.toLowerCase() : "common";
  const faction = FACTIONS.has((item.faction || "").toLowerCase()) ? item.faction.toLowerCase() : "neutral";
  const setIcon = item.set_no >= 1 && item.set_no <= 9 ? `seticon0${item.set_no}` : null;
  const nameSize = Math.min(5.8, 140 / Math.max((item.name || "").length, 1));
  const len = plainLength(item.text) + (item.flavor ? 40 : 0);
  const textSize = len <= 90 ? 4.5 : len <= 150 ? 4 : len <= 220 ? 3.5 : len <= 300 ? 3.1 : 2.7;
  const atk = state.meta?.frame?.atkdefframe;
  return `<div class="hexcard frame-${color} r-${esc(rarity)}${troop ? " troop" : ""}${full ? " full" : ""}">
    <div class="hc-art" style="${boxStyle(ART)}">${artImg(item, full)}</div>
    ${sprite(`${color}_text`)}${sprite(`${color}_1`)}${sprite(`${color}_2`)}${sprite(`${color}_3`)}${sprite(`${color}_4`)}
    ${sprite("gembar")}${sprite("typebar")}${sprite("thresholdbar")}${sprite("bottombar")}
    ${item.pve ? sprite("titlebarpve_1") + sprite("titlebarpve_2") : sprite("titlebar")}
    ${sprite("button_cardhistory_off")}${sprite("button_artist_off")}
    ${sprite("manacost")}${item.pve ? sprite("pve") : ""}
    ${circleAt("factionrarity", `faction_${faction}`, 0.115)}${sprite(`faction_${faction}`)}
    ${circleAt("factionrarity", `rarity_${rarity}`, 0.115)}${sprite(`rarity_${rarity}`)}${setIcon ? sprite(setIcon, null, "hc-set") : ""}
    ${gems(item.threshold)}${sockets(item)}
    ${troop && atk ? `${sprite("atkdefframe")}${sprite("atkdefframe", [1 - atk[0] - atk[2], atk[1], atk[2], atk[3]], "hc-mirror")}
                      ${sprite("attackicon")}${sprite("defenseicon")}` : ""}
    <div class="hc-cost"><span>${item.cost ?? ""}</span></div>
    <div class="hc-name" style="font-size:${nameSize.toFixed(2)}cqw" title="${esc(item.name)}${item.is_unique ? " (Unique)" : ""}">${esc(item.name)}</div>
    <div class="hc-type"><span>${typeLine(item)}</span></div>
    <div class="hc-body" style="font-size:${textSize}cqw"><div class="hc-text">${gameText(item.text || "")}</div></div>
    ${item.flavor ? `<div class="hc-flavor">${gameText(item.flavor)}</div>` : ""}
    ${troop ? `<div class="hc-stat hc-atk"><b>${item.attack ?? 0}</b></div><div class="hc-stat hc-def"><b>${item.defense ?? 0}</b></div>` : ""}
  </div>`;
}
