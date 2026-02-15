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

// ── Edit Streak Hotspots ─────────────────────────────────

export async function renderEditStreak() {
    const data = await apiFetch('/api/edit-streak');
    if (!data) return;

    const hotspots = data.hotspots || [];
    const riskLevel = data.risk_level || 'ok';

    // Find or create the hotspot section inside live-metrics panel
    let section = document.getElementById('edit-streak-section');
    if (!section) return;

    if (hotspots.length === 0) {
        section.innerHTML = '<div class="no-data">No edit hotspots detected.</div>';
        return;
    }

    const riskColor = riskLevel === 'danger' ? 'var(--red)' :
                      riskLevel === 'warning' ? 'var(--orange)' : 'var(--green)';

    let html = `<div class="streak-header">
        <span class="streak-risk" style="color:${riskColor}">${escapeHtml(riskLevel.toUpperCase())}</span>
        <span class="streak-total">${data.total_files || 0} files touched</span>
    </div>`;
    html += '<div class="streak-list">';

    const maxCount = Math.max(...hotspots.map(h => h.count), 1);
    for (const spot of hotspots) {
        const pct = (spot.count / maxCount * 100).toFixed(0);
        const barColor = spot.count >= 5 ? 'var(--red)' : spot.count >= 3 ? 'var(--orange)' : 'var(--cyan)';
        html += `<div class="streak-row">
            <span class="streak-file" title="${escapeHtml(spot.path)}">${escapeHtml(spot.file)}</span>
            <div class="streak-bar-bg">
                <div class="streak-bar" style="width:${pct}%;background:${barColor}"></div>
            </div>
            <span class="streak-count">${spot.count}x</span>
        </div>`;
    }
    html += '</div>';
    section.innerHTML = html;
}

// ── Activity Trend Chart ─────────────────────────────────

export async function renderActivityTrend() {
    const data = await apiFetch('/api/activity-trend');
    if (!data) return;

    const el = document.getElementById('activity-trend-content');
    if (!el) return;

    const buckets = data.buckets || [];
    if (buckets.length === 0 || typeof d3 === 'undefined') {
        el.innerHTML = '<div class="no-data">No activity data yet.</div>';
        return;
    }

    // Filter to buckets with any activity, but keep all for time continuity
    const hasActivity = buckets.some(b => b.total > 0);
    if (!hasActivity) {
        el.innerHTML = '<div class="no-data">No gate activity in the last 24h.</div>';
        return;
    }

    el.innerHTML = '';
    const margin = { top: 8, right: 12, bottom: 24, left: 32 };
    const width = el.clientWidth || 500;
    const height = 100;
    const innerWidth = width - margin.left - margin.right;
    const innerHeight = height - margin.top - margin.bottom;

    const svg = d3.select(el)
        .append('svg')
        .attr('width', width)
        .attr('height', height);

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const x = d3.scaleBand()
        .domain(buckets.map((_, i) => i))
        .range([0, innerWidth])
        .padding(0.15);

    const maxTotal = Math.max(...buckets.map(b => b.total), 1);
    const y = d3.scaleLinear()
        .domain([0, maxTotal])
        .range([innerHeight, 0]);

    // Stacked bars: pass (green) + warn (yellow) + block (red)
    const categories = [
        { key: 'pass', color: 'var(--green)' },
        { key: 'warn', color: 'var(--yellow)' },
        { key: 'block', color: 'var(--red)' },
    ];

    buckets.forEach((bucket, i) => {
        let cumY = 0;
        for (const cat of categories) {
            const val = bucket[cat.key] || 0;
            if (val > 0) {
                g.append('rect')
                    .attr('x', x(i))
                    .attr('y', y(cumY + val))
                    .attr('width', x.bandwidth())
                    .attr('height', Math.max(0, y(cumY) - y(cumY + val)))
                    .attr('fill', cat.color)
                    .attr('rx', 1)
                    .style('opacity', 0.8);
            }
            cumY += val;
        }
    });

    // X-axis: show every 4th time label
    const timeFormat = (idx) => {
        const b = buckets[idx];
        if (!b || !b.time) return '';
        const d = new Date(b.time);
        return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit' });
    };

    g.append('g')
        .attr('transform', `translate(0,${innerHeight})`)
        .call(d3.axisBottom(x)
            .tickValues(buckets.map((_, i) => i).filter(i => i % 8 === 0))
            .tickFormat(timeFormat))
        .selectAll('text')
        .style('font-size', '8px')
        .style('fill', 'var(--text-muted)');

    // Y-axis
    g.append('g')
        .call(d3.axisLeft(y).ticks(3).tickSize(-innerWidth))
        .selectAll('text')
        .style('font-size', '8px')
        .style('fill', 'var(--text-muted)');

    // Style grid lines
    g.selectAll('.tick line')
        .style('stroke', 'var(--border)')
        .style('stroke-opacity', 0.5);
    g.selectAll('.domain')
        .style('stroke', 'var(--border)');
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
