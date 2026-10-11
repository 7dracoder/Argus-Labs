import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../roboforge/web/vendor/three.module.min.js';
import {parseName, applyFinishes, explosionPoses, Viewer} from '../roboforge/web/viewer.js';

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
