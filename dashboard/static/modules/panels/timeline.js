/**
 * Timeline Panel — Audit events, observations, filters, popover
 */
import { apiFetch } from '../api.js';
import { escapeHtml, formatTime, showToast } from '../utils.js';

let cachedTimelineEntries = [];
let activeGateFilter = null;
let activeQueryFilters = {};

// ── Audit Timeline ──────────────────────────────────────

export async function renderTimeline(date) {
    const dateParam = date ? `?date=${date}&limit=300` : '?limit=300';
    const data = await apiFetch(`/api/audit${dateParam}`);
    if (!data) return;

    cachedTimelineEntries = data.entries || [];
    document.getElementById('timeline-count').textContent = data.total;
    renderFilteredTimeline();
}

export function renderFilteredTimeline() {
    const el = document.getElementById('timeline-content');
    let entries = cachedTimelineEntries;

    if (activeGateFilter) {
        entries = entries.filter(e => e.gate && e.gate.includes(activeGateFilter));
    }

    if (entries.length === 0) {
        el.innerHTML = '<div class="no-data">No audit events match this filter.</div>';
        return;
    }

    el.innerHTML = entries.map(renderTimelineEntry).join('');

    // Attach click handlers for popover
    el.querySelectorAll('.timeline-entry').forEach(entry => {
        entry.addEventListener('click', (e) => {
            const dataAttr = entry.dataset.entryData;
            if (dataAttr) showAuditDetailPopover(dataAttr, e);
        });
    });
}

function renderTimelineEntry(entry) {
    const time = formatTime(entry.ts || entry.timestamp);
    let badge, text, stateKeysBadges = '';

    const severity = entry.severity || 'info';
    const severityClass = severity === 'critical' ? 'severity-critical' :
                          severity === 'error' ? 'severity-error' :
                          severity === 'warn' ? 'severity-warn' : '';

    if (entry.type === 'gate') {
        const dec = entry.decision;
        const badgeClass = dec === 'pass' ? 'badge-pass' :
                          dec === 'block' ? 'badge-block' : 'badge-warn';
        badge = `<span class="timeline-badge ${badgeClass}">${dec}</span>`;
        const reason = entry.reason ? ` — ${entry.reason}` : '';
        text = `${entry.gate} [${entry.tool}]${reason}`;

        if (entry.state_keys && entry.state_keys.length > 0) {
            stateKeysBadges = entry.state_keys.map(key =>
                `<span class="state-key-badge">${escapeHtml(key)}</span>`
            ).join('');
        }
    } else {
        const evt = entry.event || '';
        const isError = evt === 'PostToolUseFailure';
        const badgeClass = isError ? 'badge-error' : 'badge-event';
        badge = `<span class="timeline-badge ${badgeClass}">${evt.substring(0, 12)}</span>`;
        const d = entry.data || {};
        text = Object.entries(d).map(([k, v]) => `${k}:${v}`).join(' ');
    }

    const entryData = encodeURIComponent(JSON.stringify(entry));

    return `
        <div class="timeline-entry ${severityClass}" data-entry-data="${entryData}">
            <span class="timeline-time">${time}</span>
            ${badge}
            <span class="timeline-text">${escapeHtml(text)}</span>
            ${stateKeysBadges ? `<div class="state-keys-container">${stateKeysBadges}</div>` : ''}
        </div>`;
}

export function prependTimelineEntry(entry) {
    const el = document.getElementById('timeline-content');
    if (el.querySelector('.loading') || el.querySelector('.no-data')) {
        el.innerHTML = '';
    }
    const html = renderTimelineEntry(entry);
    el.insertAdjacentHTML('afterbegin', html);

    // Attach click handler to new entry
    const newEntry = el.querySelector('.timeline-entry');
    if (newEntry) {
        newEntry.addEventListener('click', (e) => {
            const dataAttr = newEntry.dataset.entryData;
            if (dataAttr) showAuditDetailPopover(dataAttr, e);
        });
    }

    const countEl = document.getElementById('timeline-count');
    const current = parseInt(countEl.textContent) || 0;
    countEl.textContent = current + 1;

    const children = el.querySelectorAll('.timeline-entry');
    if (children.length > 500) {
        for (let i = 500; i < children.length; i++) {
            children[i].remove();
        }
    }
}

// ── Audit Detail Popover ─────────────────────────────────

