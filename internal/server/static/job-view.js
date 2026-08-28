(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});
    const { escapeHtml, formatBytes, formatDuration, stateMeta, isTerminal, apiJSON, toast } = TinyAI;

    const KIND_ICONS = {
        audio: 'audio-lines',
        image: 'image',
        markdown: 'file-text',
        text: 'file-text',
        json: 'braces',
        archive: 'file-archive',
    };

    const LEVEL_COLORS = {
        error: 'text-red',
        warn: 'text-yellow',
        debug: 'text-overlay0',
    };

    let active = null;

    function inlineURL(url) {
        return url + (url.includes('?') ? '&' : '?') + 'inline=1';
    }

    function artifactName(artifact) {
        return artifact.name || String(artifact.path || '').split('/').pop() || 'artifact';
    }

    function shell(job) {
        const meta = stateMeta(job.state);
        return `
            <div class="space-y-5">
                <div class="flex items-start gap-4">
                    <a href="#/" class="mt-1 shrink-0 rounded-lg bg-surface0/70 p-2 text-overlay1 hover:bg-surface1 hover:text-text" title="Back to tasks">
                        <i data-lucide="arrow-left" class="h-4 w-4"></i>
                    </a>
                    <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-center gap-2">
                            <h1 class="font-display text-xl font-semibold">${escapeHtml(job.title || job.task)}</h1>
                            <span data-pill class="inline-flex items-center gap-1.5 rounded-full bg-${meta.color}/15 px-2.5 py-0.5 text-xs font-medium text-${meta.color}">
                                <i data-lucide="${meta.icon}" class="h-3.5 w-3.5"></i>
                                <span data-pill-label>${escapeHtml(meta.label)}</span>
                            </span>
                            <span data-stream class="hidden items-center gap-1.5 rounded-full bg-surface0 px-2.5 py-0.5 text-xs text-subtext0"></span>
                        </div>
                        <p class="mt-1 font-mono text-xs text-overlay1">${escapeHtml(job.id)}</p>
                    </div>
                    <div class="flex shrink-0 items-center gap-2">
                        <button type="button" data-cancel class="hidden items-center gap-2 rounded-lg bg-red/10 px-3 py-1.5 text-sm text-red hover:bg-red/20">
                            <i data-lucide="square" class="h-4 w-4"></i>
                            <span>Cancel</span>
                        </button>
                        <button type="button" data-delete class="hidden items-center gap-2 rounded-lg bg-surface0/70 px-3 py-1.5 text-sm text-subtext1 hover:bg-surface1">
                            <i data-lucide="trash-2" class="h-4 w-4"></i>
                            <span>Delete</span>
                        </button>
                    </div>
                </div>

                <div data-progress-panel class="rounded-xl bg-mantle p-4">
                    <div class="flex items-baseline justify-between gap-3">
                        <span data-progress-message class="truncate text-sm text-subtext1">Waiting for the runner</span>
                        <span data-elapsed class="shrink-0 font-mono text-sm text-overlay1"></span>
                    </div>
                    <div class="mt-3 h-2 w-full overflow-hidden rounded-full bg-surface0">
                        <div data-bar class="h-full rounded-full bg-mauve transition-[width] duration-300" style="width:0%"></div>
                    </div>
                    <div class="mt-1.5 flex items-center justify-between text-[11px] text-overlay0">
                        <span data-counter></span>
                        <span data-percent></span>
                    </div>
                </div>

                <div data-summary class="flex flex-wrap gap-2"></div>

                <div data-chat-host class="hidden"></div>

                <div data-error class="hidden rounded-xl bg-red/10 p-4">
                    <div class="flex items-center gap-2 text-sm font-medium text-red">
                        <i data-lucide="circle-alert" class="h-4 w-4"></i>
                        <span data-error-message></span>
                    </div>
                    <pre data-error-trace class="mt-3 hidden max-h-64 overflow-auto whitespace-pre-wrap font-mono text-xs text-maroon"></pre>
                </div>

                <div data-artifacts-section class="hidden space-y-3">
                    <h2 class="font-display text-sm font-semibold text-subtext1">Artifacts</h2>
                    <div data-compare></div>
                    <div data-artifacts class="space-y-3"></div>
                </div>

                <div data-result-section class="hidden space-y-3">
                    <div class="flex items-center justify-between gap-3">
                        <h2 class="font-display text-sm font-semibold text-subtext1">Result</h2>
                        <button type="button" data-copy-result
                                class="hidden items-center gap-1.5 rounded-md bg-surface0/70 px-2.5 py-1 text-xs text-subtext0 hover:bg-surface1 hover:text-mauve">
                            <i data-lucide="copy" class="h-3.5 w-3.5"></i>
                            <span data-copy-label>Copy</span>
                        </button>
                    </div>
                    <div data-result class="rounded-xl bg-mantle p-4"></div>
                </div>

                <div class="overflow-hidden rounded-xl bg-crust">
                    <div class="flex items-center justify-between bg-mantle px-4 py-2.5">
                        <h2 class="font-display text-sm font-semibold text-subtext1">Log</h2>
                        <label class="flex items-center gap-2 text-xs text-overlay1">
                            <input type="checkbox" data-follow checked class="accent-mauve">
                            <span>Follow</span>
                        </label>
                    </div>
                    <div data-log class="max-h-80 space-y-0.5 overflow-y-auto p-3 font-mono text-xs leading-relaxed"></div>
                </div>
            </div>`;
    }

    function summaryChips(job) {
        const chips = [];
        (job.inputs || []).forEach((input) => {
            chips.push(
                `<span class="inline-flex items-center gap-1.5 rounded-lg bg-surface0/60 px-2.5 py-1 text-xs text-subtext0"><i data-lucide="paperclip" class="h-3 w-3 text-mauve"></i>${escapeHtml(
                    input.filename,
                )} <span class="text-overlay0">${escapeHtml(formatBytes(input.bytes))}</span></span>`,
            );
        });
        Object.entries(job.params || {}).forEach(([key, value]) => {
            if (value === '' || value === null || value === undefined) return;
            chips.push(
                `<span class="inline-flex max-w-full items-center gap-1.5 rounded-lg bg-surface0/60 px-2.5 py-1 text-xs text-overlay1"><span class="shrink-0 text-subtext0">${escapeHtml(
                    key,
                )}</span><span class="max-w-[16rem] truncate font-mono text-subtext1" title="${escapeHtml(value)}">${escapeHtml(value)}</span></span>`,
            );
        });
        return chips.join('');
    }

    function artifactCard(artifact, url) {
        const kind = artifact.kind || 'other';
        const icon = KIND_ICONS[kind] || 'file';
        const toggle =
            kind === 'markdown'
                ? `<button type="button" data-toggle class="rounded-md bg-surface0/70 px-2 py-1 text-[11px] text-subtext0 hover:bg-surface1">Source</button>`
                : '';
        return `
            <div class="overflow-hidden rounded-xl bg-mantle">
                <div class="flex items-center gap-3 px-4 py-2.5">
                    <i data-lucide="${icon}" class="h-4 w-4 shrink-0 text-mauve"></i>
                    <span class="min-w-0 flex-1 truncate text-sm text-text">${escapeHtml(artifact.label || artifactName(artifact))}</span>
                    <span class="shrink-0 rounded bg-surface0 px-1.5 py-0.5 font-mono text-[10px] uppercase text-subtext0">${escapeHtml(kind)}</span>
                    <span class="shrink-0 text-xs text-overlay1">${escapeHtml(formatBytes(artifact.bytes))}</span>
                    ${toggle}
                    <a href="${escapeHtml(url)}" download class="shrink-0 rounded-md bg-surface0/70 p-1.5 text-subtext0 hover:bg-surface1 hover:text-mauve" title="Download">
                        <i data-lucide="download" class="h-4 w-4"></i>
                    </a>
                </div>
                <div data-body class="p-4"></div>
            </div>`;
    }

    async function fillBody(body, artifact, url, toggleButton) {
        const kind = artifact.kind || 'other';

        if (kind === 'audio') {
            body.innerHTML = `<audio controls preload="metadata" src="${escapeHtml(inlineURL(url))}"></audio>`;
            return;
        }
        if (kind === 'image') {
            body.innerHTML = `<img src="${escapeHtml(inlineURL(url))}" alt="${escapeHtml(
                artifact.label || artifactName(artifact),
            )}" class="mx-auto max-h-[28rem] rounded-lg">`;
            return;
        }
        if (kind === 'archive' || kind === 'other') {
            body.innerHTML = `<p class="text-sm text-overlay1">Download to open this file.</p>`;
            return;
        }

        body.innerHTML = `<p class="text-sm text-overlay1">Loading…</p>`;
        let text;
        try {
            const response = await fetch(inlineURL(url));
            if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
            text = await response.text();
        } catch (error) {
            body.innerHTML = `<p class="text-sm text-red">Could not load this artifact: ${escapeHtml(error.message)}</p>`;
            return;
        }

        if (kind === 'markdown') {
            const rendered = document.createElement('div');
            rendered.className = 'markdown-body max-h-[32rem] overflow-y-auto pr-1';
            const source = document.createElement('pre');
            source.className = 'hidden max-h-[32rem] overflow-auto rounded-lg bg-crust p-3 font-mono text-xs text-subtext0 whitespace-pre-wrap';
            source.textContent = text;
            body.replaceChildren(rendered, source);
            TinyAI.renderMarkdown(rendered, text);
            if (toggleButton) {
                toggleButton.addEventListener('click', () => {
                    const showingSource = !source.classList.contains('hidden');
                    source.classList.toggle('hidden', showingSource);
                    rendered.classList.toggle('hidden', !showingSource);
                    toggleButton.textContent = showingSource ? 'Source' : 'Rendered';
                });
            }
            return;
        }

        let display = text;
        let highlighted = null;
        if (kind === 'json') {
            try {
                display = JSON.stringify(JSON.parse(text), null, 2);
                highlighted = hljs.highlight(display, { language: 'json' }).value;
            } catch {
                highlighted = null;
            }
        }
        body.innerHTML = `<pre class="max-h-[28rem] overflow-auto rounded-lg bg-crust p-3 font-mono text-xs leading-relaxed text-subtext0 whitespace-pre-wrap"><code class="hljs bg-transparent p-0">${
            highlighted || escapeHtml(display)
        }</code></pre>`;
    }

    function comparisonHtml(before, after, beforeURL, afterURL) {
        return `
            <div class="overflow-hidden rounded-xl bg-mantle">
                <div class="flex items-center gap-2 px-4 py-2.5">
                    <i data-lucide="columns-2" class="h-4 w-4 text-mauve"></i>
                    <span class="text-sm text-text">Before and after</span>
                </div>
                <div class="p-4">
                    <div data-cmp class="relative select-none overflow-hidden rounded-lg">
                        <img src="${escapeHtml(inlineURL(afterURL))}" alt="${escapeHtml(after.label || 'After')}" class="block w-full">
                        <img data-cmp-before src="${escapeHtml(inlineURL(beforeURL))}" alt="${escapeHtml(before.label || 'Before')}"
                             class="absolute inset-0 h-full w-full object-fill" style="clip-path: inset(0 50% 0 0)">
                        <div data-cmp-line class="pointer-events-none absolute inset-y-0 w-0.5 bg-mauve" style="left:50%"></div>
                        <span class="absolute left-2 top-2 rounded bg-crust/80 px-2 py-0.5 text-[11px] text-subtext0">${escapeHtml(before.label || 'Before')}</span>
                        <span class="absolute right-2 top-2 rounded bg-crust/80 px-2 py-0.5 text-[11px] text-subtext0">${escapeHtml(after.label || 'After')}</span>
                    </div>
                    <input type="range" data-cmp-range min="0" max="100" value="50" class="mt-3">
                </div>
            </div>`;
    }

    function open(container, jobId, onUpdate) {
        close();

        const view = {
            id: jobId,
            job: { id: jobId, state: 'queued' },
            artifacts: new Map(),
            lastSeq: -1,
            source: null,
            backoff: 500,
            reconnect: null,
            ticker: null,
            finished: false,
            fraction: null,
            chat: null,
        };
        active = view;

        container.innerHTML = shell(view.job);
        lucide.createIcons();

        const q = (selector) => container.querySelector(selector);
        const logBox = q('[data-log]');
        const follow = q('[data-follow]');
        const bar = q('[data-bar]');

        function setState(state) {
            if (!state) return;
            view.job.state = state;
            const meta = stateMeta(state);
            const pill = q('[data-pill]');
            pill.className = `inline-flex items-center gap-1.5 rounded-full bg-${meta.color}/15 px-2.5 py-0.5 text-xs font-medium text-${meta.color}`;
            pill.innerHTML = `<i data-lucide="${meta.icon}" class="h-3.5 w-3.5"></i><span data-pill-label>${escapeHtml(meta.label)}</span>`;
            lucide.createIcons({ root: pill });

            const running = !isTerminal(state);
            q('[data-cancel]').classList.toggle('hidden', !running);
            q('[data-cancel]').classList.toggle('flex', running);
            q('[data-delete]').classList.toggle('hidden', running);
            q('[data-delete]').classList.toggle('flex', !running);
            if (view.chat) view.chat.setLive(running);

            const color =
                state === 'succeeded' ? 'bg-green' : state === 'failed' ? 'bg-red' : state === 'canceled' ? 'bg-peach' : 'bg-mauve';
            const sweeping = running && bar.classList.contains('bar-indeterminate');
            bar.className = `h-full rounded-full ${color} transition-[width] duration-300${sweeping ? ' bar-indeterminate' : ''}`;
            if (running) return;

            // Dropping the sweep class restores the element's auto width, which would read as complete.
            const fraction = state === 'succeeded' ? 1 : (view.fraction ?? 0);
            bar.style.width = `${Math.round(fraction * 100)}%`;
            q('[data-percent]').textContent = `${Math.round(fraction * 100)}%`;
            if (state === 'succeeded') q('[data-counter]').textContent = '';
        }

        function setStream(text, color) {
            const badge = q('[data-stream]');
            if (!text) {
                badge.classList.add('hidden');
                badge.classList.remove('inline-flex');
                return;
            }
            badge.classList.remove('hidden');
            badge.classList.add('inline-flex');
            badge.innerHTML = `<span class="h-1.5 w-1.5 rounded-full bg-${color}"></span><span>${escapeHtml(text)}</span>`;
        }

        function tick() {
            const label = q('[data-elapsed]');
            if (!label) return;
            if (isTerminal(view.job.state) && view.job.durationSeconds) {
                label.textContent = formatDuration(view.job.durationSeconds);
                return;
            }
            const start = Date.parse(view.job.startedAt || view.job.createdAt || '');
            if (Number.isNaN(start)) return;
            label.textContent = formatDuration((Date.now() - start) / 1000);
        }

        function appendLog(level, message, at) {
            const atBottom = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 24;
            const time = at ? new Date(at).toLocaleTimeString([], { hour12: false }) : '';
            const color = LEVEL_COLORS[level] || 'text-subtext0';
            const line = document.createElement('div');
            line.className = 'flex gap-2';
            line.innerHTML = `<span class="shrink-0 text-overlay0">${escapeHtml(time)}</span><span class="w-10 shrink-0 uppercase ${color}">${escapeHtml(
                level || 'info',
            )}</span><span class="min-w-0 flex-1 whitespace-pre-wrap break-words ${color}">${escapeHtml(message)}</span>`;
            logBox.appendChild(line);
            if (follow.checked && atBottom) logBox.scrollTop = logBox.scrollHeight;
        }

        function setProgress(fraction, message, current, total) {
            if (message) q('[data-progress-message]').textContent = message;
            const counter = q('[data-counter]');
            counter.textContent = total ? `${current ?? 0} / ${total}` : '';
            const percent = q('[data-percent]');
            if (fraction === null || fraction === undefined) {
                bar.classList.add('bar-indeterminate');
                bar.style.width = '';
                percent.textContent = '';
                return;
            }
            view.fraction = fraction;
            bar.classList.remove('bar-indeterminate');
            bar.style.width = `${Math.round(fraction * 100)}%`;
            percent.textContent = `${Math.round(fraction * 100)}%`;
        }

        function renderResult(data) {
            if (!data) return;
            q('[data-result-section]').classList.remove('hidden');
            const host = q('[data-result]');
            if (view.job.task === 'dictate' && typeof data.raw === 'string') {
                TinyAI.dictationResult(host, data);
                return;
            }
            if (typeof data.text === 'string') {
                host.innerHTML = `<pre class="max-h-96 overflow-auto whitespace-pre-wrap font-mono text-xs leading-relaxed text-subtext0">${escapeHtml(
                    data.text,
                )}</pre>`;
                wireCopy(data.text);
                return;
            }
            const pretty = JSON.stringify(data, null, 2);
            host.innerHTML = `<pre class="max-h-96 overflow-auto font-mono text-xs leading-relaxed text-subtext0"><code class="hljs bg-transparent p-0">${
                hljs.highlight(pretty, { language: 'json' }).value
            }</code></pre>`;
        }

        function wireCopy(text) {
            const button = q('[data-copy-result]');
            const label = button.querySelector('[data-copy-label]');
            button.classList.remove('hidden');
            button.classList.add('inline-flex');
            button.onclick = async () => {
                await TinyAI.copyText(text);
                label.textContent = 'Copied';
                setTimeout(() => {
                    label.textContent = 'Copy';
                }, 2000);
            };
        }

        function renderComparison() {
            if (view.job.task !== 'upscale') return;
            const images = [...view.artifacts.values()].filter((entry) => entry.artifact.kind === 'image');
            if (images.length < 2) return;
            const host = q('[data-compare]');
            if (host.dataset.built === 'true') return;

            const beforeIndex = images.findIndex((entry) =>
                /original|input|source|before/i.test(entry.artifact.label || artifactName(entry.artifact)),
            );
            const before = images[beforeIndex >= 0 ? beforeIndex : 0];
            const after = images.find((entry) => entry !== before);
            if (!after) return;

            host.innerHTML = comparisonHtml(before.artifact, after.artifact, before.url, after.url);
            host.dataset.built = 'true';
            const range = host.querySelector('[data-cmp-range]');
            const overlay = host.querySelector('[data-cmp-before]');
            const line = host.querySelector('[data-cmp-line]');
            range.addEventListener('input', () => {
                overlay.style.clipPath = `inset(0 ${100 - Number(range.value)}% 0 0)`;
                line.style.left = `${range.value}%`;
            });
            lucide.createIcons({ root: host });
        }

        function addArtifact(artifact) {
            // The dictation pane already carries both transcripts, so its cards would only repeat them.
            if (view.job.task === 'dictate') return;
            const name = artifactName(artifact);
            if (view.artifacts.has(name)) return;
            const url = artifact.url || `/api/jobs/${encodeURIComponent(view.id)}/artifacts/${encodeURIComponent(name)}`;
            view.artifacts.set(name, { artifact, url });

            q('[data-artifacts-section]').classList.remove('hidden');
            const host = q('[data-artifacts]');
            const holder = document.createElement('div');
            holder.innerHTML = artifactCard(artifact, url);
            const card = holder.firstElementChild;
            host.appendChild(card);
            lucide.createIcons({ root: card });
            fillBody(card.querySelector('[data-body]'), artifact, url, card.querySelector('[data-toggle]'));
            renderComparison();
        }

        function showError(message, traceback) {
            const box = q('[data-error]');
            box.classList.remove('hidden');
            q('[data-error-message]').textContent = message || 'The task failed.';
            const trace = q('[data-error-trace]');
            if (traceback) {
                trace.textContent = traceback;
                trace.classList.remove('hidden');
            }
        }

        function applyEvent(event) {
            if (typeof event.seq === 'number') {
                if (event.seq <= view.lastSeq) return;
                view.lastSeq = event.seq;
            }
            if (view.chat) view.chat.apply(event);
            switch (event.event) {
                case 'state':
                    setState(event.state);
                    break;
                case 'start':
                    appendLog('info', 'Runner started', event.at);
                    break;
                case 'log':
                    appendLog(event.level, event.message, event.at);
                    break;
                case 'progress':
                    setProgress(event.fraction, event.message, event.current, event.total);
                    break;
                case 'chat':
                case 'delta':
                    break;
                case 'artifact':
                    addArtifact(event);
                    break;
                case 'result':
                    view.job.result = event.data;
                    renderResult(event.data);
                    break;
                case 'error':
                    showError(event.message, event.traceback);
                    appendLog('error', event.message || 'failed', event.at);
                    break;
                case 'done':
                    view.finished = true;
                    view.job.durationSeconds = event.duration_s;
                    if (!isTerminal(view.job.state)) {
                        setState(event.status === 'ok' ? 'succeeded' : event.status === 'canceled' ? 'canceled' : 'failed');
                    }
                    setStream('', '');
                    tick();
                    if (onUpdate) onUpdate();
                    break;
                default:
                    break;
            }
        }

        function stopStream() {
            if (view.source) {
                view.source.close();
                view.source = null;
            }
            if (view.reconnect) {
                clearTimeout(view.reconnect);
                view.reconnect = null;
            }
        }

        function openStream(from) {
            stopStream();
            setStream('Live', 'green');
            const source = new EventSource(`/api/jobs/${encodeURIComponent(view.id)}/events?from=${from}`);
            view.source = source;
            source.onopen = () => {
                view.backoff = 500;
                setStream('Live', 'green');
            };
            source.onmessage = (message) => {
                view.backoff = 500;
                try {
                    applyEvent(JSON.parse(message.data));
                } catch {
                    // a malformed frame is skipped rather than tearing down the stream
                }
            };
            source.onerror = () => {
                source.close();
                if (view !== active) return;
                if (view.finished || isTerminal(view.job.state)) {
                    setStream('', '');
                    return;
                }
                setStream('Reconnecting', 'yellow');
                view.reconnect = setTimeout(() => openStream(view.lastSeq + 1), view.backoff);
                view.backoff = Math.min(view.backoff * 2, 10000);
            };
        }

        q('[data-cancel]').addEventListener('click', async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            try {
                await apiJSON(`/api/jobs/${encodeURIComponent(view.id)}/cancel`, { method: 'POST' });
            } catch (error) {
                toast(error.message, 'error');
                button.disabled = false;
            }
        });

        q('[data-delete]').addEventListener('click', async () => {
            try {
                await apiJSON(`/api/jobs/${encodeURIComponent(view.id)}`, { method: 'DELETE' });
                if (onUpdate) onUpdate();
                location.hash = '#/';
            } catch (error) {
                toast(error.message, 'error');
            }
        });

        view.ticker = setInterval(tick, 1000);

        (async () => {
            let job;
            try {
                job = await apiJSON(`/api/jobs/${encodeURIComponent(view.id)}`);
            } catch (error) {
                container.innerHTML = `<div class="rounded-xl bg-red/10 p-6 text-sm text-red">Could not load job ${escapeHtml(
                    view.id,
                )}: ${escapeHtml(error.message)}</div>`;
                return;
            }
            if (view !== active) return;

            view.job = Object.assign(view.job, job);
            container.querySelector('h1').textContent = job.title || job.task;
            q('[data-summary]').innerHTML = summaryChips(job);
            lucide.createIcons({ root: q('[data-summary]') });

            const task = TinyAI.findTask ? TinyAI.findTask(job.task) : null;
            if (task && task.interactive) {
                const host = q('[data-chat-host]');
                host.classList.remove('hidden');
                q('[data-progress-panel]').classList.add('hidden');
                view.chat = TinyAI.chatPane(host, job, onUpdate);
            }
            setState(job.state);
            if (job.progress) setProgress(job.progress.fraction, job.progress.message);
            (job.artifacts || []).forEach(addArtifact);
            if (job.result) renderResult(job.result);
            if (job.error) showError(job.error);
            tick();

            const events = Array.isArray(job.events) ? job.events : null;
            if (events) {
                events.forEach(applyEvent);
                if (isTerminal(view.job.state) || view.finished) {
                    setStream('', '');
                    return;
                }
            }
            openStream(view.lastSeq + 1);
        })();
    }

    function close() {
        if (!active) return;
        if (active.source) active.source.close();
        if (active.reconnect) clearTimeout(active.reconnect);
        if (active.ticker) clearInterval(active.ticker);
        active = null;
    }

    TinyAI.jobView = { open, close };
})();
