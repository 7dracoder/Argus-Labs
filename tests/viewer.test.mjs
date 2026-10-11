import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../roboforge/web/vendor/three.module.min.js';
import {parseName, applyFinishes, explosionPoses, cameraPose, Viewer} from '../roboforge/web/viewer.js';
import {entranceFrames, reveal} from '../roboforge/web/motion.js';

test('native and loader-sanitized CAD labels retain role, finish and assembly index', () => {
  for (const [role, finish] of [['cover', 'plastic'], ['compute', 'pcb'], ['round_body', 'paint'], ['frame', 'metal']]) {
    const original = `${role}.${finish}__part123__15_2`;
    for (const name of [original, THREE.PropertyBinding.sanitizeNodeName(original)]) {
      assert.deepEqual(parseName(name), {role, finish, component_id: 'part123', node: 15});
    }
  }
});

test('explosion keeps one CAD instance together across rotated parents and restores exact poses', () => {
  const root = new THREE.Group();
  const meshes = [];
  for (const [node, x, angle] of [[0, -2, .4], [0, -2, -.8], [1, 2, 1.2]]) {
    const parent = new THREE.Group(); parent.position.x = x; parent.rotation.z = angle;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(.2, .2, .2)); mesh.userData.node = node;
    parent.add(mesh); root.add(parent); meshes.push(mesh);
  }
  root.updateMatrixWorld(true);
  const before = meshes.map(m => m.getWorldPosition(new THREE.Vector3()));
  const geometries = meshes.map(m => m.geometry.attributes.position.array.slice());
  const viewer = {poses: explosionPoses(meshes), root,
    camera: new THREE.PerspectiveCamera(), controls: {target: new THREE.Vector3(), update() {}}};
  viewer.camera.position.set(4, 3, 4);
  const cameraBefore = viewer.camera.position.clone();
  Viewer.prototype.setExploded.call(viewer, 1);
  const offsets = meshes.map((m, i) => m.getWorldPosition(new THREE.Vector3()).sub(before[i]));
  assert.ok(offsets[0].distanceTo(offsets[1]) < 1e-10, 'same node translates as one assembly');
  assert.ok(offsets[0].x < 0 && offsets[2].x > 0, 'separate instances move outward');
  assert.ok(viewer.camera.position.length() > cameraBefore.length());
  Viewer.prototype.setExploded.call(viewer, 0);
  meshes.forEach((mesh, i) => {
    assert.ok(mesh.getWorldPosition(new THREE.Vector3()).distanceTo(before[i]) < 1e-10);
    assert.deepEqual(mesh.geometry.attributes.position.array, geometries[i], 'presentation never modifies export geometry');
  });
  assert.ok(viewer.camera.position.distanceTo(cameraBefore) < 1e-10);
});

test('explosion clamps values and motion respects reduced-motion preferences', () => {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry());
  const root = new THREE.Group(); root.add(mesh);
  const viewer = {poses: explosionPoses([mesh]), root, camera: new THREE.PerspectiveCamera(),
    controls: {target: new THREE.Vector3(), update() {}}, reduced: true};
  Viewer.prototype.setExploded.call(viewer, 10);
  assert.equal(viewer.exploded, 1);
  Viewer.prototype.setExploded.call(viewer, -10);
  assert.equal(viewer.exploded, 0);
  assert.equal(Viewer.prototype.setSpin.call(viewer, true), false);
  viewer.reduced = false;
  assert.equal(Viewer.prototype.setSpin.call(viewer, true), true);
});

