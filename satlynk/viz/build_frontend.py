"""Generate the SatLynk 3D visualization HTML file — v2 with raycaster + terrain globe."""

import json
import os


def generate_html(sim_data_path: str, output_path: str):
    with open(sim_data_path) as f:
        sim_data = json.load(f)
    
    sim_json = json.dumps(sim_data, separators=(',', ':'))
    
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>SatLynk — Simulation Playback</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ background: #0a0e1a; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; overflow: hidden; height: 100%; width: 100%; touch-action: none; }}

#app {{ display: flex; flex-direction: column; height: 100%; width: 100%; }}
#main {{ display: flex; flex: 1; min-height: 0; position: relative; }}
#canvas-container {{ flex: 1; min-width: 0; position: relative; cursor: default; }}
#canvas-container canvas {{ display: block; width: 100% !important; height: 100% !important; }}
#canvas-container.hovering {{ cursor: pointer; }}

#sidebar {{ width: 260px; background: #111827; border-left: 1px solid #1f2937; overflow-y: auto; padding: 10px; font-size: 12px; flex-shrink: 0; }}
#timeline {{ background: #111827; border-top: 1px solid #1f2937; padding: 8px 12px; flex-shrink: 0; }}

#time-display {{ position: absolute; top: 8px; left: 10px; background: rgba(0,0,0,0.75); padding: 4px 10px; border-radius: 4px; font-family: monospace; font-size: 13px; z-index: 10; pointer-events: none; }}
#camera-mode {{ position: absolute; top: 8px; right: 8px; background: rgba(0,0,0,0.75); padding: 4px 6px; border-radius: 4px; font-size: 11px; z-index: 10; display: flex; gap: 2px; }}
#camera-mode button {{ background: #1f2937; border: 1px solid #374151; color: #9ca3af; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; }}
#camera-mode button.active {{ background: #3b82f6; border-color: #3b82f6; color: #fff; }}

#globe-mode {{ position: absolute; top: 40px; right: 8px; background: rgba(0,0,0,0.75); padding: 4px 6px; border-radius: 4px; font-size: 11px; z-index: 10; display: flex; gap: 2px; }}
#globe-mode button {{ background: #1f2937; border: 1px solid #374151; color: #9ca3af; padding: 4px 10px; border-radius: 3px; cursor: pointer; font-size: 11px; }}
#globe-mode button.active {{ background: #10b981; border-color: #10b981; color: #fff; }}

#legend {{ position: absolute; bottom: 6px; left: 10px; background: rgba(0,0,0,0.75); padding: 4px 10px; border-radius: 4px; font-size: 10px; z-index: 10; pointer-events: none; display: flex; gap: 8px; flex-wrap: wrap; }}
.legend-item {{ display: flex; align-items: center; gap: 3px; white-space: nowrap; }}
.legend-dot {{ width: 7px; height: 7px; border-radius: 50%; }}

#sidebar-toggle {{ display: none; position: absolute; top: 8px; right: 8px; z-index: 20; background: rgba(0,0,0,0.75); border: 1px solid #374151; color: #d1d5db; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }}

