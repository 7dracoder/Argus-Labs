import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {PacingSignal, normalizeBreathingSample} from './signal.mjs';

try { process.loadEnvFile(fileURLToPath(new URL('../../.env', import.meta.url))); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const args = process.argv.slice(2);
const check = args.includes('--check');
const consent = args.includes('--consent');
const projectId = args.find(arg => !arg.startsWith('--'));
const diagnostics = args.includes('--diagnostics');
const durationArg = args.find(arg => arg.startsWith('--duration-seconds='));
const duration = durationArg ? Number(durationArg.split('=')[1]) : null;
if (duration !== null && (!Number.isInteger(duration) || duration < 10 || duration > 600)) {
  console.error('Session duration must be an integer between 10 and 600 seconds.');
  process.exit(1);
}
const apiKey = process.env.SMARTSPECTRA_API_KEY;
const base = new URL(process.env.ROBOFORGE_API_URL || 'http://127.0.0.1:8000');
if (!['127.0.0.1', 'localhost', '[::1]'].includes(base.hostname)) {
  throw new Error('This prototype sends coarse signals only to a local Argus Labs backend.');
}

const require = createRequire(import.meta.url);
let runtime;
try { runtime = require('@smartspectra/node-sdk'); }
catch { console.error('Presage runtime could not load. Run npm install in clients/presage.'); process.exit(1); }
const {SmartSpectraSDK, CameraSelection, SmartSpectraLogLevel, MetricType} = runtime;

if (check) {
  console.log(JSON.stringify({sdkVersion: SmartSpectraSDK.version, keyConfigured: Boolean(apiKey),
                             platform: process.platform, architecture: process.arch, cameraStarted: false}));
  process.exit(0);
}
if (!apiKey || !consent || !projectId || !/^[a-zA-Z0-9_-]{1,120}$/.test(projectId)) {
  console.error('Set SMARTSPECTRA_API_KEY in .env, then run: npm start -- <project-id> --consent');
  console.error('Opt-in starts camera measurement. Press Ctrl+C to stop. Review Presage vendor privacy terms first.');
  process.exit(1);
}
// SDK measures breathing locally; vendor authentication/processing follows its policies.
// Request no face-expression classification, LLM insights, video output, or SDK telemetry.
const sdk = new SmartSpectraSDK({apiKey, requestedMetrics: [MetricType.BREATHING_RATE],
                               enableTelemetry: false, enableAccumulatedOutput: false,
                               logLevel: SmartSpectraLogLevel.kNone});
const pacing = new PacingSignal();
let ready = false, lastPacketAt = null, lastSampleTimestamp = null, latest = null, busy = false;
const diagnostic = {cameraStarted: false, runningSeen: false, validationReadySeen: false,
                    metricsSeen: false, usableSamples: 0, calibrated: false,
                    backendUpdates: 0, backendFailures: 0, decodeFailures: 0,
                    validationCodes: new Set(), errorCodes: new Set()};
let deadline;
const endpoint = new URL(`/projects/${projectId}/adaptive-interface`, base);

async function send(signal) {
  const result = await fetch(endpoint, {method: 'POST',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify(signal),
    signal: AbortSignal.timeout(5000)});
  if (!result.ok) throw new Error(`Backend returned HTTP ${result.status}`);
  const response = await result.json();
  diagnostic.backendUpdates++;
  // Only UI recommendations are printed; never camera buffers, keys, or vital signs.
  if (!diagnostics) console.log(JSON.stringify({recommendation: response.recommendation}));
}

sdk.on('processingStatus', (code) => {
  if (code === runtime.ProcessingStatus.kRunning) diagnostic.runningSeen = true;
});
sdk.on('validationStatus', (code) => {
  diagnostic.validationCodes.add(code);
  if (code === 0) diagnostic.validationReadySeen = true;
  ready = code === 0;
  if (!ready) {
    pacing.reset(); latest = null; lastPacketAt = null; lastSampleTimestamp = null;
  }
});
sdk.on('metrics', (buffer) => {
  diagnostic.metricsSeen = true;
  try {
    const metrics = runtime.decodeMetrics(buffer);
    if (Buffer.isBuffer(metrics)) throw new Error('Metrics class not registered');
    const rate = metrics.breathing?.rate?.at(-1);
    const stamp = rate?.timestamp?.toString();
    if (rate && stamp && stamp !== lastSampleTimestamp) {
      lastSampleTimestamp = stamp;
      lastPacketAt = performance.now();
      latest = normalizeBreathingSample(rate);
    }
  } catch { ready = false; diagnostic.decodeFailures++; }
});
sdk.on('error', (code) => {
  diagnostic.errorCodes.add(code);
  ready = false; pacing.reset(); latest = null; lastPacketAt = null;
  console.error(`Presage SDK error ${code}; no adaptation applied.`);
});
// Register the published protobuf type if the SDK does not do so automatically.
const messages = require('@smartspectra/node-sdk/messages');
if (messages.Metrics) runtime.setMetricsClass(messages.Metrics);

const timer = setInterval(async () => {
  if (busy) return;
  busy = true;
  try {
    const now = performance.now();
    const usable = ready && lastPacketAt !== null && now - lastPacketAt < 5000;
    const signal = pacing.update(usable ? latest : null, now, usable);
    if (usable && Number.isFinite(latest?.value) && latest.value > 0 &&
        latest.confidence >= 0.8 && latest.confidence <= 1) diagnostic.usableSamples++;
    if (signal.confidence >= 0.8) diagnostic.calibrated = true;
    await send(signal);
  } catch { diagnostic.backendFailures++; console.error('Could not update local interface; verify backend and project ID.'); }
  finally { busy = false; }
}, 2000);

let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  clearInterval(timer);
  clearTimeout(deadline);
  let cleanupSucceeded = false;
  try {
    await sdk.stopAsync();
    await sdk.destroy();
    cleanupSucceeded = true;
    pacing.reset(); latest = null;
    await send({consent: true, state: 'focused', confidence: 0});
  } catch { console.error('Camera bridge stopped; interface returns to standard on next request.'); }
  if (diagnostics) {
    const passed = diagnostic.runningSeen && diagnostic.calibrated && diagnostic.backendUpdates > 1 &&
      diagnostic.errorCodes.size === 0 && diagnostic.decodeFailures === 0 &&
      diagnostic.backendFailures === 0 && cleanupSucceeded;
    console.log(JSON.stringify({presageE2E: {...diagnostic,
      validationCodes: [...diagnostic.validationCodes], errorCodes: [...diagnostic.errorCodes],
      cleanupSucceeded, status: passed ? 'passed' : 'failed'}}));
    process.exit(passed ? 0 : 1);
  }
  process.exit(0);
}
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
try {
  // Check the project exists before taking camera input.
  await send({consent: true, state: 'focused', confidence: 0});
  if (duration !== null) deadline = setTimeout(stop, duration * 1000);
  sdk.useCamera(CameraSelection.default, {width: 1280, height: 720, fps: 30});
  sdk.start();
  diagnostic.cameraStarted = true;
  console.log('Consented camera session started. Calibrating pacing for 60 seconds; Ctrl+C stops it.');
} catch (error) {
  clearInterval(timer);
  clearTimeout(deadline);
  await sdk.destroy();
  if (diagnostics) console.log(JSON.stringify({presageE2E: {status: 'failed',
    cameraStarted: diagnostic.cameraStarted, errorCode: Number.isInteger(error.code) ? error.code : null}}));
  console.error('Presage could not start. Check key, credits, camera availability, and backend project.');
  process.exit(1);
}
