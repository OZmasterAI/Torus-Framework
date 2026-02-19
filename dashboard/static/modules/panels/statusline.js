/**
 * Statusline Metrics Bar — mirrors TUI statusline data in the dashboard header.
 * Reads from /api/statusline-snapshot and /api/live-state.
 */
import { apiFetch } from '../api.js';
import { escapeHtml } from '../utils.js';

/**
 * Render the statusline metrics bar with model, branch, context%, cost, etc.
 */
export async function renderStatuslineMetrics() {
    const [snap, live] = await Promise.all([
        apiFetch('/api/statusline-snapshot'),
        apiFetch('/api/live-state'),
    ]);

    // Model
    const modelEl = document.getElementById('sl-model');
    if (modelEl && snap) {
        const model = (snap.model || '--').toLowerCase();
        modelEl.textContent = snap.model || '--';
        modelEl.className = 'sl-item sl-model';
        if (model.includes('opus')) modelEl.classList.add('model-opus');
        else if (model.includes('sonnet')) modelEl.classList.add('model-sonnet');
        else if (model.includes('haiku')) modelEl.classList.add('model-haiku');
    }

    // Branch — extract from snapshot or fall back
    const branchEl = document.getElementById('sl-branch');
    if (branchEl) {
        // Try to get branch from live state's git info or snapshot
        branchEl.textContent = snap?.branch || '--';
    }

    // Context %
    const ctxEl = document.getElementById('sl-context');
    if (ctxEl && snap) {
        const pct = snap.context_pct ?? '--';
        ctxEl.textContent = `ctx:${pct}%`;
        ctxEl.className = 'sl-item sl-context';
        if (typeof pct === 'number') {
            if (pct >= 90) ctxEl.classList.add('ctx-danger');
            else if (pct >= 75) ctxEl.classList.add('ctx-crit');
            else if (pct >= 50) ctxEl.classList.add('ctx-high');
            else if (pct >= 25) ctxEl.classList.add('ctx-mid');
            else ctxEl.classList.add('ctx-low');
        }
    }

    // Cost
    const costEl = document.getElementById('sl-cost');
    if (costEl && snap) {
        const cost = snap.cost_usd;
        costEl.textContent = typeof cost === 'number' ? `$${cost.toFixed(2)}` : '$--';
    }

    // Compressions
    const cmpEl = document.getElementById('sl-cmp');
    if (cmpEl && snap) {
        cmpEl.textContent = `CMP:${snap.compressions ?? '--'}`;
    }

    // Memory freshness
    const memEl = document.getElementById('sl-memory');
    if (memEl && snap) {
        const dur = snap.duration_min;
        if (typeof dur === 'number') {
            const hrs = Math.floor(dur / 60);
            const mins = dur % 60;
            memEl.textContent = hrs > 0 ? `${hrs}h${mins}m` : `${mins}m`;
        } else {
            memEl.textContent = '--';
        }
    }

    // Tokens
    const tokEl = document.getElementById('sl-tokens');
    if (tokEl && snap) {
        tokEl.textContent = snap.session_tokens || '--';
    }

    // Lines
    const linesEl = document.getElementById('sl-lines');
    if (linesEl && snap) {
        const added = snap.lines_added || 0;
        const removed = snap.lines_removed || 0;
        if (added || removed) {
            linesEl.innerHTML = `<span style="color:var(--green)">+${added}</span>/<span style="color:var(--red)">-${removed}</span>`;
        } else {
            linesEl.textContent = '--';
        }
    }

    // Budget tier badge
    const budgetEl = document.getElementById('sl-budget');
    if (budgetEl && live) {
        const degradation = live.budget_degradation;
        const budget = live.session_token_budget || 0;
        if (degradation && budget > 0) {
            // Determine tier from snapshot data if available
            budgetEl.classList.remove('hidden');
            budgetEl.className = 'sl-item sl-budget';
            // Simple tier display based on settings
            budgetEl.textContent = `BUDGET:${(budget / 1000).toFixed(0)}K`;
        } else {
            budgetEl.classList.add('hidden');
        }
    }
}
