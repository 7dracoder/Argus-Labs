// Start-page showcase: the real CAD robot of each body plan on a turntable, looping like a motion reel.
import * as THREE from './vendor/three.module.min.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {RoomEnvironment} from './vendor/RoomEnvironment.js';
import {applyFinishes} from './viewer.js?v=4';

const HOLD_MS = 5200, IN_MS = 1100, OUT_MS = 700;
const easeOut = t => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);
const easeIn = t => Math.pow(Math.min(1, Math.max(0, t)), 2);

export class Showcase {
  /** items: [{glb, ...}]; onChange(index, item); onProgress(index, 0..1) */
  constructor(container, items, {onChange, onProgress} = {}) {
    Object.assign(this, {container, items, onChange, onProgress});
    this.loader = new GLTFLoader();
    this.models = new Map();
    this.index = -1; this.current = null; this.outgoing = null;
    this.reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.paused = false; this.visible = true; this.spin = 0.6; this.drag = null; this.held = 0;

    const r = this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    r.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.1;
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.domElement.setAttribute('aria-hidden', 'true');
    container.append(r.domElement);

    const scene = this.scene = new THREE.Scene();
    scene.environment = new THREE.PMREMGenerator(r).fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environmentIntensity = 0.55;
    this.camera = new THREE.PerspectiveCamera(26, 1, 0.01, 50);
    this.camera.position.set(2.9, 1.45, 2.9); this.camera.lookAt(0, 0.36, 0);

    const key = new THREE.DirectionalLight(0xfff6ea, 2.4); key.position.set(2.5, 4, 2);
    key.castShadow = true; key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 5; key.shadow.bias = -0.0005;
    Object.assign(key.shadow.camera, {left: -1.2, right: 1.2, top: 1.2, bottom: -1.2, near: 0.5, far: 10});
    const rim = new THREE.DirectionalLight(0xffffff, 1.2); rim.position.set(-2.5, 1.6, -2.2);
    const cool = new THREE.DirectionalLight(0xe9f0ff, 0.5); cool.position.set(-3, 1, 2.5);
    scene.add(key, rim, cool, new THREE.HemisphereLight(0xffffff, 0xd6ddce, 0.6));

    const floor = new THREE.Mesh(new THREE.CircleGeometry(2.2, 64), new THREE.ShadowMaterial({opacity: 0.18}));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
    const ringMat = new THREE.MeshBasicMaterial({color: 0x345d49, transparent: true, opacity: 0.45, side: THREE.DoubleSide});
    this.ring = new THREE.Mesh(new THREE.RingGeometry(0.66, 0.672, 128), ringMat);
    this.pulse = new THREE.Mesh(new THREE.RingGeometry(0.66, 0.668, 128), ringMat.clone());
    for (const ring of [this.ring, this.pulse]) { ring.rotation.x = -Math.PI / 2; ring.position.y = 0.002; scene.add(ring); }
    const ticks = new THREE.Group();
    for (let i = 0; i < 72; i++) {
      const tick = new THREE.Mesh(new THREE.PlaneGeometry(0.004, i % 6 ? 0.025 : 0.06),
        new THREE.MeshBasicMaterial({color: 0x9aa892, transparent: true, opacity: 0.7, side: THREE.DoubleSide}));
      const a = (i / 72) * Math.PI * 2;
      tick.position.set(Math.cos(a) * 0.74, 0.001, Math.sin(a) * 0.74);
      tick.rotation.set(-Math.PI / 2, 0, -a + Math.PI / 2); ticks.add(tick);
    }
    this.ticks = ticks; scene.add(ticks);

    const el = r.domElement;
    el.addEventListener('pointerdown', e => { this.drag = {x: e.clientX, spin: 0}; el.setPointerCapture(e.pointerId); });
    el.addEventListener('pointermove', e => {
      if (!this.drag || !this.current) return;
      const dx = e.clientX - this.drag.x; this.drag.x = e.clientX;
      this.current.rotation.y += dx * 0.01; this.drag.spin = dx * 0.01;
    });
    el.addEventListener('pointerup', () => { this.drag = null; });
    container.addEventListener('pointerenter', () => { this.paused = true; });
    container.addEventListener('pointerleave', () => { this.paused = false; });
    new ResizeObserver(() => this.resize()).observe(container);
    new IntersectionObserver(([entry]) => { this.visible = entry.isIntersecting; }).observe(container);
    this.resize();
    this.last = performance.now();
    const loop = now => { this.tick(now); this.frame = requestAnimationFrame(loop); };
    this.frame = requestAnimationFrame(loop);
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h;
    // Shift the turntable right of centre so the caption card never covers the robot.
    if (w > 640) this.camera.setViewOffset(w, h, -w * 0.19, h * 0.04, w, h); else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
  }

