// Blueprint sheet for one part: third-angle top / front / right views plus an isometric, with overall dimensions.
import * as THREE from './vendor/three.module.min.js';

const FILL = 0x27598d, INK = 0xe8f1ff, LINE = 'rgba(232, 241, 255, .9)', FAINT = 'rgba(232, 241, 255, .28)';
// Third-angle projection: top above front, right side beside front, isometric in the spare corner.
const VIEWS = [
  {name: 'TOP', col: 0, row: 0, dir: [0, 1, 0], up: [0, 0, -1], dims: ['x', 'z']},
  {name: 'ISOMETRIC', col: 1, row: 0, dir: [1, 0.82, 1], up: [0, 1, 0]},
  {name: 'FRONT', col: 0, row: 1, dir: [0, 0, 1], up: [0, 1, 0], dims: ['x', 'y']},
  {name: 'RIGHT', col: 1, row: 1, dir: [1, 0, 0], up: [0, 1, 0], dims: ['z', 'y']},
];
const MARGIN = 42; // px kept free around each view for dimension lines

export class Blueprint {
  constructor(container) {
    this.container = container;
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: true});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    this.overlay = document.createElement('canvas');
    this.overlay.className = 'blueprint-overlay';
    container.replaceChildren(this.renderer.domElement, this.overlay);
    this.scene = new THREE.Scene();
    this.camera = new THREE.OrthographicCamera();
    this.group = null;
    new ResizeObserver(() => this.draw()).observe(container);
  }

  /** Draw world-placed meshes (one instance of a component) as a dimensioned sheet. */
  show(meshes) {
    this.dispose();
    const group = new THREE.Group();
    const fill = new THREE.MeshBasicMaterial({color: FILL, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1}); // hides edges behind faces
    const ink = new THREE.LineBasicMaterial({color: INK});
    for (const mesh of meshes) {
      mesh.updateWorldMatrix(true, false);
      const geometry = mesh.geometry.clone().applyMatrix4(mesh.matrixWorld);
      group.add(new THREE.Mesh(geometry, fill), new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 25), ink));
    }
    const box = new THREE.Box3().setFromObject(group);
    group.position.sub(box.getCenter(new THREE.Vector3()));
    this.size = box.getSize(new THREE.Vector3());
    this.group = group; this.scene.add(group);
    this.draw();
  }

  dispose() {
    if (!this.group) return;
    this.group.traverse(o => { o.geometry?.dispose(); o.material?.dispose(); });
    this.group.removeFromParent(); this.group = null;
  }

  draw() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h || !this.group) return;
    this.renderer.setSize(w, h, false);
    const dpr = this.renderer.getPixelRatio();
    this.overlay.width = w * dpr; this.overlay.height = h * dpr;
    const ctx = this.overlay.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.font = '600 10.5px ui-monospace, SFMono-Regular, Menlo, monospace';
    const pw = w / 2, ph = h / 2, size = this.size, radius = size.length() || 0.1;
    // One scale (metres per pixel) for all orthographic views, as on a real drawing.
    const scale = Math.max(1e-6, ...VIEWS.filter(v => v.dims).map(v =>
      Math.max(size[v.dims[0]] / (pw - 2 * MARGIN), size[v.dims[1]] / (ph - 2 * MARGIN))));
    this.renderer.setScissorTest(true);
    for (const view of VIEWS) {
      const x0 = view.col * pw, y0 = view.row * ph, cam = this.camera;
      cam.up.set(...view.up);
      cam.position.set(...view.dir).normalize().multiplyScalar(radius * 4);
      cam.lookAt(0, 0, 0); cam.updateMatrixWorld();
      const k = view.dims ? scale : isoScale(cam, size, pw, ph);
      Object.assign(cam, {left: -pw / 2 * k, right: pw / 2 * k, top: ph / 2 * k, bottom: -ph / 2 * k, near: radius, far: radius * 8});
      cam.updateProjectionMatrix();
      this.renderer.setViewport(x0, h - y0 - ph, pw, ph); this.renderer.setScissor(x0, h - y0 - ph, pw, ph);
      this.renderer.render(this.scene, cam);
      ctx.fillStyle = LINE; ctx.textAlign = 'left'; ctx.fillText(view.name, x0 + 12, y0 + 20);
      if (view.dims) {
        const [a, b] = view.dims;
        dimensions(ctx, x0 + pw / 2, y0 + ph / 2, size[a] / k, size[b] / k, size[a], size[b]);
      }
    }
    this.renderer.setScissorTest(false);
    ctx.strokeStyle = FAINT; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pw, 0); ctx.lineTo(pw, h); ctx.moveTo(0, ph); ctx.lineTo(w, ph); ctx.stroke();
  }
}

function isoScale(cam, size, pw, ph) {
  const right = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 0);
  const up = new THREE.Vector3().setFromMatrixColumn(cam.matrixWorld, 1);
  let rx = 0, ry = 0;
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) {
    const corner = new THREE.Vector3(sx * size.x / 2, sy * size.y / 2, sz * size.z / 2);
    rx = Math.max(rx, Math.abs(corner.dot(right))); ry = Math.max(ry, Math.abs(corner.dot(up)));
  }
  return Math.max(1e-6, 2 * rx / (pw - 48), 2 * ry / (ph - 48));
}

const mm = metres => `${Math.round(metres * 1000)} mm`;

/** Overall width below the view and height to its right, with extension lines and arrows. */
function dimensions(ctx, cx, cy, wPx, hPx, wM, hM) {
  const left = cx - wPx / 2, right = cx + wPx / 2, top = cy - hPx / 2, bottom = cy + hPx / 2;
  const y = bottom + 18, x = right + 18;
  ctx.strokeStyle = LINE; ctx.fillStyle = LINE; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(left, bottom + 4); ctx.lineTo(left, y + 4); ctx.moveTo(right, bottom + 4); ctx.lineTo(right, y + 4);
  ctx.moveTo(left, y); ctx.lineTo(right, y);
  ctx.moveTo(right + 4, top); ctx.lineTo(x + 4, top); ctx.moveTo(right + 4, bottom); ctx.lineTo(x + 4, bottom);
  ctx.moveTo(x, top); ctx.lineTo(x, bottom);
  ctx.stroke();
  arrow(ctx, left, y, 1, 0); arrow(ctx, right, y, -1, 0); arrow(ctx, x, top, 0, 1); arrow(ctx, x, bottom, 0, -1);
  ctx.textAlign = 'center';
  ctx.fillText(mm(wM), cx, y + 14);
  ctx.save(); ctx.translate(x + 13, cy); ctx.rotate(-Math.PI / 2); ctx.fillText(mm(hM), 0, 0); ctx.restore();
}

function arrow(ctx, x, y, dx, dy) {
  ctx.beginPath(); ctx.moveTo(x, y);
  ctx.lineTo(x + dx * 6 - dy * 2.5, y + dy * 6 + dx * 2.5); ctx.lineTo(x + dx * 6 + dy * 2.5, y + dy * 6 - dx * 2.5);
  ctx.closePath(); ctx.fill();
}