function showAuditDetailPopover(entryDataEncoded, event) {
    event.stopPropagation();
    try {
        const entry = JSON.parse(decodeURIComponent(entryDataEncoded));
        let popover = document.getElementById('audit-detail-popover');
        if (!popover) {
            popover = document.createElement('div');
            popover.id = 'audit-detail-popover';
            popover.className = 'audit-detail-popover';
            document.body.appendChild(popover);
        }

        let content = '<div class="popover-close" id="popover-close-btn">&times;</div>';

        if (entry.type === 'gate') {
            const decisionColor = entry.decision === 'pass' ? 'var(--green)' :
                                entry.decision === 'block' ? 'var(--red)' : 'var(--yellow)';

            content += `<div class="popover-section">
                <div class="popover-gate-name">${escapeHtml(entry.gate)}</div>
                <div class="popover-decision" style="color:${decisionColor}">
                    Decision: <strong>${escapeHtml(entry.decision).toUpperCase()}</strong>
                </div>
            </div>`;
            content += `<div class="popover-section">
                <div class="popover-label">Tool:</div>
                <div class="popover-value">${escapeHtml(entry.tool)}</div>
            </div>`;
            if (entry.reason) {
                content += `<div class="popover-section">
                    <div class="popover-label">Reason:</div>
                    <div class="popover-reason">${escapeHtml(entry.reason)}</div>
                </div>`;
            }
            if (entry.state_keys && entry.state_keys.length > 0) {
                content += `<div class="popover-section">
                    <div class="popover-label">State Keys:</div>
                    <div class="popover-state-keys">
                        ${entry.state_keys.map(key => `<span class="state-key-badge">${escapeHtml(key)}</span>`).join('')}
                    </div>
                </div>`;
            }
            content += `<div class="popover-section">
                <div class="popover-label">Session ID:</div>
                <div class="popover-value">${escapeHtml(entry.session_id || 'N/A')}</div>
            </div>`;
            content += `<div class="popover-section">
                <div class="popover-label">Timestamp:</div>
                <div class="popover-value">${escapeHtml(entry.timestamp || formatTime(entry.ts))}</div>
            </div>`;
        } else {
            content += `<div class="popover-section">
                <div class="popover-gate-name">Event: ${escapeHtml(entry.event || 'Unknown')}</div>
            </div>`;
            if (entry.data && Object.keys(entry.data).length > 0) {
                content += `<div class="popover-section">
                    <div class="popover-label">Data:</div>
                    <div class="popover-reason">${escapeHtml(JSON.stringify(entry.data, null, 2))}</div>
                </div>`;
            }
            content += `<div class="popover-section">
                <div class="popover-label">Timestamp:</div>
                <div class="popover-value">${escapeHtml(entry.timestamp || formatTime(entry.ts))}</div>
            </div>`;
        }

        popover.innerHTML = content;
        popover.classList.remove('hidden');

        // Position near click
        const rect = event.target.getBoundingClientRect();
        popover.style.top = `${rect.top + window.scrollY + 30}px`;
        popover.style.left = `${Math.min(rect.left + window.scrollX, window.innerWidth - 420)}px`;

        // Close button
        document.getElementById('popover-close-btn')?.addEventListener('click', hideAuditDetailPopover);
    } catch (e) {
        console.error('Failed to show audit detail popover:', e);
    }
}

export function hideAuditDetailPopover() {
    const popover = document.getElementById('audit-detail-popover');
    if (popover) popover.classList.add('hidden');
}

// ── Gate Filter ──────────────────────────────────────────

export function filterTimelineByGate(gateName) {
    activeGateFilter = gateName;
    renderFilteredTimeline();

    const badge = document.getElementById('gate-filter-badge');
    if (badge) {
        badge.innerHTML = `${escapeHtml(gateName)} <span class="filter-badge-x" id="clear-gate-filter-btn">&times;</span>`;
        badge.classList.remove('hidden');
        document.getElementById('clear-gate-filter-btn')?.addEventListener('click', (e) => {
            e.stopPropagation();
            clearGateFilter();
        });
    }

    const timeline = document.getElementById('panel-timeline');
    if (timeline) timeline.scrollIntoView({ behavior: 'smooth' });
}

export function clearGateFilter() {
    activeGateFilter = null;
    renderFilteredTimeline();
    const badge = document.getElementById('gate-filter-badge');
    if (badge) {
        badge.classList.add('hidden');
        badge.innerHTML = '';
    }
}

// ── Query Filters ────────────────────────────────────────

export async function applyTimelineFilters() {
    const gate = document.getElementById('timeline-gate-filter').value;
    const decision = document.getElementById('timeline-decision-filter').value;
    const severity = document.getElementById('timeline-severity-filter')?.value || '';
    const hoursInput = document.getElementById('timeline-hours-filter');
    let hours = parseInt(hoursInput.value) || 24;

    if (hours < 1 || hours > 720) {
        showToast('Hours must be between 1 and 720', 'error', 'warning');
        hoursInput.value = Math.max(1, Math.min(720, hours));
        hours = parseInt(hoursInput.value);
    }

    if (!gate && !decision && !severity) {
        activeQueryFilters = {};
        renderActiveFilterBadges();
        renderFilteredTimeline();
        return;
    }

    const params = new URLSearchParams();
    if (gate) params.set('gate', gate);
    if (decision) params.set('decision', decision);
    if (severity) params.set('severity', severity);
    params.set('hours', hours.toString());

    const data = await apiFetch(`/api/audit/query?${params.toString()}`);
    if (!data) return;

    activeQueryFilters = {};
    if (gate) activeQueryFilters.gate = gate;
    if (decision) activeQueryFilters.decision = decision;
    if (severity) activeQueryFilters.severity = severity;

    renderActiveFilterBadges();

    const el = document.getElementById('timeline-content');
    const entries = data.entries || [];
    document.getElementById('timeline-count').textContent = data.total;

    if (entries.length === 0) {
        el.innerHTML = '<div class="no-data">No audit events match these filters.</div>';
        return;
    }
    el.innerHTML = entries.map(renderTimelineEntry).join('');
}

