/* Pair the fan's real phone: a QR code in the companion panel opens /phone on this session. */

import { $, app, on } from "./state.js";

let paired = 0;
let url = "";

export function initPairing() {
  on("device", (d) => setPaired(d.paired));
  on("state", (s) => { refresh(); setPaired(s.devices || 0); });
}

async function phoneUrl() {
  let base = location.origin;
  if (["localhost", "127.0.0.1"].includes(location.hostname)) {
    const lan = await fetch("/api/lan").then((r) => r.json()).catch(() => ({}));
    if (lan.url) base = lan.url.replace(/:80$/, `:${location.port || 80}`);
  }
  return `${base}/phone?session=${app.session}&match=${encodeURIComponent(app.matchId)}`;
}

/** A new session means a new phone link. */
async function refresh() {
  const next = await phoneUrl();
  if (next === url) return;
  url = next;
  render();
}

function render() {
  const el = $("#pair");
  if (paired) {
    el.innerHTML = `<div class="pr-ok"><i></i><span><b>PHONE PAIRED</b><small>It will ring before the big moments.</small></span></div>`;
    return;
  }
  const qr = window.qrcode ? window.qrcode(0, "M") : null;
  let img = "";
  if (qr) { qr.addData(url); qr.make(); img = qr.createSvgTag({ cellSize: 4, margin: 2, scalable: true }); }
  el.innerHTML = `<div class="pr-qr">${img}</div><div class="pr-side"><b>SCAN WITH YOUR PHONE CAMERA</b>
    <a class="pr-url" href="${url}" target="_blank" rel="noopener">${url.replace(/^https?:\/\//, "")}</a>
    <small>Then tap “Tap to pair” and keep the phone screen on.${["localhost", "127.0.0.1"].includes(location.hostname)
      ? " Same Wi-Fi as this computer." : ""}</small></div>`;
}

function setPaired(n) {
  if (Boolean(n) === Boolean(paired)) { paired = n; return; }
  paired = n;
  render();
}
