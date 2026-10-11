import {Viewer, webglAvailable} from './viewer.js?v=7';
import {LiveVoice} from './live.js?v=4';
import {Showcase} from './showcase.js?v=5';
import {Blueprint} from './blueprint.js?v=4';
import {FinancialResearch} from './financial.js?v=1';

const $ = id => document.getElementById(id);
const state = {project: null, assembly: null, bom: null, stageKey: null, view: 'robot', partId: null, selected: null,
  lastAudio: null, interaction: null, busy: false, viewer: null, buy: null, guide: null, asmViewer: null, asmKey: null};
const money = value => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(value);
const cents = value => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value);
const financialResearch = new FinancialResearch({api, action, announce, project: () => state.project});

const EXAMPLES = {
  household: ['A household robot that picks up clothes and small items in my one-floor apartment, carries up to 2 kg and responds to my voice.', 2500],
  delivery: ['A delivery rover that carries 5 kg packages between rooms in our office, for about 3 hours a day.', 1200],
  desk: ['A desk robot arm that sorts small parts into bins, carrying up to 0.5 kg.', 600],
};
const PRESETS = {
  arm_link: {S: [80, 25, 5], M: [120, 40, 6], L: [180, 45, 8], price: 8},
  chassis_plate: {S: [200, 160, 5], M: [300, 240, 6], L: [420, 340, 8], price: 18},
  motor_bracket: {S: [60, 50, 4], M: [80, 60, 5], L: [100, 70, 6], price: 6},
};
const KIND_NAMES = {arm_link: 'Arm link', chassis_plate: 'Deck plate', motor_bracket: 'Motor bracket'};

// ---------- plumbing ----------
async function api(path, body, raw = false, method, timeoutMs = 190000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {method: method || (body === undefined ? 'GET' : 'POST'),
      headers: body === undefined ? {} : {'Content-Type': raw ? (body.type || 'audio/webm') : 'application/json'},
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
      signal: controller.signal, cache: 'no-store'});
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status}). Check inputs and backend configuration.`);
    }
    return response.json();
  } finally { clearTimeout(timer); }
}
let toastTimer;
function announce(message, error = false, busy = false) {
  const el = $('status'); el.textContent = message;
  el.className = `toast${error ? ' error' : ''}${busy ? ' busy' : ''}`;
  clearTimeout(toastTimer);
  if (!busy) toastTimer = setTimeout(() => el.classList.add('idle'), error ? 9000 : 4500);
}
function lock(value) {
  state.busy = value;
  document.querySelectorAll('button').forEach(button => {
    if (button.dataset.static) return;
    button.disabled = value || (button.classList.contains('requires-project') && !state.project)
      || (button.id === 'view-part' && !partList().length);
  });
  $('project-select').disabled = value;
  $('guided').disabled = value || !state.project;
}
async function action(task, busyMessage) {
  if (state.busy) return;
  lock(true);
  if (busyMessage) announce(busyMessage, false, true);
  try { await task(); } catch (error) { announce(error.message || 'Something went wrong.', true); }
  finally {
    lock(false);
    if (live.active && state.project) live.contextUpdate(`The user changed the design in the app (now revision ${state.project.revision}). Call get_robot_status before quoting numbers.`);
    // A budget change made while busy runs as soon as the current task ends.
    if (state.pendingBudget !== null && state.pendingBudget !== undefined) { const v = state.pendingBudget; state.pendingBudget = null; queueBudget(v); }
  }
}
function projectPath(suffix = '') { if (!state.project) throw new Error('Create a robot first.'); return `/projects/${encodeURIComponent(state.project.id)}${suffix}`; }
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function partList() { return Object.values(state.project?.manufacturing?.cad_parts || {}); }
function show(screen) {
  const changed = $(screen).hidden;
  for (const id of ['start', 'workspace', 'assemble']) $(id).hidden = screen !== id;
  $('new-robot').hidden = screen === 'start';
  $('explore-robots').hidden = screen !== 'start';
  if (screen === 'workspace') state.viewer?.resize();
  if (screen === 'assemble') state.asmViewer?.resize();
  if (changed) window.scrollTo({top: 0});
}

// ---------- project + refresh ----------
async function projectList() {
  const projects = await api('/projects');
  $('project-select').replaceChildren(new Option('Choose a robot', ''));
  for (const project of projects.slice().reverse()) $('project-select').add(new Option(`${project.name} · rev ${project.revision}`, project.id));
  $('project-select').value = '';
}
async function refresh() {
  const [project, bom, budget, assembly] = await Promise.all([
    api(projectPath()), api(projectPath('/finance/bom')), api(projectPath('/finance/budget')),
    api(projectPath('/assembly'))]);
  Object.assign(state, {project, bom, assembly});
  financialResearch.invalidate(project);
  $('project-title').textContent = project.name;
  $('robot-type').textContent = assembly.robot_type.replaceAll('_', ' ');
  $('revision').textContent = `Revision ${project.revision}`;
  renderBudget(budget); renderParts(bom); renderFacts(assembly, bom); renderBrief(project);
  renderDownloads(); renderTelemetry(null);
  // Optional telemetry must never hold up design, CAD or assembly when Tiger is offline.
  const telemetryProject = project.id;
  api(projectPath('/telemetry/summary'), undefined, false, 'GET', 10000).then(result => {
    if (state.project?.id === telemetryProject) renderTelemetry(result);
  }).catch(error => { if (state.project?.id === telemetryProject) renderTelemetry(null, error.message); });
  const guide = await api(projectPath(`/assembly-guide?revision=${project.revision}`));
  state.buildGuide = guide;
  $('protection-summary').textContent = guide.protection.join(' ');
  $('print-option').textContent = `3D-print parts (${guide.prints.filter(p => p.printable).reduce((n, p) => n + p.quantity, 0)}) →`;
  await renderStage();
  show('workspace');
  await projectList();
}
function renderBudget(b) {
  const over = b.remaining_usd !== null && b.remaining_usd < 0;
  $('budget-headline').className = `big-number${over ? ' bad' : ''}`;
  $('budget-headline').replaceChildren(b.remaining_usd === null ? 'No budget set'
    : over ? `${money(-b.remaining_usd)} over` : `${money(b.remaining_usd)} left`);
  $('budget-headline').append(node('small', b.remaining_usd === null ? 'Add a budget in your brief.'
    : over ? 'Projected cost is above your budget.' : 'Projected cost fits your budget.'));
  $('budget-chip').textContent = b.status === 'over_budget' ? 'Over budget' : b.status === 'within_budget' ? 'Within budget' : 'No budget';
  $('budget-chip').className = `badge ${over ? 'bad' : b.status === 'within_budget' ? 'good' : ''}`;
  const pct = b.budget_usd ? Math.min(100, (b.projected_total_usd / b.budget_usd) * 100) : 0;
  $('budget-bar').style.width = `${pct}%`; $('budget-bar').className = over ? 'over' : '';
  $('bom-total').textContent = cents(b.bom_total_usd);
  $('contingency').textContent = `${cents(b.contingency_usd)} (${b.contingency_pct}%)`;
  $('projected').textContent = cents(b.projected_total_usd);
  $('budget-value').textContent = b.budget_usd === null ? '—' : cents(b.budget_usd);
  $('cheaper').textContent = over ? 'Fit it to my budget' : 'Make it cheaper';
  renderLever(b);
}
function shortUpgrade(label) { return label.startsWith('Add ') ? `+ ${label.slice(4)}` : `↑ ${label.split(' → ').at(-1)}`; }
function renderLever(b) {
  const arch = state.project.architecture || {};
  const slider = $('budget-slider');
  const value = b.budget_usd ?? 2500;
  slider.max = String(Math.max(8000, Math.ceil(value / 1000) * 1000));
  $('slider-max').textContent = money(Number(slider.max));
  if (state.budgetTimer === null || state.budgetTimer === undefined) { slider.value = String(value); $('budget-out').textContent = money(value); }
  const hasScore = typeof arch.performance === 'number';
  $('tier-badge').textContent = hasScore ? arch.tier : 'Not scored';
  $('perf-bar').style.width = hasScore ? `${arch.performance}%` : '0%';
  $('perf-value').textContent = hasScore ? `${arch.performance}% performance` : 'Move the slider to optimise';
  $('upgrade-list').replaceChildren(...(arch.upgrades || []).map(u => node('li', shortUpgrade(u))));
  $('edited-note').hidden = !arch.edited;
  $('upgrade-list').hidden = Boolean(arch.edited); // the budget's picks no longer match the parts list
  const next = arch.next_upgrade;
  $('next-upgrade').hidden = !hasScore;
  if (hasScore) {
    $('next-upgrade-text').textContent = !next ? 'This is the best build in the catalog; more budget won’t improve it.'
      : next.kind === 'minimum' ? `This brief needs at least ${money(next.at_budget_usd)} including contingency.`
      : `Next: ${shortUpgrade(next.label)} for +${money(next.extra_usd)}.`;
    $('next-upgrade-btn').hidden = !next;
    $('next-upgrade-btn').textContent = next ? `Set budget to ${money(Math.ceil(next.at_budget_usd / 50) * 50)}` : '';
  }
}
async function rebuildForBudget(value) {
  state.pendingBudget = null;
  $('stage').classList.add('updating');
  try {
    const res = await api(projectPath('/design/auto'), {requirements: {...state.project.requirements, budget_usd: value}});
    state.stageKey = null;
    if (state.pendingBudget === null) state.budgetTimer = null;
    await refresh();
    announce(`${money(value)} budget → ${res.tier} build (${res.performance}% performance).${res.warnings.length ? ' See warnings in the parts list.' : ''}`);
  } finally { $('stage').classList.remove('updating'); }
}
function queueBudget(value) {
  $('budget-out').textContent = money(value);
  clearTimeout(state.budgetTimer);
  state.budgetTimer = setTimeout(() => {
    if (!state.project) return;
    if (state.busy) { state.pendingBudget = value; return; }
    action(async () => {
      await rebuildForBudget(value);
      while (state.pendingBudget !== null && state.pendingBudget !== undefined) await rebuildForBudget(state.pendingBudget);
    }, `Re-picking parts for ${money(value)}…`);
  }, 450);
}
function renderParts(bom) {
  $('parts-count').textContent = `${bom.lines.reduce((n, l) => n + l.quantity, 0)} parts`;
  $('bom-lines').replaceChildren(...bom.lines.map(line => {
    const li = node('li', undefined, 'part-row'); li.dataset.component = line.component_id;
    const pick = node('button', undefined, 'pick'); pick.type = 'button'; pick.dataset.static = '1';
    pick.append(node('span', `${line.quantity} × ${line.name}`), node('small', `${line.category}${line.source === 'generated' ? ' · printed part' : ''}${line.supplier ? ' · ' + line.supplier : ''}`));
    pick.addEventListener('click', () => select(line.component_id, true));
    const remove = node('button', '×', 'remove requires-project'); remove.type = 'button';
    remove.setAttribute('aria-label', `Remove ${line.name}`);
    remove.addEventListener('click', () => action(async () => {
      await api(projectPath(`/components/${encodeURIComponent(line.component_id)}`), undefined, false, 'DELETE');
      await refresh(); announce(`Removed ${line.name}. Use “Rebuild robot” to restore the full design.`);
    }, 'Removing part…'));
    li.append(pick, node('span', cents(line.line_total_usd), 'price'), remove);
    const buy = state.buy?.project === state.project.id ? state.buy.lines[line.component_id] : null;
    if (buy && buy.name === line.name) li.append(buyLink(buy));
    return li;
  }));
  if (!bom.lines.length) $('bom-lines').append(node('li', 'No parts yet. Use “Rebuild robot”.', 'muted'));
  const arch = state.project.architecture || {};
  const warnings = [...(arch.warnings || []), ...(arch.edit_warnings || [])];
  $('warnings').hidden = !warnings.length;
  $('warnings').replaceChildren(...warnings.map(w => node('p', `⚠ ${w}`)));
  const decisions = arch.decisions || [];
  $('decisions-box').hidden = !decisions.length;
  $('decisions').replaceChildren(...decisions.map(d => { const li = node('li'); li.append(node('b', `${d.part}: `), `${d.choice}. ${d.reason}`); return li; }));
  if (state.selected) markRow(state.selected);
}
function buyLink(line) {
  const o = line.offer;
  const a = node('a', o ? `Buy at ${o.store}${o.price_usd ? ` · ~${cents(o.price_usd)} on the page` : ''} ↗` : 'No exact match found · search Amazon ↗',
    o ? 'buy' : 'buy search');
  a.href = o ? o.url : line.search_url; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}
async function findWhereToBuy() {
  const r = await api(projectPath('/finance/where-to-buy'), {});
  state.buy = {project: state.project.id, result: r, lines: Object.fromEntries(r.lines.map(l => [l.component_id, l]))};
  const found = r.lines.filter(l => l.offer).length;
  $('buy-summary').textContent = [
    r.main_store ? `Most parts at ${r.main_store} (${r.at_main_store} of ${r.bought_parts}); others where it's clearly cheaper.` : 'No store links found.',
    `${found} of ${r.bought_parts} matched a product page.`,
    r.printed_parts ? `${r.printed_parts} printed: download the STL below.` : '',
    'Check price and stock on the store page.'].filter(Boolean).join(' ');
  renderParts(state.bom);
  return r;
}
function renderFacts(a, bom) {
  const s = a.summary;
  $('fact-wheels').textContent = s.wheels || 'None';
  $('fact-joints').textContent = s.arm_joints || 'None';
  $('fact-height').textContent = `${Math.round(s.height_m * 100)} cm`;
  $('fact-reach').textContent = s.arm_reach_m ? `${Math.round(s.arm_reach_m * 100)} cm` : '—';
  $('fact-mass').textContent = `${bom.total_mass_kg.toFixed(1)} kg`;
}
function renderBrief(p) {
  const r = p.requirements;
  $('req-description').value = r.description || '';
  $('req-payload').value = r.payload_kg ?? '';
  $('req-mobility').value = r.mobility === 'fixed' ? 'fixed' : 'wheeled';
  $('req-runtime').value = r.runtime_hours ?? '';
  $('req-budget').value = r.budget_usd ?? '';
}