  load(index) {
    const item = this.items[index];
    if (!this.models.has(item.glb)) {
      const promise = this.loader.loadAsync(item.glb).then(gltf => {
        const model = gltf.scene;
        const meshes = applyFinishes(model);
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3()), centre = box.getCenter(new THREE.Vector3());
        model.position.set(-centre.x, -box.min.y, -centre.z);
        const pivot = new THREE.Group(); pivot.add(model);
        pivot.userData = {fit: 0.95 / Math.max(size.x, size.z, size.y),
          materials: meshes.map(m => m.material)};
        return pivot;
      });
      promise.catch(() => this.models.delete(item.glb));
      this.models.set(item.glb, promise);
    }
    return this.models.get(item.glb);
  }

  opacity(pivot, value) {
    for (const m of pivot.userData.materials) { m.transparent = value < 1; m.opacity = value; m.depthWrite = value > 0.6; }
  }

  async go(index) {
    index = (index + this.items.length) % this.items.length;
    if (index === this.index) return;
    const token = this.token = (this.token || 0) + 1;
    this.index = index; this.held = 0;
    this.container.classList.add('loading');
    let pivot;
    try { pivot = await this.load(index); } catch { if (token === this.token) this.container.classList.add('failed'); return; }
    if (token !== this.token) return;
    this.container.classList.remove('loading', 'failed');
    pivot.userData.index = index;
    this.onChange?.(index, this.items[index]);
    if (this.current && this.current !== pivot) {
      this.outgoing?.removeFromParent();
      this.outgoing = this.current; this.outgoing.userData.leaving = performance.now();
    }
    this.current = pivot; pivot.userData.entered = performance.now(); pivot.rotation.y = -0.9;
    this.scene.add(pivot);
    this.load((index + 1) % this.items.length).catch(() => {}); // warm the next robot while this one plays
  }

  tick(now) {
    const dt = Math.min(0.05, (now - this.last) / 1000); this.last = now;
    if (!this.visible || document.hidden) return;
    const motion = this.reduced ? 0 : 1;
    const c = this.current;
    if (c) {
      const t = easeOut((now - c.userData.entered) / IN_MS);
      const s = c.userData.fit * (0.84 + 0.16 * t);
      c.scale.setScalar(s); c.position.y = (1 - t) * -0.06;
      this.opacity(c, t);
      if (!this.drag) c.rotation.y += dt * this.spin * motion * (this.paused ? 0.35 : 1) + (1 - t) * dt * 1.6 * motion;
    }
    const o = this.outgoing;
    if (o) {
      const t = easeIn((now - o.userData.leaving) / OUT_MS);
      o.scale.setScalar(o.userData.fit * (1 + 0.08 * t)); o.position.y = t * 0.05;
      o.rotation.y += dt * (this.spin + 3 * t) * motion;
      this.opacity(o, 1 - t);
      if (t >= 1) { o.removeFromParent(); this.outgoing = null; }
    }
    const p = ((now / 2400) % 1);
    this.pulse.scale.setScalar(1 + p * 0.35 * motion); this.pulse.material.opacity = 0.45 * (1 - p) * motion;
    this.ticks.rotation.y -= dt * 0.08 * motion;
    if (c && c.userData.index === this.index) {
      if (!this.paused && !this.reduced) this.held += dt * 1000;
      const progress = Math.min(1, this.held / HOLD_MS);
      this.onProgress?.(this.index, progress);
      if (progress >= 1) this.go(this.index + 1);
    }
    this.renderer.render(this.scene, this.camera);
  }

  jump(index) { this.go(index); }
}
