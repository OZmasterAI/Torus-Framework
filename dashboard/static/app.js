/**
 * Self-Healing Claude Framework — Dashboard Client
 *
 * Fetches data from the server API, renders 7 panels, and connects
 * to the SSE stream for real-time audit event updates.
 */

// ── Config ──────────────────────────────────────────────

const API = '';  // Same origin
const REFRESH_INTERVAL = 30000; // 30s auto-refresh
const HEALTH_COLORS = {
    cyan:   '#00d2ff',
    green:  '#4ade80',
    orange: '#fb923c',
    yellow: '#facc15',
    red:    '#f87171',
};

// ── State ───────────────────────────────────────────────

let autoRefreshTimer = null;
let sseSource = null;
let componentData = null;
let activeComponentTab = 'gates';
let activeGateFilter = null;
let cachedTimelineEntries = [];

// ── Fetch Helper ────────────────────────────────────────

async function apiFetch(path) {
    try {
        const res = await fetch(`${API}${path}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return await res.json();
    } catch (e) {
        console.error(`API error: ${path}`, e);
        showToast(`API error: ${path} — ${e.message}`, 'error');
        return null;
    }
}

// ── Time Helpers ────────────────────────────────────────

function formatTime(ts) {
    if (!ts) return '';
    try {
        const d = typeof ts === 'number' ?
            new Date(ts * 1000) :
            new Date(ts);
        return d.toLocaleTimeString('en-US', {hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit'});
    } catch {
        return '';
    }
}

function formatDate(ts) {
    if (!ts) return '';
    try {
        return new Date(ts).toLocaleDateString('en-US', {month: 'short', day: 'numeric'});
    } catch {
        return '';
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Markdown Renderer ──────────────────────────────────

function renderMarkdown(text) {
    if (!text) return '';
    const lines = text.split('\n');
    let html = '';
    let inCodeBlock = false;
    let codeBuffer = [];

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];

        // Code block toggle
        if (line.trimStart().startsWith('```')) {
            if (inCodeBlock) {
                html += `<pre><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`;
                codeBuffer = [];
                inCodeBlock = false;
            } else {
                inCodeBlock = true;
            }
            continue;
        }

        if (inCodeBlock) {
            codeBuffer.push(line);
            continue;
        }

        // Empty line
        if (line.trim() === '') {
            html += '<br>';
            continue;
        }

        let processed = line;

        // Headings
        if (/^### /.test(processed)) {
            html += `<h5>${escapeHtml(processed.slice(4))}</h5>`;
            continue;
        } else if (/^## /.test(processed)) {
            html += `<h4>${escapeHtml(processed.slice(3))}</h4>`;
            continue;
        } else if (/^# /.test(processed)) {
            html += `<h3>${escapeHtml(processed.slice(2))}</h3>`;
            continue;
        }

        // List items
        if (/^- /.test(processed.trimStart())) {
            // Collect consecutive list items
            let items = [processed.trimStart().slice(2)];
            while (i + 1 < lines.length && /^- /.test(lines[i + 1].trimStart())) {
                i++;
                items.push(lines[i].trimStart().slice(2));
            }
            html += '<ul>' + items.map(item => `<li>${inlineMarkdown(escapeHtml(item))}</li>`).join('') + '</ul>';
            continue;
        }

        // Regular paragraph with inline formatting
        html += `<p>${inlineMarkdown(escapeHtml(processed))}</p>`;
    }

    // Close unclosed code block
    if (inCodeBlock && codeBuffer.length > 0) {
        html += `<pre><code>${escapeHtml(codeBuffer.join('\n'))}</code></pre>`;
    }

    return html;
}

function inlineMarkdown(escaped) {
    // Bold: **text**
    escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    // Italic: *text*
    escaped = escaped.replace(/\*(.+?)\*/g, '<em>$1</em>');
    // Inline code: `text`
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');
    return escaped;
}

// ── Toast Notifications ────────────────────────────────

function showToast(message, type = 'error', severity = null) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    // Default severity based on type if not provided
    if (!severity) {
        severity = type === 'error' ? 'critical' : 'info';
    }

    const toast = document.createElement('div');
    toast.className = `toast toast-${type} toast-${severity}`;
    toast.textContent = message;

    container.appendChild(toast);

    // Auto-dismiss timeout based on severity
    const timeout = severity === 'critical' ? 8000 :
                    severity === 'warning' ? 5000 : 3000;

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, timeout);
}

// ── Health Panel ────────────────────────────────────────