// ---------- 3D stage ----------
function ensureViewer() {
  if (state.viewer || !webglAvailable()) return state.viewer;
  state.viewer = new Viewer($('stage'), {onSelect: info => select(info?.component_id ?? null, false, info?.label)});
  return state.viewer;
}
async function renderStage(force = false) {
  const parts = partList();
  if (state.view === 'part' && !parts.length) state.view = 'robot';
  $('view-robot').setAttribute('aria-pressed', String(state.view === 'robot'));
  $('view-part').setAttribute('aria-pressed', String(state.view === 'part'));
  $('view-part').disabled = state.busy || !parts.length;
  const part = parts.find(p => p.design_id === state.partId) || parts.at(-1);
  const key = state.view === 'robot' ? `robot:${state.project.id}:${state.project.revision}` : `part:${part.design_id}`;
  if (!force && key === state.stageKey) return;
  state.stageKey = key;
  const viewer = ensureViewer();
  if (!viewer) { $('stage').replaceChildren(node('p', '3D needs WebGL, which this browser has turned off. The parts list and downloads still work.', 'placeholder')); return; }
  resetViewerControls('robot');
  $('explode').disabled = state.view !== 'robot';
  try {
    if (state.view === 'robot') {
      $('geometry-state').textContent = 'Building CAD model…';
      if (!$('stage').querySelector('canvas')) $('stage').replaceChildren(node('p', 'Building the CAD model of your robot…', 'placeholder'));
      try {
        const shown = await viewer.showRobot(projectPath(`/robot/glb?revision=${state.project.revision}`), `CAD model of ${state.assembly.robot_type}`);
        if (shown === false) return; // a newer render replaced this one
        $('geometry-state').textContent = 'CAD model · STEP ready';
      } catch {
        await viewer.showAssembly(state.assembly);
        $('geometry-state').textContent = 'Simplified preview';
      }
      viewer.inspectInternals($('inspect-internals').checked, state.assembly);
      if (state.selected) select(state.selected, true);
      else $('selection').textContent = 'Click any part in the 3D view or the list to see what it is.';
    } else {
      closeInspector();
      await viewer.showPart(projectPath(`/cad/${encodeURIComponent(part.design_id)}/glb?revision=${state.project.revision}`), KIND_NAMES[part.spec.kind]);
      $('geometry-state').textContent = 'Geometry checked';
      $('selection').textContent = `${KIND_NAMES[part.spec.kind]} · ${part.spec.length_mm} × ${part.spec.width_mm} × ${part.spec.thickness_mm} mm · ${(part.geometry.mass_kg * 1000).toFixed(0)} g · ${part.spec.material.toUpperCase()}`;
    }
  } catch { state.stageKey = null; $('stage').replaceChildren(node('p', 'The 3D model could not be loaded. Try again.', 'placeholder')); }
}
function markRow(componentId) {
  document.querySelectorAll('.part-row').forEach(row => row.classList.toggle('selected', row.dataset.component === componentId));
}
function select(componentId, fromList, label) {
  state.selected = componentId;
  if (fromList && state.view !== 'robot') { state.view = 'robot'; renderStage(); }
  state.viewer?.highlight(componentId);
  markRow(componentId);
  const line = state.bom?.lines.find(l => l.component_id === componentId);
  if (!line) {
    closeInspector();
    $('selection').textContent = label ? `${label.replaceAll('_', ' ')} (structure)` : 'Click any part in the 3D view or the list to see what it is.';
    return;
  }
  const sel = $('selection'); sel.replaceChildren(node('b', line.name), ` · ${line.quantity} × ${cents(line.unit_cost_usd)} = ${cents(line.line_total_usd)}${line.lead_time_days ? ` · ships in ~${line.lead_time_days} days` : ''}`);
  if (!fromList) document.querySelector(`.part-row[data-component="${CSS.escape(componentId)}"]`)?.scrollIntoView({block: 'nearest'});
  openInspector(componentId);
}

