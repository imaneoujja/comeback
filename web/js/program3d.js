/* PGM: 3D broadcast view (Three.js). A "main stand" camera follows the ball over a
 * floodlit stadium; a behind-the-goal camera is used for replays. Everything is
 * built procedurally (no external assets) from fictional club colours. */

import * as THREE from "three";
import { app, L, W } from "./state.js";

const toX = (x) => x - L / 2;          // pitch metres → world
const toZ = (y) => W / 2 - y;          // y = 0 (near touchline) is closest to the camera
const PLAYER_SCALE = 1.25;

export function createProgram(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x05070a);
  scene.fog = new THREE.Fog(0x05070a, 150, 290);

  const camera = new THREE.PerspectiveCamera(24, 16 / 9, 1, 700);

  /* ---------------------------------------------------------------- light */
  scene.add(new THREE.HemisphereLight(0xc8d8ff, 0x0d1a10, 0.6));
  const key = new THREE.DirectionalLight(0xfff4e6, 1.7);
  key.position.set(-35, 95, 45);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  Object.assign(key.shadow.camera, { left: -75, right: 75, top: 55, bottom: -55, near: 10, far: 250 });
  key.shadow.bias = -0.0004;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x9db8ff, 0.45);
  fill.position.set(60, 70, -60);
  scene.add(fill);

  /* ---------------------------------------------------------------- pitch */
  const pitchTex = new THREE.CanvasTexture(pitchCanvas());
  pitchTex.colorSpace = THREE.SRGBColorSpace;
  pitchTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const pitch = new THREE.Mesh(new THREE.PlaneGeometry(L + 8, W + 8), new THREE.MeshStandardMaterial({ map: pitchTex, roughness: 0.95 }));
  pitch.rotation.x = -Math.PI / 2;
  pitch.receiveShadow = true;
  scene.add(pitch);
  const apron = new THREE.Mesh(new THREE.PlaneGeometry(170, 130), new THREE.MeshStandardMaterial({ color: 0x0c1a10, roughness: 1 }));
  apron.rotation.x = -Math.PI / 2; apron.position.y = -0.02; apron.receiveShadow = true;
  scene.add(apron);

  /* ---------------------------------------------------------------- goals */
  const white = new THREE.MeshStandardMaterial({ color: 0xf5f5f0, roughness: 0.4 });
  const netMat = new THREE.MeshBasicMaterial({ color: 0xdedede, wireframe: true, transparent: true, opacity: 0.22 });
  for (const side of [-1, 1]) {
    const gx = side * L / 2;
    const post = (z) => {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.44, 10), white);
      m.position.set(gx, 1.22, z); m.castShadow = true; scene.add(m);
    };
    post(-3.66); post(3.66);
    const bar = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 7.32, 10), white);
    bar.rotation.x = Math.PI / 2; bar.position.set(gx, 2.44, 0); bar.castShadow = true; scene.add(bar);
    const net = new THREE.Mesh(new THREE.BoxGeometry(2, 2.44, 7.32, 4, 5, 12), netMat);
    net.position.set(gx + side * 1, 1.22, 0); scene.add(net);
  }

  /* ---------------------------------------------------------------- LED boards */
  const ledCanvas = document.createElement("canvas");
  ledCanvas.width = 2048; ledCanvas.height = 64;
  const ledTex = new THREE.CanvasTexture(ledCanvas);
  ledTex.colorSpace = THREE.SRGBColorSpace;
  ledTex.wrapS = THREE.RepeatWrapping;
  const paintLed = (bg, fg, text) => {
    const c = ledCanvas.getContext("2d");
    c.fillStyle = bg; c.fillRect(0, 0, 2048, 64);
    c.fillStyle = fg; c.font = "700 40px 'IBM Plex Sans Condensed', sans-serif"; c.textBaseline = "middle";
    const stepX = c.measureText(text).width + 420;   // a short word, well spaced
    for (let x = 30; x < 2048; x += stepX) c.fillText(text, x, 34);
    ledTex.needsUpdate = true;
  };
  paintLed("#05060a", "#9a988f", "COMEBACK");
  const ledMat = new THREE.MeshBasicMaterial({ map: ledTex });
  const board = (w, x, z, ry) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, 0.9), ledMat);
    m.position.set(x, 0.45, z); m.rotation.y = ry; scene.add(m);
  };
  board(L + 10, 0, -(W / 2 + 4), 0);
  board(W + 6, -(L / 2 + 5), 0, Math.PI / 2);
  board(W + 6, L / 2 + 5, 0, -Math.PI / 2);

  /* ---------------------------------------------------------------- stands + crowd */
  const standMat = new THREE.MeshStandardMaterial({ color: 0x0b0d10, roughness: 0.95 });
  const crowdSpots = [];
  const tierStand = (length, along, base, dir, tiers) => {
    for (let i = 0; i < tiers; i++) {
      const depth = 6, h = 2.6;
      const geo = along === "x" ? new THREE.BoxGeometry(length, h, depth) : new THREE.BoxGeometry(depth, h, length);
      const m = new THREE.Mesh(geo, standMat);
      const off = base + i * depth + depth / 2;
      const y = i * h + h / 2;
      if (along === "x") m.position.set(0, y, dir * off); else m.position.set(dir * off, y, 0);
      m.receiveShadow = true; scene.add(m);
      for (let row = 0; row < 3; row++) {
        const rowOff = base + i * depth + 1 + row * 1.8;
        for (let s = -length / 2 + 1; s < length / 2 - 1; s += 1.05) {
          const jitter = (Math.random() - 0.5) * 0.3;
          crowdSpots.push(along === "x"
            ? { x: s + jitter, y: (i + 1) * h, z: dir * rowOff, along }
            : { x: dir * rowOff, y: (i + 1) * h, z: s + jitter, along });
        }
      }
    }
  };
  tierStand(L + 26, "x", W / 2 + 7, -1, 4);   // far stand
  tierStand(W + 20, "z", L / 2 + 8, -1, 3);   // left end
  tierStand(W + 20, "z", L / 2 + 8, 1, 3);    // right end

  const crowdGeo = new THREE.BoxGeometry(0.5, 0.75, 0.42);
  const crowd = new THREE.InstancedMesh(crowdGeo, new THREE.MeshLambertMaterial(), crowdSpots.length);
  const dummy = new THREE.Object3D();
  const crowdTeam = [];
  const colour = new THREE.Color();
  crowdSpots.forEach((s, i) => {
    // home fans everywhere, away fans packed in the right-end stand
    const awaySector = s.along === "z" && s.x > 0;
    const r = Math.random();
    let team = null;
    if (awaySector ? r < 0.6 : r < 0.35) team = awaySector ? app.away : app.home;
    crowdTeam.push(team);
    colour.set(team ? app.teams[team].colour : ["#22252b", "#2e3138", "#3d4047", "#8d8a83", "#1a1c21"][Math.floor(Math.random() * 5)]);
    colour.multiplyScalar(0.45);                         // a TV camera exposes for the pitch: the stands fall darker
    colour.multiplyScalar(team ? 0.35 + Math.random() * 0.3 : 0.5 + Math.random() * 0.4);
    crowd.setColorAt(i, colour);
    dummy.position.set(s.x, s.y + 0.38, s.z); dummy.updateMatrix(); crowd.setMatrixAt(i, dummy.matrix);
  });
  scene.add(crowd);
  let excitement = { team: null, until: 0 };

  /* floodlight pylons */
  const pylonMat = new THREE.MeshStandardMaterial({ color: 0x23262b });
  const lampMat = new THREE.MeshBasicMaterial({ color: 0xfff8e8 });
  for (const [sx, sz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) {
    const px = sx * (L / 2 + 22), pz = sz * (W / 2 + 26);
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.8, 42, 8), pylonMat);
    mast.position.set(px, 21, pz); scene.add(mast);
    const lamp = new THREE.Mesh(new THREE.BoxGeometry(7, 3.5, 0.6), lampMat);
    lamp.position.set(px, 43, pz); lamp.lookAt(0, 0, 0); scene.add(lamp);
  }

  /* ---------------------------------------------------------------- players & ball */
  const torsoGeo = new THREE.CapsuleGeometry(0.27, 0.42, 4, 10);
  const shortsGeo = new THREE.CylinderGeometry(0.27, 0.25, 0.3, 10);
  const legGeo = new THREE.CylinderGeometry(0.085, 0.07, 0.78, 6);
  legGeo.translate(0, -0.39, 0);               // pivot at the hip
  const headGeo = new THREE.SphereGeometry(0.19, 12, 10);
  const sockMat = new THREE.MeshStandardMaterial({ color: 0x111214, roughness: 0.8 });
  const shortsMat = { home: new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.7 }),
                      away: new THREE.MeshStandardMaterial({ color: 0xe9e7e1, roughness: 0.7 }) };
  const skins = [0xe0b48f, 0xc68d61, 0x8d5a3b, 0xf1caa7, 0x6b4430].map((c) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7 }));
  const kit = {};
  const kitFor = (team, gk) => {
    const k = `${team}${gk ? "gk" : ""}`;
    if (!kit[k]) kit[k] = new THREE.MeshStandardMaterial({ color: gk ? 0xd9d7d0 : app.teams[team].colour, roughness: 0.55 });
    return kit[k];
  };
  const meshes = {};
  const playerMesh = (pid) => {
    if (meshes[pid]) return meshes[pid];
    const info = app.roster[pid];
    const g = new THREE.Group();
    const torso = new THREE.Mesh(torsoGeo, kitFor(info.team, info.position === "GK"));
    torso.position.y = 1.28; torso.castShadow = true;
    const shorts = new THREE.Mesh(shortsGeo, shortsMat[info.team === app.home ? "home" : "away"]);
    shorts.position.y = 0.93; shorts.castShadow = true;
    const legs = [-0.12, 0.12].map((x) => {
      const leg = new THREE.Mesh(legGeo, sockMat);
      leg.position.set(x, 0.8, 0); leg.castShadow = true;
      return leg;
    });
    const head = new THREE.Mesh(headGeo, skins[info.number % skins.length]);
    head.position.y = 1.82; head.castShadow = true;
    g.add(torso, shorts, ...legs, head);
    g.userData.legs = legs;
    g.userData.phase = Math.random() * Math.PI * 2;
    g.scale.setScalar(PLAYER_SCALE);
    scene.add(g);
    meshes[pid] = g;
    return g;
  };

  const ball = new THREE.Mesh(new THREE.SphereGeometry(0.3, 18, 14), new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.35 }));
  ball.castShadow = true;
  scene.add(ball);
  const ring = new THREE.Mesh(new THREE.RingGeometry(1.0, 1.25, 32), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.03;
  scene.add(ring);

  /* ---------------------------------------------------------------- player focus */
  const favCanvas = document.createElement("canvas");
  favCanvas.width = 512; favCanvas.height = 128;
  const favTex = new THREE.CanvasTexture(favCanvas);
  favTex.colorSpace = THREE.SRGBColorSpace;
  const favLabel = new THREE.Sprite(new THREE.SpriteMaterial({ map: favTex, depthTest: false, transparent: true }));
  favLabel.scale.set(7, 1.75, 1);
  favLabel.renderOrder = 10;
  const favRing = new THREE.Mesh(new THREE.RingGeometry(1.35, 1.7, 40), new THREE.MeshBasicMaterial({ color: 0xffb000 }));
  favRing.rotation.x = -Math.PI / 2; favRing.position.y = 0.035;
  scene.add(favLabel, favRing);
  // the player named by the lower third: a ring in their team's colour while the graphic is on screen
  const tagRing = new THREE.Mesh(new THREE.RingGeometry(1.5, 1.95, 40), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true }));
  tagRing.rotation.x = -Math.PI / 2; tagRing.position.y = 0.04;
  scene.add(tagRing);
  let favourite = null;
  function setFavourite(pid) {
    favourite = pid;
    if (!pid || !app.roster[pid]) return;
    const g = favCanvas.getContext("2d");
    g.clearRect(0, 0, 512, 128);
    g.fillStyle = "#ffb000"; g.fillRect(0, 18, 512, 92);
    g.fillStyle = "#0a0a0a"; g.font = "700 60px 'IBM Plex Sans Condensed', sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(`★ ${app.roster[pid].name.split(" ").at(-1).toUpperCase()}`, 256, 66);
    favTex.needsUpdate = true;
  }

  /* ---------------------------------------------------------------- camera director */
  const cam = { mode: "main", x: 0, fov: 24, side: 1 };
  function setCamera(mode, opts = {}) {   // a cut, as in a real gallery: no zoom from one camera to the other
    cam.mode = mode;
    if (opts.side) cam.side = opts.side;
    if (mode === "goal") camera.position.set(cam.side * (L / 2 + 6.5), 7.5, toZ(app.ball.y) * 0.3);
    camera.fov = mode === "goal" ? 48 : 24 * frameFit();
  }
  // a taller screen shows more beyond the near touchline: zoom in a little to keep the pitch filling it
  const frameFit = () => Math.max(0.8, Math.min(1, camera.aspect / 2.3));

  function directCamera(dt) {
    const bx = toX(app.ball.x), bz = toZ(app.ball.y);
    const k = 1 - Math.exp(-dt * 1.7);
    if (cam.mode === "goal") {
      // behind the attacked goal, above the LED boards and in front of the stand
      const gx = cam.side * (L / 2 + 6.5);
      camera.position.lerp(new THREE.Vector3(gx, 7.5, bz * 0.3), k * 2);
      camera.fov += (48 - camera.fov) * k;
      camera.lookAt(cam.side * 28, 0.5, bz * 0.45);
    } else {
      const tx = Math.max(-34, Math.min(34, bx * 0.88));
      cam.x += (tx - cam.x) * k;
      const inBox = Math.abs(bx) > 36;
      camera.fov += ((inBox ? 20.5 : 24) * frameFit() - camera.fov) * k * 0.6;
      camera.position.set(cam.x * 0.92, 27, 88);
      camera.lookAt(cam.x, 0, 3 + bz * 0.12);
    }
    camera.updateProjectionMatrix();
  }

  /* ---------------------------------------------------------------- celebration */
  function celebrate(team) {
    excitement = { team, until: performance.now() + 5000 };
    paintLed(app.teams[team].colour, "#0a0a0a", "GOAL");
    setTimeout(() => paintLed("#05060a", "#9a988f", "COMEBACK"), 5000);
  }

  function animateCrowd(now) {
    if (!excitement.team && now > excitement.until) return;
    const active = now < excitement.until;
    crowdSpots.forEach((s, i) => {
      const jump = active && crowdTeam[i] === excitement.team ? Math.abs(Math.sin(now / 130 + i * 1.7)) * 0.6 : 0;
      dummy.position.set(s.x, s.y + 0.38 + jump, s.z); dummy.updateMatrix(); crowd.setMatrixAt(i, dummy.matrix);
    });
    crowd.instanceMatrix.needsUpdate = true;
    if (!active) excitement.team = null;
  }

  /* ---------------------------------------------------------------- frame */
  let ledOffset = 0;
  function render(dt) {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== Math.round(w * renderer.getPixelRatio()) || canvas.height !== Math.round(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
    }
    const seen = new Set();
    for (const [pid, p] of Object.entries(app.pos)) {
      if (!app.roster[pid]) continue;
      const m = playerMesh(pid);
      m.visible = true;
      seen.add(pid);
      const speed = Math.hypot(p.vx, p.vy);
      const stride = Math.min(1, speed / 6);
      m.userData.phase += dt * (4 + speed * 1.6);
      const swing = Math.sin(m.userData.phase) * 0.75 * stride;
      m.userData.legs[0].rotation.x = swing; m.userData.legs[1].rotation.x = -swing;
      m.position.set(toX(p.x), Math.abs(Math.sin(m.userData.phase)) * 0.06 * stride, toZ(p.y));
      if (speed > 0.3) {
        const target = Math.atan2(p.vx, -p.vy);
        const d = target - m.rotation.y;
        m.rotation.y += Math.atan2(Math.sin(d), Math.cos(d)) * Math.min(1, dt * 8);
      }
    }
    for (const pid of Object.keys(meshes)) if (!seen.has(pid)) meshes[pid].visible = false;

    ball.position.set(toX(app.ball.x), 0.3 + app.ball.z, toZ(app.ball.y));
    const fp = favourite && app.pos[favourite];
    favLabel.visible = favRing.visible = Boolean(fp);
    if (fp) {
      favLabel.position.set(toX(fp.x), 4.3, toZ(fp.y));
      favRing.position.x = toX(fp.x); favRing.position.z = toZ(fp.y);
      favRing.material.color.set(app.teams[app.roster[favourite].team].colour);
    }
    const tag = app.tagged && performance.now() < app.tagged.until && app.pos[app.tagged.pid];
    tagRing.visible = Boolean(tag);
    if (tag) {
      tagRing.position.x = toX(tag.x); tagRing.position.z = toZ(tag.y);
      tagRing.material.color.set(app.teams[app.roster[app.tagged.pid].team].colour);
      tagRing.material.opacity = 0.65 + 0.35 * Math.sin(performance.now() / 160);
    }
    const holder = app.holder && app.pos[app.holder];
    ring.visible = Boolean(holder);
    if (holder) {
      ring.position.x = toX(holder.x); ring.position.z = toZ(holder.y);
      ring.material.color.set(app.teams[app.roster[app.holder].team].colour);
    }
    ledOffset = (ledOffset + dt * 0.04) % 1;
    ledTex.offset.x = ledOffset;
    animateCrowd(performance.now());
    directCamera(dt);
    renderer.render(scene, camera);
  }

  return { render, setCamera, celebrate, setFavourite };
}