async function renderHealth() {
    const data = await apiFetch('/api/health');
    if (!data) return;

    const pct = data.health_pct;
    const color = HEALTH_COLORS[data.color] || HEALTH_COLORS.cyan;

    // Update header
    const headerFill = document.getElementById('header-bar-fill');
    headerFill.style.width = `${pct}%`;
    headerFill.style.background = color;
    document.getElementById('header-hp').textContent = `HP: ${pct}%`;
    document.getElementById('header-hp').style.color = color;
    document.getElementById('header-project').textContent = data.project || 'unknown';
    document.getElementById('header-session').textContent = `S:${data.session_count}`;

    // Render health panel
    const el = document.getElementById('health-content');
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
                    <span class="dimension-value">${dimPct}% (${dim.weight}w)</span>
                </div>`;
        }
    }

    el.innerHTML = `
        <div class="health-big">
            <div class="health-big-pct" style="color:${color}">${pct}%</div>
            <div class="health-bar-big">
                <div class="bar-fill" style="width:${pct}%; background:${color}"></div>
            </div>
            <div style="color:var(--text-muted); font-size:12px; margin-top:4px;">
                G:${data.gate_count} | M:${data.mem_count} | ${data.status}
            </div>
        </div>
        <div class="dimension-list">${dimHtml}</div>`;
}

// ── Gate Statistics ─────────────────────────────────────

async function renderGates(date) {
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
        // Short name: "GATE 1: READ BEFORE EDIT" -> "G1: READ..."
        const shortName = name.replace('GATE ', 'G');
        html += `
            <div class="gate-row" title="${escapeHtml(name)}" onclick="filterTimelineByGate('${escapeHtml(name)}')">
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
}

// ── Timeline ────────────────────────────────────────────

async function renderTimeline(date) {
    const dateParam = date ? `?date=${date}&limit=300` : '?limit=300';
    const data = await apiFetch(`/api/audit${dateParam}`);
    if (!data) return;

    cachedTimelineEntries = data.entries || [];
    document.getElementById('timeline-count').textContent = data.total;

    renderFilteredTimeline();
}

function renderFilteredTimeline() {
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
}

function renderTimelineEntry(entry) {
    const time = formatTime(entry.ts || entry.timestamp);
    let badge, text;

    if (entry.type === 'gate') {
        const dec = entry.decision;
        const badgeClass = dec === 'pass' ? 'badge-pass' :
                          dec === 'block' ? 'badge-block' : 'badge-warn';
        badge = `<span class="timeline-badge ${badgeClass}">${dec}</span>`;
        const reason = entry.reason ? ` — ${entry.reason}` : '';
        text = `${entry.gate} [${entry.tool}]${reason}`;
    } else {
        const evt = entry.event || '';
        const isError = evt === 'PostToolUseFailure';
        const badgeClass = isError ? 'badge-error' : 'badge-event';
        badge = `<span class="timeline-badge ${badgeClass}">${evt.substring(0, 12)}</span>`;
        const d = entry.data || {};
        text = Object.entries(d).map(([k, v]) => `${k}:${v}`).join(' ');
    }

    return `
        <div class="timeline-entry">
            <span class="timeline-time">${time}</span>
            ${badge}
            <span class="timeline-text">${escapeHtml(text)}</span>
        </div>`;
}

function prependTimelineEntry(entry) {
    const el = document.getElementById('timeline-content');
    // Don't prepend if showing "Loading..." or "No data"
    if (el.querySelector('.loading') || el.querySelector('.no-data')) {
        el.innerHTML = '';
    }
    const html = renderTimelineEntry(entry);
    el.insertAdjacentHTML('afterbegin', html);

    // Update count
    const countEl = document.getElementById('timeline-count');
    const current = parseInt(countEl.textContent) || 0;
    countEl.textContent = current + 1;

    // Limit DOM entries to prevent memory issues
    const children = el.querySelectorAll('.timeline-entry');
    if (children.length > 500) {
        for (let i = 500; i < children.length; i++) {
            children[i].remove();
        }
    }
}

// ── Gate Filter ─────────────────────────────────────────

function filterTimelineByGate(gateName) {
    activeGateFilter = gateName;
    renderFilteredTimeline();

    // Show filter badge
    const badge = document.getElementById('gate-filter-badge');
    if (badge) {
        badge.innerHTML = `${escapeHtml(gateName)} <span class="filter-badge-x" onclick="event.stopPropagation(); clearGateFilter()">&times;</span>`;
        badge.classList.remove('hidden');
    }

    // Scroll timeline into view
    const timeline = document.getElementById('panel-timeline');
    if (timeline) timeline.scrollIntoView({ behavior: 'smooth' });
}

function clearGateFilter() {
    activeGateFilter = null;
    renderFilteredTimeline();

    const badge = document.getElementById('gate-filter-badge');
    if (badge) {
        badge.classList.add('hidden');
        badge.innerHTML = '';
    }
}

// ── Memory Browser ──────────────────────────────────────

