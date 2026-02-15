/**
 * Memory Graph Panel — D3 force-directed tag co-occurrence graph
 */
import { apiFetch } from '../api.js';
import { searchMemoryByTag } from './memory.js';

let memoryGraphVisible = false;

export function isGraphVisible() {
    return memoryGraphVisible;
}

export function toggleMemoryGraph() {
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
    }
}

// ── Node color by tag prefix ─────────────────────────────

function nodeColor(label) {
    if (label.startsWith('type:')) return '#00fff0';     // cyan
    if (label.startsWith('area:')) return '#39ff14';     // green
    if (label.startsWith('priority:')) return '#ff9500'; // orange
    if (label.startsWith('outcome:')) return '#ffe600';  // yellow
    if (label.startsWith('error_pattern:')) return '#ff3333'; // red
    return '#8888a0';
}

async function renderMemoryGraph() {
    const data = await apiFetch('/api/memories/graph');
    const container = document.getElementById('memory-graph-container');
    if (!container) return;

    if (!data || !data.nodes || data.nodes.length === 0 || typeof d3 === 'undefined') {
        container.innerHTML = '<div class="no-data" style="padding:40px; text-align:center;">No tag data available</div>';
        return;
    }

    container.innerHTML = '';

    const rect = container.getBoundingClientRect();
    const W = rect.width || 600;
    const H = 400;
    const nodes = data.nodes;
    const edges = data.edges;
    const maxCount = Math.max(...nodes.map(n => n.count), 1);
    const maxWeight = Math.max(...edges.map(e => e.weight), 1);

    // Create SVG
    const svg = d3.select(container)
        .append('svg')
        .attr('class', 'memory-graph-svg')
        .attr('width', W)
        .attr('height', H);

    // Glow filter
    const defs = svg.append('defs');
    const glowFilter = defs.append('filter')
        .attr('id', 'node-glow')
        .attr('x', '-50%').attr('y', '-50%')
        .attr('width', '200%').attr('height', '200%');
    glowFilter.append('feGaussianBlur')
        .attr('stdDeviation', '4')
        .attr('result', 'blur');
    glowFilter.append('feMerge')
        .selectAll('feMergeNode')
        .data(['blur', 'SourceGraphic'])
        .enter()
        .append('feMergeNode')
        .attr('in', d => d);

    // Zoom behavior
    const zoomGroup = svg.append('g');
    const zoom = d3.zoom()
        .scaleExtent([0.3, 5])
        .on('zoom', (event) => {
            zoomGroup.attr('transform', event.transform);
        });
    svg.call(zoom);

    // D3 tooltip
    let tooltip = document.getElementById('graph-tooltip');
    if (!tooltip) {
        tooltip = document.createElement('div');
        tooltip.id = 'graph-tooltip';
        tooltip.className = 'd3-tooltip';
        tooltip.style.display = 'none';
        document.body.appendChild(tooltip);
    }

    // Build links
    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const links = edges.filter(e => nodeById.has(e.source) && nodeById.has(e.target))
        .map(e => ({ source: e.source, target: e.target, weight: e.weight }));

    // Force simulation
    const simulation = d3.forceSimulation(nodes)
        .force('link', d3.forceLink(links).id(d => d.id).distance(80))
        .force('charge', d3.forceManyBody().strength(-200))
        .force('center', d3.forceCenter(W / 2, H / 2))
        .force('collide', d3.forceCollide().radius(d => radiusScale(d.count) + 4));

    const radiusScale = (count) => 6 + (count / maxCount) * 18;

    // Draw edges
    const link = zoomGroup.append('g')
        .selectAll('line')
        .data(links)
        .enter()
        .append('line')
        .attr('stroke', 'rgba(136, 136, 160, 0.3)')
        .attr('stroke-width', d => 0.5 + 2 * (d.weight / maxWeight));

    // Draw nodes
    const node = zoomGroup.append('g')
        .selectAll('circle')
        .data(nodes)
        .enter()
        .append('circle')
        .attr('r', d => radiusScale(d.count))
        .attr('fill', d => nodeColor(d.label))
        .attr('stroke', 'rgba(255,255,255,0.15)')
        .attr('stroke-width', 1)
        .style('filter', 'url(#node-glow)')
        .style('cursor', 'pointer')
        .call(d3.drag()
            .on('start', dragstarted)
            .on('drag', dragged)
            .on('end', dragended));

    // Node hover
    node.on('mouseover', (event, d) => {
        const topCo = edges
            .filter(e => e.source.id === d.id || e.target.id === d.id)
            .sort((a, b) => b.weight - a.weight)
            .slice(0, 3)
            .map(e => e.source.id === d.id ? e.target.id || e.target : e.source.id || e.source);

        tooltip.innerHTML = `<strong>${d.label}</strong><br>Count: ${d.count}${topCo.length ? '<br>Co-occurs: ' + topCo.join(', ') : ''}`;
        tooltip.style.display = 'block';
        tooltip.style.left = `${event.pageX + 12}px`;
        tooltip.style.top = `${event.pageY - 10}px`;
    })
    .on('mousemove', (event) => {
        tooltip.style.left = `${event.pageX + 12}px`;
        tooltip.style.top = `${event.pageY - 10}px`;
    })
    .on('mouseout', () => {
        tooltip.style.display = 'none';
    });

    // Node click — filter memory browser
    node.on('click', (event, d) => {
        memoryGraphVisible = false;
        container.classList.add('hidden');
        document.getElementById('memory-content').style.display = '';
        document.getElementById('memory-search-bar').style.display = '';
        document.getElementById('memory-tags').style.display = '';
        document.getElementById('memory-graph-toggle').classList.remove('active');
        searchMemoryByTag(d.label);
    });

    // Labels
    const label = zoomGroup.append('g')
        .selectAll('text')
        .data(nodes)
        .enter()
        .append('text')
        .text(d => d.label.length > 20 ? d.label.substring(0, 18) + '..' : d.label)
        .attr('text-anchor', 'middle')
        .attr('dy', d => radiusScale(d.count) + 12)
        .style('font-size', '9px')
        .style('fill', 'var(--text-secondary)')
        .style('pointer-events', 'none');

    // Tick
    simulation.on('tick', () => {
        link
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y);
        node
            .attr('cx', d => d.x)
            .attr('cy', d => d.y);
        label
            .attr('x', d => d.x)
            .attr('y', d => d.y);
    });

    function dragstarted(event, d) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }
    function dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }
    function dragended(event, d) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }
}