test('covers are opaque by default and inspection hides only protective skins', () => {
  const scene = new THREE.Group();
  for (const role of ['cover', 'battery', 'compute', 'deck', 'frame']) {
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial());
    mesh.name = THREE.PropertyBinding.sanitizeNodeName(`${role}.plastic__part__0_0`);
    scene.add(mesh);
  }
  const meshes = applyFinishes(scene);
  assert.ok(meshes.every(m => m.visible && !m.material.transparent));
  const viewer = {meshes};
  Viewer.prototype.inspectInternals.call(viewer, true, {archetype: 'mobile_robot'});
  assert.deepEqual(meshes.filter(m => m.visible).map(m => m.userData.role), ['battery', 'compute', 'frame']);
  Viewer.prototype.inspectInternals.call(viewer, false, {archetype: 'mobile_robot'});
  assert.ok(meshes.every(m => m.visible));
  Viewer.prototype.inspectInternals.call(viewer, true, {archetype: 'delivery_rover'});
  assert.deepEqual(meshes.filter(m => m.visible).map(m => m.userData.role), ['battery', 'compute']);
});

test('reference grid is visible only at exactly zero explosion and reset restores it', () => {
  const root = new THREE.Group();
  const viewer = {root, poses: [], grid: {visible: true}, ground: {visible: true},
    container: {dataset: {}}, camera: new THREE.PerspectiveCamera(),
    controls: {target: new THREE.Vector3(), update() {}},
    setExploded: Viewer.prototype.setExploded, setSpin: Viewer.prototype.setSpin};
  viewer.camera.position.set(4, 3, 4);
  for (const [value, visible] of [[0, true], [.01, false], [.5, false], [1, false], [0, true], [NaN, true], [-1, true]]) {
    Viewer.prototype.setExploded.call(viewer, value);
    assert.equal(viewer.grid.visible, visible);
    assert.equal(viewer.container.dataset.gridVisible, String(visible));
    assert.equal(viewer.ground.visible, true, 'shadows remain independent of reference grid');
  }
  viewer.setExploded(.01);
  Viewer.prototype.resetView.call(viewer);
  assert.equal(viewer.grid.visible, true);
  assert.equal(viewer.exploded, 0);
});

test('camera presets orbit around the model and end at the exact requested view', () => {
  const center = new THREE.Vector3(2, 1, 3);
  const from = center.clone().add(new THREE.Vector3(4, 0, 0));
  const to = center.clone().add(new THREE.Vector3(-4, 0, 0));
  for (const progress of [0, .25, .5, .75, 1]) {
    const pose = cameraPose(from, to, center, center, progress);
    assert.ok(Math.abs(pose.position.distanceTo(center) - 4) < 1e-10);
  }
  assert.ok(cameraPose(from, to, center, center, 1).position.distanceTo(to) < 1e-10);
  const viewer = {renderer: {}, reduced: false, camera: new THREE.PerspectiveCamera(),
    controls: {target: center.clone(), update() {}}};
  viewer.camera.position.copy(from);
  Viewer.prototype.moveCamera.call(viewer, to, center);
  assert.ok(viewer.camera.position.equals(from), 'preset starts from current orbit');
  const start = viewer.cameraTween.start;
  Viewer.prototype.advanceCamera.call(viewer, start + 240);
  assert.ok(Math.abs(viewer.camera.position.distanceTo(center) - 4) < 1e-10);
  Viewer.prototype.advanceCamera.call(viewer, start + 480);
  assert.equal(viewer.cameraTween, null);
  assert.ok(viewer.camera.position.distanceTo(to) < 1e-10);
  viewer.reduced = true;
  Viewer.prototype.moveCamera.call(viewer, from, center);
  assert.ok(viewer.camera.position.equals(from), 'reduced motion updates view immediately');
});

test('entrance animation respects reduced motion and works without animation support', () => {
  const calls = [];
  const element = {animate(frames, options) { calls.push({frames, options}); return 'animation'; }};
  assert.equal(reveal(element, true), null);
  assert.equal(reveal({}, false), null);
  assert.equal(calls.length, 0);
  assert.equal(reveal(element, false, 45), 'animation');
  assert.deepEqual(calls[0].frames, entranceFrames);
  assert.equal(calls[0].options.delay, 45);
  assert.equal(calls[0].options.duration, 460);
});
