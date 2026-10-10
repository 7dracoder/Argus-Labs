import test from 'node:test';
import assert from 'node:assert/strict';
import {PacingSignal, normalizeBreathingSample} from './signal.mjs';

function calibrated() {
  const pacing = new PacingSignal();
  for (let time = 0; time < 60000; time += 2000) {
    assert.equal(pacing.update({value: 12, confidence: 0.95}, time).state, 'focused');
  }
  return pacing;
}
test('calibration and sustained change, not one spike', () => {
  const pacing = calibrated();
  for (let time = 60000; time <= 74000; time += 2000) {
    assert.equal(pacing.update({value: 16, confidence: 0.95}, time).state, 'focused');
  }
  assert.equal(pacing.update({value: 16, confidence: 0.95}, 76000).state, 'needs_guidance');
  assert.equal(pacing.update({value: 12, confidence: 0.95}, 78000).state, 'focused');
});
test('bad quality, invalid samples, and missing camera never imply confusion', () => {
  const pacing = calibrated();
  for (const sample of [null, {value: NaN, confidence: 1}, {value: 30, confidence: 0.2}, {value: 30, confidence: 2}]) {
    assert.equal(pacing.update(sample, 70000).confidence, 0);
  }
  assert.equal(pacing.update({value: 30, confidence: 1}, 70000, false).state, 'focused');
});
test('a sampling gap resets sustained change', () => {
  const pacing = calibrated();
  pacing.update({value: 16, confidence: 1}, 60000);
  assert.equal(pacing.update({value: 16, confidence: 1}, 80000).state, 'focused');
});

test('SDK percentage confidence is normalized exactly once at the boundary', () => {
  assert.deepEqual(normalizeBreathingSample({value: 12, confidence: 95}), {value: 12, confidence: 0.95});
  assert.equal(normalizeBreathingSample({value: 12, confidence: 1}).confidence, 0.01);
  for (const confidence of [0, 80, 100]) {
    assert.equal(normalizeBreathingSample({value: 12, confidence}).confidence, confidence / 100);
  }
  for (const sample of [null, {value: NaN, confidence: 95}, {value: 0, confidence: 95},
    {value: 12, confidence: -1}, {value: 12, confidence: 101}, {value: 12, confidence: Infinity}]) {
    assert.equal(normalizeBreathingSample(sample), null);
  }
});

test('real SDK-shaped samples calibrate and produce a normalized coarse signal', () => {
  const pacing = new PacingSignal();
  for (let time = 0; time < 60000; time += 2000) {
    pacing.update(normalizeBreathingSample({value: 12, confidence: 95}), time);
  }
  assert.equal(pacing.baseline.length, 30);
  for (let time = 60000; time <= 76000; time += 2000) {
    const signal = pacing.update(normalizeBreathingSample({value: 16, confidence: 95}), time);
    assert.equal(signal.confidence, 0.95);
    assert.equal(signal.state, time === 76000 ? 'needs_guidance' : 'focused');
  }
  assert.equal(pacing.update(normalizeBreathingSample({value: 16, confidence: 45}), 78000).confidence, 0);
});
