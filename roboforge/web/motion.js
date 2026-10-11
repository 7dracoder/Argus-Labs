// Entrance motion never hides content or blocks an interaction.
export const entranceFrames = [
  {opacity: .35, transform: 'translateY(14px)'},
  {opacity: 1, transform: 'translateY(0)'},
];

export function reveal(element, reduced, delay = 0) {
  if (reduced || !element.animate) return null;
  return element.animate(entranceFrames, {duration: 460, delay,
    easing: 'cubic-bezier(.22, 1, .36, 1)'});
}

export function initMotion(root = document) {
  if (!window.IntersectionObserver || !window.MutationObserver) return;
  const preference = matchMedia('(prefers-reduced-motion: reduce)');
  const seen = new WeakSet(), active = new Set();
  const selector = '.hero-copy, .showcase, .how > li, .collection-note, .card, .next-row, .asm-steps > li';
  const observer = new IntersectionObserver(entries => {
    let index = 0;
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      const animation = reveal(entry.target, preference.matches, Math.min(index++ * 45, 135));
      if (animation) {
        active.add(animation);
        animation.finished.then(() => active.delete(animation), () => active.delete(animation));
      }
    }
  }, {threshold: .08});
  const register = node => {
    if (node.nodeType !== 1 && node !== root) return;
    const elements = [...node.querySelectorAll(selector)];
    if (node.matches?.(selector)) elements.unshift(node);
    for (const element of elements) {
      if (seen.has(element)) continue;
      seen.add(element); observer.observe(element);
    }
  };
  register(root);
  const changes = new MutationObserver(records => {
    for (const record of records) for (const node of record.addedNodes) register(node);
  });
  changes.observe(root, {childList: true, subtree: true});
  preference.addEventListener('change', event => {
    if (event.matches) for (const animation of active) animation.cancel();
  });
}
