/**
 * Gate Statistics Panel — stacked bar chart + dependencies matrix
 */
import { apiFetch } from '../api.js';
import { escapeHtml } from '../utils.js';

let gateFilterCallback = null;

export function setGateFilterCallback(cb) {
    gateFilterCallback = cb;
}

export async function renderGates(date) {
    const dateParam = date ? `?date=${date}` : '';
    const data = await apiFetch(`/api/gates${dateParam}`);
    if (!data) return;

    const el = document.getElementById('gates-content');
    const gates = data.gates;

    if (!gates || Object.keys(gates).length === 0) {
        el.innerHTML = '<div class="no-data">No gate activity recorded for this date.</div>';
        return;
    }

    let html = '';
    for (const [name, stats] of Object.entries(gates)) {
        const total = stats.total || 1;
        const pPass = (stats.pass / total * 100).toFixed(0);
        const pWarn = (stats.warn / total * 100).toFixed(0);
        const pBlock = (stats.block / total * 100).toFixed(0);
        const shortName = name.replace('GATE ', 'G');
        html += `
            <div class="gate-row" title="${escapeHtml(name)}" data-gate-name="${escapeHtml(name)}">
                <span class="gate-name">${escapeHtml(shortName)}</span>
                <div class="gate-bar-container">
                    <div class="gate-bar-pass" style="width:${pPass}%"></div>
                    <div class="gate-bar-warn" style="width:${pWarn}%"></div>
                    <div class="gate-bar-block" style="width:${pBlock}%"></div>
                </div>
                <span class="gate-counts">${stats.pass}/${stats.warn}/${stats.block}</span>
            </div>`;
    }
    el.innerHTML = html;

    // Attach click handlers
    el.querySelectorAll('.gate-row').forEach(row => {
        row.addEventListener('click', () => {
            const gateName = row.dataset.gateName;
            if (gateFilterCallback) gateFilterCallback(gateName);
        });
    });
}

export async function renderGatePerf() {
    const data = await apiFetch('/api/gate-perf');
    if (!data) return;

    const el = document.getElementById('gate-perf-content');
    const gates = data.gates || [];

    if (gates.length === 0) {
        el.innerHTML = '<div class="no-data">No gate performance data available.</div>';
        return gates;
    }

    // D3 horizontal stacked bar chart
    if (typeof d3 !== 'undefined' && gates.length > 0) {
        renderGatePerfChart(el, gates);
    } else {
        renderGatePerfTable(el, gates);
    }

    return gates;
}

function renderGatePerfChart(el, gates) {
    el.innerHTML = '';
    const margin = { top: 4, right: 50, left: 100, bottom: 4 };
    const rowHeight = 20;
    const width = el.clientWidth || 400;
    const height = gates.length * rowHeight + margin.top + margin.bottom;
    const innerWidth = width - margin.left - margin.right;

    const svg = d3.select(el)
        .append('svg')
        .attr('width', width)
        .attr('height', height)
        .style('overflow', 'visible');

    const g = svg.append('g')
        .attr('transform', `translate(${margin.left},${margin.top})`);

    const maxTotal = Math.max(...gates.map(g => g.total), 1);

    const x = d3.scaleLinear().domain([0, maxTotal]).range([0, innerWidth]);
    const y = d3.scaleBand()
        .domain(gates.map(g => g.gate))
        .range([0, gates.length * rowHeight])
        .padding(0.25);

    const categories = ['pass', 'warn', 'block'];
    const colors = {
        pass: 'var(--green)',
        warn: 'var(--yellow)',
        block: 'var(--red)',
    };

    // Stack data
    gates.forEach(gate => {
        let cumX = 0;
        for (const cat of categories) {
            const val = gate[cat] || 0;
            g.append('rect')
                .attr('x', x(cumX))
                .attr('y', y(gate.gate))
                .attr('width', Math.max(0, x(val)))
                .attr('height', y.bandwidth())
                .attr('fill', colors[cat])
                .attr('rx', 2)
                .style('opacity', 0.85);
            cumX += val;
        }
    });

    // Labels on left
    g.selectAll('.gate-label')
        .data(gates)
        .enter()
        .append('text')
        .attr('x', -6)
        .attr('y', d => y(d.gate) + y.bandwidth() / 2)
        .attr('dy', '0.35em')
        .attr('text-anchor', 'end')
        .style('font-size', '10px')
        .style('font-family', 'var(--font-mono)')
        .style('fill', 'var(--text-secondary)')
        .text(d => d.gate.replace('GATE ', 'G'));

    // Counts on right
    g.selectAll('.gate-count')
        .data(gates)
        .enter()
        .append('text')
        .attr('x', d => x(d.total) + 6)
        .attr('y', d => y(d.gate) + y.bandwidth() / 2)
        .attr('dy', '0.35em')
        .attr('text-anchor', 'start')
        .style('font-size', '10px')
        .style('font-family', 'var(--font-mono)')
        .style('fill', 'var(--text-muted)')
        .text(d => `${d.block_rate}%`);
}

