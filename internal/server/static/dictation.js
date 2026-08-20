(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});
    const { escapeHtml, copyText } = TinyAI;

    // An LCS table is quadratic, so a long dictation with a heavy rewrite falls back to
    // reporting the changed span wholesale rather than stalling the page.
    const MAX_CELLS = 4_000_000;

    function words(text) {
        return String(text || '').match(/\S+/g) || [];
    }

    function run(type, items) {
        return items.length ? [{ type, words: items }] : [];
    }

    function lcsRuns(a, b) {
        if (!a.length || !b.length || a.length * b.length > MAX_CELLS) {
            return [...run('del', a), ...run('ins', b)];
        }

        const width = b.length + 1;
        const table = new Int32Array((a.length + 1) * width);
        for (let i = a.length - 1; i >= 0; i -= 1) {
            for (let j = b.length - 1; j >= 0; j -= 1) {
                table[i * width + j] =
                    a[i] === b[j]
                        ? table[(i + 1) * width + j + 1] + 1
                        : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
            }
        }

        const ops = [];
        let i = 0;
        let j = 0;
        while (i < a.length && j < b.length) {
            if (a[i] === b[j]) {
                ops.push(['same', a[i]]);
                i += 1;
                j += 1;
            } else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) {
                ops.push(['del', a[i]]);
                i += 1;
            } else {
                ops.push(['ins', b[j]]);
                j += 1;
            }
        }
        for (; i < a.length; i += 1) ops.push(['del', a[i]]);
        for (; j < b.length; j += 1) ops.push(['ins', b[j]]);

        return ops.reduce((runs, [type, word]) => {
            const last = runs[runs.length - 1];
            if (last && last.type === type) last.words.push(word);
            else runs.push({ type, words: [word] });
            return runs;
        }, []);
    }

    function wordDiff(before, after) {
        const a = words(before);
        const b = words(after);

        let head = 0;
        while (head < a.length && head < b.length && a[head] === b[head]) head += 1;
        let tail = 0;
        while (
            tail < a.length - head &&
            tail < b.length - head &&
            a[a.length - 1 - tail] === b[b.length - 1 - tail]
        ) {
            tail += 1;
        }

        return [
            ...run('same', a.slice(0, head)),
            ...lcsRuns(a.slice(head, a.length - tail), b.slice(head, b.length - tail)),
            ...run('same', a.slice(a.length - tail)),
        ];
    }

    // The plain word-diff markers git itself emits, so a pasted diff reads the same anywhere.
    const MARKERS = { del: ['[-', '-]'], ins: ['{+', '+}'], same: ['', ''] };

    function diffPatch(runs) {
        return runs
            .map(({ type, words: items }) => MARKERS[type][0] + items.join(' ') + MARKERS[type][1])
            .join(' ');
    }

    const RUN_CLASS = {
        del: 'bg-red/15 text-red line-through decoration-red/60',
        ins: 'bg-green/15 text-green',
        same: 'text-subtext0',
    };

    function diffHtml(runs) {
        if (runs.every((entry) => entry.type === 'same')) {
            return '<p class="text-sm text-overlay1">The polish pass changed nothing.</p>';
        }
        const body = runs
            .map(
                ({ type, words: items }) =>
                    `<span class="${RUN_CLASS[type]} rounded-sm">${escapeHtml(items.join(' '))}</span>`,
            )
            .join(' ');
        return `<p class="whitespace-pre-wrap font-mono text-xs leading-relaxed">${body}</p>`;
    }

    function textHtml(text) {
        return `<p class="whitespace-pre-wrap font-mono text-xs leading-relaxed text-subtext0">${escapeHtml(
            text,
        )}</p>`;
    }

    const TAB_BASE =
        'inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium transition-colors';
    const TAB_ACTIVE = 'bg-surface1 text-text';
    const TAB_IDLE = 'bg-surface0/50 text-overlay1 hover:bg-surface0 hover:text-subtext1';

    function tabClass(active) {
        return `${TAB_BASE} ${active ? TAB_ACTIVE : TAB_IDLE}`;
    }

    function tabButton(tab, active) {
        return `
            <button type="button" data-tab="${tab.id}" class="${tabClass(active)}">
                <i data-lucide="${tab.icon}" class="h-3.5 w-3.5"></i>
                <span>${escapeHtml(tab.label)}</span>
            </button>`;
    }

    function render(host, data) {
        const raw = String(data.raw || '');
        const polished = String(data.text || '');
        const runs = wordDiff(raw, polished);

        const panes = {
            diff: { html: diffHtml(runs), copy: diffPatch(runs) },
            raw: { html: textHtml(raw), copy: raw },
            polished: { html: textHtml(polished), copy: polished },
        };
        const tabs = [
            { id: 'diff', label: 'Diff', icon: 'git-compare' },
            { id: 'raw', label: 'Raw', icon: 'audio-lines' },
            { id: 'polished', label: 'Polished', icon: 'sparkles' },
        ];
        let current = 'polished';

        host.innerHTML = `
            <div class="space-y-3">
                <div data-tabs class="flex flex-wrap gap-1.5">${tabs.map((tab) => tabButton(tab, tab.id === current)).join('')}</div>
                <div data-pane class="max-h-96 overflow-auto rounded-lg bg-crust p-3"></div>
                <button type="button" data-copy
                        class="inline-flex items-center gap-1.5 rounded-lg bg-surface0/70 px-3 py-1.5 text-xs text-subtext1 hover:bg-surface1 hover:text-mauve">
                    <i data-lucide="copy" class="h-3.5 w-3.5"></i>
                    <span data-pane-copy-label>Copy polished</span>
                </button>
            </div>`;

        const pane = host.querySelector('[data-pane]');
        const label = host.querySelector('[data-pane-copy-label]');

        function show(id) {
            current = id;
            pane.innerHTML = panes[id].html;
            label.textContent = `Copy ${id}`;
            host.querySelectorAll('[data-tab]').forEach((button) => {
                button.className = tabClass(button.dataset.tab === id);
            });
        }

        host.querySelector('[data-tabs]').addEventListener('click', (event) => {
            const button = event.target.closest('[data-tab]');
            if (button) show(button.dataset.tab);
        });
        host.querySelector('[data-copy]').addEventListener('click', async () => {
            await copyText(panes[current].copy);
            label.textContent = 'Copied';
            setTimeout(() => {
                label.textContent = `Copy ${current}`;
            }, 2000);
        });

        show(current);
        lucide.createIcons({ root: host });
    }

    TinyAI.dictationResult = render;
    TinyAI.wordDiff = wordDiff;
    TinyAI.diffPatch = diffPatch;
})();
