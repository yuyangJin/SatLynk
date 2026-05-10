"""Generate the OASIS 3D visualization HTML file — responsive (desktop + mobile landscape)."""

import json
import sys
sys.path.insert(0, '/workspace')


def generate_html(sim_data_path: str, output_path: str):
    with open(sim_data_path) as f:
        sim_data = json.load(f)
    
    sim_json = json.dumps(sim_data, separators=(',', ':'))
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>OASIS — Simulation Playback</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ background: #0a0e1a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; height: 100%; width: 100%; touch-action: none; }}

/* === LAYOUT === */
#app {{ display: flex; flex-direction: column; height: 100%; width: 100%; }}
#main {{ display: flex; flex: 1; min-height: 0; position: relative; }}
#canvas-container {{ flex: 1; min-width: 0; position: relative; }}
#canvas-container canvas {{ display: block; width: 100% !important; height: 100% !important; }}

/* Sidebar — desktop */
#sidebar {{ width: 240px; background: #111827; border-left: 1px solid #1f2937; overflow-y: auto; padding: 10px; font-size: 12px; flex-shrink: 0; }}

/* Timeline — bottom bar */
#timeline {{ background: #111827; border-top: 1px solid #1f2937; padding: 8px 12px; flex-shrink: 0; }}

/* === OVERLAYS === */
#time-display {{ position: absolute; top: 8px; left: 10px; background: rgba(0,0,0,0.75); padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 13px; z-index: 10; pointer-events: none; }}
#camera-mode {{ position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.75); padding: 4px 6px; border-radius: 4px; font-size: 11px; z-index: 10; display: flex; gap: 2px; }}
#camera-mode button {{ background: #1f2937; border: 1px solid #374151; color: #9ca3af; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; -webkit-tap-highlight-color: transparent; }}
#camera-mode button.active {{ background: #3b82f6; border-color: #3b82f6; color: #fff; }}
#legend {{ position: absolute; bottom: 6px; left: 10px; background: rgba(0,0,0,0.75); padding: 4px 10px; border-radius: 4px; font-size: 10px; z-index: 10; pointer-events: none; display: flex; gap: 8px; flex-wrap: wrap; }}
.legend-item {{ display: flex; align-items: center; gap: 3px; white-space: nowrap; }}
.legend-dot {{ width: 7px; height: 7px; border-radius: 50%; }}

/* Toggle sidebar button (mobile) */
#sidebar-toggle {{ display: none; position: absolute; top: 8px; right: 8px; z-index: 20; background: rgba(0,0,0,0.75); border: 1px solid #374151; color: #d1d5db; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }}