async function renderMemory(query) {
    const qParam = query ? `?q=${encodeURIComponent(query)}&limit=30` : '?limit=30';
    const data = await apiFetch(`/api/memories${qParam}`);
    if (!data) return;

    const el = document.getElementById('memory-content');
    document.getElementById('memory-total').textContent = data.total || 0;

    if (!data.results || data.results.length === 0) {
        el.innerHTML = '<div class="no-data">No memories found.</div>';
        return;
    }

    el.innerHTML = data.results.map(m => `
        <div class="memory-entry" onclick="showMemoryDetail('${escapeHtml(m.id)}')">
            <div class="memory-preview">${escapeHtml(m.preview || '(no preview)')}</div>
            <div class="memory-meta">
                <span>${escapeHtml(m.tags || '')}</span>
                <span>${formatDate(m.timestamp)}</span>
                ${m.relevance !== undefined ? `<span>rel: ${m.relevance}</span>` : ''}
            </div>
        </div>`).join('');
}

async function renderMemoryTags() {
    const data = await apiFetch('/api/memories/tags');
    if (!data || !data.tags) return;

    const el = document.getElementById('memory-tags');
    const entries = Object.entries(data.tags).slice(0, 30); // Top 30 tags
    el.innerHTML = entries.map(([tag, count]) =>
        `<span class="tag-pill" onclick="searchMemoryByTag('${escapeHtml(tag)}')">${escapeHtml(tag)}<span class="tag-count">${count}</span></span>`
    ).join('');
}

async function renderMemoryHealth() {
    const data = await apiFetch('/api/memory-health');
    if (!data) return;

    const el = document.getElementById('memory-health-content');
    if (!el) return;

    const score = data.health_score || 0;
    const scoreColor = score > 70 ? 'var(--green)' : (score > 40 ? 'var(--yellow)' : 'var(--red)');
    const label = data.health_label || 'unknown';

    let topTagsHtml = '';
    if (data.top_tags && data.top_tags.length > 0) {
        topTagsHtml = data.top_tags.map(t =>
            `<span class="health-tag">${escapeHtml(t.tag)} <span class="tag-count">${t.count}</span></span>`
        ).join('');
    }

    const staleWarning = (data.stale_count || 0) > 20
        ? `<span class="health-stale-warn">! ${data.stale_count} stale</span>`
        : `<span class="health-stale-ok">${data.stale_count || 0} stale</span>`;

    el.innerHTML = `
        <div class="health-gauge">
            <div class="health-gauge-score" style="color:${scoreColor}">${score}</div>
            <div class="health-gauge-label" style="color:${scoreColor}">${escapeHtml(label)}</div>
        </div>
        <div class="health-metrics">
            <div class="health-metric-row">
                <span class="health-metric-label">Growth</span>
                <span class="health-metric-value">${data.growth_rate_per_day || 0}/day</span>
            </div>
            <div class="health-metric-row">
                <span class="health-metric-label">24h / 7d / 30d</span>
                <span class="health-metric-value">${data.added_24h || 0} / ${data.added_7d || 0} / ${data.added_30d || 0}</span>
            </div>
            <div class="health-metric-row">
                <span class="health-metric-label">Avg Retrieval</span>
                <span class="health-metric-value">${data.avg_retrieval_count || 0}</span>
            </div>
            <div class="health-metric-row">
                <span class="health-metric-label">Stale</span>
                <span class="health-metric-value">${staleWarning}</span>
            </div>
            <div class="health-metric-row">
                <span class="health-metric-label">Tags</span>
                <span class="health-metric-value">${data.unique_tags || 0} unique</span>
            </div>
        </div>
        ${topTagsHtml ? `<div class="health-top-tags">${topTagsHtml}</div>` : ''}
    `;
}

async function showMemoryDetail(id) {
    const data = await apiFetch(`/api/memories/${id}`);
    if (!data || data.error) return;

    document.getElementById('overlay-title').textContent = `Memory: ${id}`;
    const body = document.getElementById('overlay-body');
    const metaHtml = `<div class="memory-detail-meta">
        <div><strong>Context:</strong> ${escapeHtml(data.context || '—')}</div>
        <div><strong>Tags:</strong> ${escapeHtml(data.tags || '—')}</div>
        <div><strong>Timestamp:</strong> ${escapeHtml(data.timestamp || '—')}</div>
    </div><hr style="border-color:var(--border); margin:12px 0;">`;
    body.innerHTML = metaHtml + renderMarkdown(data.content || '');
    document.getElementById('detail-overlay').classList.remove('hidden');
}

function searchMemoryByTag(tag) {
    const input = document.getElementById('memory-search');
    input.value = tag;
    renderMemory(tag);
}

// ── Memory Tag Graph ────────────────────────────────────

let memoryGraphVisible = false;
let graphAnimationId = null;

function toggleMemoryGraph() {
    memoryGraphVisible = !memoryGraphVisible;
    const container = document.getElementById('memory-graph-container');
    const listView = document.getElementById('memory-content');
    const searchBar = document.getElementById('memory-search-bar');
    const tagCloud = document.getElementById('memory-tags');
    const btn = document.getElementById('memory-graph-toggle');

    if (memoryGraphVisible) {
        container.classList.remove('hidden');
        listView.style.display = 'none';
        searchBar.style.display = 'none';
        tagCloud.style.display = 'none';
        btn.classList.add('active');
        renderMemoryGraph();
    } else {
        container.classList.add('hidden');
        listView.style.display = '';
        searchBar.style.display = '';
        tagCloud.style.display = '';
        btn.classList.remove('active');
        if (graphAnimationId) {
            cancelAnimationFrame(graphAnimationId);
            graphAnimationId = null;
        }
    }
}

