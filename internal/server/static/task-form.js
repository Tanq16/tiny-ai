(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});
    const { escapeHtml, formatBytes, groupColor } = TinyAI;

    function labelHtml(param) {
        const required = param.required ? '<span class="text-red ml-0.5">*</span>' : '';
        return `<span class="text-sm font-medium text-text">${escapeHtml(param.label)}${required}</span>`;
    }

    function helpHtml(param) {
        if (!param.help) return '';
        return `<p class="mt-1.5 text-xs text-overlay1">${escapeHtml(param.help)}</p>`;
    }

    function acceptSummary(accept) {
        if (!accept) return 'Any file type';
        return accept
            .split(',')
            .map((ext) => ext.trim().replace(/^\./, '').toUpperCase())
            .join(' · ');
    }

    function fileControl(param) {
        return `
            <div data-dropzone
                 class="mt-2 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-surface1 bg-mantle/60 px-4 py-7 text-center cursor-pointer transition-colors hover:border-mauve hover:bg-surface0/40">
                <i data-lucide="upload-cloud" class="w-7 h-7 text-overlay1"></i>
                <p class="text-sm text-subtext0">Drop a file here or <span class="text-mauve font-medium">browse</span></p>
                <p class="text-[11px] text-overlay0 break-all">${escapeHtml(acceptSummary(param.accept))}</p>
                <input type="file" class="hidden" data-input="${escapeHtml(param.name)}"
                       ${param.accept ? `accept="${escapeHtml(param.accept)}"` : ''}>
            </div>
            <div data-chosen class="mt-2 hidden items-center gap-3 rounded-lg bg-surface0/50 px-3 py-2">
                <i data-lucide="file" class="w-4 h-4 text-mauve shrink-0"></i>
                <span data-chosen-name class="flex-1 min-w-0 truncate text-sm text-text"></span>
                <span data-chosen-size class="text-xs text-overlay1 shrink-0"></span>
                <button type="button" data-clear class="text-overlay1 hover:text-red shrink-0" title="Remove file">
                    <i data-lucide="x" class="w-4 h-4"></i>
                </button>
            </div>`;
    }

    function textControl(param) {
        return `<input type="text" data-input="${escapeHtml(param.name)}" value="${escapeHtml(param.default || '')}"
                       class="mt-2 w-full rounded-lg bg-surface0/60 px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:ring-1 focus:ring-mauve/60">`;
    }

    function textareaControl(param) {
        return `<textarea rows="5" data-input="${escapeHtml(param.name)}"
                          class="mt-2 w-full rounded-lg bg-surface0/60 px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:ring-1 focus:ring-mauve/60 resize-y">${escapeHtml(param.default || '')}</textarea>`;
    }

    function selectControl(param) {
        const options = (param.options || [])
            .map((option) => {
                const selected = option.value === param.default ? ' selected' : '';
                return `<option value="${escapeHtml(option.value)}"${selected}>${escapeHtml(option.label)}</option>`;
            })
            .join('');
        return `<select data-input="${escapeHtml(param.name)}"
                        class="mt-2 w-full rounded-lg bg-surface0/60 px-3 py-2 text-sm text-text focus:outline-none focus:ring-1 focus:ring-mauve/60">${options}</select>`;
    }

    function numberControl(param) {
        const min = param.min ?? 0;
        const max = param.max ?? 100;
        const step = param.step || 1;
        const value = param.default !== undefined && param.default !== '' ? param.default : min;
        return `
            <div class="mt-3">
                <input type="range" data-input="${escapeHtml(param.name)}"
                       min="${min}" max="${max}" step="${step}" value="${escapeHtml(value)}">
                <div class="mt-1.5 flex items-center justify-between text-[11px] text-overlay0">
                    <span>${min}</span>
                    <span>${max}</span>
                </div>
            </div>`;
    }

    function boolControl(param) {
        const checked = param.default === 'true' ? ' checked' : '';
        return `
            <label class="mt-1 inline-flex items-center gap-3 cursor-pointer">
                <input type="checkbox" class="peer sr-only" data-input="${escapeHtml(param.name)}"${checked}>
                <span class="relative h-6 w-11 shrink-0 rounded-full bg-surface1 transition-colors peer-checked:bg-mauve peer-focus-visible:ring-2 peer-focus-visible:ring-lavender after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-text after:transition-transform after:content-[''] peer-checked:after:translate-x-5 peer-checked:after:bg-crust"></span>
                <span class="text-sm text-subtext1">${escapeHtml(param.label)}</span>
            </label>`;
    }

    const CONTROLS = {
        file: fileControl,
        textarea: textareaControl,
        select: selectControl,
        number: numberControl,
        bool: boolControl,
        text: textControl,
    };

    function paramHtml(param) {
        const when = param.visibleWhen
            ? ` data-when-param="${escapeHtml(param.visibleWhen.param)}" data-when-equals="${escapeHtml(param.visibleWhen.equals)}"`
            : '';
        const widget = param.widget && TinyAI.widgets[param.widget];
        const body = widget ? widget.html(param) : (CONTROLS[param.type] || textControl)(param);

        const heading =
            param.type === 'bool'
                ? ''
                : `<div class="flex items-baseline justify-between gap-3">${labelHtml(param)}${
                      param.type === 'number' ? '<span data-value class="font-mono text-sm text-mauve"></span>' : ''
                  }</div>`;

        const wide = param.type === 'textarea' || param.type === 'file';
        return `
            <div data-param="${escapeHtml(param.name)}" data-type="${escapeHtml(param.type)}"${when}
                 class="rounded-xl bg-mantle/50 p-4${wide ? ' sm:col-span-2 min-[1800px]:col-span-3' : ''}">
                ${heading}
                ${body}
                ${helpHtml(param)}
                <p data-error class="mt-1.5 hidden text-xs text-red"></p>
            </div>`;
    }

    function renderTaskForm(container, task, onSubmit) {
        const color = groupColor(task.group);
        container.innerHTML = `
            <div class="space-y-5">
                <div class="flex items-start gap-4">
                    <a href="#/" class="mt-1 shrink-0 rounded-lg bg-surface0/70 p-2 text-overlay1 hover:bg-surface1 hover:text-text" title="Back to tasks">
                        <i data-lucide="arrow-left" class="w-4 h-4"></i>
                    </a>
                    <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-${color}/15 text-${color}">
                        <i data-lucide="${escapeHtml(task.icon)}" class="w-6 h-6"></i>
                    </div>
                    <div class="min-w-0">
                        <div class="flex flex-wrap items-center gap-2">
                            <h1 class="font-display text-xl font-semibold text-text">${escapeHtml(task.title)}</h1>
                            <span class="rounded-full bg-surface0 px-2 py-0.5 font-mono text-[11px] text-subtext0">${escapeHtml(task.engine)}</span>
                        </div>
                        <p class="mt-1 text-sm text-subtext0">${escapeHtml(task.description)}</p>
                    </div>
                </div>

                <form data-form class="space-y-4">
                    <div class="grid gap-3 sm:grid-cols-2 min-[1800px]:grid-cols-3">${(task.params || []).map(paramHtml).join('')}</div>
                    <div data-form-error class="hidden rounded-lg bg-red/10 px-3 py-2 text-sm text-red"></div>
                    <div class="flex items-center gap-3 pt-1">
                        <button type="submit" data-submit
                                class="inline-flex items-center gap-2 rounded-lg bg-mauve px-4 py-2 text-sm font-semibold text-crust hover:bg-lavender disabled:opacity-60">
                            <i data-lucide="play" class="w-4 h-4"></i>
                            <span>Run task</span>
                        </button>
                        <button type="reset" data-reset
                                class="inline-flex items-center gap-2 rounded-lg bg-surface0/70 px-4 py-2 text-sm text-subtext1 hover:bg-surface1">
                            <i data-lucide="rotate-ccw" class="w-4 h-4"></i>
                            <span>Reset</span>
                        </button>
                    </div>
                </form>
            </div>`;

        const form = container.querySelector('[data-form]');
        const files = new Map();

        function controlOf(name) {
            return form.querySelector(`[data-input="${CSS.escape(name)}"]`);
        }

        function valueOf(param) {
            if (param.type === 'file') return files.has(param.name) ? files.get(param.name).name : '';
            const control = controlOf(param.name);
            if (!control) return '';
            if (param.type === 'bool') return control.checked ? 'true' : 'false';
            return control.value;
        }

        function isVisible(param) {
            if (!param.visibleWhen) return true;
            const owner = (task.params || []).find((p) => p.name === param.visibleWhen.param);
            return owner ? valueOf(owner) === param.visibleWhen.equals : true;
        }

        function applyVisibility() {
            (task.params || []).forEach((param) => {
                const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
                if (block) block.classList.toggle('hidden', !isVisible(param));
            });
        }

        function syncNumbers() {
            (task.params || [])
                .filter((param) => param.type === 'number')
                .forEach((param) => {
                    const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
                    const control = controlOf(param.name);
                    const readout = block && block.querySelector('[data-value]');
                    if (readout && control) readout.textContent = control.value;
                });
        }

        function showFile(param, file) {
            const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
            const chosen = block.querySelector('[data-chosen]');
            const zone = block.querySelector('[data-dropzone]');
            if (!file) {
                files.delete(param.name);
                controlOf(param.name).value = '';
                chosen.classList.add('hidden');
                chosen.classList.remove('flex');
                zone.classList.remove('hidden');
                return;
            }
            files.set(param.name, file);
            block.querySelector('[data-chosen-name]').textContent = file.name;
            block.querySelector('[data-chosen-size]').textContent = formatBytes(file.size);
            chosen.classList.remove('hidden');
            chosen.classList.add('flex');
            zone.classList.add('hidden');
        }

        (task.params || [])
            .filter((param) => param.widget && TinyAI.widgets[param.widget])
            .forEach((param) => {
                const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
                TinyAI.widgets[param.widget].wire(block, (file) => {
                    if (file) files.set(param.name, file);
                    else files.delete(param.name);
                });
            });

        (task.params || [])
            .filter((param) => param.type === 'file' && !param.widget)
            .forEach((param) => {
                const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
                const zone = block.querySelector('[data-dropzone]');
                const input = controlOf(param.name);

                zone.addEventListener('click', () => input.click());
                input.addEventListener('change', () => showFile(param, input.files[0] || null));
                block.querySelector('[data-clear]').addEventListener('click', () => showFile(param, null));

                ['dragenter', 'dragover'].forEach((name) =>
                    zone.addEventListener(name, (event) => {
                        event.preventDefault();
                        zone.classList.add('border-mauve', 'bg-surface0/60');
                    }),
                );
                ['dragleave', 'drop'].forEach((name) =>
                    zone.addEventListener(name, (event) => {
                        event.preventDefault();
                        zone.classList.remove('border-mauve', 'bg-surface0/60');
                    }),
                );
                zone.addEventListener('drop', (event) => {
                    const file = event.dataTransfer && event.dataTransfer.files[0];
                    if (file) showFile(param, file);
                });
            });

        form.addEventListener('input', () => {
            syncNumbers();
            applyVisibility();
        });
        form.addEventListener('change', applyVisibility);
        form.addEventListener('reset', () => {
            setTimeout(() => {
                (task.params || [])
                    .filter((param) => param.type === 'file' && !param.widget)
                    .forEach((param) => showFile(param, null));
                syncNumbers();
                applyVisibility();
            }, 0);
        });

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const banner = form.querySelector('[data-form-error]');
            banner.classList.add('hidden');
            form.querySelectorAll('[data-error]').forEach((node) => node.classList.add('hidden'));

            const payload = new FormData();
            payload.append('task', task.id);
            let invalid = 0;

            for (const param of task.params || []) {
                if (!isVisible(param)) continue;
                const value = valueOf(param);
                if (param.required && !value) {
                    const block = form.querySelector(`[data-param="${CSS.escape(param.name)}"]`);
                    const error = block.querySelector('[data-error]');
                    error.textContent = `${param.label} is required.`;
                    error.classList.remove('hidden');
                    invalid += 1;
                    continue;
                }
                if (param.type === 'file') {
                    if (files.has(param.name)) payload.append(param.name, files.get(param.name));
                    continue;
                }
                if (param.type === 'text' || param.type === 'textarea') {
                    if (value !== '') payload.append(param.name, value);
                    continue;
                }
                payload.append(param.name, value);
            }

            if (invalid > 0) {
                banner.textContent = `Fill in ${invalid} required ${invalid === 1 ? 'field' : 'fields'} before running.`;
                banner.classList.remove('hidden');
                return;
            }

            const button = form.querySelector('[data-submit]');
            button.disabled = true;
            try {
                await onSubmit(payload);
            } catch (error) {
                banner.textContent = error.message;
                banner.classList.remove('hidden');
            } finally {
                button.disabled = false;
            }
        });

        syncNumbers();
        applyVisibility();
        lucide.createIcons();
    }

    TinyAI.renderTaskForm = renderTaskForm;
})();
