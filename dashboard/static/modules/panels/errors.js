/**
 * Error Patterns Panel
 */
import { apiFetch } from '../api.js';
import { escapeHtml } from '../utils.js';

export async function renderErrors() {
    const data = await apiFetch('/api/errors');
    if (!data) return;

    const el = document.getElementById('errors-content');
    let html = '';

    const patterns = data.error_patterns || {};
    const bans = data.active_bans || [];

    if (Object.keys(patterns).length === 0 && bans.length === 0) {
        el.innerHTML = `
            <div class="no-data">No errors recorded this session.</div>
            <div style="margin-top:8px; font-size:12px; color:var(--text-muted);">
                Tool calls: ${data.tool_call_count || 0}
            </div>`;
        return;
    }

    for (const [pattern, count] of Object.entries(patterns)) {
        html += `
            <div class="error-entry">
                <span class="error-pattern">${escapeHtml(pattern)}</span>
                <span class="error-count">${count}</span>
            </div>`;
    }

    if (bans.length > 0) {
        html += '<div style="margin-top:12px; font-size:11px; color:var(--text-muted); text-transform:uppercase;">Active Bans</div>';
        for (const ban of bans) {
            html += `<div class="ban-entry">${escapeHtml(typeof ban === 'string' ? ban : JSON.stringify(ban))}</div>`;
        }
    }

    html += `<div style="margin-top:8px; font-size:11px; color:var(--text-muted);">Tool calls: ${data.tool_call_count || 0}</div>`;
    el.innerHTML = html;
}
