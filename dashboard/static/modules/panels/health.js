/**
 * Health Panel — Radial D3 gauge + dimension bars
 */
import { apiFetch } from '../api.js';
import { escapeHtml, HEALTH_COLORS } from '../utils.js';

let gaugeInitialized = false;

export async function renderHealth() {
    const data = await apiFetch('/api/health');
    if (!data) return;

    const pct = data.health_pct;
    const color = HEALTH_COLORS[data.color] || HEALTH_COLORS.cyan;

    // Update header bar
    const headerFill = document.getElementById('header-bar-fill');
    if (headerFill) {
        headerFill.style.width = `${pct}%`;
        headerFill.style.background = color;
    }
    const hpEl = document.getElementById('header-hp');
    if (hpEl) {
        hpEl.textContent = `HP: ${pct}%`;
        hpEl.style.color = color;
    }
    const projEl = document.getElementById('header-project');
    if (projEl) projEl.textContent = data.project || 'unknown';
    const sessEl = document.getElementById('header-session');
    if (sessEl) sessEl.textContent = `S:${data.session_count}`;

    // Render health panel
    const el = document.getElementById('health-content');
    if (!el) return;

    // Build dimension bars HTML
    let dimHtml = '';
    if (data.dimensions) {
        for (const [name, dim] of Object.entries(data.dimensions)) {
            const dimPct = Math.round(dim.score * 100);
            const dimColor = dimPct >= 90 ? HEALTH_COLORS.green :
                           dimPct >= 75 ? HEALTH_COLORS.orange :
                           dimPct >= 50 ? HEALTH_COLORS.yellow : HEALTH_COLORS.red;
            dimHtml += `
                <div class="dimension-row">
                    <span class="dimension-label">${escapeHtml(name)}</span>
                    <div class="dimension-bar">
                        <div class="bar-fill" style="width:${dimPct}%; background:${dimColor}"></div>
                    </div>
                    <span class="dimension-value">${dimPct}%</span>
                </div>`;
        }
    }

    // Radial gauge with D3 + dimension bars side-by-side
    el.innerHTML = `
        <div class="health-layout">
            <div class="radial-gauge" id="health-radial-gauge"></div>
            <div class="health-right">
                <div class="health-stats">
                    G:${data.gate_count} | M:${data.mem_count} | ${escapeHtml(data.status || '')}
                </div>
                <div class="dimension-list">${dimHtml}</div>
            </div>
        </div>`;

    renderRadialGauge(pct, color);
}

function renderRadialGauge(pct, color) {
    const container = document.getElementById('health-radial-gauge');
    if (!container || typeof d3 === 'undefined') {
        // Fallback if D3 not loaded
        if (container) {
            container.innerHTML = `<div class="health-big">
                <div class="health-big-pct" style="color:${color}">${pct}%</div>
            </div>`;
        }
        return;
    }

    const size = 140;
    const thickness = 14;
    const radius = size / 2;
    const innerRadius = radius - thickness;

    container.innerHTML = '';

    const svg = d3.select(container)
        .append('svg')
        .attr('width', size)
        .attr('height', size)
        .append('g')
        .attr('transform', `translate(${radius},${radius})`);

    // Glow filter
    const defs = svg.append('defs');
    const filter = defs.append('filter').attr('id', 'gauge-glow');
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'blur');
    filter.append('feMerge')
        .selectAll('feMergeNode')
        .data(['blur', 'SourceGraphic'])
        .enter()
        .append('feMergeNode')
        .attr('in', d => d);

    const arc = d3.arc()
        .innerRadius(innerRadius)
        .outerRadius(radius)
        .startAngle(0)
        .cornerRadius(2);

    // Background track
    svg.append('path')
        .datum({ endAngle: Math.PI * 2 })
        .style('fill', 'rgba(255,255,255,0.05)')
        .attr('d', arc);

    // Foreground arc — animated
    const foreground = svg.append('path')
        .datum({ endAngle: 0 })
        .style('fill', color)
        .style('filter', 'url(#gauge-glow)')
        .attr('d', arc);

    const targetAngle = (pct / 100) * Math.PI * 2;

    foreground.transition()
        .duration(1200)
        .ease(d3.easeCubicOut)
        .attrTween('d', function(d) {
            const interpolate = d3.interpolate(d.endAngle, targetAngle);
            return function(t) {
                d.endAngle = interpolate(t);
                return arc(d);
            };
        });

    // Center text
    svg.append('text')
        .attr('text-anchor', 'middle')
        .attr('dy', '0.1em')
        .style('font-size', '28px')
        .style('font-weight', '800')
        .style('font-family', 'var(--font-mono)')
        .style('fill', color)
        .text(`${pct}%`);
}
