/* Pair the fan's real phone: a QR code on the FAN monitor opens /phone on this session. */

import { $, app, on } from "./state.js";

let paired = 0;

export function initPairing() {
  $("#pair-btn").addEventListener("click", toggle);
  on("device", (d) => setPaired(d.paired));
  on("state", (s) => setPaired(s.devices || 0));
}

async function phoneUrl() {
  let base = location.origin;
  if (["localhost", "127.0.0.1"].includes(location.hostname)) {
    const lan = await fetch("/api/lan").then((r) => r.json()).catch(() => ({}));
    if (lan.url) base = lan.url.replace(/:80$/, `:${location.port || 80}`);
  }
  return `${base}/phone?session=${app.session}`;
}

async function toggle() {
  const box = $("#pair-box");
  if (!box.hidden) { box.hidden = true; return; }
  const url = await phoneUrl();
  const qr = window.qrcode ? window.qrcode(0, "M") : null;
  let img = "";
  if (qr) { qr.addData(url); qr.make(); img = qr.createSvgTag({ cellSize: 5, margin: 2, scalable: true }); }
  box.innerHTML = `<div class="pb-k">SCAN WITH YOUR PHONE CAMERA</div><div class="pb-qr">${img}</div>
    <div class="pb-url">${url}</div>
    <div class="pb-hint">Same Wi-Fi as this computer · then tap “Tap to pair” · keep the phone screen on</div>`;
  box.hidden = false;
}

function setPaired(n) {
  paired = n;
  const btn = $("#pair-btn");
  btn.textContent = paired ? "● PHONE PAIRED" : "PAIR PHONE";
  btn.classList.toggle("paired", Boolean(paired));
  if (paired) $("#pair-box").hidden = true;
}