async function renderMemoryGraph() {
    const data = await apiFetch('/api/memories/graph');
    if (!data || !data.nodes || data.nodes.length === 0) {
        const canvas = document.getElementById('memory-graph-canvas');
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#64748b';
        ctx.font = '14px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('No tag data available', canvas.width / 2, canvas.height / 2);
        return;
    }

    const canvas = document.getElementById('memory-graph-canvas');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * (window.devicePixelRatio || 1);
    canvas.height = 400 * (window.devicePixelRatio || 1);
    canvas.style.width = rect.width + 'px';
    canvas.style.height = '400px';
    const ctx = canvas.getContext('2d');
    ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

    const W = rect.width;
    const H = 400;
    const nodes = data.nodes;
    const edges = data.edges;

    // Build lookup
    const nodeMap = {};
    const maxCount = Math.max(...nodes.map(n => n.count), 1);
    nodes.forEach((n, i) => {
        n.x = W / 2 + (Math.random() - 0.5) * W * 0.6;
        n.y = H / 2 + (Math.random() - 0.5) * H * 0.6;
        n.vx = 0;
        n.vy = 0;
        n.radius = 6 + (n.count / maxCount) * 18;
        nodeMap[n.id] = i;
    });

    // Color by prefix
    function nodeColor(label) {
        if (label.startsWith('type:')) return '#00d2ff';
        if (label.startsWith('area:')) return '#4ade80';
        if (label.startsWith('priority:')) return '#fb923c';
        if (label.startsWith('outcome:')) return '#facc15';
        if (label.startsWith('error_pattern:')) return '#f87171';
        return '#94a3b8';
    }

    const maxWeight = Math.max(...edges.map(e => e.weight), 1);

    // Force simulation
    function simulate(steps) {
        for (let step = 0; step < steps; step++) {
            // Repulsion between all nodes
            for (let i = 0; i < nodes.length; i++) {
                for (let j = i + 1; j < nodes.length; j++) {
                    let dx = nodes[j].x - nodes[i].x;
                    let dy = nodes[j].y - nodes[i].y;
                    let dist = Math.sqrt(dx * dx + dy * dy) || 1;
                    let force = 800 / (dist * dist);
                    let fx = (dx / dist) * force;
                    let fy = (dy / dist) * force;
                    nodes[i].vx -= fx;
                    nodes[i].vy -= fy;
                    nodes[j].vx += fx;
                    nodes[j].vy += fy;
                }
            }

            // Attraction along edges
            for (const edge of edges) {
                const si = nodeMap[edge.source];
                const ti = nodeMap[edge.target];
                if (si === undefined || ti === undefined) continue;
                let dx = nodes[ti].x - nodes[si].x;
                let dy = nodes[ti].y - nodes[si].y;
                let dist = Math.sqrt(dx * dx + dy * dy) || 1;
                let force = (dist - 80) * 0.005 * (edge.weight / maxWeight);
                let fx = (dx / dist) * force;
                let fy = (dy / dist) * force;
                nodes[si].vx += fx;
                nodes[si].vy += fy;
                nodes[ti].vx -= fx;
                nodes[ti].vy -= fy;
            }

            // Center gravity
            for (const node of nodes) {
                node.vx += (W / 2 - node.x) * 0.001;
                node.vy += (H / 2 - node.y) * 0.001;
            }

            // Apply velocity with damping
            const damping = 0.85;
            for (const node of nodes) {
                node.vx *= damping;
                node.vy *= damping;
                node.x += node.vx;
                node.y += node.vy;
                // Clamp to canvas bounds
                node.x = Math.max(node.radius + 5, Math.min(W - node.radius - 5, node.x));
                node.y = Math.max(node.radius + 5, Math.min(H - node.radius - 5, node.y));
            }
        }
    }

    // Run simulation in batches for smoother animation
    let simStep = 0;
    const totalSteps = 200;

    function animateStep() {
        if (simStep >= totalSteps) return;
        simulate(5);
        simStep += 5;
        drawGraph();
        graphAnimationId = requestAnimationFrame(animateStep);
    }

    function drawGraph() {
        ctx.clearRect(0, 0, W, H);

        // Draw edges
        for (const edge of edges) {
            const si = nodeMap[edge.source];
            const ti = nodeMap[edge.target];
            if (si === undefined || ti === undefined) continue;
            ctx.beginPath();
            ctx.moveTo(nodes[si].x, nodes[si].y);
            ctx.lineTo(nodes[ti].x, nodes[ti].y);
            ctx.strokeStyle = `rgba(148, 163, 184, ${0.1 + 0.5 * (edge.weight / maxWeight)})`;
            ctx.lineWidth = 0.5 + 1.5 * (edge.weight / maxWeight);
            ctx.stroke();
        }

        // Draw nodes
        for (const node of nodes) {
            ctx.beginPath();
            ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
            ctx.fillStyle = nodeColor(node.label);
            ctx.globalAlpha = 0.85;
            ctx.fill();
            ctx.globalAlpha = 1;
            ctx.strokeStyle = 'rgba(255,255,255,0.2)';
            ctx.lineWidth = 1;
            ctx.stroke();
        }

        // Draw labels
        ctx.font = '10px -apple-system, BlinkMacSystemFont, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        for (const node of nodes) {
            const label = node.label.length > 20 ? node.label.substring(0, 18) + '..' : node.label;
            // Text shadow for readability
            ctx.fillStyle = 'rgba(0,0,0,0.7)';
            ctx.fillText(label, node.x + 1, node.y + node.radius + 11);
            ctx.fillStyle = '#e2e8f0';
            ctx.fillText(label, node.x, node.y + node.radius + 10);
        }
    }

    // Start animation
    if (graphAnimationId) cancelAnimationFrame(graphAnimationId);
    animateStep();

    // Click handling
    canvas.onclick = function(e) {
        const canvasRect = canvas.getBoundingClientRect();
        const mx = e.clientX - canvasRect.left;
        const my = e.clientY - canvasRect.top;
        for (const node of nodes) {
            const dx = mx - node.x;
            const dy = my - node.y;
            if (dx * dx + dy * dy <= (node.radius + 4) * (node.radius + 4)) {
                // Switch to list view filtered by this tag
                memoryGraphVisible = false;
                document.getElementById('memory-graph-container').classList.add('hidden');
                document.getElementById('memory-content').style.display = '';
                document.getElementById('memory-search-bar').style.display = '';
                document.getElementById('memory-tags').style.display = '';
                document.getElementById('memory-graph-toggle').classList.remove('active');
                searchMemoryByTag(node.label);
                break;
            }
        }
    };
}

