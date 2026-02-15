/**
 * Session History Panel — list, detail view, comparison
 */
import { apiFetch } from '../api.js';
import { escapeHtml, formatDate } from '../utils.js';

let selectedSessions = new Set();

export async function renderHistory() {
    const data = await apiFetch('/api/history');
    if (!data) return;

    const el = document.getElementById('history-content');
    const files = data.files || [];
    document.getElementById('history-count').textContent = files.length;

    if (files.length === 0) {
        el.innerHTML = '<div class="no-data">No archived sessions found.</div>';
        return;
    }

    selectedSessions.clear();
    const btn = document.getElementById('compare-btn');
    if (btn) btn.classList.add('hidden');

    el.innerHTML = files.map(f => `
        <div class="history-entry">
            <label class="history-check-label" onclick="event.stopPropagation()">
                <input type="checkbox" class="history-check" data-filename="${escapeHtml(f.filename)}">
            </label>
            <div class="history-entry-body" data-filename="${escapeHtml(f.filename)}">
                <div class="history-name">${escapeHtml(f.filename)}</div>
                <div class="history-meta">${formatDate(f.modified)} | ${(f.size / 1024).toFixed(1)} KB</div>
            </div>
        </div>`).join('');

    // Attach event handlers
    el.querySelectorAll('.history-check').forEach(cb => {
        cb.addEventListener('change', () => {
            toggleSessionSelect(cb.dataset.filename, cb);
        });
    });
    el.querySelectorAll('.history-entry-body').forEach(body => {
        body.addEventListener('click', () => {
            showHistoryDetail(body.dataset.filename);
        });
    });
}

async function showHistoryDetail(filename) {
    const data = await apiFetch(`/api/history/${filename}`);
    if (!data || data.error) return;

    document.getElementById('overlay-title').textContent = filename;
    document.getElementById('overlay-body').textContent = data.content || '(empty)';
    document.getElementById('detail-overlay').classList.remove('hidden');
}

function toggleSessionSelect(filename, checkbox) {
    if (checkbox.checked) {
        selectedSessions.add(filename);
    } else {
        selectedSessions.delete(filename);
    }
    const btn = document.getElementById('compare-btn');
    if (selectedSessions.size === 2) {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

export async function compareSessions() {
    const files = Array.from(selectedSessions);
    if (files.length !== 2) return;

    const data = await apiFetch(`/api/history/compare?a=${encodeURIComponent(files[0])}&b=${encodeURIComponent(files[1])}`);
    if (!data || data.error) return;

    document.getElementById('overlay-title').textContent = 'Session Comparison';
    const body = document.getElementById('overlay-body');

    let html = '<div class="compare-view">';
    html += `<div class="compare-header">
        <div class="compare-col-header">${escapeHtml(data.a.filename)}</div>
        <div class="compare-col-header">${escapeHtml(data.b.filename)}</div>
    </div>`;

    const diff = data.diff || {};

    for (const section of (diff.added_sections || [])) {
        html += `<div class="compare-row compare-added">
            <div class="compare-col compare-empty"><em>(not present)</em></div>
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.b.sections[section] || '').substring(0, 300)}</div>
        </div>`;
    }

    for (const section of (diff.removed_sections || [])) {
        html += `<div class="compare-row compare-removed">
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.a.sections[section] || '').substring(0, 300)}</div>
            <div class="compare-col compare-empty"><em>(not present)</em></div>
        </div>`;
    }

    for (const section of (diff.changed_sections || [])) {
        html += `<div class="compare-row compare-changed">
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.a.sections[section] || '').substring(0, 300)}</div>
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.b.sections[section] || '').substring(0, 300)}</div>
        </div>`;
    }

    const allSections = new Set([
        ...Object.keys(data.a.sections || {}),
        ...Object.keys(data.b.sections || {}),
    ]);
    const changedSet = new Set([
        ...(diff.added_sections || []),
        ...(diff.removed_sections || []),
        ...(diff.changed_sections || []),
    ]);
    for (const section of allSections) {
        if (changedSet.has(section)) continue;
        html += `<div class="compare-row">
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br><span class="text-muted">(unchanged)</span></div>
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br><span class="text-muted">(unchanged)</span></div>
        </div>`;
    }

    html += '</div>';
    body.innerHTML = html;
    document.getElementById('detail-overlay').classList.remove('hidden');
}

// ── Date Selectors ───────────────────────────────────────

export async function populateDateSelects() {
    const data = await apiFetch('/api/audit/dates');
    if (!data || !data.dates) return;

    const selects = [
        document.getElementById('gate-date-select'),
        document.getElementById('timeline-date-select'),
    ];

    for (const select of selects) {
        const currentOptions = select.querySelectorAll('option:not(:first-child)');
        currentOptions.forEach(o => o.remove());

        for (const date of data.dates) {
            const opt = document.createElement('option');
            opt.value = date;
            opt.textContent = date;
            select.appendChild(opt);
        }
    }
}