.panel-section {{ margin-bottom: 10px; padding-bottom: 8px; border-bottom: 1px solid #1f2937; }}
.panel-title {{ font-size: 10px; color: #6b7280; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }}
.sat-item {{ padding: 4px 6px; border-radius: 3px; margin-bottom: 2px; cursor: pointer; display: flex; align-items: center; gap: 5px; font-size: 11px; }}
.sat-item:hover {{ background: #1f2937; }}
.sat-item.selected {{ background: #1e3a5f; }}
.sat-dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}

.sat-detail {{ font-size: 11px; line-height: 1.6; color: #d1d5db; }}
.sat-detail .label {{ color: #6b7280; font-size: 10px; }}
.sat-detail .value {{ color: #e2e8f0; font-family: monospace; }}

.event-log {{ font-family: monospace; font-size: 10px; line-height: 1.5; max-height: 160px; overflow-y: auto; }}
.event-log .ev {{ padding: 2px 3px; border-radius: 2px; margin-bottom: 1px; }}
.event-log .ev.active {{ background: #1e3a5f; }}

#controls {{ display: flex; align-items: center; gap: 6px; margin-bottom: 5px; }}
#controls button {{ background: #1f2937; border: 1px solid #374151; color: #d1d5db; padding: 5px 10px; border-radius: 4px; cursor: pointer; font-size: 13px; min-width: 34px; min-height: 30px; }}
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

/* Hover tooltip */
#sat-tooltip {{ position: absolute; background: rgba(0,0,0,0.88); color: #e2e8f0; padding: 4px 8px; border-radius: 4px; font-size: 11px; pointer-events: none; z-index: 15; display: none; white-space: nowrap; border: 1px solid #374151; }}

@media (max-width: 900px) {{
  #sidebar {{ display: none; position: absolute; top: 0; right: 0; bottom: 0; width: 220px; z-index: 30; border-left: 1px solid #1f2937; }}
  #sidebar.open {{ display: block; }}
  #sidebar-toggle {{ display: block; }}
  #camera-mode {{ right: auto; left: 50%; transform: translateX(-50%); top: auto; bottom: 6px; }}
  #globe-mode {{ right: auto; left: 50%; transform: translateX(-50%); top: auto; bottom: 32px; }}
  #legend {{ bottom: auto; top: 8px; left: 50%; transform: translateX(-50%); font-size: 9px; }}
}}

@media (max-width: 600px) {{
  #legend {{ display: none; }}
}}

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
      <div id="sat-tooltip"></div>
      <div id="camera-mode">
        <button class="active" data-mode="free">Free</button>
        <button data-mode="fixed">Fixed</button>
        <button data-mode="track">Track</button>
      </div>
      <div id="globe-mode">
        <button class="active" data-mode="smooth">Smooth</button>
        <button data-mode="terrain">Terrain</button>
      </div>
      <div id="legend">
        <span class="legend-item"><span class="legend-dot" style="background:#4299e1"></span>Detector</span>
        <span class="legend-item"><span class="legend-dot" style="background:#48bb78"></span>Compute</span>
        <span class="legend-item"><span class="legend-dot" style="background:#ed8936"></span>Relay</span>
        <span class="legend-item"><span class="legend-dot" style="background:#f6e05e"></span>Data flow</span>
      </div>
    </div>

    <button id="sidebar-toggle" onclick="document.getElementById('sidebar').classList.toggle('open')">☰</button>

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
        <div class="panel-title">Selected Satellite</div>
        <div id="node-info" style="color:#6b7280;">Click a satellite to inspect</div>
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
let hoveredSat = -1;
let earthMode = 'smooth'; // 'smooth' or 'terrain'
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

// ============ EARTH RENDERING ============

// --- Smooth Earth (default) ---
const earthGeo = new THREE.SphereGeometry(R, 48, 48);
const earthMat = new THREE.MeshPhongMaterial({{ color: 0x1a365d, emissive: 0x0a1628, shininess: 5, transparent: true, opacity: 0.92 }});
const earthSmooth = new THREE.Mesh(earthGeo, earthMat);
scene.add(earthSmooth);

const wireGeo = new THREE.SphereGeometry(R * 1.002, 32, 32);
const earthWire = new THREE.Mesh(wireGeo, new THREE.MeshBasicMaterial({{ color: 0x2d3748, wireframe: true, transparent: true, opacity: 0.12 }}));
scene.add(earthWire);

// --- Terrain Earth (procedural shader) ---
const terrainVertShader = `
varying vec3 vNormal;
varying vec3 vPosition;
varying vec2 vUv;
void main() {{
  vNormal = normalize(normalMatrix * normal);
  vPosition = (modelMatrix * vec4(position, 1.0)).xyz;
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}}`;

const terrainFragShader = `
varying vec3 vNormal;
varying vec3 vPosition;
varying vec2 vUv;
uniform vec3 uSunDir;

// Simplex noise helpers
vec3 mod289(vec3 x) {{ return x - floor(x * (1.0/289.0)) * 289.0; }}
vec4 mod289(vec4 x) {{ return x - floor(x * (1.0/289.0)) * 289.0; }}
vec4 permute(vec4 x) {{ return mod289(((x*34.0)+1.0)*x); }}
vec4 taylorInvSqrt(vec4 r) {{ return 1.79284291400159 - 0.85373472095314 * r; }}

float snoise(vec3 v) {{
  const vec2 C = vec2(1.0/6.0, 1.0/3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
    i.z + vec4(0.0, i1.z, i2.z, 1.0))
    + i.y + vec4(0.0, i1.y, i2.y, 1.0))
    + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0)*2.0 + 1.0;
  vec4 s1 = floor(b1)*2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw*sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw*sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0,p0), dot(p1,p1), dot(p2,p2), dot(p3,p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0,x0), dot(x1,x1), dot(x2,x2), dot(x3,x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m*m, vec4(dot(p0,x0), dot(p1,x1), dot(p2,x2), dot(p3,x3)));
}}

float fbm(vec3 p) {{
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 5; i++) {{
    v += a * snoise(p);
    p *= 2.0;
    a *= 0.5;
  }}
  return v;
}}

void main() {{
  // Convert position to spherical for noise
  vec3 dir = normalize(vPosition);
  float lat = asin(dir.y);
  float lon = atan(dir.z, dir.x);
  
  // Noise-based elevation
  float elev = fbm(dir * 3.0 + vec3(0.5, 1.2, 0.8));
  
  // Color based on elevation
  vec3 deepOcean = vec3(0.05, 0.12, 0.28);
  vec3 shallowOcean = vec3(0.08, 0.22, 0.45);
  vec3 coast = vec3(0.12, 0.35, 0.18);
  vec3 land = vec3(0.15, 0.42, 0.12);
  vec3 highland = vec3(0.35, 0.32, 0.18);
  vec3 mountain = vec3(0.55, 0.52, 0.48);
  vec3 snow = vec3(0.85, 0.88, 0.92);
  
  vec3 col;
  if (elev < -0.05) {{
    col = mix(deepOcean, shallowOcean, smoothstep(-0.4, -0.05, elev));
  }} else if (elev < 0.05) {{
    col = mix(shallowOcean, coast, smoothstep(-0.05, 0.05, elev));
  }} else if (elev < 0.2) {{
    col = mix(coast, land, smoothstep(0.05, 0.2, elev));
  }} else if (elev < 0.35) {{
    col = mix(land, highland, smoothstep(0.2, 0.35, elev));
  }} else if (elev < 0.5) {{
    col = mix(highland, mountain, smoothstep(0.35, 0.5, elev));
  }} else {{
    col = mix(mountain, snow, smoothstep(0.5, 0.7, elev));
  }}
  
  // Latitude-based polar ice
  float polarFactor = smoothstep(1.1, 1.4, abs(lat * 2.0));
  col = mix(col, snow * 0.9, polarFactor);
  
  // Simple lighting
  float diffuse = max(dot(vNormal, normalize(uSunDir)), 0.0);
  float ambient = 0.25;
  col *= (ambient + diffuse * 0.75);
  
  // Latitude/longitude grid lines
  float latLine = 1.0 - smoothstep(0.0, 0.015, abs(fract(lat / (3.14159/6.0) + 0.5) - 0.5));
  float lonLine = 1.0 - smoothstep(0.0, 0.015, abs(fract(lon / (3.14159/6.0) + 0.5) - 0.5));
  // Equator and prime meridian thicker
  float eqLine = 1.0 - smoothstep(0.0, 0.025, abs(lat));
  float pmLine = 1.0 - smoothstep(0.0, 0.025, abs(lon));
  
  float gridAlpha = max(max(latLine, lonLine) * 0.25, max(eqLine, pmLine) * 0.4);
  col = mix(col, vec3(0.6, 0.7, 0.8), gridAlpha);
  
  gl_FragColor = vec4(col, 0.95);
}}`;

const terrainMat = new THREE.ShaderMaterial({{
  vertexShader: terrainVertShader,
  fragmentShader: terrainFragShader,
  uniforms: {{ uSunDir: {{ value: new THREE.Vector3(10, 5, 10).normalize() }} }},
  transparent: true
}});
const earthTerrain = new THREE.Mesh(new THREE.SphereGeometry(R, 64, 64), terrainMat);
earthTerrain.visible = false;
scene.add(earthTerrain);

// Lat/lon grid lines (3D lines for smooth mode — hidden by default)
const gridGroup = new THREE.Group();
gridGroup.visible = false;
scene.add(gridGroup);

// Equator ring
const eqGeo = new THREE.RingGeometry(R * 1.003, R * 1.005, 64);
const eqMesh = new THREE.Mesh(eqGeo, new THREE.MeshBasicMaterial({{ color: 0x4a5568, side: THREE.DoubleSide, transparent: true, opacity: 0.25 }}));
eqMesh.rotation.x = Math.PI / 2;
scene.add(eqMesh);

// Globe mode switch
function setEarthMode(mode) {{
  earthMode = mode;
  earthSmooth.visible = (mode === 'smooth');
  earthWire.visible = (mode === 'smooth');
  eqMesh.visible = (mode === 'smooth');
  earthTerrain.visible = (mode === 'terrain');
  document.querySelectorAll('#globe-mode button').forEach(b => b.classList.toggle('active', b.dataset.mode === mode));
}}
document.querySelectorAll('#globe-mode button').forEach(btn => {{
  btn.addEventListener('click', () => setEarthMode(btn.dataset.mode));
}});

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

// ============ SATELLITES ============
const satMeshes = [];
const orbitLines = [];
const selectRings = []; // selection indicator rings

SIM.satellites.forEach((sat, i) => {{
  const size = sat.role === 'relay' ? 0.18 : sat.role === 'compute' ? 0.14 : 0.12;
  const mesh = new THREE.Mesh(
    new THREE.SphereGeometry(size, 10, 10),
    new THREE.MeshBasicMaterial({{ color: sat.color }})
  );
  mesh.userData = {{ satIndex: i }};
  scene.add(mesh);
  satMeshes.push(mesh);
  
  // Glow
  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(size * 1.8, 10, 10),
    new THREE.MeshBasicMaterial({{ color: sat.color, transparent: true, opacity: 0.15 }})
  );
  mesh.add(glow);
  
  // Selection ring (initially invisible)
  const ringGeo = new THREE.RingGeometry(size * 2.2, size * 2.8, 24);
  const ringMat = new THREE.MeshBasicMaterial({{ color: 0xffffff, transparent: true, opacity: 0.0, side: THREE.DoubleSide }});
  const ring = new THREE.Mesh(ringGeo, ringMat);
  ring.lookAt(camera.position); // will be updated each frame
  mesh.add(ring);
  selectRings.push(ring);
  
  // Orbit path
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
  const inc = orbit.inclination_deg * Math.PI / 180;
  const raan = orbit.raan_deg * Math.PI / 180;
  const pts = [];
  for (let s = 0; s <= segs; s++) {{
    const nu = (s / segs) * Math.PI * 2;
    const xo = a * Math.cos(nu), yo = a * Math.sin(nu);
    const x = xo * Math.cos(raan) - yo * Math.sin(raan) * Math.cos(inc);
    const y = xo * Math.sin(raan) + yo * Math.cos(raan) * Math.cos(inc);
    const z = yo * Math.sin(inc);
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

// ============ RAYCASTER (hover + click) ============
const raycaster = new THREE.Raycaster();
const mouse = new THREE.Vector2();
const tooltip = document.getElementById('sat-tooltip');
raycaster.params.Sphere = {{ threshold: 0.0 }}; // use geometry bounds

function getMouseNDC(event) {{
  const rect = renderer.domElement.getBoundingClientRect();
  mouse.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  mouse.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
}}

function raycastSatellites(event) {{
  getMouseNDC(event);
  raycaster.setFromCamera(mouse, camera);
  const intersects = raycaster.intersectObjects(satMeshes, false);
  if (intersects.length > 0) {{
    return intersects[0].object.userData.satIndex;
  }}
  return -1;
}}

// Hover
container.addEventListener('mousemove', (e) => {{
  const idx = raycastSatellites(e);
  if (idx !== hoveredSat) {{
    // Unhover previous
    if (hoveredSat >= 0 && hoveredSat !== selectedSat) {{
      const glow = satMeshes[hoveredSat].children[0];
      if (glow) {{ glow.material.opacity = 0.15; glow.scale.setScalar(1.0); }}
    }}
    hoveredSat = idx;
    // Hover new
    if (hoveredSat >= 0 && hoveredSat !== selectedSat) {{
      const glow = satMeshes[hoveredSat].children[0];
      if (glow) {{ glow.material.opacity = 0.35; glow.scale.setScalar(1.8); }}
    }}
  }}
  // Tooltip
  if (hoveredSat >= 0) {{
    container.classList.add('hovering');
    tooltip.style.display = 'block';
    tooltip.style.left = (e.clientX - container.getBoundingClientRect().left + 12) + 'px';
    tooltip.style.top = (e.clientY - container.getBoundingClientRect().top - 8) + 'px';
    const sat = SIM.satellites[hoveredSat];
    tooltip.textContent = `${{sat.id}} (${{sat.role}})`;
  }} else {{
    container.classList.remove('hovering');
    tooltip.style.display = 'none';
  }}
}});

container.addEventListener('mouseleave', () => {{
  if (hoveredSat >= 0 && hoveredSat !== selectedSat) {{
    const glow = satMeshes[hoveredSat].children[0];
    if (glow) {{ glow.material.opacity = 0.15; glow.scale.setScalar(1.0); }}
  }}
  hoveredSat = -1;
  container.classList.remove('hovering');
  tooltip.style.display = 'none';
}});

// Click to select
container.addEventListener('click', (e) => {{
  const idx = raycastSatellites(e);
  if (idx >= 0) {{
    selectSatellite(idx);
  }}
}});

// ============ POSITION + SCENE UPDATE ============
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
    if (glow && i !== hoveredSat && i !== selectedSat) {{
      glow.material.opacity = computing ? 0.3 + 0.15 * Math.sin(t * 6) : 0.12;
      glow.scale.setScalar(computing ? 1.6 : 1.0);
    }}
    // Update selection ring to face camera
    const ring = selectRings[i];
    if (ring) {{
      ring.lookAt(camera.position.clone().sub(mesh.position));
      ring.material.opacity = (i === selectedSat) ? 0.6 + 0.2 * Math.sin(t * 4) : 0.0;
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

  // Track mode: camera follows selected satellite from behind
  if (cameraMode === 'track' && trackTarget >= 0) {{
    const satPos = satMeshes[trackTarget].position.clone();
    const dir = satPos.clone().normalize();
    // Place camera behind + above the satellite (relative to earth center)
    const camOffset = dir.clone().multiplyScalar(3.0);
    const upOffset = new THREE.Vector3(0, 1.2, 0);
    const targetCamPos = satPos.clone().add(camOffset).add(upOffset);
    // Smooth lerp
    camera.position.lerp(targetCamPos, 0.03);
    camera.lookAt(satPos);
  }}
}}

// ============ UI ============
const duration = SIM.scenario.duration_s;
document.getElementById('duration-display').textContent = duration.toFixed(0);
document.getElementById('scenario-info').innerHTML = `${{SIM.scenario.name}}<br>${{SIM.satellites.length}} sats, ${{duration}}s`;
document.getElementById('time-slider').max = duration;

// Satellite list in sidebar
const satListEl = document.getElementById('sat-list');
SIM.satellites.forEach((sat, i) => {{
  const el = document.createElement('div');
  el.className = 'sat-item';
  el.innerHTML = `<span class="sat-dot" style="background:${{sat.color}}"></span>${{sat.id}}`;
  el.onclick = () => selectSatellite(i);
  satListEl.appendChild(el);
}});

// Event markers
const markersEl = document.getElementById('event-markers');
const evColors = {{ task_arrive:'#4299e1', compute_start:'#48bb78', compute_done:'#48bb78', transfer_done:'#f6e05e', task_complete:'#10b981', transfer_start:'#ed8936' }};
SIM.events.forEach(ev => {{
  const dot = document.createElement('div');
  dot.className = 'event-marker';
  dot.style.left = (ev.t/duration*100)+'%';
  dot.style.background = evColors[ev.type]||'#6b7280';
  markersEl.appendChild(dot);
}});

// Event log
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
  // Deselect previous
  if (selectedSat >= 0) {{
    const prevGlow = satMeshes[selectedSat].children[0];
    if (prevGlow) {{ prevGlow.material.opacity = 0.15; prevGlow.scale.setScalar(1.0); }}
  }}
  
  selectedSat = i;
  
  // Highlight selected
  const glow = satMeshes[i].children[0];
  if (glow) {{ glow.material.opacity = 0.4; glow.scale.setScalar(2.0); }}
  
  // Sidebar list highlight
  document.querySelectorAll('.sat-item').forEach((el, idx) => el.classList.toggle('selected', idx===i));
  
  // Orbit highlight
  orbitLines.forEach((l, idx) => {{ l.material.opacity = idx===i ? 0.4 : 0.08; }});
  
  // Detail panel
  const sat = SIM.satellites[i];
  const flopsStr = sat.compute_flops > 0 ? (sat.compute_flops >= 1e12 ? (sat.compute_flops/1e12).toFixed(0)+' TFLOPS' : (sat.compute_flops/1e9).toFixed(0)+' GFLOPS') : '—';
  const orbit = sat.orbit;
  document.getElementById('node-info').innerHTML = `
    <div class="sat-detail">
      <div style="margin-bottom:6px;"><strong style="color:${{sat.color}};font-size:13px;">${{sat.id}}</strong></div>
      <div><span class="label">Role:</span> <span class="value">${{sat.role}}</span></div>
      <div><span class="label">Compute:</span> <span class="value">${{flopsStr}}</span></div>
      <div><span class="label">Altitude:</span> <span class="value">${{(orbit.semi_major_axis_km - 6371).toFixed(0)}} km</span></div>
      <div><span class="label">Inclination:</span> <span class="value">${{orbit.inclination_deg.toFixed(1)}}°</span></div>
      <div><span class="label">RAAN:</span> <span class="value">${{orbit.raan_deg.toFixed(1)}}°</span></div>
      <div id="node-batt"><span class="label">Battery:</span> <span class="value">—</span></div>
      <div id="node-pos"><span class="label">Position:</span> <span class="value">—</span></div>
    </div>`;
  
  // Track mode: bind to this satellite
  if (cameraMode === 'track') {{
    trackTarget = i;
  }}
}}

function updateUI() {{
  document.getElementById('time-display').textContent = `t = ${{currentTime.toFixed(1)}}s`;
  document.getElementById('time-slider').value = currentTime;
  document.getElementById('time-info').textContent = `${{currentTime.toFixed(1)}} / ${{duration.toFixed(0)}}s`;
  updateEventLog(currentTime);
  if (selectedSat >= 0) {{
    // Battery
    const times = SIM.energy.times, data = SIM.energy.data[String(selectedSat)];
    if (data) {{
      let idx=0; for(let j=0;j<times.length;j++){{ if(times[j]<=currentTime) idx=j; }}
      const el = document.getElementById('node-batt');
      if(el) el.innerHTML = `<span class="label">Battery:</span> <span class="value">${{data[idx]?.toFixed(1)||'—'}}%</span>`;
    }}
    // Position (lat/lon/alt)
    const pos = getSatPos(selectedSat, currentTime);
    const posKm = pos.clone().multiplyScalar(1000); // back to km
    const alt = posKm.length() - EARTH_RADIUS;
    const lat = Math.asin(posKm.y / posKm.length()) * 180 / Math.PI;
    const lon = Math.atan2(-posKm.z, posKm.x) * 180 / Math.PI;
    const posEl = document.getElementById('node-pos');
    if (posEl) posEl.innerHTML = `<span class="label">Position:</span> <span class="value">${{lat.toFixed(1)}}°, ${{lon.toFixed(1)}}° | ${{alt.toFixed(0)}}km</span>`;
  }}
}}

// ============ CONTROLS ============
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

// Camera mode buttons
document.querySelectorAll('#camera-mode button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    cameraMode = btn.dataset.mode;
    document.querySelectorAll('#camera-mode button').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    controls.enabled = (cameraMode === 'free') || (cameraMode === 'fixed' && !playing);
    if (cameraMode === 'track') {{
      controls.enabled = false;
      trackTarget = selectedSat >= 0 ? selectedSat : 0;
    }}
  }});
}});

document.addEventListener('keydown', e => {{
  if (e.code === 'Space') {{ e.preventDefault(); togglePlay(); }}
  if (e.code === 'ArrowRight') {{ currentTime = Math.min(currentTime+1, duration); updateUI(); }}
  if (e.code === 'ArrowLeft') {{ currentTime = Math.max(currentTime-1, 0); updateUI(); }}
}});

// ============ ANIMATION LOOP ============
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
    
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)
    
    print(f"Generated: {output_path} ({len(html)/1024:.1f} KB)")


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        generate_html(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python build_frontend.py <sim_data.json> <output.html>")