/* === SIDEBAR CONTENT === */
.panel-section {{ margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #1f2937; }}
.panel-title {{ font-size: 10px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.sat-item {{ padding: 4px 6px; border-radius: 3px; margin-bottom: 2px; cursor: pointer; display: flex; align-items: center; gap: 5px; font-size: 11px; }}
.sat-item:hover {{ background: #1f2937; }}
.sat-item.selected {{ background: #1e3a5f; }}
.sat-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.event-log {{ font-family: monospace; font-size: 10px; line-height: 1.5; max-height: 160px; overflow-y: auto; }}
.event-log .ev {{ padding: 2px 3px; border-radius: 2px; margin-bottom: 1px; }}
.event-log .ev.active {{ background: #1e3a5f; }}

/* === TIMELINE === */
#controls {{ display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }}
#controls button {{ background: #1f2937; border: 1px solid #374151; color: #d1d5db; padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 13px; min-width: 34px; min-height: 30px; -webkit-tap-highlight-color: transparent; }}
#controls button:active {{ background: #374151; }}
#controls button.playing {{ background: #3b82f6; border-color: #3b82f6; color: #fff; }}
#speed-display {{ font-size: 11px; color: #9ca3af; }}
#time-info {{ font-family: monospace; font-size: 12px; color: #9ca3af; margin-left: auto; }}
#slider-container {{ position: relative; height: 28px; }}
#time-slider {{ width: 100%; height: 8px; -webkit-appearance: none; appearance: none; background: #1f2937; border-radius: 4px; outline: none; cursor: pointer; margin-top: 10px; }}
#time-slider::-webkit-slider-thumb {{ -webkit-appearance: none; width: 18px; height: 18px; background: #3b82f6; border-radius: 50%; cursor: pointer; }}
#time-slider::-moz-range-thumb {{ width: 18px; height: 18px; background: #3b82f6; border-radius: 50%; cursor: pointer; border: none; }}
#event-markers {{ position: absolute; top: 4px; left: 0; right: 0; height: 6px; pointer-events: none; }}
.event-marker {{ position: absolute; width: 5px; height: 5px; border-radius: 50%; transform: translateX(-50%); }}

/* === MOBILE LANDSCAPE === */
@media (max-width: 900px) {{
  #sidebar {{ display: none; position: absolute; top: 0; right: 0; bottom: 0; width: 220px; z-index: 30; border-left: 1px solid #1f2937; }}
  #sidebar.open {{ display: block; }}
  #sidebar-toggle {{ display: block; }}
  #camera-mode {{ right: auto; left: 50%; transform: translateX(-50%); top: auto; bottom: 6px; }}
  #legend {{ bottom: auto; top: 8px; left: 50%; transform: translateX(-50%); font-size: 9px; }}
  #time-display {{ font-size: 12px; }}
  #timeline {{ padding: 6px 10px; }}
  #controls button {{ min-height: 28px; padding: 4px 8px; }}
  #time-slider::-webkit-slider-thumb {{ width: 22px; height: 22px; }}
  #time-slider::-moz-range-thumb {{ width: 22px; height: 22px; }}
}}

@media (max-width: 600px) {{
  #legend {{ display: none; }}
  #timeline {{ padding: 5px 8px; }}
  #time-info {{ font-size: 10px; }}
}}

/* Force landscape prompt for portrait mobile */
@media (orientation: portrait) and (max-width: 600px) {{
  #rotate-prompt {{ display: flex !important; }}
}}
#rotate-prompt {{ display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: #0a0e1a; z-index: 9999; align-items: center; justify-content: center; flex-direction: column; gap: 12px; }}
#rotate-prompt svg {{ width: 48px; height: 48px; color: #6b7280; }}
#rotate-prompt p {{ color: #9ca3af; font-size: 14px; }}
</style>
</head>
<body>

<div id="rotate-prompt">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.5 1.5H8.25A2.25 2.25 0 006 3.75v16.5a2.25 2.25 0 002.25 2.25h7.5A2.25 2.25 0 0018 20.25V3.75a2.25 2.25 0 00-2.25-2.25H13.5m-3 0V3h3V1.5m-3 0h3"/><path d="M3.75 12l2.25-2.25M3.75 12l2.25 2.25M3.75 12H9"/></svg>
  <p>Please rotate to landscape</p>
</div>

<div id="app">
  <div id="main">
    <div id="canvas-container">
      <div id="time-display">t = 0.0s</div>
      <div id="camera-mode">
        <button class="active" onclick="setCameraMode('free')">Free</button>
        <button onclick="setCameraMode('fixed')">Fixed</button>
        <button onclick="setCameraMode('track')">Track</button>
      </div>
      <div id="legend">
        <span class="legend-item"><span class="legend-dot" style="background:#4299e1"></span>Detector</span>
        <span class="legend-item"><span class="legend-dot" style="background:#48bb78"></span>Compute</span>
        <span class="legend-item"><span class="legend-dot" style="background:#ed8936"></span>Relay</span>
        <span class="legend-item"><span class="legend-dot" style="background:#f6e05e"></span>Data flow</span>
      </div>
    </div>

    <button id="sidebar-toggle" onclick="toggleSidebar()">☰</button>

    <div id="sidebar">
      <div class="panel-section">
        <div class="panel-title">Scenario</div>
        <div id="scenario-info" style="color:#d1d5db;"></div>
      </div>
      <div class="panel-section">
        <div class="panel-title">Satellites</div>
        <div id="sat-list" style="max-height:150px;overflow-y:auto;"></div>
      </div>
      <div class="panel-section">
        <div class="panel-title">Selected</div>
        <div id="node-info" style="color:#6b7280;">Tap a satellite</div>
      </div>
      <div class="panel-section">
        <div class="panel-title">Events</div>
        <div class="event-log" id="event-log"></div>
      </div>
    </div>
  </div>

  <div id="timeline">
    <div id="controls">
      <button onclick="skipToStart()">⏮</button>
      <button id="play-btn" onclick="togglePlay()">▶</button>
      <button onclick="skipToEnd()">⏭</button>
      <button onclick="changeSpeed()"><span id="speed-display">1×</span></button>
      <div id="time-info">0.0 / <span id="duration-display">0</span>s</div>
    </div>
    <div id="slider-container">
      <div id="event-markers"></div>
      <input type="range" id="time-slider" min="0" max="100" step="0.1" value="0" oninput="onSliderInput(this.value)">
    </div>
  </div>
</div>

<script type="importmap">
{{
  "imports": {{
    "three": "https://unpkg.com/three@0.160.0/build/three.module.js",
    "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"
  }}
}}
</script>

<script type="module">
import * as THREE from 'three';
import {{ OrbitControls }} from 'three/addons/controls/OrbitControls.js';

const SIM = {sim_json};

const EARTH_RADIUS = 6371;
const SCALE = 1 / 1000;
const R = EARTH_RADIUS * SCALE;

let currentTime = 0, playing = false, speed = 1, selectedSat = -1;
let cameraMode = 'free', trackTarget = -1;
const speeds = [0.5, 1, 2, 5, 10, 20, 50];
let speedIdx = 1;

// Scene
const container = document.getElementById('canvas-container');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(50, 1, 0.01, 200);
camera.position.set(0, 8, 18);
const renderer = new THREE.WebGLRenderer({{ antialias: true, alpha: true }});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
container.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.minDistance = R * 1.3;
controls.maxDistance = 60;
controls.touches = {{ ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }};

function resize() {{
  const w = container.clientWidth, h = container.clientHeight;
  if (w === 0 || h === 0) return;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}}
resize();
window.addEventListener('resize', resize);
setTimeout(resize, 100);

// Earth
const earthGeo = new THREE.SphereGeometry(R, 48, 48);
const earthMat = new THREE.MeshPhongMaterial({{ color: 0x1a365d, emissive: 0x0a1628, shininess: 5, transparent: true, opacity: 0.92 }});
scene.add(new THREE.Mesh(earthGeo, earthMat));
const wireGeo = new THREE.SphereGeometry(R * 1.002, 32, 32);
scene.add(new THREE.Mesh(wireGeo, new THREE.MeshBasicMaterial({{ color: 0x2d3748, wireframe: true, transparent: true, opacity: 0.12 }})));

// Equator
const eqGeo = new THREE.RingGeometry(R * 1.003, R * 1.005, 64);
const eq = new THREE.Mesh(eqGeo, new THREE.MeshBasicMaterial({{ color: 0x4a5568, side: THREE.DoubleSide, transparent: true, opacity: 0.25 }}));
eq.rotation.x = Math.PI / 2;
scene.add(eq);

// Light
scene.add(new THREE.AmbientLight(0x404060, 0.5));
const sun = new THREE.DirectionalLight(0xffffff, 1.0);
sun.position.set(10, 5, 10);
scene.add(sun);

// Stars
const starsGeo = new THREE.BufferGeometry();
const sv = [];
for (let i = 0; i < 1500; i++) {{ const r=80+Math.random()*40,t=Math.random()*Math.PI*2,p=Math.acos(2*Math.random()-1); sv.push(r*Math.sin(p)*Math.cos(t),r*Math.sin(p)*Math.sin(t),r*Math.cos(p)); }}
starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(sv, 3));
scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({{ color: 0xffffff, size: 0.08 }})));

// Satellites
const satMeshes = [];
const orbitLines = [];

SIM.satellites.forEach((sat, i) => {{
  const size = sat.role === 'relay' ? 0.18 : sat.role === 'compute' ? 0.14 : 0.12;
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(size, 10, 10),
    new THREE.MeshBasicMaterial({{ color: sat.color }})
  );
  scene.add(mesh);
  satMeshes.push(mesh);
  
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(size * 1.8, 10, 10),
    new THREE.MeshBasicMaterial({{ color: sat.color, transparent: true, opacity: 0.15 }})
  );
  mesh.add(glow);
  
  const pts = computeOrbitPath(sat.orbit, 80);
  const line = new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({{ color: sat.color, transparent: true, opacity: 0.08 }})
  );
  scene.add(line);
  orbitLines.push(line);
}});

function computeOrbitPath(orbit, segs) {{
  const a = orbit.semi_major_axis_km * SCALE;
  const i = orbit.inclination_deg * Math.PI / 180;
  const raan = orbit.raan_deg * Math.PI / 180;
  const pts = [];
  for (let s = 0; s <= segs; s++) {{
    const nu = (s / segs) * Math.PI * 2;
    const xo = a * Math.cos(nu), yo = a * Math.sin(nu);
    const x = xo * Math.cos(raan) - yo * Math.sin(raan) * Math.cos(i);
    const y = xo * Math.sin(raan) + yo * Math.cos(raan) * Math.cos(i);
    const z = yo * Math.sin(i);
    pts.push(new THREE.Vector3(x, z, -y));
  }}
  return pts;
}}

// Links
const linkLines = [];
SIM.contact_windows.forEach(w => {{
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute([0,0,0,0,0,0], 3));
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({{ color: 0x4a5568, transparent: true, opacity: 0.3 }}));
  line.visible = false;
  scene.add(line);
  linkLines.push({{ line, window: w }});
}});

// Transfer particles
const pGeo = new THREE.SphereGeometry(0.07, 6, 6);
const pMats = {{ input: 0xf6e05e, relay: 0xed8936, result_direct: 0x48bb78, weight: 0x9f7aea }};
const particles = SIM.transfers.map(xfer => {{
  const mesh = new THREE.Mesh(pGeo, new THREE.MeshBasicMaterial({{ color: pMats[xfer.purpose] || 0xf6e05e }}));
  mesh.visible = false;
  scene.add(mesh);
  return {{ mesh, transfer: xfer }};
}});

// Position interpolation
function getSatPos(idx, t) {{
  const times = SIM.positions.times, data = SIM.positions.data[idx];
  if (!data || data.length === 0) return new THREE.Vector3();
  if (t <= times[0]) {{ const p=data[0]; return new THREE.Vector3(p[0]*SCALE, p[2]*SCALE, -p[1]*SCALE); }}
  const last = times.length-1;
  if (t >= times[last]) {{ const p=data[last]; return new THREE.Vector3(p[0]*SCALE, p[2]*SCALE, -p[1]*SCALE); }}
  let lo=0, hi=last;
  while(hi-lo>1){{ const m=(lo+hi)>>1; if(times[m]<=t)lo=m; else hi=m; }}
  const f=(t-times[lo])/(times[hi]-times[lo]);
  const a=data[lo], b=data[hi];
  return new THREE.Vector3(
    (a[0]+(b[0]-a[0])*f)*SCALE,
    (a[2]+(b[2]-a[2])*f)*SCALE,
    -(a[1]+(b[1]-a[1])*f)*SCALE
  );
}}

function updateScene(t) {{
  satMeshes.forEach((mesh, i) => {{
    mesh.position.copy(getSatPos(i, t));
    const computing = SIM.compute_jobs.some(j => j.node === i && t >= j.start && t <= j.end);
    const glow = mesh.children[0];
    if (glow) {{
      glow.material.opacity = computing ? 0.3 + 0.15 * Math.sin(t * 6) : 0.12;
      glow.scale.setScalar(computing ? 1.6 : 1.0);
    }}
  }});

  linkLines.forEach(ll => {{
    const w = ll.window;
    const active = t >= w.start && t < w.end;
    ll.line.visible = active;
    if (active) {{
      const pA = satMeshes[w.src].position, pB = satMeshes[w.dst].position;
      const pos = ll.line.geometry.attributes.position;
      pos.setXYZ(0, pA.x, pA.y, pA.z);
      pos.setXYZ(1, pB.x, pB.y, pB.z);
      pos.needsUpdate = true;
      const hasXfer = SIM.transfers.some(x => ((x.src===w.src&&x.dst===w.dst)||(x.src===w.dst&&x.dst===w.src)) && t>=x.start && t<=x.end);
      ll.line.material.opacity = hasXfer ? 0.85 : 0.25;
      ll.line.material.color.set(hasXfer ? 0xf6e05e : 0x4a5568);
    }}
  }});

  particles.forEach(tp => {{
    const x = tp.transfer;
    const active = t >= x.start && t <= x.end;
    tp.mesh.visible = active;
    if (active) {{
      const p = (t - x.start) / (x.end - x.start);
      tp.mesh.position.lerpVectors(satMeshes[x.src].position, satMeshes[x.dst].position, p);
      tp.mesh.position.y += Math.sin(p * Math.PI) * 0.08;
    }}
  }});

  if (cameraMode === 'track' && trackTarget >= 0) {{
    const sp = satMeshes[trackTarget].position;
    const lon = Math.atan2(-sp.z, sp.x);
    const dist = camera.position.length();
    const lat = Math.asin(camera.position.y / Math.max(dist, 0.01));
    camera.position.set(dist*Math.cos(lat)*Math.cos(lon+0.4), camera.position.y, -dist*Math.cos(lat)*Math.sin(lon+0.4));
    camera.lookAt(0, 0, 0);
  }}
}}

// UI
const duration = SIM.scenario.duration_s;
document.getElementById('duration-display').textContent = duration.toFixed(0);
document.getElementById('scenario-info').innerHTML = `${{SIM.scenario.name}}<br>${{SIM.satellites.length}} sats, ${{duration}}s`;
document.getElementById('time-slider').max = duration;

const satListEl = document.getElementById('sat-list');
SIM.satellites.forEach((sat, i) => {{
  const el = document.createElement('div');
  el.className = 'sat-item';
  el.innerHTML = `<span class="sat-dot" style="background:${{sat.color}}"></span>${{sat.id}}`;
  el.onclick = () => selectSatellite(i);
  satListEl.appendChild(el);
}});

const markersEl = document.getElementById('event-markers');
const evColors = {{ task_arrive:'#4299e1', compute_start:'#48bb78', compute_done:'#48bb78', transfer_done:'#f6e05e', task_complete:'#10b981', transfer_start:'#ed8936' }};
SIM.events.forEach(ev => {{
  const dot = document.createElement('div');
  dot.className = 'event-marker';
  dot.style.left = (ev.t/duration*100)+'%';
  dot.style.background = evColors[ev.type]||'#6b7280';
  markersEl.appendChild(dot);
}});

const eventLogEl = document.getElementById('event-log');
SIM.events.forEach((ev, i) => {{
  const div = document.createElement('div');
  div.className = 'ev'; div.id = `ev-${{i}}`;
  div.innerHTML = `<span style="color:#6b7280">${{ev.t.toFixed(1)}}</span> ${{ev.detail}}`;
  eventLogEl.appendChild(div);
}});

function updateEventLog(t) {{
  document.querySelectorAll('.event-log .ev').forEach(el => el.classList.remove('active'));
  for (let i = SIM.events.length-1; i >= 0; i--) {{
    if (SIM.events[i].t <= t) {{
      const el = document.getElementById(`ev-${{i}}`);
      if (el) {{ el.classList.add('active'); el.scrollIntoView({{block:'nearest'}}); }}
      break;
    }}
  }}
}}

function selectSatellite(i) {{
  selectedSat = i;
  document.querySelectorAll('.sat-item').forEach((el, idx) => el.classList.toggle('selected', idx===i));
  orbitLines.forEach((l, idx) => {{ l.material.opacity = idx===i ? 0.4 : 0.08; }});
  const sat = SIM.satellites[i];
  document.getElementById('node-info').innerHTML = `<strong style="color:${{sat.color}}">${{sat.id}}</strong> (${{sat.role}})<br>FLOPS: ${{sat.compute_flops > 0 ? (sat.compute_flops/1e9).toFixed(0)+'G':'—'}}<br><span id="node-batt">Battery: —</span>`;
  if (cameraMode === 'track') trackTarget = i;
}}

function updateUI() {{
  document.getElementById('time-display').textContent = `t = ${{currentTime.toFixed(1)}}s`;
  document.getElementById('time-slider').value = currentTime;
  document.getElementById('time-info').textContent = `${{currentTime.toFixed(1)}} / ${{duration.toFixed(0)}}s`;
  updateEventLog(currentTime);
  if (selectedSat >= 0) {{
    const times = SIM.energy.times, data = SIM.energy.data[String(selectedSat)];
    if (data) {{
      let idx=0; for(let i=0;i<times.length;i++){{ if(times[i]<=currentTime) idx=i; }}
      const el = document.getElementById('node-batt');
      if(el) el.textContent = `Battery: ${{data[idx]?.toFixed(1)||'—'}}%`;
    }}
  }}
}}

// Controls
window.togglePlay = function() {{
  playing = !playing;
  const btn = document.getElementById('play-btn');
  btn.textContent = playing ? '⏸' : '▶';
  btn.classList.toggle('playing', playing);
  if (cameraMode === 'fixed') controls.enabled = !playing;
}};
window.skipToStart = () => {{ currentTime = 0; updateUI(); }};
window.skipToEnd = () => {{ currentTime = duration; updateUI(); }};
window.changeSpeed = () => {{ speedIdx = (speedIdx+1)%speeds.length; speed = speeds[speedIdx]; document.getElementById('speed-display').textContent = speed+'×'; }};
window.onSliderInput = (v) => {{ currentTime = parseFloat(v); updateUI(); }};
window.setCameraMode = function(mode) {{
  cameraMode = mode;
  document.querySelectorAll('#camera-mode button').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  controls.enabled = mode === 'free' || (mode === 'fixed' && !playing);
  if (mode === 'track') {{ controls.enabled = false; trackTarget = selectedSat >= 0 ? selectedSat : 0; }}
}};
window.toggleSidebar = () => {{ document.getElementById('sidebar').classList.toggle('open'); }};

document.addEventListener('keydown', e => {{
  if (e.code === 'Space') {{ e.preventDefault(); togglePlay(); }}
  if (e.code === 'ArrowRight') {{ currentTime = Math.min(currentTime+1, duration); updateUI(); }}
  if (e.code === 'ArrowLeft') {{ currentTime = Math.max(currentTime-1, 0); updateUI(); }}
}});

// Animation loop
let lastFrame = performance.now();
function animate() {{
  requestAnimationFrame(animate);
  const now = performance.now(), dt = (now - lastFrame) / 1000;
  lastFrame = now;
  if (playing) {{
    currentTime += dt * speed;
    if (currentTime >= duration) {{ currentTime = duration; playing = false; document.getElementById('play-btn').textContent = '▶'; document.getElementById('play-btn').classList.remove('playing'); }}
    updateUI();
  }}
  updateScene(currentTime);
  if (cameraMode !== 'track') controls.update();
  renderer.render(scene, camera);
}}
animate();
updateUI();
</script>
</body>
</html>'''
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Generated: {output_path} ({len(html)/1024:.1f} KB)")


if __name__ == "__main__":
    generate_html(
        "/workspace/oasis/viz/50sat_export.json",
        "/workspace/site/index.html"
    )