// ---------- part inspector: what it holds, how hard it works, edit it with Forge ----------
const KIND_LABELS = {frame: 'Frame', drive_motor: 'Drive motor', arm_servo: 'Arm joint', battery: 'Battery', compute: 'Computer',
  camera: 'Camera', lidar: 'Lidar', microphone: 'Microphone', gripper: 'Gripper', wheel: 'Wheels', track: 'Tracks',
  pan_tilt: 'Pan-tilt head', lights: 'Lights', cargo_bin: 'Cargo bin', lift: 'Lift', vacuum: 'Vacuum', side_brush: 'Side brushes',
  proximity: 'Bumper sensors', display: 'Screen', speaker: 'Speaker', wiring: 'Wiring'};
const fmt = v => String(Math.round(v * 100) / 100);
const kindLabel = kind => KIND_LABELS[kind] || kind.replaceAll('_', ' ');
async function openInspector(componentId) {
  const token = state.inspToken = (state.inspToken || 0) + 1;
  $('inspector').classList.add('loading');
  let info;
  try { info = await api(projectPath(`/components/${encodeURIComponent(componentId)}/info?revision=${state.project.revision}`)); }
  catch { if (token === state.inspToken) closeInspector(); return; }
  if (token !== state.inspToken || state.selected !== componentId) return;
  state.inspInfo = info;
  renderInspector(info);
}
function closeInspector() {
  state.inspToken = (state.inspToken || 0) + 1; state.inspInfo = null;
  $('inspector').hidden = true; $('selection').hidden = false;
}
function partChip(item) {
  const li = node('li'); const b = node('button', item.quantity > 1 ? `${item.quantity} × ${item.name}` : item.name); b.type = 'button';
  b.addEventListener('click', () => select(item.component_id, true)); li.append(b); return li;
}
function renderInspector(info) {
  const box = $('inspector'); box.hidden = false; box.classList.remove('loading'); $('selection').hidden = true;
  $('insp-kind').textContent = `${kindLabel(info.kind)} · ${info.category}`;
  $('insp-name').textContent = info.name;
  $('insp-meta').textContent = [info.supplier, info.lead_time_days ? `ships in ~${info.lead_time_days} days` : null,
    info.source === 'generated' ? 'printed part' : null].filter(Boolean).join(' · ');
  $('insp-price').textContent = cents(info.line_total_usd);
  $('insp-unit').textContent = info.quantity > 1 ? `${info.quantity} × ${cents(info.unit_cost_usd)}` : 'per robot';
  const about = info.explain;
  $('insp-does').textContent = about.does;
  $('insp-job').hidden = !about.job; $('insp-job').textContent = about.job ? `In this robot: ${about.job}` : '';
  $('insp-why-box').hidden = !about.why; $('insp-why').textContent = about.why || '';
  $('insp-specs').replaceChildren(...info.specs.map(s => {
    const d = node('div'); const dd = node('dd', fmt(s.value)); dd.append(' ', node('small', s.unit)); d.append(node('dt', s.label), dd); return d;
  }));
  const load = info.load; $('insp-load').hidden = !load;
  if (load) {
    $('insp-load').className = `insp-load ${load.status}`;
    $('insp-load-label').textContent = load.label;
    $('insp-load-value').textContent = `${fmt(load.need)} of ${fmt(load.have)} ${load.unit}`;
    $('insp-load-bar').style.width = '0%';
    requestAnimationFrame(() => requestAnimationFrame(() => { $('insp-load-bar').style.width = `${Math.min(100, load.pct)}%`; }));
    $('insp-load-note').textContent = load.status === 'over' ? `${load.pct}% of its rating: too weak for this robot. Ask Forge for a stronger one.`
      : load.status === 'tight' ? `${load.pct}% of its rating: little margin left.` : `${load.pct}% of its rating: plenty of margin.`;
  }
  $('insp-holds-title').textContent = info.holds_verb;
  $('insp-holds').replaceChildren(...(info.holds.length ? info.holds.map(partChip) : [node('li', 'No other parts', 'none')]));
  $('insp-carries').hidden = !info.carries; $('insp-carries').textContent = info.carries || '';
  $('insp-mounted-box').hidden = !info.mounted_on;
  $('insp-mounted').replaceChildren(...(info.mounted_on ? [partChip(info.mounted_on)] : []));
  $('insp-swap').hidden = !info.alternatives.length;
  $('insp-alts').replaceChildren(...info.alternatives.map(a => {
    const li = node('li'); const b = node('button'); b.type = 'button';
    const row = node('span', undefined, 'alt-row');
    row.append(node('span', a.key_spec ? `${a.key_spec.label} ${fmt(a.key_spec.value)} ${a.key_spec.unit}` : `Quality ${a.quality}/5`),
      node('span', `${a.delta_usd >= 0 ? '+' : '−'}${money(Math.abs(a.delta_usd))}`, `delta ${a.delta_usd > 0 ? 'up' : 'down'}`));
    b.append(node('b', a.name), row);
    if (a.meets !== null) b.append(node('span', a.meets ? 'Strong enough' : 'Too weak here', `verdict ${a.meets ? 'ok' : 'weak'}`));
    b.setAttribute('aria-label', `Swap to ${a.name}`);
    b.addEventListener('click', () => action(() => editPart({catalog_id: a.catalog_id}), `Swapping to ${a.name}…`));
    li.append(b); return li;
  }));
  drawBlueprint(info);
  lock(state.busy); // new buttons follow the current busy state
  tellForgeSelection();
}
function drawBlueprint(info) {
  const meshes = state.viewer?.partMeshes(info.component_id) || [];
  $('insp-blueprint').hidden = !meshes.length;
  if (!meshes.length) return;
  state.blueprint ||= new Blueprint($('blueprint-sheet'));
  state.blueprint.show(meshes);
  $('blueprint-caption').textContent = `${info.name}${info.quantity > 1 ? ` · 1 of ${info.quantity} shown` : ''} · third-angle projection, overall dimensions in mm`;
}
function tellForgeSelection() {
  const info = state.inspInfo;
  if (!live.active || !info || state.toldForge === `${info.component_id}:${state.project.revision}`) return;
  state.toldForge = `${info.component_id}:${state.project.revision}`;
  live.contextUpdate(`The user selected "${info.name}" (${kindLabel(info.kind)}) in the 3D view. "This", "it" or "this part" means it. Use edit_part to change it. What it does: ${info.explain.does}${info.explain.job ? ` In this robot: ${info.explain.job}` : ''}${info.explain.why ? ` Why this one: ${info.explain.why}` : ''}`);
}
async function editPart(change, componentId = state.selected) {
  if (!componentId) throw new Error('Select a part first.');
  $('inspector').classList.add('thinking');
  try {
    const res = await api(projectPath(`/components/${encodeURIComponent(componentId)}/edit`), change);
    if (res.changed) {
      if (!res.component_id) { state.selected = null; closeInspector(); }
      state.stageKey = null;
      await refresh();
    }
    announce(res.reply);
    return res;
  } finally { $('inspector').classList.remove('thinking'); }
}
function findLine(name) {
  const words = String(name || '').toLowerCase().split(/\W+/).filter(w => w.length > 1 && !['this', 'it', 'the', 'part', 'one', 'selected'].includes(w));
  const scored = (state.bom?.lines || []).map(l => ({l, score: words.filter(w => `${l.name} ${l.category} ${l.kind.replaceAll('_', ' ')}`.toLowerCase().includes(w)).length}))
    .sort((a, b) => b.score - a.score);
  return scored.length && scored[0].score ? scored[0].l : null;
}