function renderGatePerfTable(el, gates) {
    let html = '<table class="gate-perf-table"><thead><tr>' +
        '<th>Gate</th><th>Pass</th><th>Block</th><th>Warn</th><th>Block Rate</th>' +
        '</tr></thead><tbody>';

    for (const g of gates) {
        const rateClass = g.block_rate > 30 ? 'rate-high' :
                          g.block_rate > 10 ? 'rate-med' : 'rate-low';
        const shortName = g.gate.replace('GATE ', 'G');
        html += `<tr>
            <td class="gate-perf-name" title="${escapeHtml(g.gate)}">${escapeHtml(shortName)}</td>
            <td class="color-green">${g.pass}</td>
            <td class="color-red">${g.block}</td>
            <td class="color-yellow">${g.warn}</td>
            <td class="${rateClass}">${g.block_rate}%</td>
        </tr>`;
    }
    html += '</tbody></table>';
    el.innerHTML = html;
}

export function populateGateFilterDropdown(gateNames) {
    const select = document.getElementById('timeline-gate-filter');
    if (!select) return;
    while (select.options.length > 1) select.remove(1);
    for (const name of gateNames) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name.replace('GATE ', 'G');
        select.appendChild(opt);
    }
}

export async function renderGateDeps() {
    const data = await apiFetch('/api/gate-deps');
    if (!data) return;

    const el = document.getElementById('gate-deps-content');
    if (!el) return;
    const deps = data.dependencies || {};
    const gateNames = Object.keys(deps).sort();

    if (gateNames.length === 0) {
        el.innerHTML = '<div class="no-data">No gate dependency data available.</div>';
        return;
    }

    const stateKeys = new Set();
    for (const gate of gateNames) {
        const d = deps[gate];
        (d.reads || []).forEach(k => stateKeys.add(k));
        (d.writes || []).forEach(k => stateKeys.add(k));
    }
    const stateKeysList = Array.from(stateKeys).sort();

    if (stateKeysList.length === 0) {
        el.innerHTML = '<div class="no-data">No state key dependencies found.</div>';
        return;
    }

    let html = '<table class="gate-dep-matrix"><thead><tr><th>Gate</th>';
    for (const key of stateKeysList) {
        html += `<th title="${escapeHtml(key)}">${escapeHtml(key)}</th>`;
    }
    html += '</tr></thead><tbody>';

    for (const gate of gateNames) {
        const d = deps[gate];
        const reads = new Set(d.reads || []);
        const writes = new Set(d.writes || []);
        const shortName = gate.replace('gate_', 'G').replace(/_/g, ' ');
        html += `<tr><td class="gate-dep-name" title="${escapeHtml(gate)}">${escapeHtml(shortName)}</td>`;

        for (const key of stateKeysList) {
            const isRead = reads.has(key);
            const isWrite = writes.has(key);
            let cellContent = '';
            if (isRead && isWrite) {
                cellContent = '<span class="dep-read"></span><span class="dep-write"></span>';
            } else if (isRead) {
                cellContent = '<span class="dep-read"></span>';
            } else if (isWrite) {
                cellContent = '<span class="dep-write"></span>';
            }
            html += `<td class="dep-cell">${cellContent}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table>';
    html += '<div class="gate-dep-legend">';
    html += '<span class="legend-item"><span class="dep-read"></span> Reads</span>';
    html += '<span class="legend-item"><span class="dep-write"></span> Writes</span>';
    html += '</div>';
    el.innerHTML = html;
}