// ── Timeline Tab Switching ───────────────────────────────

function switchTimelineTab(tab) {
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

// ── Observation Timeline ────────────────────────────────

async function renderObservations() {
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
        'Bash': '>_',
        'Edit': '~',
        'Write': '+',
        'Read': '@',
        'Grep': '?',
        'Glob': '*',
        'NotebookEdit': 'N',
        'UserPrompt': 'U',
        'Task': 'T',
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

// ── Error Patterns ──────────────────────────────────────

async function renderErrors() {
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

    // Error patterns
    for (const [pattern, count] of Object.entries(patterns)) {
        html += `
            <div class="error-entry">
                <span class="error-pattern">${escapeHtml(pattern)}</span>
                <span class="error-count">${count}</span>
            </div>`;
    }

    // Active bans
    if (bans.length > 0) {
        html += '<div style="margin-top:12px; font-size:11px; color:var(--text-muted); text-transform:uppercase;">Active Bans</div>';
        for (const ban of bans) {
            html += `<div class="ban-entry">${escapeHtml(typeof ban === 'string' ? ban : JSON.stringify(ban))}</div>`;
        }
    }

    html += `<div style="margin-top:8px; font-size:11px; color:var(--text-muted);">Tool calls: ${data.tool_call_count || 0}</div>`;
    el.innerHTML = html;
}

// ── Component Inventory ─────────────────────────────────

async function renderComponents() {
    if (!componentData) {
        const [comp, skillUsage] = await Promise.all([
            apiFetch('/api/components'),
            apiFetch('/api/skill-usage'),
        ]);
        if (!comp) return;
        componentData = comp;
        // Merge skill usage data into componentData for rendering
        if (skillUsage && skillUsage.skills) {
            componentData._skillUsage = {};
            for (const s of skillUsage.skills) {
                componentData._skillUsage[s.name] = s;
            }
        }
    }
    renderComponentTab(activeComponentTab);
}

function renderComponentTab(tab) {
    activeComponentTab = tab;
    const el = document.getElementById('components-content');

    // Update tab active state
    document.querySelectorAll('#component-tabs .tab').forEach(t => {
        t.classList.toggle('active', t.dataset.tab === tab);
    });

    if (!componentData) {
        el.innerHTML = '<div class="no-data">Loading components...</div>';
        return;
    }

    let items = [];
    switch (tab) {
        case 'gates':
            items = (componentData.gates || []).map(g =>
                `<div class="component-item">
                    <div class="component-name">${escapeHtml(g.file)}</div>
                    ${g.description ? `<div class="component-desc">${escapeHtml(g.description)}</div>` : ''}
                </div>`);
            break;
        case 'hooks':
            items = (componentData.hooks || []).map(h =>
                `<div class="component-item">
                    <div class="component-name">${escapeHtml(h.event)}</div>
                    <div class="component-desc">${escapeHtml(h.command)} (${h.timeout}ms)</div>
                </div>`);
            break;
        case 'skills':
            // Build skill usage chart
            let chartHtml = '';
            if (componentData._skillUsage) {
                const usageEntries = Object.values(componentData._skillUsage).sort((a, b) => b.count - a.count);
                if (usageEntries.length > 0) {
                    const maxCount = Math.max(...usageEntries.map(s => s.count), 1);
                    chartHtml = '<div class="skill-usage-section"><h4 style="margin:0 0 8px 0; font-size:13px; color:var(--text-muted); text-transform:uppercase;">Skill Usage</h4>';
                    for (const skill of usageEntries) {
                        const widthPct = (skill.count / maxCount) * 100;
                        chartHtml += `
                            <div class="skill-usage-bar-row">
                                <span class="skill-usage-label">/${escapeHtml(skill.name)}</span>
                                <div class="skill-usage-bar-container">
                                    <div class="skill-usage-bar-fill" style="width:${widthPct}%; background:var(--cyan)"></div>
                                </div>
                                <span class="skill-usage-count-num">${skill.count}</span>
                            </div>`;
                    }
                    chartHtml += '</div><div style="border-top:1px solid var(--border); margin:16px 0;"></div>';
                }
            }

            items = (componentData.skills || []).map(s => {
                const usage = (componentData._skillUsage || {})[s.name];
                let usageHtml = '';
                if (usage) {
                    const lastUsed = usage.last_used ? formatTime(usage.last_used) : 'never';
                    usageHtml = `<div class="skill-usage-info">
                        <span class="skill-usage-count">${usage.count} call${usage.count !== 1 ? 's' : ''}</span>
                        <span class="skill-usage-last">last: ${lastUsed}</span>
                    </div>`;
                }
                return `<div class="component-item">
                    <div class="component-name">/${escapeHtml(s.name)}${usageHtml}</div>
                    ${s.description ? `<div class="component-desc">${escapeHtml(s.description)}</div>` : ''}
                    ${s.purpose ? `<div class="component-purpose">${escapeHtml(s.purpose)}</div>` : ''}
                </div>`;
            });
            // Prepend chart to items
            if (chartHtml) {
                items = [chartHtml, ...items];
            }
            break;
        case 'agents':
            items = (componentData.agents || []).map(a =>
                `<div class="component-item">
                    <div class="component-name">${escapeHtml(a.name)}</div>
                    ${a.description ? `<div class="component-desc">${escapeHtml(a.description)}</div>` : ''}
                </div>`);
            break;
        case 'plugins':
            items = (componentData.plugins || []).map(p => {
                // Support both old format (string) and new format (object)
                if (typeof p === 'string') {
                    return `<div class="component-item">
                        <div class="component-name">${escapeHtml(p)}</div>
                    </div>`;
                }
                const statusClass = p.status === 'active' ? 'plugin-status-active' :
                                    p.status === 'error' ? 'plugin-status-error' : 'plugin-status-inactive';
                const statusLabel = p.status || 'unknown';
                return `<div class="component-item plugin-card">
                    <div class="plugin-header">
                        <span class="component-name">${escapeHtml(p.name)}</span>
                        <span class="plugin-version">v${escapeHtml(p.version || '?')}</span>
                        <span class="plugin-status ${statusClass}">${escapeHtml(statusLabel)}</span>
                    </div>
                    <div class="component-desc">${escapeHtml(p.description || '')}</div>
                    <div class="plugin-meta">
                        ${p.file_count ? `<span>${p.file_count} file${p.file_count !== 1 ? 's' : ''}</span>` : ''}
                        ${p.marketplace ? `<span>from ${escapeHtml(p.marketplace)}</span>` : ''}
                    </div>
                </div>`;
            });
            break;
    }

    if (items.length === 0) {
        el.innerHTML = `<div class="no-data">No ${tab} found.</div>`;
        return;
    }
    el.innerHTML = items.join('');
}

// ── Session History ─────────────────────────────────────

async function renderHistory() {
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
                <input type="checkbox" class="history-check" data-filename="${escapeHtml(f.filename)}"
                    onchange="toggleSessionSelect('${escapeHtml(f.filename)}', this)">
            </label>
            <div class="history-entry-body" onclick="showHistoryDetail('${escapeHtml(f.filename)}')">
                <div class="history-name">${escapeHtml(f.filename)}</div>
                <div class="history-meta">${formatDate(f.modified)} | ${(f.size / 1024).toFixed(1)} KB</div>
            </div>
        </div>`).join('');
}

async function showHistoryDetail(filename) {
    const data = await apiFetch(`/api/history/${filename}`);
    if (!data || data.error) return;

    document.getElementById('overlay-title').textContent = filename;
    document.getElementById('overlay-body').textContent = data.content || '(empty)';
    document.getElementById('detail-overlay').classList.remove('hidden');
}

// ── Gate Performance ────────────────────────────────────

async function renderGatePerf() {
    const data = await apiFetch('/api/gate-perf');
    if (!data) return;

    const el = document.getElementById('gate-perf-content');
    const gates = data.gates || [];

    if (gates.length === 0) {
        el.innerHTML = '<div class="no-data">No gate performance data available.</div>';
        return;
    }

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

    // Also populate the gate filter dropdown for timeline
    populateGateFilterDropdown(gates.map(g => g.gate));
}

// ── Gate Dependencies ────────────────────────────────────

async function renderGateDeps() {
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

    // Extract all unique state keys across all gates
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

    // Build matrix table
    let html = '<table class="gate-dep-matrix"><thead><tr><th>Gate</th>';
    for (const key of stateKeysList) {
        html += `<th title="${escapeHtml(key)}">${escapeHtml(key)}</th>`;
    }
    html += '</tr></thead><tbody>';

    // Rows: gates
    for (const gate of gateNames) {
        const d = deps[gate];
        const reads = new Set(d.reads || []);
        const writes = new Set(d.writes || []);
        const shortName = gate.replace('gate_', 'G').replace(/_/g, ' ');
        html += `<tr><td class="gate-dep-name" title="${escapeHtml(gate)}">${escapeHtml(shortName)}</td>`;

        // Columns: state keys
        for (const key of stateKeysList) {
            const isRead = reads.has(key);
            const isWrite = writes.has(key);
            let cellContent = '';
            if (isRead && isWrite) {
                // Both read and write: show both dots
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

    // Add legend
    html += '<div class="gate-dep-legend">';
    html += '<span class="legend-item"><span class="dep-read"></span> Reads</span>';
    html += '<span class="legend-item"><span class="dep-write"></span> Writes</span>';
    html += '</div>';

    el.innerHTML = html;
}

function populateGateFilterDropdown(gateNames) {
    const select = document.getElementById('timeline-gate-filter');
    if (!select) return;
    // Keep the "All Gates" option, remove the rest
    while (select.options.length > 1) select.remove(1);
    for (const name of gateNames) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name.replace('GATE ', 'G');
        select.appendChild(opt);
    }
}

// ── Audit Query Filters ────────────────────────────────

let activeQueryFilters = {};

async function applyTimelineFilters() {
    const gate = document.getElementById('timeline-gate-filter').value;
    const decision = document.getElementById('timeline-decision-filter').value;
    const hoursInput = document.getElementById('timeline-hours-filter');
    let hours = parseInt(hoursInput.value) || 24;

    // Validate hours parameter
    if (hours < 1 || hours > 720) {
        showToast('Hours must be between 1 and 720 (30 days max)', 'error', 'warning');
        hoursInput.value = Math.max(1, Math.min(720, hours)); // Clamp to valid range
        hours = parseInt(hoursInput.value);
    }

    // If no filters, fall back to regular timeline
    if (!gate && !decision) {
        activeQueryFilters = {};
        renderActiveFilterBadges();
        renderFilteredTimeline();
        return;
    }

    const params = new URLSearchParams();
    if (gate) params.set('gate', gate);
    if (decision) params.set('decision', decision);
    params.set('hours', hours.toString());

    const data = await apiFetch(`/api/audit/query?${params.toString()}`);
    if (!data) return;

    activeQueryFilters = {};
    if (gate) activeQueryFilters.gate = gate;
    if (decision) activeQueryFilters.decision = decision;

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
            `<span class="filter-badge-x" onclick="event.stopPropagation(); removeQueryFilter('${key}')">&times;</span></span>`;
    }).join(' ');
}

function removeQueryFilter(key) {
    delete activeQueryFilters[key];
    // Reset the corresponding dropdown
    if (key === 'gate') document.getElementById('timeline-gate-filter').value = '';
    if (key === 'decision') document.getElementById('timeline-decision-filter').value = '';

    if (Object.keys(activeQueryFilters).length === 0) {
        renderActiveFilterBadges();
        renderFilteredTimeline();
    } else {
        applyTimelineFilters();
    }
}

// ── Session Comparison ─────────────────────────────────

let selectedSessions = new Set();

function toggleSessionSelect(filename, checkbox) {
    if (checkbox.checked) {
        selectedSessions.add(filename);
    } else {
        selectedSessions.delete(filename);
    }
    // Show/hide Compare button
    const btn = document.getElementById('compare-btn');
    if (selectedSessions.size === 2) {
        btn.classList.remove('hidden');
    } else {
        btn.classList.add('hidden');
    }
}

async function compareSessions() {
    const files = Array.from(selectedSessions);
    if (files.length !== 2) return;

    const data = await apiFetch(`/api/history/compare?a=${encodeURIComponent(files[0])}&b=${encodeURIComponent(files[1])}`);
    if (!data || data.error) return;

    document.getElementById('overlay-title').textContent = 'Session Comparison';
    const body = document.getElementById('overlay-body');

    let html = '<div class="compare-view">';

    // Header
    html += `<div class="compare-header">
        <div class="compare-col-header">${escapeHtml(data.a.filename)}</div>
        <div class="compare-col-header">${escapeHtml(data.b.filename)}</div>
    </div>`;

    const diff = data.diff || {};

    // Added sections (only in B)
    for (const section of (diff.added_sections || [])) {
        html += `<div class="compare-row compare-added">
            <div class="compare-col compare-empty"><em>(not present)</em></div>
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.b.sections[section] || '').substring(0, 300)}</div>
        </div>`;
    }

    // Removed sections (only in A)
    for (const section of (diff.removed_sections || [])) {
        html += `<div class="compare-row compare-removed">
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.a.sections[section] || '').substring(0, 300)}</div>
            <div class="compare-col compare-empty"><em>(not present)</em></div>
        </div>`;
    }

    // Changed sections
    for (const section of (diff.changed_sections || [])) {
        html += `<div class="compare-row compare-changed">
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.a.sections[section] || '').substring(0, 300)}</div>
            <div class="compare-col"><strong>${escapeHtml(section)}</strong><br>${escapeHtml(data.b.sections[section] || '').substring(0, 300)}</div>
        </div>`;
    }

    // Unchanged sections
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

// ── Date Selectors ──────────────────────────────────────

async function populateDateSelects() {
    const data = await apiFetch('/api/audit/dates');
    if (!data || !data.dates) return;

    const selects = [
        document.getElementById('gate-date-select'),
        document.getElementById('timeline-date-select'),
    ];

    for (const select of selects) {
        // Keep the "Today" option
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

// ── SSE Connection ──────────────────────────────────────

// ── Notification Badge ──────────────────────────────────

let notificationCount = 0;

function incrementNotificationBadge() {
    notificationCount++;
    const badge = document.getElementById('notification-badge');
    if (badge) {
        badge.textContent = notificationCount > 99 ? '99+' : notificationCount;
        badge.classList.remove('hidden');
    }
}

function clearNotificationBadge() {
    notificationCount = 0;
    const badge = document.getElementById('notification-badge');
    if (badge) {
        badge.textContent = '0';
        badge.classList.add('hidden');
    }
}

// ── SSE Connection ──────────────────────────────────────

function connectSSE() {
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
                prependTimelineEntry(entry);
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

                // Re-render errors panel
                renderErrors();
            } catch {}
        });

        sseSource.onerror = () => {
            indicator.classList.remove('on');
            indicator.classList.add('off');
            // Auto-reconnect after 5s
            setTimeout(() => {
                if (sseSource.readyState === EventSource.CLOSED) {
                    connectSSE();
                }
            }, 5000);
        };
    } catch {
        indicator.classList.remove('on');
        indicator.classList.add('off');
    }
}

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
        }
    });
}

// ── Auto Refresh ────────────────────────────────────────

function setupAutoRefresh() {
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
            startAutoRefresh();
        } else {
            stopAutoRefresh();
        }
    });

    // Start auto-refresh if checkbox is checked
    if (cb.checked) {
        startAutoRefresh();
    }
}

function startAutoRefresh() {
    stopAutoRefresh();
    autoRefreshTimer = setInterval(() => {
        refreshAll();
    }, REFRESH_INTERVAL);
}

function stopAutoRefresh() {
    if (autoRefreshTimer) {
        clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
}

async function refreshAll() {
    await Promise.all([
        renderHealth(),
        renderGates(),
        renderTimeline(),
        renderGatePerf(),
        renderErrors(),
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

    // Session comparison
    document.getElementById('compare-btn').addEventListener('click', () => {
        compareSessions();
    });

    // Notification badge - click to clear
    const notifBadge = document.getElementById('notification-badge');
    if (notifBadge) {
        notifBadge.addEventListener('click', () => {
            clearNotificationBadge();
        });
    }
}

// ── Theme Toggle ────────────────────────────────────────

function setupTheme() {
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

function updateThemeIcon() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const isLight = document.documentElement.dataset.theme === 'light';
    btn.innerHTML = isLight ? '&#9728;' : '&#9790;';
    btn.title = isLight ? 'Switch to dark theme' : 'Switch to light theme';
}

// ── Panel Collapse ──────────────────────────────────────

function setupPanelCollapse() {
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

// ── Init ────────────────────────────────────────────────

async function init() {
    setupTheme();
    setupOverlay();
    setupEventListeners();
    setupPanelCollapse();

    // Initial render — all panels in parallel
    await Promise.all([
        renderHealth(),
        renderGates(),
        renderGatePerf(),
        renderGateDeps(),
        renderTimeline(),
        renderMemory(''),
        renderMemoryTags(),
        renderMemoryHealth(),
        renderObservations(),
        renderErrors(),
        renderComponents(),
        renderHistory(),
        populateDateSelects(),
    ]);

    // Start SSE and auto-refresh
    connectSSE();
    setupAutoRefresh();
}

// Boot
document.addEventListener('DOMContentLoaded', init);
