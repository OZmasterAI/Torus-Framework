/**
 * SSE (Server-Sent Events) connection and notification badge module.
 * Handles real-time event streaming from the dashboard server.
 */

import { showToast } from './utils.js';
import { HEALTH_COLORS } from './utils.js';

const API = '';  // Same origin

let sseSource = null;
let notificationCount = 0;

// ── Notification Badge ──────────────────────────────────

export function incrementNotificationBadge() {
    notificationCount++;
    const badge = document.getElementById('notification-badge');
    if (badge) {
        badge.textContent = notificationCount > 99 ? '99+' : notificationCount;
        badge.classList.remove('hidden');
    }
}

export function clearNotificationBadge() {
    notificationCount = 0;
    const badge = document.getElementById('notification-badge');
    if (badge) {
        badge.textContent = '0';
        badge.classList.add('hidden');
    }
}

// ── SSE Connection ──────────────────────────────────────

/**
 * Connect to the SSE stream. Callbacks are invoked when specific events arrive,
 * allowing the main module to update panels without circular imports.
 *
 * @param {Object} callbacks
 * @param {Function} callbacks.onAuditEntry  - Called with parsed audit entry object
 * @param {Function} callbacks.onHealthUpdate - Called with parsed health data object
 * @param {Function} callbacks.onGateEvent   - Called with parsed gate event object
 * @param {Function} callbacks.onMemoryEvent - Called with parsed memory event object
 * @param {Function} callbacks.onErrorEvent  - Called with parsed error event object
 */
export function connectSSE({ onAuditEntry, onHealthUpdate, onGateEvent, onMemoryEvent, onErrorEvent } = {}) {
    if (sseSource) {
        sseSource.close();
    }

    const indicator = document.getElementById('live-indicator');

    try {
        sseSource = new EventSource(`${API}/api/stream`);

        sseSource.onopen = () => {
            indicator.classList.remove('off');
            indicator.classList.add('on');
        };

        sseSource.addEventListener('audit', (e) => {
            try {
                const entry = JSON.parse(e.data);
                if (onAuditEntry) onAuditEntry(entry);
            } catch {}
        });

        sseSource.addEventListener('health', (e) => {
            try {
                const data = JSON.parse(e.data);
                const color = HEALTH_COLORS[data.color] || HEALTH_COLORS.cyan;
                const fill = document.getElementById('header-bar-fill');
                fill.style.width = `${data.health_pct}%`;
                fill.style.background = color;
                document.getElementById('header-hp').textContent = `HP: ${data.health_pct}%`;
                document.getElementById('header-hp').style.color = color;
                if (onHealthUpdate) onHealthUpdate(data);
            } catch {}
        });

        // Handle gate_event: flash gate row, increment counter, show toast
        sseSource.addEventListener('gate_event', (e) => {
            try {
                const data = JSON.parse(e.data);
                const decision = data.decision || '';
                const gate = data.gate || '';
                const shortGate = gate.replace('GATE ', 'G');

                // Show toast for blocks/warns
                if (decision === 'block') {
                    showToast(`Gate blocked: ${shortGate} [${data.tool || ''}]`, 'error');
                } else if (decision === 'warn') {
                    showToast(`Gate warning: ${shortGate}`, 'info');
                }

                // Increment notification badge
                incrementNotificationBadge();

                // Flash the matching gate row in the Gates panel
                const gateRows = document.querySelectorAll('.gate-row');
                for (const row of gateRows) {
                    if (row.title && row.title.includes(gate)) {
                        row.classList.add('gate-flash');
                        setTimeout(() => row.classList.remove('gate-flash'), 1500);
                        break;
                    }
                }

                if (onGateEvent) onGateEvent(data);
            } catch {}
        });

        // Handle memory_event: show toast notification
        sseSource.addEventListener('memory_event', (e) => {
            try {
                const data = JSON.parse(e.data);
                const delta = data.delta || 1;
                showToast(`Memory saved (${data.new_count} total, +${delta})`, 'info');
                incrementNotificationBadge();

                // Update memory total badge if visible
                const memTotal = document.getElementById('memory-total');
                if (memTotal) {
                    memTotal.textContent = data.new_count;
                }

                if (onMemoryEvent) onMemoryEvent(data);
            } catch {}
        });

        // Handle error_event: highlight in Error Patterns panel
        sseSource.addEventListener('error_event', (e) => {
            try {
                const data = JSON.parse(e.data);
                showToast(`Error pressure increased: ${data.error_pressure} (+${data.delta})`, 'error');
                incrementNotificationBadge();

                // Flash the errors panel
                const errPanel = document.getElementById('panel-errors');
                if (errPanel) {
                    errPanel.classList.add('panel-flash-error');
                    setTimeout(() => errPanel.classList.remove('panel-flash-error'), 2000);
                }

                if (onErrorEvent) onErrorEvent(data);
            } catch {}
        });

        sseSource.onerror = () => {
            indicator.classList.remove('on');
            indicator.classList.add('off');
            // Auto-reconnect after 5s
            setTimeout(() => {
                if (sseSource.readyState === EventSource.CLOSED) {
                    connectSSE({ onAuditEntry, onHealthUpdate, onGateEvent, onMemoryEvent, onErrorEvent });
                }
            }, 5000);
        };
    } catch {
        indicator.classList.remove('on');
        indicator.classList.add('off');
    }
}
