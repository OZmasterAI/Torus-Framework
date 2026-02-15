/**
 * Live Metrics Panel — metric cards with D3 sparklines
 */
import { apiFetch } from '../api.js';
import { escapeHtml, HEALTH_COLORS } from '../utils.js';

// Sparkline history stored in sessionStorage (48 points max)
const SPARKLINE_MAX = 48;

function getSparklineData(key) {
    try {
        const raw = sessionStorage.getItem(`sparkline_${key}`);
        return raw ? JSON.parse(raw) : [];
    } catch { return []; }
}

function pushSparklineData(key, value) {
    const arr = getSparklineData(key);
    arr.push(value);
    if (arr.length > SPARKLINE_MAX) arr.shift();
    try {
        sessionStorage.setItem(`sparkline_${key}`, JSON.stringify(arr));
    } catch { /* quota exceeded */ }
    return arr;
}

export function recordHealthForSparkline(healthPct) {
    pushSparklineData('hp', healthPct);
}

export async function renderLiveMetrics() {
    const data = await apiFetch('/api/live-metrics');
    if (!data) return;

    const el = document.getElementById('live-metrics-content');
    if (!el) return;

    const h = data.health || {};
    const s = data.session || {};
    const t = data.tools || {};
    const e = data.errors || {};
    const v = data.verification || {};
    const sub = data.subagents || {};
    const sk = data.skills || {};
    const hotspots = data.hotspots || {};

    const hpColor = HEALTH_COLORS[h.color] || HEALTH_COLORS.cyan;

    // Record sparkline data
    pushSparklineData('hp', h.hp || 0);
    pushSparklineData('errors', e.pressure || 0);
    pushSparklineData('gates', h.gates || 0);
    pushSparklineData('memories', h.memories || 0);

    // Format session age
    let ageStr = '—';
    if (s.age_min > 0) {
        if (s.age_min >= 60) {
            const hrs = Math.floor(s.age_min / 60);
            const mins = s.age_min % 60;
            ageStr = `${hrs}h ${mins}m`;
        } else {
            ageStr = `${s.age_min}m`;
        }
    }

    let metricsHtml = '<div class="live-metrics-grid">';

    // Row 1: Core session info
    metricsHtml += metricCard('HP', `${h.hp || 0}%`, hpColor, 'hp');
    metricsHtml += metricCard('Project', escapeHtml(s.project || '—'), 'var(--cyan)');
    metricsHtml += metricCard('Sessions', s.session_count || 0, 'var(--text-primary)');
    metricsHtml += metricCard('Age', ageStr, 'var(--text-primary)');
    metricsHtml += metricCard('Status', escapeHtml(s.status || '—'), s.status === 'active' ? 'var(--green)' : 'var(--text-muted)');

    // Row 2: Framework health
    metricsHtml += metricCard('Gates', h.gates || 0, 'var(--cyan)', 'gates');
    metricsHtml += metricCard('Memories', h.memories || 0, 'var(--green)', 'memories');
    metricsHtml += metricCard('Errors', e.pressure || 0, (e.pressure || 0) > 0 ? 'var(--red)' : 'var(--green)', 'errors');
    metricsHtml += metricCard('Plan Warns', data.plan_mode_warns || 0, (data.plan_mode_warns || 0) > 0 ? 'var(--yellow)' : 'var(--text-muted)');
    metricsHtml += metricCard('Verified', `${v.verified || 0}/${(v.verified || 0) + (v.pending || 0)}`, v.ratio >= 0.8 ? 'var(--green)' : v.ratio >= 0.5 ? 'var(--yellow)' : 'var(--red)');

    metricsHtml += '</div>';

    // Tool usage bars
    const toolStats = t.stats || {};
    const toolEntries = Object.entries(toolStats);
    if (toolEntries.length > 0) {
        const maxCount = Math.max(...toolEntries.map(([, c]) => c), 1);
        metricsHtml += '<div class="live-metrics-section">';
        metricsHtml += `<div class="live-metrics-section-label">Tools (${t.total_calls || 0} calls)</div>`;
        metricsHtml += toolEntries.slice(0, 10).map(([name, count]) => {
            const pct = maxCount > 0 ? (count / maxCount * 100) : 0;
            return `<div class="tool-stat-row">
                <span class="tool-stat-name">${escapeHtml(name)}</span>
                <div class="tool-stat-bar-bg">
                    <div class="tool-stat-bar" style="width:${pct}%"></div>
                </div>
                <span class="tool-stat-count">${count}</span>
            </div>`;
        }).join('');
        metricsHtml += '</div>';
    }

    // Subagents
    const activeSubagents = sub.active || [];
    if (activeSubagents.length > 0 || sub.total_tokens > 0) {
        metricsHtml += '<div class="live-metrics-section">';
        metricsHtml += '<div class="live-metrics-section-label">Subagents</div>';
        metricsHtml += '<div class="live-metrics-grid">';
        metricsHtml += metricCard('Active', activeSubagents.length, 'var(--cyan)');
        metricsHtml += metricCard('Tokens', sub.total_tokens || 0, 'var(--text-primary)');
        metricsHtml += '</div></div>';
    }

    // Edit streak hotspots + skill usage
    const hotspotEntries = Object.entries(hotspots);
    const skillEntries = Object.entries(sk.usage || {});
    if (hotspotEntries.length > 0 || skillEntries.length > 0) {
        metricsHtml += '<div class="live-metrics-section">';
        if (hotspotEntries.length > 0) {
            metricsHtml += '<div class="live-metrics-section-label">Edit Hotspots</div>';
            metricsHtml += '<div class="live-metrics-grid">';
            for (const [file, count] of hotspotEntries) {
                metricsHtml += metricCard(escapeHtml(file), `${count}x`, count >= 5 ? 'var(--red)' : 'var(--orange)');
            }
            metricsHtml += '</div>';
        }
        if (skillEntries.length > 0) {
            metricsHtml += '<div class="live-metrics-section-label">Skills Used</div>';
            metricsHtml += '<div class="live-metrics-grid">';
            for (const [name, count] of skillEntries.sort((a, b) => b[1] - a[1])) {
                metricsHtml += metricCard(`/${escapeHtml(name)}`, count, 'var(--cyan)');
            }
            metricsHtml += '</div>';
        }
        metricsHtml += '</div>';
    }

    // Active bans
    if (e.active_bans && e.active_bans.length > 0) {
        metricsHtml += '<div class="live-metrics-section">';
        metricsHtml += '<div class="live-metrics-section-label" style="color:var(--red)">Active Bans</div>';
        metricsHtml += e.active_bans.map(ban =>
            `<div class="ban-entry">${escapeHtml(typeof ban === 'string' ? ban : JSON.stringify(ban))}</div>`
        ).join('');
        metricsHtml += '</div>';
    }

    el.innerHTML = metricsHtml;

    // Render sparklines after DOM is updated
    requestAnimationFrame(() => {
        renderAllSparklines();
    });
}

