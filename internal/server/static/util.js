(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});

    const STATES = {
        queued: { label: 'Queued', color: 'overlay1', icon: 'clock' },
        running: { label: 'Running', color: 'blue', icon: 'loader' },
        succeeded: { label: 'Succeeded', color: 'green', icon: 'check' },
        failed: { label: 'Failed', color: 'red', icon: 'triangle-alert' },
        canceled: { label: 'Canceled', color: 'peach', icon: 'ban' },
    };

    const GROUP_COLORS = {
        Audio: 'mauve',
        Speech: 'blue',
        Documents: 'peach',
        Images: 'green',
    };

    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatBytes(bytes) {
        const n = Number(bytes) || 0;
        if (n < 1024) return `${n} B`;
        const units = ['KB', 'MB', 'GB', 'TB'];
        let value = n / 1024;
        let i = 0;
        while (value >= 1024 && i < units.length - 1) {
            value /= 1024;
            i += 1;
        }
        return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[i]}`;
    }

    function formatDuration(seconds) {
        const total = Math.max(0, Math.floor(Number(seconds) || 0));
        const h = Math.floor(total / 3600);
        const m = Math.floor((total % 3600) / 60);
        const s = total % 60;
        if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
        if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
        return `${s}s`;
    }

    function relativeTime(iso) {
        if (!iso) return '';
        const then = Date.parse(iso);
        if (Number.isNaN(then)) return '';
        const diff = Math.round((Date.now() - then) / 1000);
        if (diff < 45) return 'just now';
        if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
        if (diff < 86400) return `${Math.round(diff / 3600)}h ago`;
        return `${Math.round(diff / 86400)}d ago`;
    }

    function stateMeta(state) {
        return STATES[state] || { label: state || 'unknown', color: 'overlay1', icon: 'circle' };
    }

    function groupColor(group) {
        return GROUP_COLORS[group] || 'lavender';
    }

    function isTerminal(state) {
        return state === 'succeeded' || state === 'failed' || state === 'canceled';
    }

    async function apiJSON(path, options) {
        const response = await fetch(path, options);
        if (response.status === 204) return null;
        const text = await response.text();
        let body = null;
        if (text) {
            try {
                body = JSON.parse(text);
            } catch {
                body = null;
            }
        }
        if (!response.ok) {
            const message = (body && body.error) || `${response.status} ${response.statusText}`;
            throw new Error(message);
        }
        return body;
    }

    async function copyText(text) {
        try {
            await navigator.clipboard.writeText(text);
            return;
        } catch {
            // The clipboard API needs a secure context, so plain HTTP falls back to a hidden selection.
        }
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
    }

    function toast(message, kind) {
        const host = document.getElementById('toasts');
        if (!host) return;
        const color = kind === 'error' ? 'red' : kind === 'success' ? 'green' : 'blue';
        const node = document.createElement('div');
        node.className = `flex items-start gap-2 max-w-sm rounded-lg border border-${color}/40 bg-mantle px-3 py-2 text-sm shadow-lg`;
        node.innerHTML = `<i data-lucide="${kind === 'error' ? 'circle-alert' : 'info'}" class="w-4 h-4 mt-0.5 shrink-0 text-${color}"></i><span class="text-subtext1 break-words">${escapeHtml(message)}</span>`;
        host.appendChild(node);
        lucide.createIcons({ root: node });
        setTimeout(() => node.remove(), 6000);
    }

    TinyAI.escapeHtml = escapeHtml;
    TinyAI.formatBytes = formatBytes;
    TinyAI.formatDuration = formatDuration;
    TinyAI.relativeTime = relativeTime;
    TinyAI.stateMeta = stateMeta;
    TinyAI.groupColor = groupColor;
    TinyAI.isTerminal = isTerminal;
    TinyAI.apiJSON = apiJSON;
    TinyAI.copyText = copyText;
    TinyAI.toast = toast;
})();
