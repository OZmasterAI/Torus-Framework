/**
 * Component Inventory Panel — gates, hooks, skills, agents, plugins tabs
 */
import { apiFetch } from '../api.js';
import { escapeHtml, formatTime } from '../utils.js';

let componentData = null;
let activeComponentTab = 'gates';

export async function renderComponents() {
    if (!componentData) {
        const [comp, skillUsage] = await Promise.all([
            apiFetch('/api/components'),
            apiFetch('/api/skill-usage'),
        ]);
        if (!comp) return;
        componentData = comp;
        if (skillUsage && skillUsage.skills) {
            componentData._skillUsage = {};
            for (const s of skillUsage.skills) {
                componentData._skillUsage[s.name] = s;
            }
        }
    }
    renderComponentTab(activeComponentTab);
}

export function renderComponentTab(tab) {
    activeComponentTab = tab;
    const el = document.getElementById('components-content');

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
        case 'skills': {
            let chartHtml = '';
            if (componentData._skillUsage) {
                const usageEntries = Object.values(componentData._skillUsage).sort((a, b) => b.count - a.count);
                if (usageEntries.length > 0) {
                    const maxCount = Math.max(...usageEntries.map(s => s.count), 1);
                    chartHtml = '<div class="skill-usage-section"><h4 style="margin:0 0 8px 0; font-size:11px; color:var(--text-muted); text-transform:uppercase; letter-spacing:0.1em;">Skill Usage</h4>';
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
                    chartHtml += '</div><div style="border-top:1px solid var(--border); margin:12px 0;"></div>';
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
            if (chartHtml) items = [chartHtml, ...items];
            break;
        }
        case 'agents':
            items = (componentData.agents || []).map(a =>
                `<div class="component-item">
                    <div class="component-name">${escapeHtml(a.name)}</div>
                    ${a.description ? `<div class="component-desc">${escapeHtml(a.description)}</div>` : ''}
                </div>`);
            break;
        case 'plugins':
            items = (componentData.plugins || []).map(p => {
                if (typeof p === 'string') {
                    return `<div class="component-item">
                        <div class="component-name">${escapeHtml(p)}</div>
                    </div>`;
                }
                const statusClass = p.status === 'active' ? 'plugin-status-active' :
                                    p.status === 'error' ? 'plugin-status-error' : 'plugin-status-inactive';
                return `<div class="component-item plugin-card">
                    <div class="plugin-header">
                        <span class="component-name">${escapeHtml(p.name)}</span>
                        <span class="plugin-version">v${escapeHtml(p.version || '?')}</span>
                        <span class="plugin-status ${statusClass}">${escapeHtml(p.status || 'unknown')}</span>
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
