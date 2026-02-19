/**
 * Toggles Panel — interactive toggle pills matching TUI's TOGGLE_DISPLAY.
 * Reads from /api/live-state, writes via POST /api/toggles/{key}.
 */
import { apiFetch, API } from '../api.js';
import { showToast, escapeHtml } from '../utils.js';

// Toggle definitions matching tui/data.py:TOGGLES
const TOGGLE_DEFS = [
    { label: 'Terminal L2',    key: 'terminal_l2_always', type: 'bool', desc: 'Always run terminal FTS5 search' },
    { label: 'L2 enrichment', key: 'context_enrichment',  type: 'bool', desc: 'Attach terminal history to ChromaDB results' },
    { label: 'TG L3',         key: 'tg_l3_always',        type: 'bool', desc: 'Always run Telegram FTS5 search' },
    { label: 'TG enrichment', key: 'tg_enrichment',       type: 'bool', desc: 'Attach Telegram messages to results' },
    { label: 'TG bot',        key: 'tg_bot_tmux',         type: 'bool', desc: 'Telegram bot in tmux session' },
    { label: 'Auto-tune',     key: 'gate_auto_tune',      type: 'bool', desc: 'Auto-adjust gate thresholds' },
    { label: 'Chain memory',  key: 'chain_memory',        type: 'bool', desc: 'Remember skill chain sequences' },
    { label: 'Notify',        key: 'tg_session_notify',   type: 'bool', desc: 'Telegram session notifications' },
    { label: 'Mirror',        key: 'tg_mirror_messages',  type: 'bool', desc: 'Mirror Claude responses to TG' },
    { label: 'Budget degrade', key: 'budget_degradation',  type: 'bool', desc: 'Auto-degrade on token budget' },
    { label: 'Budget',        key: 'session_token_budget', type: 'num',  desc: 'Session token budget', cycle: [0, 50000, 100000, 200000] },
];

let currentState = {};

export async function renderToggles(stateOverride) {
    const el = document.getElementById('toggles-content');
    if (!el) return;

    const state = stateOverride || await apiFetch('/api/live-state');
    if (!state) {
        el.innerHTML = '<div class="no-data">No state available</div>';
        return;
    }
    currentState = state;

    let html = '<div class="toggle-grid">';
    for (const tog of TOGGLE_DEFS) {
        const val = state[tog.key];
        const isOn = tog.type === 'bool' ? !!val : (val > 0);
        const onClass = isOn ? 'toggle-on' : '';

        let displayVal = '';
        if (tog.type === 'num') {
            displayVal = val === 0 ? 'OFF' : `${(val / 1000).toFixed(0)}K`;
        }

        html += `<button class="toggle-pill ${onClass}" data-key="${tog.key}" data-type="${tog.type}" title="${escapeHtml(tog.desc)}">
            <span class="toggle-dot"></span>
            <span class="toggle-label">${escapeHtml(tog.label)}</span>
            ${displayVal ? `<span class="toggle-value">${displayVal}</span>` : ''}
        </button>`;
    }
    html += '</div>';
    el.innerHTML = html;

    // Attach click handlers
    el.querySelectorAll('.toggle-pill').forEach(pill => {
        pill.addEventListener('click', () => handleToggleClick(pill));
    });
}

async function handleToggleClick(pill) {
    const key = pill.dataset.key;
    const type = pill.dataset.type;

    let newValue;
    if (type === 'num') {
        const def = TOGGLE_DEFS.find(t => t.key === key);
        const cycle = def?.cycle || [0];
        const current = currentState[key] || 0;
        const idx = cycle.indexOf(current);
        newValue = cycle[(idx + 1) % cycle.length];
    } else {
        newValue = !currentState[key];
    }

    // Optimistic UI update
    currentState[key] = newValue;
    const isOn = type === 'bool' ? !!newValue : (newValue > 0);
    pill.classList.toggle('toggle-on', isOn);

    // Update numeric display
    if (type === 'num') {
        const valSpan = pill.querySelector('.toggle-value');
        if (valSpan) {
            valSpan.textContent = newValue === 0 ? 'OFF' : `${(newValue / 1000).toFixed(0)}K`;
        }
    }

    // POST to server
    try {
        const res = await fetch(`${API}/api/toggles/${key}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: newValue }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.error || `HTTP ${res.status}`);
        }
        showToast(`${key} = ${JSON.stringify(newValue)}`, 'info');
    } catch (e) {
        // Revert optimistic update
        currentState[key] = type === 'bool' ? !newValue : newValue;
        pill.classList.toggle('toggle-on', !isOn);
        showToast(`Toggle failed: ${e.message}`, 'error');
    }
}

/**
 * Handle SSE live_state_event — refresh toggles from external changes.
 */
export function handleLiveStateEvent(data) {
    currentState = data;
    renderToggles(data);
}
