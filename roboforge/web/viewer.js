// 3D stage: whole-robot assembly or a single generated part (three.js, vendored for the CSP).
import * as THREE from './vendor/three.module.min.js';
import {GLTFLoader} from './vendor/GLTFLoader.js';
import {OrbitControls} from './vendor/OrbitControls.js';
import {RoomEnvironment} from './vendor/RoomEnvironment.js';

// Physically based finishes keyed by the CAD part name ("role.finish__component__n").
const FINISHES = {
  metal: {metalness: 0.85, roughness: 0.32}, chrome: {metalness: 1, roughness: 0.12},
  paint: {metalness: 0.15, roughness: 0.45}, plastic: {metalness: 0, roughness: 0.55},
  rubber: {metalness: 0, roughness: 0.92}, pcb: {metalness: 0.1, roughness: 0.5},
  glass: {metalness: 0.2, roughness: 0.05},
};
function parseName(name = '') {
  const [head, component, instance] = name.split('__');
  const [role, finish] = (head || '').split('.');
  return {role: role || 'part', finish: FINISHES[finish] ? finish : 'plastic', component_id: component && component !== 'none' ? component : null,
    node: Number.parseInt(instance, 10) || 0};
}

/** Give every mesh of a backend robot GLB its physical finish; returns the meshes. */
export function applyFinishes(model) {
  const meshes = [];
  model.traverse(o => {
    if (!o.isMesh) return;
    // glTF exporters may name the node or its parent; use the first that parses.
    const info = parseName(o.name.includes('__') ? o.name : o.parent?.name);
    const color = o.material?.color ? o.material.color.clone() : new THREE.Color(0x999999);
    o.material = new THREE.MeshPhysicalMaterial({color, ...FINISHES[info.finish],
      ...(info.finish === 'paint' ? {clearcoat: 0.4, clearcoatRoughness: 0.35} : {}),
      ...(info.finish === 'glass' ? {clearcoat: 1} : {})});
    o.castShadow = o.receiveShadow = true;
    o.userData = {...info, label: info.role, baseColor: color.clone()};
    meshes.push(o);
  });
  return meshes;
}

export function webglAvailable() {
  try { const c = document.createElement('canvas'); return !!(c.getContext('webgl2') || c.getContext('webgl')); }
  catch { return false; }
}

const HIGHLIGHT = new THREE.Color(0xf2b134);