function renderActiveFilterBadges() {
    const container = document.getElementById('timeline-active-filters');
    if (!container) return;

    const keys = Object.keys(activeQueryFilters);
    if (keys.length === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = keys.map(key => {
        const val = activeQueryFilters[key];
        const display = key === 'gate' ? val.replace('GATE ', 'G') : val;
        return `<span class="filter-badge">${escapeHtml(key)}: ${escapeHtml(display)} ` +
            `<span class="filter-badge-x" data-filter-key="${key}">&times;</span></span>`;
    }).join(' ');

    container.querySelectorAll('.filter-badge-x').forEach(x => {
        x.addEventListener('click', (e) => {
            e.stopPropagation();
            removeQueryFilter(x.dataset.filterKey);
        });
    });
}

function removeQueryFilter(key) {
    delete activeQueryFilters[key];
    if (key === 'gate') document.getElementById('timeline-gate-filter').value = '';
    if (key === 'decision') document.getElementById('timeline-decision-filter').value = '';
    if (key === 'severity') {
        const el = document.getElementById('timeline-severity-filter');
        if (el) el.value = '';
    }

    if (Object.keys(activeQueryFilters).length === 0) {
        renderActiveFilterBadges();
        renderFilteredTimeline();
    } else {
        applyTimelineFilters();
    }
}

// ── Tab Switching ────────────────────────────────────────

export function switchTimelineTab(tab) {
    const auditView = document.getElementById('timeline-audit-view');
    const obsView = document.getElementById('timeline-observations-view');
    const tabs = document.querySelectorAll('#timeline-tabs .tab');

    tabs.forEach(t => t.classList.toggle('active', t.dataset.timelineTab === tab));

    if (tab === 'observations') {
        auditView.style.display = 'none';
        obsView.style.display = '';
        renderObservations();
    } else {
        auditView.style.display = '';
        obsView.style.display = 'none';
    }
}

// ── Observations ─────────────────────────────────────────

export async function renderObservations() {
    const data = await apiFetch('/api/observations/recent');
    if (!data) return;

    const el = document.getElementById('observations-content');
    if (!el) return;

    const obs = data.observations || [];
    if (obs.length === 0) {
        el.innerHTML = '<div class="no-data">No observations captured yet.</div>';
        return;
    }

    const toolIcons = {
        'Bash': '>_', 'Edit': '~', 'Write': '+', 'Read': '@',
        'Grep': '?', 'Glob': '*', 'NotebookEdit': 'N',
        'UserPrompt': 'U', 'Task': 'T',
    };

    el.innerHTML = obs.map(o => {
        const icon = toolIcons[o.tool] || '#';
        const isError = o.has_error === 'true' || o.has_error === true;
        const priority = o.priority || 'low';
        const priorityClass = priority === 'high' ? 'obs-priority-high' :
                              priority === 'medium' ? 'obs-priority-medium' : '';
        const errorClass = isError ? 'obs-error' : '';
        const sentiment = o.sentiment || '';
        const sentimentDot = sentiment === 'frustration' ? '<span class="obs-sentiment obs-sentiment-frustration"></span>' :
                            sentiment === 'confidence' ? '<span class="obs-sentiment obs-sentiment-confidence"></span>' :
                            sentiment === 'uncertainty' ? '<span class="obs-sentiment obs-sentiment-uncertainty"></span>' : '';
        const time = formatTime(o.timestamp || o.session_time);
        const summary = escapeHtml((o.summary || '').substring(0, 120));

        return `<div class="observation-item ${priorityClass} ${errorClass}">
            <span class="obs-tool-badge" title="${escapeHtml(o.tool)}">${icon}</span>
            <span class="obs-time">${time}</span>
            <span class="obs-summary">${summary}</span>
            ${sentimentDot}
        </div>`;
    }).join('');
}

// ── Popover Global Close ─────────────────────────────────

export function setupPopoverClose() {
    document.addEventListener('click', (e) => {
        const popover = document.getElementById('audit-detail-popover');
        if (popover && !popover.contains(e.target) && !e.target.closest('.timeline-entry')) {
            hideAuditDetailPopover();
        }
    });
}