// ---------- design flow ----------
async function startDesign(brief, budget) {
  const name = brief.length > 48 ? `${brief.slice(0, 46).trim()}…` : brief;
  announce('Picking parts and sizing motors, battery and arm…', false, true);
  state.project = await api('/projects', {name, requirements: {description: brief, budget_usd: budget}});
  resetConversation();
  await api(projectPath('/design/auto'), {});
  await refresh();
  announce('Your robot is ready. Click parts to inspect them, or adjust the brief and rebuild.');
  reviewBrief(brief);
}
async function reviewBrief(message) {
  // Background: the Architect reads the brief and asks one follow-up question.
  const projectId = state.project.id;
  $('architect-state').textContent = 'Reviewing…';
  try {
    const result = await api(projectPath('/architect/chat'), {message});
    if (state.project?.id !== projectId) return;
    $('architect-note').hidden = false;
    $('architect-reply').textContent = [result.reply, ...(result.feasibility_concerns || []).slice(0, 2)].join(' ');
    $('architect-form').hidden = !result.next_question;
    $('architect-state').textContent = result.ready_for_design ? 'Brief complete' : 'Has a question';
    const p = await api(projectPath());
    if (state.project?.id !== projectId) return;
    state.project = p; renderBrief(p); $('revision').textContent = `Revision ${p.revision}`;
  } catch { $('architect-state').textContent = 'Argus'; }
}
function readBrief() {
  const number = id => $(id).value === '' ? null : Number($(id).value);
  return {...state.project.requirements, description: $('req-description').value.trim(), payload_kg: number('req-payload'),
    mobility: $('req-mobility').value, runtime_hours: number('req-runtime'), budget_usd: number('req-budget')};
}
async function createDemo() {
  state.project = await api('/projects/demo', {}); resetConversation(); state.stageKey = null; state.selected = null; await refresh();
  $('architect-note').hidden = true;
}