function metricCard(label, value, valueColor, sparklineKey) {
    const sparklineHtml = sparklineKey
        ? `<div class="sparkline-container" id="sparkline-${sparklineKey}"></div>`
        : '';
    return `<div class="live-metric-card">
        <div class="live-metric-label">${label}</div>
        <div class="live-metric-value metric-pulse" style="color:${valueColor}">${value}</div>
        ${sparklineHtml}
    </div>`;
}

function renderAllSparklines() {
    if (typeof d3 === 'undefined') return;

    for (const key of ['hp', 'errors', 'gates', 'memories']) {
        const container = document.getElementById(`sparkline-${key}`);
        if (!container) continue;

        const data = getSparklineData(key);
        if (data.length < 2) continue;

        renderSparkline(container, data, key);
    }
}

function renderSparkline(container, data, key) {
    container.innerHTML = '';
    const w = 80, h = 24;

    const svg = d3.select(container)
        .append('svg')
        .attr('width', w)
        .attr('height', h);

    const x = d3.scaleLinear()
        .domain([0, data.length - 1])
        .range([1, w - 1]);

    const y = d3.scaleLinear()
        .domain([Math.min(...data) * 0.9, Math.max(...data) * 1.1 || 1])
        .range([h - 1, 1]);

    const line = d3.line()
        .x((d, i) => x(i))
        .y(d => y(d))
        .curve(d3.curveMonotoneX);

    const color = key === 'errors' ? 'var(--red)' :
                  key === 'hp' ? 'var(--cyan)' :
                  key === 'gates' ? 'var(--green)' : 'var(--yellow)';

    svg.append('path')
        .datum(data)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1.5)
        .attr('d', line);

    // Dot at last point
    svg.append('circle')
        .attr('cx', x(data.length - 1))
        .attr('cy', y(data[data.length - 1]))
        .attr('r', 2)
        .attr('fill', color);
}

// ── Tool Stats ───────────────────────────────────────────

export async function renderToolStats() {
    const el = document.getElementById('tool-stats-content');
    if (!el) return;
    try {
        const resp = await fetch('/api/tool-stats');
        const data = await resp.json();
        const stats = data.tool_stats || {};
        const entries = Object.entries(stats);
        if (entries.length === 0) {
            el.innerHTML = '<div class="no-data">No tool data yet</div>';
            return;
        }
        const maxCount = Math.max(...entries.map(([,v]) => v.count || 0));
        const html = entries.map(([name, info]) => {
            const count = info.count || 0;
            const pct = maxCount > 0 ? (count / maxCount * 100) : 0;
            return `<div class="tool-stat-row">
                <span class="tool-stat-name">${escapeHtml(name)}</span>
                <div class="tool-stat-bar-bg">
                    <div class="tool-stat-bar" style="width:${pct}%"></div>
                </div>
                <span class="tool-stat-count">${count}</span>
            </div>`;
        }).join('');
        el.innerHTML = `<div class="tool-stat-total">Total: ${data.total_calls} calls</div>${html}`;
    } catch (e) {
        el.innerHTML = '<div class="no-data">Failed to load</div>';
    }
}
