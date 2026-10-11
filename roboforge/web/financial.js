// Filing facts and arithmetic stay separate from the optional analyst note.
const $ = id => document.getElementById(id);
const money = n => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', maximumFractionDigits: 0}).format(n);
const revenue = n => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', notation: 'compact', maximumFractionDigits: 2}).format(n);
const el = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
const row = values => { const tr = el('tr'); values.forEach(v => tr.append(el('td', v))); return tr; };
function sourceLink(source, text = source.title) {
  const link = el('a', text);
  const url = new URL(source.url);
  if (url.protocol === 'https:' && ['www.sec.gov', 'investors.teradyne.com'].includes(url.hostname)) link.href = url.href;
  link.target = '_blank'; link.rel = 'noopener noreferrer'; return link;
}

export class FinancialResearch {
  constructor({api, action, announce, project}) {
    Object.assign(this, {api, action, announce, project, report: null});
    $('research-form').addEventListener('submit', event => {
      event.preventDefault();
      action(() => this.run(), 'Reading public filings and comparing the economics…');
    });
    $('research-export').addEventListener('click', () => {
      if (!this.report) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(this.report, null, 2)], {type: 'application/json'}));
      const a = el('a'); a.href = url; a.download = `argus-research-rev-${this.report.revision}.json`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  invalidate(project) {
    if (this.report && (this.report.project_id !== project.id || this.report.revision !== project.revision)) {
      this.report = null; $('research-results').hidden = true;
      $('research-status').textContent = 'The design changed. Run research again to update ownership costs for this revision.';
    }
  }
  async run() {
    const project = this.project();
    if (!project) throw new Error('Create a robot before running research.');
    this.report = null; $('research-results').hidden = true;
    $('research-status').textContent = 'Retrieving the selected public data and preparing the note…';
    try {
      const report = await this.api(`/projects/${encodeURIComponent(project.id)}/finance/research?revision=${project.revision}`, {
        source: $('research-source').value, use_ai: $('research-ai').checked, question: $('research-question').value.trim(),
        economics: {annual_savings_usd: Number($('research-savings').value), hours_per_day: Number($('research-hours').value), years: 3},
      });
      if (this.project()?.id !== project.id || this.project()?.revision !== project.revision) {
        $('research-status').textContent = 'The design changed while research ran. Run it again for the current revision.';
        this.announce('Research needs to be updated for the current design.'); return;
      }
      this.report = report; this.render(report);
      this.announce('Financial research ready. Review the sources and assumptions below.');
    } catch (error) {
      $('research-status').textContent = 'Research could not complete. Check the connection and try again.'; throw error;
    }
  }
  render(report) {
    const missing = report.companies.filter(c => c.status === 'unavailable');
    const mode = report.source_mode === 'snapshot' ? 'Historical snapshot, not current market data.' : 'Annual SEC filings, not share prices.';
    const ai = report.ai_status === 'generated' ? 'AI note generated with filing citations.' : report.ai_status === 'unavailable' ? 'AI was unavailable; the note below uses calculated filing facts.' : report.ai_status === 'no_public_data' ? 'No data for an AI note.' : 'Calculated filing facts; AI was not requested.';
    $('research-status').textContent = `Revision ${report.revision}. ${mode} ${ai}${report.ai_notice ? ` ${report.ai_notice}` : ''}${missing.length ? ' SEC retrieval failed. Select the historical snapshot to run the demo.' : ''}`;
    $('research-companies').replaceChildren(...report.companies.map(c => {
      const latest = c.records.at(-1);
      return row([`${c.name} (${c.ticker})`, latest ? `${revenue(latest.revenue_usd)} / ${latest.period_end}` : 'Unavailable', c.revenue_growth_pct === null ? 'Unavailable' : `${c.revenue_growth_pct > 0 ? '+' : ''}${c.revenue_growth_pct.toFixed(1)}%`, c.signal]);
    }));
    const notes = $('research-notes'); notes.replaceChildren(el('h3', 'Research note'));
    for (const finding of report.analyst_note.findings) {
      const p = el('p', finding.observation);
      finding.source_ids.forEach(id => { const s = report.sources.find(s => s.id === id); if (s) { p.append(' '); p.append(sourceLink(s, `[${id}]`)); } });
      notes.append(p);
    }
    notes.append(el('h3', 'Questions to investigate'));
    const questions = el('ul'); report.analyst_note.questions_to_check.forEach(q => questions.append(el('li', q))); notes.append(questions);
    $('research-economics').replaceChildren(...report.economics.map(s => row([
      s.name, money(s.assumptions.annual_savings_usd), money(s.total_cost_of_ownership_usd), s.payback_years === null ? 'No positive payback' : `${s.payback_years} years`, s.roi_pct === null ? 'Not calculated' : `${s.roi_pct}%`,
    ])));
    const evaluation = $('research-evaluation'); evaluation.replaceChildren();
    for (const c of report.companies) {
      const e = c.evaluation;
      evaluation.append(el('h3', `${c.name}: ${e.samples} held-out annual periods`));
      if (!e.samples) { evaluation.append(el('p', 'Insufficient public data to evaluate.', 'muted')); continue; }
      evaluation.append(el('p', `Trend MAE ${money(e.trend_mae_usd)} · Unchanged-revenue MAE ${money(e.baseline_mae_usd)}. ${e.trend_mae_usd < e.baseline_mae_usd ? 'Trend had lower error in this sample.' : 'The simple baseline had equal or lower error in this sample.'}`));
      const wrapper = el('div', undefined, 'table-scroll'), table = el('table', undefined, 'research-table');
      const head = el('thead'); const tr = el('tr'); ['Period end', 'Actual revenue', 'Trend estimate', 'Baseline estimate'].forEach(v => tr.append(el('th', v))); head.append(tr);
      const body = el('tbody'); e.folds.forEach(f => body.append(row([f.period_end, revenue(f.actual_usd), revenue(f.trend_usd), revenue(f.baseline_usd)])));
      table.append(head, body); wrapper.append(table); evaluation.append(wrapper, el('p', e.limitation, 'muted'));
    }
    $('research-sources').replaceChildren(...report.sources.map(s => { const li = el('li'); li.append(sourceLink(s, `${s.id}: ${s.title}`)); return li; }));
    $('research-limitations').textContent = [...report.limitations, ...report.companies.map(c => `${c.name}: ${c.notice}`), 'Ownership assumptions: three years, 50% duty cycle, $0.17/kWh and annual maintenance at 8% of hardware cost. Savings scenarios are 75%, 100% and 125% of your estimate.'].join(' ');
    $('research-results').hidden = false;
  }
}
