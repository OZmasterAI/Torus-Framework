/**
 * Memory Browser Panel — search, tags, detail overlay, memory health
 */
import { apiFetch } from '../api.js';
import { escapeHtml, formatDate, renderMarkdown } from '../utils.js';

export async function renderMemory(query) {
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
        <div class="memory-entry" data-memory-id="${escapeHtml(m.id)}">
            <div class="memory-preview">${escapeHtml(m.preview || '(no preview)')}</div>
            <div class="memory-meta">
                <span>${escapeHtml(m.tags || '')}</span>
                <span>${formatDate(m.timestamp)}</span>
                ${m.relevance !== undefined ? `<span>rel: ${m.relevance}</span>` : ''}
            </div>
        </div>`).join('');

    // Attach click handlers
    el.querySelectorAll('.memory-entry').forEach(entry => {
        entry.addEventListener('click', () => {
            showMemoryDetail(entry.dataset.memoryId);
        });
    });
}

export async function renderMemoryTags() {
    const data = await apiFetch('/api/memories/tags');
    if (!data || !data.tags) return;

    const el = document.getElementById('memory-tags');
    const entries = Object.entries(data.tags).slice(0, 30);
    el.innerHTML = entries.map(([tag, count]) =>
        `<span class="tag-pill" data-tag="${escapeHtml(tag)}">${escapeHtml(tag)}<span class="tag-count">${count}</span></span>`
    ).join('');

    el.querySelectorAll('.tag-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            searchMemoryByTag(pill.dataset.tag);
        });
    });
}

export async function renderMemoryHealth() {
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
        ${topTagsHtml ? `<div class="health-top-tags">${topTagsHtml}</div>` : ''}`;
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

export function searchMemoryByTag(tag) {
    const input = document.getElementById('memory-search');
    input.value = tag;
    renderMemory(tag);
}
