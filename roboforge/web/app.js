const $ = id => document.getElementById(id);
const state = {project: null, history: [], audioURL: null, lastAudio: null, proposal: null,
  interaction: null, busy: false, micPending: false, recorder: null, stream: null, recordingTimer: null, discard: false,
  suggestedSpec: null};
const KIND_NAMES = {chassis_plate: 'Chassis plate', arm_link: 'Arm link', motor_bracket: 'Motor bracket',
  wheel_hub: 'Drive wheel hub', gripper_jaw: 'Gripper jaw', sensor_mount: 'Sensor mount'};
const money = value => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'}).format(value);

async function api(path, body, raw = false, signal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 190000);
  try {
    const response = await fetch(path, {method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : {'Content-Type': raw ? (body.type || 'audio/webm') : 'application/json'},
      body: body === undefined ? undefined : raw ? body : JSON.stringify(body),
      signal: signal || controller.signal, cache: 'no-store'});
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status}). Check inputs and backend configuration.`);
    }
    return response.json();
  } finally { clearTimeout(timer); }
}
function announce(message, error = false) { $('status').textContent = message; $('status').classList.toggle('error', error); }
function lock(value) {
  state.busy = value;
  const recording = state.recorder?.state === 'recording' || state.micPending;
  document.querySelectorAll('button').forEach(button => {
    button.disabled = value || (recording && button.id !== 'record') || (state.micPending && button.id === 'record') || (button.classList.contains('requires-project') && !state.project);
  });
  $('project-select').disabled = value || recording;
  $('guided').disabled = value || recording || !state.project;
}
async function action(task) {
  if (state.busy) return;
  if (state.micPending || state.recorder?.state === 'recording') { announce('Stop or discard the recording before another action.'); return; }
  lock(true);
  try { await task(); } catch (error) { announce(error.message || 'Operation failed.', true); }
  finally { lock(false); }
}
function projectPath(suffix = '') { if (!state.project) throw new Error('Create a project first.'); return `/projects/${encodeURIComponent(state.project.id)}${suffix}`; }
function node(tag, text, className) { const el = document.createElement(tag); if (text !== undefined) el.textContent = text; if (className) el.className = className; return el; }
function resetConversation() {
  state.history = []; state.proposal = null; state.interaction = null; state.lastAudio = null;
  if (state.audioURL) URL.revokeObjectURL(state.audioURL);
  state.audioURL = null; $('speech').pause(); $('speech').removeAttribute('src'); $('speech').hidden = true;
  $('proposal').hidden = true; $('conversation').replaceChildren(node('p', 'Ask Forge about this project.', 'empty-chat'));
  $('transcript').textContent = ''; $('guided').checked = false;
  $('pacing-result').textContent = 'Standard explanations · speech at 1×';
}
async function projectList() {
  const projects = await api('/projects');
  $('project-select').replaceChildren(new Option('Choose a project', ''));
  for (const project of projects) $('project-select').add(new Option(`${project.name} · r${project.revision} · ${project.id.slice(0, 6)}`, project.id));
  $('project-select').value = state.project?.id || '';
}
async function refresh() {
  const [project, bom, budget, telemetry] = await Promise.all([
    api(projectPath()), api(projectPath('/finance/bom')), api(projectPath('/finance/budget')),
    api(projectPath('/telemetry/summary')).catch(() => null)]);
  state.project = project;
  $('project-title').textContent = project.name; $('revision').textContent = `REVISION ${project.revision}`;
  $('bom-total').textContent = money(bom.total_usd); $('projected').textContent = money(budget.projected_total_usd);
  $('budget-result').textContent = budget.remaining_usd === null ? 'No budget set.' : budget.remaining_usd >= 0
    ? `${money(budget.remaining_usd)} remaining, including ${budget.contingency_pct}% contingency.`
    : `${money(-budget.remaining_usd)} over budget, including ${budget.contingency_pct}% contingency.`;
  $('bom-lines').replaceChildren(...bom.lines.map(line => {
    const el = node('div', undefined, 'bom-line');
    el.append(node('span', `${line.quantity} × ${line.name}`), node('span', money(line.line_total_usd))); return el;
  }));
  renderTelemetry(telemetry);
  const parts = Object.values(project.manufacturing.cad_parts || {});
  if (parts.length) renderPart(parts.at(-1));
  else { $('preview').replaceChildren(node('p', 'Your part will appear here.', 'muted')); $('downloads').replaceChildren(); $('part-details').textContent = ''; $('geometry-state').textContent = 'AWAITING PART'; }
  await projectList();
}
function renderTelemetry(result) {
  $('telemetry-result').textContent = !result ? 'Telemetry unavailable; check Tiger connection.' : !result.metrics.length
    ? `No measurements · ${result.storage} storage.` : result.metrics.map(metric =>
      `${metric.metric}: average ${metric.average} ${metric.unit} · ${metric.samples} samples · ${result.storage} storage`).join(' | ');
}
function sketch(spec) {
  const ns = 'http://www.w3.org/2000/svg'; const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 360 185'); svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', `${spec.kind.replaceAll('_', ' ')} dimension schematic`);
  const add = (tag, attrs, text) => { const el = document.createElementNS(ns, tag); for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, String(value)); if (text) el.textContent = text; svg.append(el); };
  add('rect', {x: 0, y: 0, width: 360, height: 185, fill: '#edf1e7'});
  if (spec.kind === 'wheel_hub') {
    add('ellipse', {cx: 180, cy: 96, rx: 78, ry: 48, fill: '#9aa7b5', stroke: '#3d4a57', 'stroke-width': 1.6});
    add('ellipse', {cx: 180, cy: 96, rx: 28, ry: 17, fill: '#c5ced7', stroke: '#3d4a57'});
    add('ellipse', {cx: 180, cy: 96, rx: 12, ry: 7, fill: '#edf1e7', stroke: '#3d4a57'});
    for (const [cx, cy] of [[132, 70], [228, 70], [132, 122], [228, 122]])
      add('ellipse', {cx, cy, rx: 6, ry: 4, fill: '#edf1e7', stroke: '#3d4a57'});
  } else if (spec.kind === 'gripper_jaw') {
    add('path', {d: 'M 70 70 L 250 70 L 290 88 L 250 118 L 70 118 Z', fill: '#c6d8b6', stroke: '#487450', 'stroke-width': 1.5});
    add('path', {d: 'M 70 118 L 70 128 L 250 128 L 290 98 L 290 88 L 250 118 Z', fill: '#a0b889', stroke: '#487450'});
    for (const x of [210, 228, 246]) add('rect', {x, y: 62, width: 10, height: 8, fill: '#6f8f6a', stroke: '#487450'});
    for (const [cx, cy] of [[92, 84], [92, 104]]) add('ellipse', {cx, cy, rx: 5, ry: 3, fill: '#edf1e7', stroke: '#487450'});
  } else if (spec.kind === 'sensor_mount') {
    add('path', {d: 'M 90 130 L 280 130 L 310 108 L 120 108 Z', fill: '#c6d8b6', stroke: '#487450', 'stroke-width': 1.5});
    add('path', {d: 'M 90 50 L 120 50 L 120 108 L 90 130 Z', fill: '#d1dfc5', stroke: '#487450'});
    add('rect', {x: 98, y: 68, width: 14, height: 28, fill: '#edf1e7', stroke: '#487450'});
    for (const [cx, cy] of [[160, 118], [250, 118]]) add('ellipse', {cx, cy, rx: 5, ry: 3, fill: '#edf1e7', stroke: '#487450'});
  } else if (spec.kind === 'arm_link') {
    add('path', {d: 'M 70 96 A 28 28 0 0 1 98 68 L 262 68 A 28 28 0 0 1 290 96 A 28 28 0 0 1 262 124 L 98 124 A 28 28 0 0 1 70 96 Z', fill: '#c6d8b6', stroke: '#487450', 'stroke-width': 1.5});
    add('rect', {x: 140, y: 82, width: 80, height: 28, fill: '#edf1e7', stroke: '#487450'});
    for (const [cx, cy] of [[98, 96], [262, 96]]) add('ellipse', {cx, cy, rx: 8, ry: 8, fill: '#edf1e7', stroke: '#487450'});
  } else if (spec.kind === 'motor_bracket') {
    add('path', {d: 'M 80 138 L 270 138 L 300 112 L 110 112 Z', fill: '#c6d8b6', stroke: '#487450', 'stroke-width': 1.5});
    add('path', {d: 'M 80 60 L 110 60 L 110 112 L 80 138 Z', fill: '#d1dfc5', stroke: '#487450'});
    add('path', {d: 'M 110 112 L 190 112 L 110 70 Z', fill: '#b7c9a8', stroke: '#487450'});
    for (const [cx, cy] of [[130, 124], [240, 124], [150, 116], [260, 116]]) add('ellipse', {cx, cy, rx: 5, ry: 3, fill: '#edf1e7', stroke: '#487450'});
  } else {
    add('path', {d: 'M 50 142 L 260 142 L 310 99 L 100 99 Z', fill: '#c6d8b6', stroke: '#487450', 'stroke-width': 1.5});
    add('path', {d: 'M 50 142 L 50 151 L 260 151 L 310 108 L 310 99 L 260 142 Z', fill: '#a0b889', stroke: '#487450'});
    add('rect', {x: 140, y: 112, width: 70, height: 22, fill: '#edf1e7', stroke: '#487450'});
    for (const [cx, cy] of [[78, 135], [244, 135], [117, 107], [283, 107]]) add('ellipse', {cx, cy, rx: 6, ry: 3, fill: '#edf1e7', stroke: '#487450'});
  }
  const height = spec.bracket_height_mm && ['motor_bracket', 'sensor_mount'].includes(spec.kind) ? ` × ${spec.bracket_height_mm}H` : '';
  add('text', {x: 18, y: 172, fill: '#487450', 'font-size': 11, 'font-family': 'monospace'}, `${spec.kind.replaceAll('_', ' ')} · ${spec.length_mm} × ${spec.width_mm} × ${spec.thickness_mm}${height} mm`);
  add('text', {x: 18, y: 24, fill: '#728175', 'font-size': 9, 'font-family': 'monospace'}, 'SCHEMATIC / NOT TO SCALE');
  return svg;
}
function applySuggestedSpec(spec) {
  state.suggestedSpec = spec;
  $('part-kind').value = spec.kind;
  $('length').value = spec.length_mm;
  $('width').value = spec.width_mm;
  $('thickness').value = spec.thickness_mm;
  $('preview').replaceChildren(sketch(spec));
  $('geometry-state').textContent = 'SUGGESTED';
  $('part-details').textContent = `Suggested ${spec.name} (${spec.kind.replaceAll('_', ' ')}) for this robot brief. Generate to build real STEP/STL/GLB.`;
}
function renderPart(part) {
  $('preview').replaceChildren(sketch(part.spec));
  $('geometry-state').textContent = 'GEOMETRY CHECKED';
  $('part-details').textContent = `${part.spec.kind.replaceAll('_', ' ')} · ${part.geometry.mass_kg.toFixed(4)} kg estimated solid mass · ${part.spec.material.toUpperCase()}`;
  $('downloads').replaceChildren();
  for (const format of ['step', 'stl', 'glb', 'report']) {
    const link = node('a', `↓ ${format.toUpperCase()}`);
    link.href = projectPath(`/cad/${encodeURIComponent(part.design_id)}/${format}?revision=${state.project.revision}`);
    link.setAttribute('download', ''); $('downloads').append(link);
  }
}
async function suggestForProject() {
  const result = await api(projectPath('/cad/suggest'));
  applySuggestedSpec(result.spec);
  return result;
}
async function createDemo() { state.project = await api('/projects/demo', {}); resetConversation(); await refresh(); await suggestForProject(); }
async function generatePart(spec, prompt) {
  announce('Building reviewed geometry and checking the exported STEP…');
  const payload = {estimated_unit_cost_usd: Number($('part-price').value)};
  if (prompt) payload.prompt = prompt;
  else {
    const suggested = state.suggestedSpec && state.suggestedSpec.kind === spec.kind ? state.suggestedSpec : null;
    payload.spec = {
      name: spec.name || suggested?.name || KIND_NAMES[spec.kind] || 'Robot part',
      kind: spec.kind,
      length_mm: Number(spec.length_mm),
      width_mm: Number(spec.width_mm),
      thickness_mm: Number(spec.thickness_mm),
      ...(suggested ? {
        hole_diameter_mm: suggested.hole_diameter_mm,
        hole_inset_mm: suggested.hole_inset_mm,
        bracket_height_mm: suggested.bracket_height_mm,
        material: suggested.material,
      } : {}),
    };
    if (['motor_bracket', 'sensor_mount'].includes(spec.kind))
      payload.spec.hole_inset_mm = Math.max(14, Number(payload.spec.hole_inset_mm) || 14);
    if (spec.kind === 'wheel_hub') {
      payload.spec.hole_diameter_mm = Number(payload.spec.hole_diameter_mm) || Math.max(8, Math.round(Number(spec.length_mm) * 0.15));
      if (!(payload.spec.width_mm < payload.spec.length_mm - 2 * payload.spec.hole_diameter_mm))
        payload.spec.width_mm = Math.round(payload.spec.length_mm * 0.6);
    }
  }
  const result = await api(projectPath('/agents/mechanical'), payload);
  await refresh(); renderPart(result); return result;
}
async function seedTelemetry() {
  const observed_at = new Date().toISOString();
  for (const value of [40, 60]) await api(projectPath('/telemetry'), {observed_at, scenario_id: 'frontend-demo', metric: 'battery_pct', value, unit: 'percent'});
  const summary = await api(projectPath('/telemetry/summary') + '?scenario_id=frontend-demo');
  const points = await api(projectPath('/telemetry/timeseries') + '?scenario_id=frontend-demo');
  if (summary.storage !== 'tiger' || points.storage !== 'tiger') throw new Error('Development samples used memory storage, not Tiger. Configure TIGER_DATABASE_URL.');
  if (!points.points.length) throw new Error('Tiger minute rollup is unavailable. Check database setup.');
  renderTelemetry(summary); return summary;
}
function bubble(role, text) {
  const empty = $('conversation').querySelector('.empty-chat'); if (empty) empty.remove();
  const el = node('div', undefined, `bubble ${role}`); el.append(node('small', role === 'user' ? 'YOU' : 'FORGE'), node('span', text));
  $('conversation').append(el); $('conversation').scrollTop = $('conversation').scrollHeight;
}
async function askForge(message, speak = $('speak').checked) {
  bubble('user', message); announce('Forge is reasoning over your current project…');
  const result = await api(projectPath('/voice/agent'), {message, speak, history: state.history, ...(state.interaction ? {interaction: state.interaction} : {})});
  bubble('assistant', result.reply);
  state.history.push({role: 'user', content: message.slice(0, 2000)}, {role: 'assistant', content: result.reply}); state.history = state.history.slice(-12);
  state.lastAudio = null; $('speech').pause(); $('speech').hidden = true; $('transcript').textContent = '';
  if (state.audioURL) URL.revokeObjectURL(state.audioURL);
  state.audioURL = null;
  if (result.audio) {
    const bytes = Uint8Array.from(atob(result.audio.base64), c => c.charCodeAt(0));
    state.lastAudio = new Blob([bytes], {type: 'audio/mpeg'}); state.audioURL = URL.createObjectURL(state.lastAudio);
    $('speech').src = state.audioURL; $('speech').hidden = false;
  }
  state.proposal = result.cad_proposal; $('proposal').hidden = !state.proposal;
  if (state.proposal) $('proposal-detail').textContent = JSON.stringify(state.proposal, null, 2);
  if (result.speech_error) announce(`Forge replied, but speech failed: ${result.speech_error}`, true);
  else announce(`Forge replied using project revision ${result.project_revision}. No design edits were made.`);
  return result;
}
function step(index, status) {
  const el = document.querySelector(`[data-step="${index}"]`); el.className = status;
  el.querySelector('small').textContent = {running: 'In progress…', passed: 'Passed', failed: 'Failed', '': 'Not run'}[status];
}
async function runDemo() {
  let current = 0; for (let index = 0; index < 5; index++) step(index, '');
  try {
    step(0, 'running'); announce('01 / Creating a fresh demo robot project…'); await createDemo(); step(0, 'passed');
    current = 1; step(1, 'running'); $('part-price').value = '8';
    const suggestion = await suggestForProject();
    const part = await generatePart(suggestion.spec);
    if (!Object.values(part.geometry.checks).every(Boolean)) throw new Error('CAD geometry checks did not pass.'); step(1, 'passed');
    current = 2; step(2, 'running'); announce('03 / Writing labelled test telemetry to Tiger and checking its minute rollup…'); await seedTelemetry(); step(2, 'passed');
    current = 3; step(3, 'running');
    const reply = await askForge('Summarize this robot’s current parts estimate, budget including contingency, and the battery_pct development test samples in two short sentences. Speak all currency amounts in words with dollars and cents so speech reads them clearly. Do not propose CAD or claim a real simulation ran.', true);
    if (!reply.audio) throw new Error(reply.speech_error || 'Forge returned no speech.'); step(3, 'passed');
    current = 4; step(4, 'running'); announce('05 / Transcribing the generated Forge speech with ElevenLabs (no microphone)…');
    const transcript = await api('/voice/transcribe?consent=true', state.lastAudio, true);
    if (!transcript.text) throw new Error('The generated speech returned no transcript.');
    $('transcript').textContent = `ElevenLabs transcript (check numbers against the BOM): ${transcript.text}`; step(4, 'passed');
    announce('E2E demo passed: project → CAD + budget → Tiger → Baseten + speech → transcription. Camera and microphone stayed off.');
  } catch (error) { step(current, 'failed'); throw error; }
}
async function integrations() {
  const [status, health] = await Promise.all([api('/integrations/status'), api('/integrations/tiger/health')]);
  $('llm-status').textContent = `${status.llm.provider} · ${status.llm.configured ? status.llm.model : 'key missing'} (configuration only)`;
  $('voice-status').textContent = `ElevenLabs · ${status.elevenlabs.configured ? 'configured' : 'not configured'}`;
  $('tiger-status').textContent = `Tiger · ${health.connected && health.schema_ready ? 'connected' : 'not ready'}`;
  $('presage-status').textContent = `Presage · ${status.presage.key_configured ? 'key configured' : 'key missing'} · camera off`;
}
$('demo').addEventListener('click', () => action(runDemo));
$('project-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
  state.project = await api('/projects', {name: $('project-name').value.trim(), requirements: {description: $('description').value, budget_usd: Number($('budget-input').value)}});
  resetConversation(); await refresh(); await suggestForProject();
  announce('Project created. A signature part was suggested for this brief — generate it or change the template.');
}); });
$('project-select').addEventListener('change', () => { const id = $('project-select').value; if (!id) return; action(async () => {
  state.project = await api(`/projects/${encodeURIComponent(id)}`); resetConversation(); await refresh();
  if (!Object.keys(state.project.manufacturing.cad_parts || {}).length) await suggestForProject();
  announce(`Resumed ${state.project.name}.`);
}); });
$('suggest-part').addEventListener('click', () => action(async () => {
  const result = await suggestForProject();
  announce(`Suggested ${result.spec.kind.replaceAll('_', ' ')} for this robot. ${result.reason}`);
}));
$('cad-form').addEventListener('submit', event => { event.preventDefault(); action(async () => {
  const kind = $('part-kind').value;
  const defaults = {kind, length_mm: Number($('length').value), width_mm: Number($('width').value), thickness_mm: Number($('thickness').value)};
  if (kind === 'motor_bracket' || kind === 'sensor_mount') defaults.hole_inset_mm = 14;
  if (kind === 'wheel_hub') { defaults.hole_diameter_mm = Math.max(8, Math.round(defaults.length_mm * 0.15)); defaults.width_mm = Math.min(defaults.width_mm, Math.round(defaults.length_mm * 0.6)); }
  await generatePart(defaults, $('cad-prompt').value.trim());
  announce('Actual CAD exports are ready. The fabrication estimate is now included in the BOM.');
}); });
$('seed-telemetry').addEventListener('click', () => action(async () => { await seedTelemetry(); announce('Two labelled development samples written to Tiger. Minute rollup verified.'); }));
$('voice-form').addEventListener('submit', event => { event.preventDefault(); const message = $('message').value.trim(); if (message) action(async () => { await askForge(message); $('message').value = ''; }); });
$('guided').addEventListener('change', () => action(async () => {
  const guided = $('guided').checked;
  const signal = {consent: true, state: guided ? 'needs_guidance' : 'focused', confidence: guided ? 1 : 0};
  try {
    const result = await api(projectPath('/adaptive-interface'), signal); state.interaction = guided ? signal : null;
    $('pacing-result').textContent = `${result.recommendation.mode} · speech at ${result.recommendation.voice_speed}× · manual preview only`;
    announce('Manual pacing preview updated. This is not a Presage camera measurement.');
  } catch (error) { $('guided').checked = !guided; throw error; }
}));
$('confirm-proposal').addEventListener('click', () => action(async () => { if (state.proposal) await generatePart(state.proposal.spec); $('proposal').hidden = true; state.proposal = null; announce('Confirmed proposal generated as a new project revision.'); }));
function releaseMicrophone() { clearTimeout(state.recordingTimer); state.stream?.getTracks().forEach(track => track.stop()); state.stream = null; $('record').textContent = 'Record up to 15 seconds'; lock(state.busy); }
$('mic-consent').addEventListener('change', () => { if (!$('mic-consent').checked && state.recorder?.state === 'recording') { state.discard = true; state.recorder.stop(); releaseMicrophone(); } });
$('record').addEventListener('click', async () => {
  if (state.micPending) return;
  if (state.recorder?.state === 'recording') { state.recorder.stop(); releaseMicrophone(); return; }
  if (!$('mic-consent').checked) { announce('Check microphone consent first. Nothing was recorded.', true); return; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { announce('Recording is unavailable in this browser. Use typed questions.', true); return; }
  const recordingProject = state.project?.id;
  state.micPending = true; lock(false); $('record').textContent = 'Waiting for microphone permission…';
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({audio: true, video: false});
    state.micPending = false;
    if (!$('mic-consent').checked || state.busy || state.project?.id !== recordingProject) { releaseMicrophone(); return; }
    const mimeType = ['audio/webm', 'audio/ogg', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
    if (!mimeType) throw new Error('No supported recording format. Use typed questions.');
    const chunks = []; let size = 0; state.discard = false;
    state.recorder = new MediaRecorder(state.stream, {mimeType});
    state.recorder.ondataavailable = event => { size += event.data.size; if (size <= 10 * 1024 * 1024) chunks.push(event.data); else { state.discard = true; if (state.recorder.state === 'recording') state.recorder.stop(); releaseMicrophone(); } };
    state.recorder.onerror = () => { state.discard = true; releaseMicrophone(); announce('Recording failed. No audio was sent.', true); };
    state.recorder.onstop = () => {
      releaseMicrophone();
      if (state.discard || !$('mic-consent').checked || !chunks.length || state.project?.id !== recordingProject) { announce('Recording discarded. No audio sent.'); return; }
      action(async () => { announce('Transcribing your consented recording with ElevenLabs…');
        const result = await api('/voice/transcribe?consent=true', new Blob(chunks, {type: mimeType}), true);
        await askForge(result.text); $('transcript').textContent = `Your transcript: ${result.text}`;
      });
    };
    state.recorder.start(1000); lock(false); $('record').textContent = 'Stop & send recording';
    announce('Microphone recording started. Stops automatically after 15 seconds.');
    state.recordingTimer = setTimeout(() => { if (state.recorder?.state === 'recording') state.recorder.stop(); releaseMicrophone(); }, 15000);
  } catch (error) { releaseMicrophone(); announce(error.message || 'Microphone permission was not granted.', true); }
  finally { state.micPending = false; lock(state.busy); }
});
window.addEventListener('pagehide', () => { state.discard = true; if (state.recorder?.state === 'recording') state.recorder.stop(); releaseMicrophone(); if (state.audioURL) URL.revokeObjectURL(state.audioURL); });
lock(true);
Promise.all([integrations(), projectList()]).then(() => announce('Ready. Run the guided demo, or create your own project.'))
  .catch(error => announce(error.message || 'Backend unavailable.', true)).finally(() => lock(false));
