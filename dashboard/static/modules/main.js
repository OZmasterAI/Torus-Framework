/**
 * Self-Healing Claude Framework — Dashboard Entry Point
 *
 * Orchestrates all panel modules, SSE connection, theme, and auto-refresh.
 * Loaded as <script type="module"> from index.html.
 */

// Foundation modules
import { setupTheme, setupPanelCollapse, setupAutoRefresh } from './theme.js';
import { connectSSE, clearNotificationBadge } from './sse.js';
import { recordHealthForSparkline } from './panels/metrics.js';

// Panel modules
import { renderHealth } from './panels/health.js';
import { renderGates, renderGatePerf, renderGateDeps, populateGateFilterDropdown, setGateFilterCallback } from './panels/gates.js';
import { renderTimeline, renderFilteredTimeline, prependTimelineEntry, filterTimelineByGate, clearGateFilter, applyTimelineFilters, switchTimelineTab, renderObservations, setupPopoverClose, hideAuditDetailPopover } from './panels/timeline.js';
import { renderMemory, renderMemoryTags, renderMemoryHealth, searchMemoryByTag } from './panels/memory.js';
import { toggleMemoryGraph } from './panels/memory-graph.js';
import { renderLiveMetrics, renderToolStats, renderEditStreak, renderActivityTrend } from './panels/metrics.js';
import { renderErrors } from './panels/errors.js';
import { renderComponents, renderComponentTab } from './panels/components.js';
import { renderHistory, compareSessions, populateDateSelects } from './panels/history.js';

// ── Overlay ─────────────────────────────────────────────

function setupOverlay() {
    document.getElementById('overlay-close').addEventListener('click', () => {
        document.getElementById('detail-overlay').classList.add('hidden');
    });
    document.getElementById('detail-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) {
            e.currentTarget.classList.add('hidden');
        }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('detail-overlay').classList.add('hidden');
            hideAuditDetailPopover();
        }
    });
}

// ── Refresh All ─────────────────────────────────────────

async function refreshAll() {
    await Promise.all([
        renderHealth(),
        renderGates(),
        renderTimeline(),
        renderGatePerf(),
        renderErrors(),
        renderToolStats(),
        renderLiveMetrics(),
        renderEditStreak(),
        renderActivityTrend(),
    ]);
}

// ── Event Listeners ─────────────────────────────────────

function setupEventListeners() {
    // Memory search
    const searchBtn = document.getElementById('memory-search-btn');
    const searchInput = document.getElementById('memory-search');
    searchBtn.addEventListener('click', () => {
        renderMemory(searchInput.value.trim());
    });
    searchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            renderMemory(searchInput.value.trim());
        }
    });

    // Memory graph toggle
    document.getElementById('memory-graph-toggle').addEventListener('click', () => {
        toggleMemoryGraph();
    });

    // Component tabs
    document.getElementById('component-tabs').addEventListener('click', (e) => {
        if (e.target.classList.contains('tab')) {
            renderComponentTab(e.target.dataset.tab);
        }
    });

    // Date selectors
    document.getElementById('gate-date-select').addEventListener('change', (e) => {
        renderGates(e.target.value);
    });
    document.getElementById('timeline-date-select').addEventListener('change', (e) => {
        renderTimeline(e.target.value);
    });

    // Gate performance refresh
    document.getElementById('gate-perf-refresh').addEventListener('click', () => {
        renderGatePerf();
    });

    // Timeline query filters
    document.getElementById('timeline-filter-btn').addEventListener('click', () => {
        applyTimelineFilters();
    });

    // Timeline tab switching
    document.querySelectorAll('#timeline-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchTimelineTab(tab.dataset.timelineTab);
        });
    });

    // Session comparison
    document.getElementById('compare-btn').addEventListener('click', () => {
        compareSessions();
    });

    // Notification badge — click to clear
    const notifBadge = document.getElementById('notification-badge');
    if (notifBadge) {
        notifBadge.addEventListener('click', () => {
            clearNotificationBadge();
        });
    }

    // Wire gate click → timeline filter
    setGateFilterCallback(filterTimelineByGate);
}

// ── Init ────────────────────────────────────────────────

async function init() {
    setupTheme();
    setupOverlay();
    setupEventListeners();
    setupPanelCollapse();
    setupPopoverClose();

    // Initial render — all panels in parallel
    const gatePerf = renderGatePerf();

    await Promise.all([
        renderHealth(),
        renderGates(),
        gatePerf.then(gates => {
            if (gates && Array.isArray(gates)) {
                populateGateFilterDropdown(gates.map(g => g.gate));
            }
        }),
        renderGateDeps(),
        renderTimeline(),
        renderLiveMetrics(),
        renderEditStreak(),
        renderActivityTrend(),
        renderMemory(''),
        renderMemoryTags(),
        renderMemoryHealth(),
        renderObservations(),
        renderErrors(),
        renderToolStats(),
        renderComponents(),
        renderHistory(),
        populateDateSelects(),
    ]);

    // Start SSE with callbacks
    connectSSE({
        onAuditEntry: (entry) => {
            prependTimelineEntry(entry);
        },
        onHealthUpdate: (data) => {
            recordHealthForSparkline(data.health_pct);
        },
        onGateEvent: () => {},
        onMemoryEvent: () => {},
        onErrorEvent: () => {
            renderErrors();
        },
    });

    // Start auto-refresh
    setupAutoRefresh(refreshAll);
}

// Boot
document.addEventListener('DOMContentLoaded', init);
