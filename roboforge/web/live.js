// Real-time, hands-free voice conversation with Forge (ElevenLabs Agents over WebSocket).
// The backend creates the agent and signs a short-lived URL; no API key reaches the browser.
import {Conversation} from './vendor/elevenlabs-client.js';

const $ = id => document.getElementById(id);
const WORKLETS = {
  workletPaths: {rawAudioProcessor: '/ui/assets/vendor/rawAudioProcessor.js',
    audioConcatProcessor: '/ui/assets/vendor/audioConcatProcessor.js'},
  libsampleratePath: '/ui/assets/vendor/libsamplerate.worklet.js',
};

export class LiveVoice {
  /** tools: {name: async (params) => object}; getProjectId: () => string|null; announce(msg, error) */
  constructor({tools, getProjectId, announce}) {
    this.tools = tools; this.getProjectId = getProjectId; this.announce = announce;
    this.conversation = null; this.starting = false; this.frame = 0;
    $('live-toggle').addEventListener('click', () => (this.conversation || this.starting ? this.stop() : this.start()));
    $('live-mute').addEventListener('click', () => this.toggleMute());
    $('live-type').addEventListener('submit', event => {
      event.preventDefault();
      const text = $('live-text').value.trim();
      if (text && this.conversation) { this.conversation.sendUserMessage(text); this.line('user', text); $('live-text').value = ''; }
    });
    window.addEventListener('pagehide', () => this.stop());
  }

  get active() { return Boolean(this.conversation); }

  ui(state, sub) {
    const bar = $('voice-bar');
    bar.classList.toggle('live', state !== 'idle');
    bar.classList.toggle('speaking', state === 'speaking');
    $('live-toggle').setAttribute('aria-pressed', String(state !== 'idle'));
    $('live-label').textContent = state === 'idle' ? 'Talk to Forge' : 'End conversation';
    $('live-sub').textContent = sub;
    $('live-mute').hidden = $('live-type').hidden = state === 'idle' || state === 'connecting';
    $('live-status').textContent = {
      idle: 'Talk to Forge: “Make it cheaper”, “Set the budget to three thousand”, “Show me the battery”.',
      connecting: 'Connecting… allow the microphone if your browser asks.',
      listening: 'Listening… speak naturally. You can interrupt Forge at any time.',
      speaking: 'Forge is speaking…', thinking: 'Working on your design…',
    }[state];
  }

  line(role, text) {
    const list = $('live-transcript');
    const li = document.createElement('li'); if (role === 'tool') li.className = 'tool';
    const who = document.createElement('b'); who.textContent = role === 'user' ? 'YOU' : role === 'tool' ? 'ACTION' : 'FORGE';
    li.append(who, text); list.append(li);
    while (list.children.length > 6) list.firstElementChild.remove();
    list.scrollTop = list.scrollHeight;
  }

  wrapTools() {
    const wrapped = {};
    for (const [name, fn] of Object.entries(this.tools)) {
      wrapped[name] = async params => {
        this.ui('thinking', 'Running ' + name.replaceAll('_', ' '));
        this.line('tool', name.replaceAll('_', ' ') + '…');
        try { return JSON.stringify(await fn(params || {})); }
        catch (error) { return JSON.stringify({error: error.message || 'Tool failed'}); }
        finally { if (this.conversation) this.ui('listening', 'Live · tap to end'); }
      };
    }
    return wrapped;
  }

  async start() {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      this.announce('Live voice needs a secure page (localhost or HTTPS) and a microphone.', true); return;
    }
    this.starting = true; this.ui('connecting', 'Connecting…');
    $('live-transcript').replaceChildren();
    try {
      const response = await fetch('/voice/live/session', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_id: this.getProjectId()}), cache: 'no-store'});
      const session = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(session.detail || 'Voice service unavailable.');
      if (!this.starting) return; // user cancelled while connecting
      this.conversation = await Conversation.startSession({
        signedUrl: session.signed_url, connectionType: 'websocket', ...WORKLETS,
        dynamicVariables: {robot_context: session.robot_context},
        clientTools: this.wrapTools(),
        onConnect: () => { this.ui('listening', 'Live · tap to end'); this.meter(); },
        onDisconnect: () => this.cleanup('Conversation ended.'),
        onError: message => this.announce(`Voice error: ${message}`, true),
        onModeChange: ({mode}) => this.ui(mode === 'speaking' ? 'speaking' : 'listening', 'Live · tap to end'),
        // Expressive TTS models may include audio tags like "[happy]"; hide them in the transcript.
        onMessage: ({message, role, source}) => {
          const text = (message || '').replace(/\[[a-z][a-z ]{0,30}\]\s*/gi, '').trim();
          if (text) this.line((role || source) === 'user' ? 'user' : 'agent', text);
        },
      });
    } catch (error) {
      this.cleanup();
      this.announce(error?.message?.includes('Permission') || error?.name === 'NotAllowedError'
        ? 'Microphone permission was denied. Allow it to talk to Forge.' : (error.message || 'Could not start the conversation.'), true);
    } finally { this.starting = false; }
  }

  async stop() {
    this.starting = false;
    const conversation = this.conversation; this.conversation = null;
    if (conversation) { try { await conversation.endSession(); } catch { /* already closed */ } }
    this.cleanup('Conversation ended.');
  }

  cleanup(message) {
    cancelAnimationFrame(this.frame); this.conversation = null;
    $('live-orb').style.transform = ''; $('live-mute').setAttribute('aria-pressed', 'false'); $('live-mute').textContent = 'Mute mic';
    this.ui('idle', 'Hands-free voice conversation');
    if (message) this.announce(message);
  }

  toggleMute() {
    if (!this.conversation) return;
    const muted = $('live-mute').getAttribute('aria-pressed') !== 'true';
    this.conversation.setMicMuted(muted);
    $('live-mute').setAttribute('aria-pressed', String(muted)); $('live-mute').textContent = muted ? 'Unmute mic' : 'Mute mic';
  }

  meter() {
    const tick = () => {
      if (!this.conversation) return;
      const level = Math.max(this.conversation.getInputVolume?.() || 0, this.conversation.getOutputVolume?.() || 0);
      $('live-orb').style.transform = `scale(${1 + Math.min(1.2, level * 2)})`;
      this.frame = requestAnimationFrame(tick);
    };
    tick();
  }

  /** Tell the agent about changes the user made by hand (not via voice). */
  contextUpdate(text) { try { this.conversation?.sendContextualUpdate(text); } catch { /* not connected */ } }
}
