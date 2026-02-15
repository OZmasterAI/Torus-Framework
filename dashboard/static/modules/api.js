/**
 * API fetch helper module.
 * Centralizes all HTTP communication with the dashboard server.
 */

import { showToast } from './utils.js';

const API = '';  // Same origin

export async function apiFetch(path) {
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

export { API };
