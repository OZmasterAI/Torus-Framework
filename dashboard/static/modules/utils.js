/**
 * Utility functions module.
 * Pure helpers for formatting, escaping, rendering markdown, and toast notifications.
 */

const HEALTH_COLORS = {
    cyan:   '#00fff0',
    green:  '#39ff14',
    orange: '#ff9500',
    yellow: '#ffe600',
    red:    '#ff3333',
};

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

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

export {
    HEALTH_COLORS,
    escapeHtml,
    formatTime,
    formatDate,
    renderMarkdown,
    inlineMarkdown,
    showToast,
};