// ---------- CAD ----------
function applyPreset() {
  const kind = document.querySelector('input[name="part-kind"]:checked').value;
  const size = document.querySelector('input[name="part-size"]:checked').value;
  [$('length').value, $('width').value, $('thickness').value] = PRESETS[kind][size];
  $('part-price').value = PRESETS[kind].price;
}
async function generatePart(spec, prompt) {
  announce('Building the part and checking the exported geometry…', false, true);
  const result = await api(projectPath('/agents/mechanical'), {
    ...(prompt ? {prompt} : {spec}), estimated_unit_cost_usd: Number($('part-price').value)});
  state.partId = result.design_id; state.view = 'part';
  await refresh();
  $('part-details').textContent = `${KIND_NAMES[result.spec.kind]} built: ${result.spec.length_mm} × ${result.spec.width_mm} × ${result.spec.thickness_mm} mm, ${(result.geometry.mass_kg * 1000).toFixed(0)} g. Added to the parts list and the robot. Switch to “Whole robot” to see it in place.`;
  return result;
}
function robotDownload() {
  const box = node('div', undefined, 'download');
  box.append(node('h3', 'Whole robot'), node('p', 'Full assembly as one CAD file. Store-bought parts are representative models.', 'muted'));
  const links = node('div', undefined, 'links');
  for (const [format, label] of [['step', 'STEP (CAD)'], ['glb', 'GLB (3D view)'], ['report', 'Build report']]) {
    const a = node('a', `↓ ${label}`); a.href = projectPath(`/robot/${format}?revision=${state.project.revision}`);
    a.setAttribute('download', ''); links.append(a);
  }
  box.append(links); return box;
}
function renderDownloads() {
  const parts = partList();
  if (!parts.length) { $('downloads').replaceChildren(robotDownload(), node('p', 'Build a custom part to download its printable files too.', 'muted')); return; }
  $('downloads').replaceChildren(robotDownload(), ...parts.map(part => {
    const box = node('div', undefined, 'download');
    box.append(node('h3', KIND_NAMES[part.spec.kind] || part.spec.kind),
      node('p', `${part.spec.length_mm} × ${part.spec.width_mm} × ${part.spec.thickness_mm} mm · ${part.spec.material.toUpperCase()} · ${(part.geometry.mass_kg * 1000).toFixed(0)} g`, 'muted'));
    const links = node('div', undefined, 'links');
    for (const [format, label] of [['step', 'STEP (CAD)'], ['stl', 'STL (3D print)'], ['glb', 'GLB (3D view)'], ['report', 'Check report']]) {
      const a = node('a', `↓ ${label}`); a.href = projectPath(`/cad/${encodeURIComponent(part.design_id)}/${format}?revision=${state.project.revision}`);
      a.setAttribute('download', ''); links.append(a);
    }
    const view = node('button', 'View in 3D', 'quiet view'); view.type = 'button';
    view.addEventListener('click', () => { state.partId = part.design_id; state.view = 'part'; renderStage(); $('stage').scrollIntoView({behavior: 'smooth', block: 'center'}); });
    box.append(links, view); return box;
  }));
}
function downloadCSV() {
  const buy = state.buy?.project === state.project.id ? state.buy.lines : {};
  const rows = [['Part', 'Category', 'Source', 'Quantity', 'Unit USD', 'Total USD', 'Supplier', 'Lead time days', 'Store', 'Buy link']];
  for (const l of state.bom.lines) {
    const offer = buy[l.component_id]?.name === l.name ? buy[l.component_id].offer : null;
    rows.push([l.name, l.category, l.source, l.quantity, l.unit_cost_usd, l.line_total_usd, l.supplier || '', l.lead_time_days ?? '',
      offer?.store || '', offer?.url || '']);
  }
  rows.push(['Total', '', '', '', '', state.bom.total_usd, '', '', '', '']);
  const csv = rows.map(r => r.map(v => `"${String(v).replaceAll('"', '""')}"`).join(',')).join('\n');
  const url = URL.createObjectURL(new Blob([csv], {type: 'text/csv'}));
  const a = node('a'); a.href = url; a.download = `${state.project.name.replace(/[^\w-]+/g, '_').slice(0, 40)}_parts.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---------- assembly guide ----------
function partName(componentId) { return state.bom?.lines.find(l => l.component_id === componentId)?.name; }
async function openAssemble() {
  const data = await api(projectPath(`/assembly-guide?revision=${state.project.revision}`));
  state.guide = {data, index: 0};
  renderGuide(data);
  show('assemble');
  goStep(0);
  await renderAsmStage();
  goStep(state.guide.index);
  announce('Assembly guide ready. Use “Next step” to build it part by part.');
}
async function renderAsmStage() {
  if (state.asmViewer === null && webglAvailable()) {
    state.asmViewer = new Viewer($('asm-stage'), {onSelect: info => {
      $('asm-picked').textContent = info ? partName(info.component_id) || info.label : 'Click a part to name it';
      goStep(state.guide.index);
    }});
  }
  if (!state.asmViewer) { $('asm-stage').replaceChildren(node('p', '3D needs WebGL, which this browser has turned off. The steps below still work.', 'placeholder')); return; }
  const key = `${state.project.id}:${state.project.revision}`;
  if (state.asmKey === key) return;
  try {
    const shown = await state.asmViewer.showRobot(projectPath(`/robot/glb?revision=${state.project.revision}`), `Assembly of ${state.assembly.robot_type}`);
    if (shown === false) return;
  } catch { await state.asmViewer.showAssembly(state.assembly); }
  resetViewerControls('assembly');
  state.asmKey = key;
}
function goStep(index) {
  const steps = state.guide.data.steps;
  index = Math.max(0, Math.min(steps.length - 1, index));
  state.guide.index = index;
  // Parts appear as they are fitted; printed parts are only shown on the print step and once fitted.
  const current = new Set(steps[index].nodes), shown = new Set(current);
  steps.forEach((s, i) => { if (i <= index && s.key !== 'print') s.nodes.forEach(n => shown.add(n)); });
  state.asmViewer?.stage(shown, current);
  $('asm-count').textContent = `Step ${index + 1} of ${steps.length} · ${steps[index].title}`;
  const detail = $('asm-detail-link'), key = steps[index].key;
  detail.hidden = !['wiring', 'print'].includes(key);
  detail.href = key === 'wiring' ? '#wiring-title' : '#prints-title';
  detail.textContent = key === 'wiring' ? 'View wiring table →' : 'View printable files →';
  $('asm-prev').disabled = index === 0;
  $('asm-next').disabled = index === steps.length - 1;
  $('asm-next').textContent = index === steps.length - 1 ? 'All done ✓' : 'Next step →';
  const s = steps[index];
  $('asm-current-title').textContent = `${index + 1}. ${s.title}`;
  $('asm-current-items').replaceChildren(...s.items.map(text => node('li', text)));
  const parts = [...new Set(s.components.map(partName).filter(Boolean))];
  $('asm-current-parts').textContent = parts.length ? `Parts: ${parts.join(', ')}` : '';
  document.querySelectorAll('#asm-steps > li').forEach((li, i) => {
    li.className = i === index ? 'current' : i < index ? 'done' : '';
    li.querySelector('button').setAttribute('aria-current', i === index ? 'step' : 'false');
  });
}
function renderGuide(g) {
  $('asm-type').textContent = `${g.robot_type.replaceAll('_', ' ')} · assembly guide`;
  $('asm-title').textContent = `How to build ${state.project.name}`;
  $('asm-notes').replaceChildren(...g.notes.map(t => node('li', t)));
  $('asm-protection').replaceChildren(...g.protection.map(t => node('li', t)));
  $('asm-buy').replaceChildren(...g.buy.map(p => node('li', `${p.quantity} × ${p.name}`)));
  $('asm-step-count').textContent = `${g.steps.length} steps`;
  $('asm-steps').replaceChildren(...g.steps.map((s, i) => {
    const li = node('li');
    const head = node('button'); head.type = 'button'; head.dataset.static = '1';
    head.append(node('b', String(i + 1)), node('span', s.title));
    head.addEventListener('click', () => goStep(i));
    li.append(head); return li;
  }));

  const printable = g.prints.filter(p => p.printable);
  $('prints-count').textContent = printable.length ? `${printable.reduce((n, p) => n + p.quantity, 0)} to print` : 'None';
  $('asm-prints').replaceChildren(...(g.prints.length ? g.prints.map(p => {
    const li = node('li', undefined, 'print-row');
    const text = node('div');
    text.append(node('b', `${p.name}${p.quantity > 1 ? ` × ${p.quantity}` : ''}`));
    if (p.printable) {
      text.append(node('small', `${p.size_mm.join(' × ')} mm · ${p.material} · ≈${p.grams_each} g · ≈${p.hours_each} h each`),
        node('small', `${p.orientation} ${p.settings}.`, 'muted'));
      text.append(node('small', p.note, p.fits_bed ? 'muted' : 'warn'));
    } else text.append(node('small', p.note, 'muted'));
    li.append(text);
    if (p.printable) {
      const links = node('div', undefined, 'links');
      for (const [format, label] of [['stl', '↓ STL (print)'], ['step', '↓ STEP (CAD)']]) {
        const b = node('button', label, 'quiet'); b.type = 'button'; b.dataset.static = '1';
        b.addEventListener('click', () => downloadPrint(p, format, b));
        links.append(b);
      }
      li.append(links);
    }
    return li;
  }) : [node('li', 'Nothing in this robot is 3D-printed. Every part is bought.', 'muted')]));
  $('prints-bed').textContent = printable.length ? `Sizes are checked against a ${g.bed_mm.join(' × ')} mm printer. Files are generated and geometry-checked when you download them.` : '';

  const w = g.wiring;
  $('wiring-source').textContent = `${w.voltage_v} V`;
  $('wiring-summary').textContent = `Power comes from the ${w.source}: ${w.voltage_v} V nominal, ${w.full_voltage_v} V fully charged, about ${w.total_a} A in normal use.`;
  $('wiring-rows').replaceChildren(...w.rows.flatMap(r => {
    const tr = node('tr', undefined, r.type);
    const route = node('td'); route.append(node('b', r.from), node('span', ` → ${r.to}`));
    tr.append(route, node('td', r.voltage), node('td', r.current_a === null ? '—' : `${r.current_a} A`),
      node('td', r.wire), node('td', r.connector || '—'), node('td', r.fuse_a ? `${r.fuse_a} A` : '—'));
    if (!r.note) return [tr];
    const note = node('tr', undefined, 'note'); const td = node('td', r.note); td.colSpan = 6; note.append(td);
    return [tr, note];
  }));
  $('wiring-notes').replaceChildren(...w.notes.map(t => node('li', t)));
  $('asm-extras').replaceChildren(...w.extras.map(t => node('li', t)));
  $('asm-tools').replaceChildren(...g.tools.map(t => node('li', t)));
}
async function downloadPrint(item, format, button) {
  const label = button.textContent;
  button.disabled = true; button.textContent = 'Preparing…';
  announce(`Generating ${item.name} and checking its geometry…`, false, true);
  try {
    const guide = state.guide.data;
    const response = await fetch(`/projects/${encodeURIComponent(guide.project_id)}/prints/${item.index}/${format}?revision=${guide.revision}`, {cache: 'no-store'});
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === 'string' ? payload.detail : 'The file could not be generated.');
    }
    const url = URL.createObjectURL(await response.blob());
    const a = node('a'); a.href = url; a.download = `${item.name.replace(/[^\w-]+/g, '_')}.${format}`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce(`${item.name} ${format.toUpperCase()} downloaded.`);
  } catch (error) { announce(error.message, true); }
  finally { button.disabled = false; button.textContent = label; }
}

// ---------- telemetry ----------
function renderTelemetry(result, error) {
  $('telemetry-result').textContent = !result ? error || 'Loading telemetry…' : !result.metrics.length
    ? `No measurements yet · ${result.storage} storage.` : result.metrics.map(metric =>
      `${metric.metric}: average ${metric.average} ${metric.unit} · ${metric.samples} samples · ${result.storage} storage`).join(' | ');
}
async function seedTelemetry() {
  const observed_at = new Date().toISOString();
  for (const value of [40, 60]) await api(projectPath('/telemetry'), {observed_at, scenario_id: 'frontend-demo', metric: 'battery_pct', value, unit: 'percent'});
  const summary = await api(projectPath('/telemetry/summary') + '?scenario_id=frontend-demo');
  const points = await api(projectPath('/telemetry/timeseries') + '?scenario_id=frontend-demo');
  if (summary.storage !== 'tiger' || points.storage !== 'tiger') throw new Error('Samples used memory storage, not Tiger. Configure TIGER_DATABASE_URL.');
  if (!points.points.length) throw new Error('Tiger minute rollup is unavailable. Check database setup.');
  renderTelemetry(summary); return summary;
}

// ---------- chat / voice ----------
function resetConversation() {
  closeInspector(); state.selected = null;
  state.interaction = null; state.lastAudio = null; state.partId = null; state.view = 'robot'; state.buy = null;
  $('buy-summary').textContent = '';
  $('guided').checked = false; $('part-details').textContent = ''; $('cheaper-result').textContent = '';
  $('architect-note').hidden = true; $('architect-state').textContent = 'Argus';
  $('pacing-result').textContent = 'Standard explanations · speech at 1×';
}
async function askForge(message) {
  announce('Thinking about your robot…', false, true);
  const result = await api(projectPath('/voice/agent'), {message, speak: true, history: [], ...(state.interaction ? {interaction: state.interaction} : {})});
  state.lastAudio = result.audio ? new Blob([Uint8Array.from(atob(result.audio.base64), c => c.charCodeAt(0))], {type: 'audio/mpeg'}) : null;
  return result;
}

// ---------- guided E2E check ----------
function step(index, status) {
  const el = document.querySelector(`[data-step="${index}"]`); el.className = status;
  el.querySelector('small').textContent = {running: 'In progress…', passed: 'Passed', failed: 'Failed', '': 'Not run'}[status];
}
async function runDemo() {
  let current = 0; for (let index = 0; index < 5; index++) step(index, '');
  try {
    step(0, 'running'); announce('01 / Creating the sample robot…', false, true); await createDemo(); step(0, 'passed');
    current = 1; step(1, 'running'); $('part-price').value = '8';
    const part = await generatePart({kind: 'arm_link', length_mm: 120, width_mm: 40, thickness_mm: 6});
    if (!Object.values(part.geometry.checks).every(Boolean)) throw new Error('CAD geometry checks did not pass.'); step(1, 'passed');
    current = 2; step(2, 'running'); announce('03 / Writing labelled test telemetry to Tiger…', false, true); await seedTelemetry(); step(2, 'passed');
    current = 3; step(3, 'running');
    const reply = await askForge('Summarize this robot’s current parts estimate, budget including contingency, and the battery_pct development test samples in two short sentences. Speak all currency amounts in words with dollars and cents so speech reads them clearly. Do not propose CAD or claim a real simulation ran.');
    if (!reply.audio) throw new Error(reply.speech_error || 'No speech was returned.'); step(3, 'passed');
    current = 4; step(4, 'running'); announce('05 / Transcribing the generated speech with ElevenLabs (no microphone)…', false, true);
    const transcript = await api('/voice/transcribe?consent=true', state.lastAudio, true);
    if (!transcript.text) throw new Error('The generated speech returned no transcript.');
    step(4, 'passed');
    announce(`E2E check passed. ElevenLabs heard: “${transcript.text}”`);
  } catch (error) { step(current, 'failed'); throw error; }
}
async function integrations() {
  const status = await api('/integrations/status');
  $('llm-status').textContent = `AI · ${status.llm.provider} ${status.llm.configured ? status.llm.model : 'key missing'}`;
  $('voice-status').textContent = `ElevenLabs · ${status.elevenlabs.configured ? 'configured' : 'not configured'}`;
  $('presage-status').textContent = `Presage · ${status.presage.key_configured ? 'key configured' : 'key missing'} · camera off`;
  await checkTiger(false);
}

async function checkTiger(retry = true) {
  $('retry-tiger').disabled = true;
  $('tiger-status').textContent = 'Tiger · checking…';
  $('tiger-detail').textContent = 'Checking encrypted database access…';
  try {
    const health = await api(`/integrations/tiger/health${retry ? '?retry=true' : ''}`, undefined, false, 'GET', 20000);
    $('tiger-status').textContent = `Tiger · ${health.connected ? health.schema_ready ? 'connected' : 'schema missing' : health.configured ? 'connection failed' : 'not configured'}`;
    $('tiger-detail').textContent = health.error || (health.connected && health.schema_ready
      ? 'Connected to Tiger. Telemetry table and minute rollup are ready. No real robot measurements are collected automatically.'
      : health.action || 'Initialize the telemetry schema.');
    $('setup-tiger').hidden = !health.connected || health.schema_ready;
    if (health.connected && health.schema_ready && state.project) renderTelemetry(await api(projectPath('/telemetry/summary')));
    return health;
  } catch (error) {
    $('tiger-status').textContent = 'Tiger · check failed';
    $('tiger-detail').textContent = error.name === 'AbortError' ? 'Database health check timed out. Check network access, then retry.' : error.message;
  } finally { $('retry-tiger').disabled = false; }
}

// ---------- events ----------
$('start-form').addEventListener('submit', event => { event.preventDefault(); const brief = $('brief').value.trim(); if (brief) action(() => startDesign(brief, Number($('budget').value))); });
document.querySelectorAll('[data-example]').forEach(chip => chip.addEventListener('click', () => {
  const [text, budget] = EXAMPLES[chip.dataset.example]; $('brief').value = text; $('budget').value = budget; $('brief').focus();
}));
$('sample').addEventListener('click', () => action(async () => { await createDemo(); announce('Sample robot loaded. It starts over budget; try “Fit it to my budget”.'); }, 'Loading the sample robot…'));
$('new-robot').addEventListener('click', () => { if (state.busy) return; state.project = null; resetConversation(); lock(false); show('start'); $('brief').focus(); });
async function openProject(id) {
  state.project = await api(`/projects/${encodeURIComponent(id)}`); resetConversation(); state.stageKey = null; await refresh(); announce(`Opened ${state.project.name}.`);
}
$('project-select').addEventListener('change', () => { const id = $('project-select').value; if (id) action(() => openProject(id), 'Opening robot…'); });
$('view-robot').addEventListener('click', () => { state.view = 'robot'; renderStage(); });
$('view-part').addEventListener('click', () => { state.view = 'part'; renderStage(); });
async function makeCheaper() {
  const budget = await api(projectPath('/finance/budget'));
  const body = budget.status === 'over_budget' ? {target_savings_usd: -budget.remaining_usd, apply: true} : {target_savings_pct: 10, apply: true};
  const {result} = await api(projectPath('/finance/optimize'), body);
  await refresh();
  $('cheaper-result').textContent = result.substitutions.length
    ? `Saved ${cents(result.savings_usd)}: ${result.substitutions.map(s => `${s.from_name} → ${s.to_name}`).join('; ')}. Swaps keep the same or better torque/capacity; fit still needs checking.`
    : 'No cheaper catalog parts with equal specs. Try a lower payload, fewer features, or a higher budget in your brief.';
  announce(result.substitutions.length ? `Saved ${cents(result.savings_usd)}.` : 'Nothing cheaper found with equal specs.');
  return result;
}
$('cheaper').addEventListener('click', () => action(makeCheaper, 'Looking for cheaper parts with the same specs…'));

// ---------- live voice agent (tools run here, on the same revisioned API) ----------
async function whenIdle(task) {
  // Voice tools wait for any running UI action, then hold the lock while they run.
  for (let i = 0; state.busy && i < 600; i++) await new Promise(r => setTimeout(r, 100));
  lock(true);
  try { return await task(); } finally { lock(false); }
}
async function summary() { return state.project ? api(projectPath('/summary')) : {robot: null, hint: 'No robot yet. Ask what it should do and the budget, then call start_new_robot.'}; }
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, Number(v)));
const liveTools = {
  get_robot_status: () => summary(),
  start_new_robot: ({description, budget_usd}) => whenIdle(async () => {
    $('brief').value = description; $('budget').value = clamp(budget_usd || 2500, 300, 20000);
    await startDesign(String(description).slice(0, 4000), clamp(budget_usd || 2500, 300, 20000));
    return summary();
  }),
  set_budget: ({budget_usd}) => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet. Use start_new_robot first.'};
    const value = Math.round(clamp(budget_usd, 300, 20000) / 50) * 50;
    $('budget-slider').max = String(Math.max(Number($('budget-slider').max), value));
    await rebuildForBudget(value); return summary();
  }),
  update_brief: params => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet. Use start_new_robot first.'};
    const updates = {};
    if (params.payload_kg !== undefined) updates.payload_kg = clamp(params.payload_kg, 0, 50);
    if (params.runtime_hours !== undefined) updates.runtime_hours = clamp(params.runtime_hours, 0.5, 12);
    if (['wheeled', 'fixed'].includes(params.mobility)) updates.mobility = params.mobility;
    if (params.description) updates.description = String(params.description).slice(0, 4000);
    if (params.robot_type) updates.robot_type = params.robot_type === 'automatic' ? null : params.robot_type;
    if (params.contingency_pct !== undefined) updates.contingency_pct = clamp(params.contingency_pct, 0, 50);
    await api(projectPath('/design/auto'), {requirements: {...state.project.requirements, ...updates}});
    state.stageKey = null; await refresh(); return summary();
  }),
  make_it_cheaper: () => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet.'};
    const result = await makeCheaper();
    return {saved_usd: result.savings_usd, swaps: result.substitutions.map(s => `${s.from_name} to ${s.to_name}`), status: await summary()};
  }),
  find_where_to_buy: () => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet.'};
    const r = await findWhereToBuy();
    $('bom-lines').scrollIntoView({behavior: 'smooth', block: 'center'});
    return {main_store: r.main_store, parts_at_main_store: r.at_main_store, bought_parts: r.bought_parts,
      printed_parts: r.printed_parts, note: 'Prices are from store pages and must be checked before buying.',
      parts: r.lines.map(l => ({name: l.name, store: l.offer?.store || 'no exact match', price_seen_usd: l.offer?.price_usd ?? null}))};
  }),
  highlight_part: async ({part_name}) => {
    if (!state.bom) return {error: 'No robot yet.'};
    const line = findLine(part_name);
    if (!line) return {found: false, parts: state.bom.lines.map(l => l.name)};
    select(line.component_id, true);
    $('stage').scrollIntoView({behavior: 'smooth', block: 'center'});
    const info = await api(projectPath(`/components/${encodeURIComponent(line.component_id)}/info`));
    return {found: true, name: line.name, quantity: line.quantity, total_usd: line.line_total_usd, explain: info.explain,
      [info.holds_verb.toLowerCase()]: info.holds.map(h => h.name), mounted_on: info.mounted_on?.name || null,
      load: info.load, alternatives: info.alternatives.map(a => ({name: a.name, extra_usd: a.delta_usd, strong_enough: a.meets}))};
  },
  edit_part: ({part_name, instruction}) => whenIdle(async () => {
    if (!state.bom) return {error: 'No robot yet.'};
    const line = part_name ? findLine(part_name) : null;
    const id = line?.component_id || state.selected;
    if (!id) return {error: 'No part selected. Ask which part, then pass part_name.', parts: state.bom.lines.map(l => l.name)};
    if (id !== state.selected) select(id, true);
    const res = await editPart({instruction: String(instruction || '').slice(0, 500)}, id);
    return {changed: res.changed, reply: res.reply, warnings: res.warnings, status: await summary()};
  }),
  build_custom_part: ({kind, size, length_mm, width_mm, thickness_mm, material}) => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet.'};
    if (!PRESETS[kind]) return {error: 'Unknown part type.'};
    size = ['S', 'M', 'L'].includes(size) ? size : 'M';
    document.querySelector(`input[name="part-kind"][value="${kind}"]`).checked = true;
    document.querySelector(`input[name="part-size"][value="${size}"]`).checked = true;
    applyPreset();
    const preset = PRESETS[kind][size];
    const dims = [length_mm ? clamp(length_mm, 10, 1000) : preset[0], width_mm ? clamp(width_mm, 10, 1000) : preset[1],
      thickness_mm ? clamp(thickness_mm, 1, 50) : preset[2]];
    [$('length').value, $('width').value, $('thickness').value] = dims;
    const part = await generatePart({kind, length_mm: dims[0], width_mm: dims[1], thickness_mm: dims[2],
      ...(['petg', 'pla', 'aluminum'].includes(material) ? {material} : {}),
      ...(kind === 'motor_bracket' ? {hole_inset_mm: Math.min(16, Math.max(12, dims[1] / 4))} : {})});
    return {built: KIND_NAMES[kind], size_mm: dims, material: part.spec.material, mass_g: Math.round(part.geometry.mass_kg * 1000), status: await summary()};
  }),
  download_file: async ({file, part_name}) => {
    if (!state.project) return {error: 'No robot yet.'};
    if (file === 'parts_csv') { downloadCSV(); return {downloaded: 'parts list (CSV)'}; }
    const [scope, format] = file === 'build_report' ? ['robot', 'report'] : String(file).split('_');
    let path;
    if (scope === 'robot') path = `/robot/${format}?revision=${state.project.revision}`;
    else {
      const parts = partList();
      if (!parts.length) return {error: 'No custom parts yet. Offer to build one with build_custom_part.'};
      const words = String(part_name || '').toLowerCase().split(/\W+/).filter(Boolean);
      const part = parts.slice().reverse().find(p => words.some(w => KIND_NAMES[p.spec.kind].toLowerCase().includes(w))) || parts.at(-1);
      path = `/cad/${encodeURIComponent(part.design_id)}/${format}?revision=${state.project.revision}`;
    }
    if (!['step', 'glb', 'stl', 'report'].includes(format)) return {error: 'Unknown file type.'};
    const a = node('a'); a.href = projectPath(path); a.setAttribute('download', ''); a.click();
    return {downloaded: file.replace('_', ' ')};
  },
  set_view: async ({view, angle, close_panel}) => {
    if (!state.project) return {error: 'No robot yet.'};
    if (view === 'custom_part' && !partList().length) return {error: 'No custom parts yet.'};
    if (view) { state.view = view === 'custom_part' ? 'part' : 'robot'; await renderStage(); }
    if (close_panel) select(null);
    if (angle) state.viewer?.setAngle(angle);
    $('stage').scrollIntoView({behavior: 'smooth', block: 'center'});
    return {showing: state.view === 'part' ? 'custom part' : 'whole robot', angle: angle || null};
  },
  open_robot: ({name}) => whenIdle(async () => {
    const words = String(name || '').toLowerCase().split(/\W+/).filter(w => w.length > 2);
    const projects = await api('/projects');
    const match = projects.map(p => ({p, score: words.filter(w => `${p.name} ${p.requirements?.description || ''}`.toLowerCase().includes(w)).length}))
      .sort((a, b) => b.score - a.score)[0];
    if (!match?.score) return {found: false, robots: projects.map(p => p.name)};
    await openProject(match.p.id); show('workspace'); return summary();
  }),
  show_assembly: ({step}) => whenIdle(async () => {
    if (!state.project) return {error: 'No robot yet.'};
    if ($('assemble').hidden || !state.guide) await openAssemble();
    if (step) goStep(Math.round(Number(step)) - 1);
    const g = state.guide.data, current = g.steps[state.guide.index];
    return {showing_step: `${state.guide.index + 1} of ${g.steps.length}: ${current.title}`, instructions: current.items,
      steps: g.steps.map(s => s.title),
      to_print: g.prints.filter(p => p.printable).map(p => ({name: p.name, quantity: p.quantity, grams_each: p.grams_each, fits_printer: p.fits_bed})),
      power: `${g.wiring.source}, ${g.wiring.voltage_v} V`,
      wiring: g.wiring.rows.filter(r => r.type === 'power').map(r => `${r.from} to ${r.to}: ${r.wire}, ${r.fuse_a ? `${r.fuse_a} A fuse` : 'no fuse'}`)};
  }),
};
const live = new LiveVoice({tools: liveTools, getProjectId: () => state.project?.id || null, announce});
$('requirements-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
  const res = await api(projectPath('/design/auto'), {requirements: readBrief()}); state.stageKey = null;
  await refresh(); announce(res.warnings.length ? `Rebuilt with ${res.warnings.length} warning(s). See the parts list.` : 'Robot rebuilt from your brief.');
}, 'Rebuilding the robot from your brief…'); });
$('architect-form').addEventListener('submit', event => { event.preventDefault(); const answer = $('architect-answer').value.trim(); if (!answer) return; action(async () => {
  $('architect-answer').value = ''; await reviewBrief(answer);
  announce('Brief updated. Press “Rebuild robot” to apply it.');
}, 'Updating your brief…'); });
document.querySelectorAll('input[name="part-kind"], input[name="part-size"]').forEach(input => input.addEventListener('change', applyPreset));
$('cad-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
  const kind = document.querySelector('input[name="part-kind"]:checked').value;
  await generatePart({kind, length_mm: Number($('length').value), width_mm: Number($('width').value), thickness_mm: Number($('thickness').value),
    ...(kind === 'motor_bracket' ? {hole_inset_mm: Math.min(16, Math.max(12, Number($('width').value) / 4))} : {})}, $('cad-prompt').value.trim());
  announce('Part built. STEP, STL and GLB downloads are ready below.');
}); });
$('csv').addEventListener('click', downloadCSV);
$('to-assemble').addEventListener('click', () => action(openAssemble, 'Preparing the assembly guide…'));
$('print-option').addEventListener('click', () => action(async () => {
  await openAssemble(); $('asm-prints').scrollIntoView({behavior: 'smooth', block: 'start'});
}, 'Preparing printable parts…'));
$('inspect-internals').addEventListener('change', () => {
  if (state.view === 'robot') state.viewer?.inspectInternals($('inspect-internals').checked, state.assembly);
});
// Viewport-only transforms never edit engineering data or trigger model APIs.
function resetViewerControls(kind) {
  const tools = document.querySelector(`[data-viewer="${kind}"]`);
  tools.querySelectorAll('[data-angle]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.angle === 'default')));
  tools.querySelector('[data-spin]')?.setAttribute('aria-pressed', 'false');
  if (kind === 'robot') { $('explode').value = '0'; $('explode-value').textContent = '0%'; }
}
document.querySelectorAll('[data-viewer]').forEach(tools => {
  tools.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button) return;
    const kind = tools.dataset.viewer, viewer = kind === 'robot' ? state.viewer : state.asmViewer;
    if (!viewer) return;
    if (button.dataset.angle) {
      viewer.setAngle(button.dataset.angle);
      tools.querySelectorAll('[data-angle]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    }
    if (button.hasAttribute('data-spin')) {
      const enabled = viewer.setSpin(button.getAttribute('aria-pressed') !== 'true');
      button.setAttribute('aria-pressed', String(enabled));
    }
    if (button.hasAttribute('data-reset')) { viewer.resetView(); resetViewerControls(kind); }
  });
});
$('explode').addEventListener('input', () => {
  if (state.view !== 'robot') return;
  state.viewer?.setExploded(Number($('explode').value) / 100);
  $('explode-value').textContent = `${$('explode').value}%`;
});
document.querySelectorAll('[data-fullscreen]').forEach(button => {
  button.addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await $(button.dataset.fullscreen).requestFullscreen();
    } catch { announce('Fullscreen is unavailable in this browser. The 3D controls still work.', true); }
  });
});
document.addEventListener('fullscreenchange', () => {
  document.querySelectorAll('[data-fullscreen]').forEach(button => {
    const expanded = document.fullscreenElement?.id === button.dataset.fullscreen;
    button.setAttribute('aria-label', expanded ? 'Exit expanded viewport' : 'Expand viewport');
    button.setAttribute('aria-pressed', String(expanded));
  });
});
$('save-guide').addEventListener('click', () => {
  const guide = state.guide?.data; if (!guide) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(guide, null, 2)], {type: 'application/json'}));
  const a = node('a'); a.href = url; a.download = `assembly_rev${guide.revision}.json`; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('back-to-design').addEventListener('click', () => show('workspace'));
$('asm-prev').addEventListener('click', () => goStep(state.guide.index - 1));
$('asm-next').addEventListener('click', () => goStep(state.guide.index + 1));
$('find-buy').addEventListener('click', () => action(async () => {
  const r = await findWhereToBuy();
  announce(r.main_store ? `Found stores. Most parts are at ${r.main_store}.` : 'No store links found for these parts.');
}, 'Searching stores for each part…'));
$('insp-close').addEventListener('click', () => select(null));
$('budget-slider').addEventListener('input', () => queueBudget(Number($('budget-slider').value)));
$('next-upgrade-btn').addEventListener('click', () => {
  const next = state.project?.architecture?.next_upgrade; if (!next) return;
  const value = Math.ceil(next.at_budget_usd / 50) * 50;
  $('budget-slider').max = String(Math.max(Number($('budget-slider').max), value));
  $('budget-slider').value = String(value); queueBudget(value);
});
$('seed-telemetry').addEventListener('click', () => action(async () => { await seedTelemetry(); announce('Two labelled samples written to Tiger. Minute rollup verified.'); }, 'Writing test samples…'));
$('retry-tiger').addEventListener('click', () => checkTiger());
$('setup-tiger').addEventListener('click', async () => {
  $('setup-tiger').disabled = true;
  try { await api('/integrations/tiger/setup'); await checkTiger(); }
  catch (error) { announce(error.message, true); }
  finally { $('setup-tiger').disabled = false; }
});
$('demo').addEventListener('click', () => action(runDemo));
$('guided').addEventListener('change', () => action(async () => {
  const guided = $('guided').checked;
  const signal = {consent: true, state: guided ? 'needs_guidance' : 'focused', confidence: guided ? 1 : 0};
  try {
    const result = await api(projectPath('/adaptive-interface'), signal); state.interaction = guided ? signal : null;
    $('pacing-result').textContent = `${result.recommendation.mode} · speech at ${result.recommendation.voice_speed}× · manual preview only`;
    announce('Pacing preview updated. This is not a camera measurement.');
  } catch (error) { $('guided').checked = !guided; throw error; }
}));
// ---------- start-page showcase: one real CAD robot per body plan ----------
async function initShowcase() {
  const items = await api('/showcase');
  if (!items.length) return;
  const pad = n => String(n).padStart(2, '0');
  const dots = items.map((item, i) => {
    const li = node('li'); const b = node('button'); b.type = 'button'; b.dataset.static = '1';
    b.setAttribute('aria-label', `Show the ${item.label}`);
    const bar = node('i'); bar.append(node('b'));
    b.append(node('span', item.label), bar); li.append(b); return li;
  });
  $('sc-dots').replaceChildren(...dots);
  if (!webglAvailable()) {
    $('showcase-stage').classList.add('failed');
    $('showcase-stage').replaceChildren(node('p', 'Turn on WebGL to see the robots in 3D. You can still design a robot below.', 'sc-loading'));
    return;
  }
  let current = null;
  const reel = new Showcase($('showcase-stage'), items, {
    onChange: (index, item) => {
      current = item;
      const box = $('showcase'); box.classList.remove('swap'); void box.offsetWidth; box.classList.add('swap');
      $('sc-kind').textContent = `Body plan ${pad(index + 1)}`;
      $('sc-title').textContent = item.label;
      $('sc-blurb').textContent = item.blurb;
      const moves = item.wheels === 'Tracks' ? 'Tracks' : item.wheels ? `${item.wheels} wheels` : 'Fixed';
      $('sc-specs').replaceChildren(...[['Parts', item.parts], ['Cost', money(item.cost_usd)], ['Height', `${Math.round(item.height_m * 100)} cm`],
        ['Moves', moves]].map(([k, v]) => { const d = node('div'); d.append(node('dt', k), node('dd', String(v))); return d; }));
      $('sc-count').replaceChildren(node('b', pad(index + 1)), ` / ${pad(items.length)}`);
      $('sc-use').hidden = false;
      dots.forEach((li, i) => {
        li.className = i === index ? 'active' : '';
        li.querySelector('button').setAttribute('aria-pressed', String(i === index));
      });
    },
    onProgress: (index, p) => { dots[index].querySelector('i b').style.transform = `scaleX(${p})`; },
  });
  dots.forEach((li, i) => li.querySelector('button').addEventListener('click', () => reel.jump(i)));
  $('sc-spin').addEventListener('click', () => {
    const enabled = reel.setSpin($('sc-spin').getAttribute('aria-pressed') !== 'true');
    $('sc-spin').setAttribute('aria-pressed', String(enabled));
  });
  $('sc-reset').addEventListener('click', () => {
    reel.resetView(); reel.setSpin(false); $('sc-spin').setAttribute('aria-pressed', 'false');
  });
  $('sc-use').addEventListener('click', () => {
    if (!current) return;
    $('brief').value = current.brief; $('budget').value = current.budget_usd; $('brief').focus();
  });
  reel.go(Math.max(0, items.findIndex(item => item.label === 'Mobile manipulator')));
}

applyPreset();
initShowcase().catch(() => {
  $('showcase-stage').classList.add('failed');
  $('showcase-stage').replaceChildren(node('p', 'Robot collection unavailable. You can still describe and build a robot.', 'sc-loading'));
});
lock(true);
integrations().catch(() => { $('tiger-status').textContent = 'Tiger · unreachable'; });
projectList().then(() => announce('Ready. Describe your robot to begin.'))
  .catch(error => announce(error.message || 'Backend unavailable.', true)).finally(() => lock(false));
