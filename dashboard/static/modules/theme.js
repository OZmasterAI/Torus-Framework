/**
 * Theme, panel collapse, and auto-refresh module.
 * Manages UI chrome behaviors with localStorage persistence.
 */

const REFRESH_INTERVAL = 30000; // 30s auto-refresh

let autoRefreshTimer = null;

// ── Theme Toggle ────────────────────────────────────────

export function setupTheme() {
    const saved = localStorage.getItem('dashboard-theme');
    if (saved === 'light') {
        document.documentElement.dataset.theme = 'light';
    }
    updateThemeIcon();

    document.getElementById('theme-toggle').addEventListener('click', () => {
        const current = document.documentElement.dataset.theme;
        const next = current === 'light' ? 'dark' : 'light';
        if (next === 'dark') {
            delete document.documentElement.dataset.theme;
        } else {
            document.documentElement.dataset.theme = next;
        }
        localStorage.setItem('dashboard-theme', next);
        updateThemeIcon();
    });
}

export function updateThemeIcon() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const isLight = document.documentElement.dataset.theme === 'light';
    btn.innerHTML = isLight ? '&#9728;' : '&#9790;';
    btn.title = isLight ? 'Switch to dark theme' : 'Switch to light theme';
}

// ── Panel Collapse ──────────────────────────────────────

export function setupPanelCollapse() {
    document.querySelectorAll('.card h2').forEach(h2 => {
        // Don't add if already has a collapse button
        if (h2.querySelector('.panel-collapse-btn')) return;
        const btn = document.createElement('button');
        btn.className = 'panel-collapse-btn';
        btn.innerHTML = '&#9660;';
        btn.title = 'Collapse/Expand';
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            h2.closest('.card').classList.toggle('collapsed');
        });
        h2.appendChild(btn);
    });
}

// ── Auto Refresh ────────────────────────────────────────

export function setupAutoRefresh(refreshAll) {
    const cb = document.getElementById('auto-refresh-cb');

    // Restore from localStorage
    const savedPref = localStorage.getItem('dashboardAutoRefresh');
    if (savedPref === 'off') {
        cb.checked = false;
    } else {
        cb.checked = true;
    }

    cb.addEventListener('change', () => {
        // Save to localStorage
        localStorage.setItem('dashboardAutoRefresh', cb.checked ? 'on' : 'off');

        if (cb.checked) {
            startAutoRefresh(refreshAll);
        } else {
            stopAutoRefresh();
        }
    });

    // Start auto-refresh if checkbox is checked
    if (cb.checked) {
        startAutoRefresh(refreshAll);
    }
}

export function startAutoRefresh(refreshAll) {
    stopAutoRefresh();
    autoRefreshTimer = setInterval(() => {
        refreshAll();
    }, REFRESH_INTERVAL);
}

export function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}
