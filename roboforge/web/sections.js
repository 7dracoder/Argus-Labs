// Accessible, local-only navigation. Switching sections never edits a project.
export class SectionTabs {
  constructor(root, onChange = () => {}) {
    this.tabs = [...root.querySelectorAll('[role="tab"]')];
    this.panels = this.tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
    this.onChange = onChange;
    this.tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => this.select(tab.dataset.section, false, true));
      tab.addEventListener('keydown', event => {
        const last = this.tabs.length - 1;
        const next = {ArrowRight: (index + 1) % this.tabs.length, ArrowLeft: (index + last) % this.tabs.length,
          Home: 0, End: last}[event.key];
        if (next === undefined) return;
        event.preventDefault(); this.select(this.tabs[next].dataset.section, true, true);
      });
    });
    this.select(this.tabs.find(tab => tab.getAttribute('aria-selected') === 'true')?.dataset.section);
  }
  select(section, focus = false, scroll = false) {
    const index = this.tabs.findIndex(tab => tab.dataset.section === section);
    if (index < 0) return false;
    this.tabs.forEach((tab, i) => {
      tab.setAttribute('aria-selected', String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
      this.panels[i].hidden = i !== index;
    });
    this.current = section;
    if (focus) this.tabs[index].focus();
    this.onChange(section);
    if (scroll) this.panels[index].scrollIntoView?.({block: 'start', behavior: 'instant'});
    return true;
  }
}