export class Viewer {
  constructor(container, {onSelect} = {}) {
    this.container = container;
    this.onSelect = onSelect;
    this.loader = new GLTFLoader();
    this.cache = new Map(); // GLB url -> Promise<THREE.Object3D>
    this.meshes = [];
    this.token = 0;

    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.canvas = this.renderer.domElement;
    this.canvas.setAttribute('role', 'img');

    this.scene = new THREE.Scene();
    // Studio reflections so metal, rubber and plastic read as real materials.
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    this.scene.environmentIntensity = 0.8;
    this.camera = new THREE.PerspectiveCamera(32, 1, 0.001, 100);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8a9580, 0.35));
    this.key = new THREE.DirectionalLight(0xffffff, 2.2); this.key.position.set(3, 6, 4);
    this.key.castShadow = true; this.key.shadow.mapSize.set(2048, 2048); this.key.shadow.bias = -0.0004;
    this.key.shadow.radius = 4;
    this.scene.add(this.key, this.key.target);
    const fill = new THREE.DirectionalLight(0xffffff, 0.4); fill.position.set(-4, 2, -3); this.scene.add(fill);
    this.root = new THREE.Group(); this.scene.add(this.root);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;

    this.hint = document.createElement('span');
    this.hint.className = 'viewer-hint';
    this.hint.textContent = 'DRAG TO ROTATE · SCROLL TO ZOOM · RIGHT-DRAG TO MOVE · CLICK A PART';

    // Click (not drag) selects a part.
    let down = null;
    this.canvas.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
    this.canvas.addEventListener('pointerup', e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
      const rect = this.canvas.getBoundingClientRect();
      const pointer = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
      const ray = new THREE.Raycaster(); ray.setFromCamera(pointer, this.camera);
      const hit = ray.intersectObjects(this.meshes.filter(m => m.visible), false)[0];
      const info = hit ? hit.object.userData : null;
      this.highlight(info?.component_id ?? null);
      this.onSelect?.(info);
    });

    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(container);
    const tick = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); this.frame = requestAnimationFrame(tick); };
    tick();
  }

  attach(label) {
    this.canvas.setAttribute('aria-label', `${label}. Drag to rotate, scroll to zoom.`);
    if (this.canvas.parentNode !== this.container) this.container.replaceChildren(this.canvas, this.hint);
    this.resize();
  }

  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  clear() {
    this.root.traverse(o => { o.geometry?.dispose(); [o.material].flat().forEach(m => m?.dispose?.()); });
    this.root.clear(); this.meshes = [];
    for (const extra of [this.grid, this.ground]) extra?.removeFromParent();
    this.grid = this.ground = null;
  }

  /** Whole-robot CAD GLB from the backend (roboforge/cad/robot.py). */
  async showRobot(url, label) {
    const token = ++this.token;
    const gltf = await this.loader.loadAsync(url);
    if (token !== this.token) return false;
    const model = gltf.scene;
    const meshes = applyFinishes(model);
    this.clear();
    this.meshes = meshes;
    this.root.add(model);
    this.frameObject(model, true);
    this.attach(label);
    return true;
  }

  async glb(url) {
    if (!this.cache.has(url)) {
      const promise = this.loader.loadAsync(url).then(g => g.scene);
      promise.catch(() => this.cache.delete(url));
      this.cache.set(url, promise);
    }
    return (await this.cache.get(url)).clone(true);
  }

  material(color) {
    return new THREE.MeshStandardMaterial({color: new THREE.Color(color), roughness: .6, metalness: .05,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1});
  }

  register(mesh, info, color) {
    mesh.material = this.material(color);
    mesh.userData = {...info, baseColor: mesh.material.color.clone()};
    mesh.castShadow = mesh.receiveShadow = true;
    this.meshes.push(mesh);
  }

  /** Render the backend assembly (see roboforge/assembly.py). */
  async showAssembly(assembly) {
    const token = ++this.token;
    const group = new THREE.Group();
    for (const [index, n] of assembly.nodes.entries()) {
      const info = {component_id: n.component_id, label: n.label, node: index};
      let object;
      if (n.shape === 'glb' && n.glb) {
        try {
          const model = await this.glb(n.glb);
          if (token !== this.token) return;
          const inner = new THREE.Group(); inner.add(model);
          const center = new THREE.Box3().setFromObject(model).getCenter(new THREE.Vector3());
          model.position.sub(center);
          inner.rotation.set(...n.glb_rotation);
          model.traverse(o => { if (o.isMesh) this.register(o, info, n.color); });
          object = new THREE.Group(); object.add(inner);
        } catch { continue; }
      } else {
        const geometry = n.shape === 'cylinder' ? new THREE.CylinderGeometry(n.size[0], n.size[0], n.size[1], 32)
          : n.shape === 'sphere' ? new THREE.SphereGeometry(n.size[0], 24, 16)
          : new THREE.BoxGeometry(...n.size);
        object = new THREE.Mesh(geometry);
        this.register(object, info, n.color);
      }
      object.position.set(...n.position);
      object.rotation.set(...n.rotation);
      group.add(object);
    }
    if (token !== this.token) return;
    this.clear(); this.meshes = []; group.traverse(o => { if (o.isMesh) this.meshes.push(o); });
    this.root.add(group);
    this.frameObject(group, true);
    this.attach(`3D layout of ${assembly.robot_type}`);
  }

  /** Render one generated GLB part at its real size. */
  async showPart(url, label) {
    const token = ++this.token;
    const model = await this.glb(url);
    if (token !== this.token) return;
    this.clear();
    const center = new THREE.Box3().setFromObject(model).getCenter(new THREE.Vector3());
    model.position.sub(center);
    model.traverse(o => { if (o.isMesh) this.register(o, {component_id: null, label}, '#c6d8b6'); });
    this.root.add(model);
    this.frameObject(model, false);
    this.attach(`${label} 3D model`);
  }

  frameObject(object, isRobot) {
    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
    const radius = Math.max(size.x, size.y, size.z) || 0.1;
    const floor = box.min.y - (isRobot ? 0 : radius * 0.02);
    this.grid = new THREE.GridHelper(radius * 4, 32, 0xb3bcab, 0xdde2d6);
    this.grid.material.transparent = true; this.grid.material.opacity = 0.55;
    this.grid.position.set(center.x, floor, center.z);
    this.ground = new THREE.Mesh(new THREE.PlaneGeometry(radius * 8, radius * 8), new THREE.ShadowMaterial({opacity: 0.22}));
    this.ground.rotation.x = -Math.PI / 2; this.ground.position.set(center.x, floor + 0.0005, center.z);
    this.ground.receiveShadow = true;
    this.scene.add(this.grid, this.ground);
    const s = this.key.shadow.camera; const e = radius * 1.4;
    Object.assign(s, {left: -e, right: e, top: e, bottom: -e, near: 0.01, far: radius * 12}); s.updateProjectionMatrix();
    this.key.position.set(center.x + radius * 1.6, center.y + radius * 3.2, center.z + radius * 1.9);
    this.key.target.position.copy(center);
    this.camera.near = radius / 200; this.camera.far = radius * 100; this.camera.updateProjectionMatrix();
    const d = radius * (isRobot ? 2.1 : 2.4);
    this.camera.position.set(center.x + d * 0.75, center.y + d * 0.55, center.z + d * 0.9);
    this.controls.target.copy(center);
    this.controls.minDistance = radius * 0.3; this.controls.maxDistance = radius * 10;
    this.controls.update();
  }

  /** Turn the camera to a named side of the model, keeping the current zoom. */
  setAngle(angle) {
    // Robots are laid out driving toward +x (see assembly.py), so +x is the front.
    const dirs = {front: [1, 0.25, 0], back: [-1, 0.25, 0], side: [0, 0.25, 1], top: [0.001, 1, 0], default: [0.75, 0.55, 0.9]};
    const target = this.controls.target, distance = this.camera.position.distanceTo(target);
    this.camera.position.copy(target).add(new THREE.Vector3(...(dirs[angle] || dirs.default)).normalize().multiplyScalar(distance));
    this.controls.update();
  }

  /** Meshes of the first placed instance of a component (one wheel of four). */
  partMeshes(componentId) {
    const own = this.meshes.filter(m => componentId && m.userData.component_id === componentId);
    const first = Math.min(...own.map(m => m.userData.node));
    return own.filter(m => m.userData.node === first);
  }

  /** Assembly step: show only layout nodes in `shown`, highlight the nodes in `current`. */
  stage(shown, current) {
    for (const mesh of this.meshes) {
      const on = current.has(mesh.userData.node);
      mesh.visible = shown.has(mesh.userData.node);
      mesh.material.color.copy(mesh.userData.baseColor);
      if (on) mesh.material.color.lerp(HIGHLIGHT, 0.55);
      mesh.material.emissive.set(on ? 0x5a3a05 : 0x000000);
    }
  }

  highlight(componentId) {
    for (const mesh of this.meshes) {
      const on = componentId && mesh.userData.component_id === componentId;
      mesh.material.color.copy(mesh.userData.baseColor);
      if (on) mesh.material.color.lerp(HIGHLIGHT, 0.65);
      mesh.material.emissive.set(on ? 0x5a3a05 : 0x000000);
    }
  }
}
