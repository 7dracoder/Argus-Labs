// UI preference heuristic, not an emotion, cognitive, or medical classifier.
// SmartSpectra's protobuf confidence is a percentage, not a probability.
// Normalize only at the SDK boundary; reject malformed input rather than clamp it.
export function normalizeBreathingSample(sample) {
  if (!sample || !Number.isFinite(sample.value) || sample.value <= 0 ||
      !Number.isFinite(sample.confidence) || sample.confidence < 0 || sample.confidence > 100) {
    return null;
  }
  return {value: sample.value, confidence: sample.confidence / 100};
}

export class PacingSignal {
  constructor() {
    this.baseline = [];
    this.startedAt = null;
    this.lastAt = null;
    this.elevatedSince = null;
  }

  reset() {
    this.baseline = [];
    this.startedAt = this.lastAt = this.elevatedSince = null;
  }

  update(sample, now, validationReady = true) {
    const normal = {consent: true, state: 'focused', confidence: 0};
    // Five seconds with no usable sample resets the sustained-change window.
    if (!validationReady || !sample || !Number.isFinite(sample.value) || sample.value <= 0
        || !Number.isFinite(sample.confidence) || sample.confidence < 0.8 || sample.confidence > 1) {
      this.elevatedSince = null;
      return normal;
    }
    if (this.lastAt !== null && now - this.lastAt > 5000) this.elevatedSince = null;
    this.lastAt = now;
    this.startedAt ??= now;
    if (now - this.startedAt < 60000) {
      this.baseline.push(sample.value);
      if (this.baseline.length > 120) this.baseline.shift();
      return normal;
    }
    if (this.baseline.length < 10) return normal;
    const sorted = [...this.baseline].sort((a, b) => a - b);
    const baseline = sorted[Math.floor(sorted.length / 2)];
    if (sample.value > baseline * 1.25) this.elevatedSince ??= now;
    else this.elevatedSince = null;
    // Sustained relative breathing change ONLY suggests simpler, slower speech.
    return {consent: true,
            state: this.elevatedSince !== null && now - this.elevatedSince >= 15000
              ? 'needs_guidance' : 'focused', confidence: sample.confidence};
  }
}