/* Mowing stripes and line markings, drawn once into a texture (20 px per metre). */
function pitchCanvas() {
  const ppm = 20, pad = 4;
  const c = document.createElement("canvas");
  c.width = (L + 2 * pad) * ppm; c.height = (W + 2 * pad) * ppm;
  const g = c.getContext("2d");
  const X = (x) => (x + pad) * ppm, Y = (y) => (W - y + pad) * ppm;
  g.fillStyle = "#1d5a2c"; g.fillRect(0, 0, c.width, c.height);
  for (let i = 0; i < 18; i++) {
    g.fillStyle = i % 2 ? "#226734" : "#1c5a2b";
    g.fillRect(X(-pad + (i * (L + 2 * pad)) / 18), 0, ((L + 2 * pad) / 18) * ppm + 1, c.height);
  }
  for (let i = 0; i < 9000; i++) {   // grain
    g.fillStyle = `rgba(${Math.random() < 0.5 ? "0,0,0" : "255,255,255"},0.035)`;
    g.fillRect(Math.random() * c.width, Math.random() * c.height, 2, 2);
  }
  g.strokeStyle = "rgba(245,245,240,.9)"; g.lineWidth = 0.14 * ppm;
  const rect = (x, y, w, h) => g.strokeRect(X(x), Y(y + h), w * ppm, h * ppm);
  rect(0, 0, L, W);
  g.beginPath(); g.moveTo(X(L / 2), Y(0)); g.lineTo(X(L / 2), Y(W)); g.stroke();
  g.beginPath(); g.arc(X(L / 2), Y(W / 2), 9.15 * ppm, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "rgba(245,245,240,.9)";
  g.beginPath(); g.arc(X(L / 2), Y(W / 2), 0.25 * ppm, 0, Math.PI * 2); g.fill();
  for (const left of [true, false]) {
    rect(left ? 0 : L - 16.5, W / 2 - 20.16, 16.5, 40.32);
    rect(left ? 0 : L - 5.5, W / 2 - 9.16, 5.5, 18.32);
    const px = left ? 11 : L - 11;
    g.beginPath(); g.arc(X(px), Y(W / 2), 0.25 * ppm, 0, Math.PI * 2); g.fill();
    g.beginPath();
    const a = 0.927;
    if (left) g.arc(X(px), Y(W / 2), 9.15 * ppm, -a, a); else g.arc(X(px), Y(W / 2), 9.15 * ppm, Math.PI - a, Math.PI + a);
    g.stroke();
  }
  g.save();
  g.beginPath(); g.rect(X(0), Y(W), L * ppm, W * ppm); g.clip();   // corner arcs stay inside the pitch
  for (const [cx, cy] of [[0, 0], [L, 0], [0, W], [L, W]]) {
    g.beginPath(); g.arc(X(cx), Y(cy), 1 * ppm, 0, Math.PI * 2); g.stroke();
  }
  g.restore();
  return c;
}
