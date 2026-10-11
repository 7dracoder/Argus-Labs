import test from 'node:test';
import assert from 'node:assert/strict';
import {SectionTabs} from '../roboforge/web/sections.js';

function fixture() {
  const sections = ['review', 'edit', 'finance', 'files'];
  const panels = sections.map(section => ({hidden: section !== 'review', savedInput: 'Keep this draft'}));
  const tabs = sections.map((section, i) => ({dataset: {section}, tabIndex: i === 0 ? 0 : -1,
    attributes: {'aria-controls': section, 'aria-selected': String(i === 0)}, listeners: {},
    getAttribute(name) { return this.attributes[name]; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    focus() { this.focused = true; }}));
  const changes = [];
  globalThis.document = {getElementById: id => panels[sections.indexOf(id)]};
  const navigation = new SectionTabs({querySelectorAll: () => tabs}, section => changes.push(section));
  return {navigation, tabs, panels, changes};
}

test('only one section is visible and switching preserves form drafts', () => {
  const {navigation, tabs, panels, changes} = fixture();
  tabs[2].listeners.click();
  assert.deepEqual(panels.map(p => p.hidden), [true, true, false, true]);
  assert.deepEqual(tabs.map(t => t.tabIndex), [-1, -1, 0, -1]);
  assert.equal(tabs[2].attributes['aria-selected'], 'true');
  navigation.select('edit'); navigation.select('review');
  assert.ok(panels.every(p => p.savedInput === 'Keep this draft'));
  assert.equal(changes.at(-1), 'review', 'the viewer resize callback runs when returning');
  assert.equal(navigation.select('unknown'), false);
  assert.equal(navigation.current, 'review');
});

test('arrow keys wrap and Home/End move both focus and selected panel', () => {
  const {navigation, tabs, panels} = fixture();
  let prevented = false;
  tabs[0].listeners.keydown({key: 'ArrowLeft', preventDefault() { prevented = true; }});
  assert.equal(navigation.current, 'files');
  assert.equal(tabs[3].focused, true); assert.equal(prevented, true);
  tabs[3].listeners.keydown({key: 'ArrowRight', preventDefault() {}});
  assert.equal(navigation.current, 'review');
  tabs[0].listeners.keydown({key: 'End', preventDefault() {}});
  assert.equal(panels[3].hidden, false);
  tabs[3].listeners.keydown({key: 'Home', preventDefault() {}});
  assert.equal(navigation.current, 'review');
  tabs[0].listeners.keydown({key: 'Tab', preventDefault() { throw new Error('Tab should use normal focus order'); }});
});
