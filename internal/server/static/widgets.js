(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});
    const { escapeHtml, apiJSON, toast } = TinyAI;

    const CAPTURE_TYPES = [
        ['audio/webm;codecs=opus', 'webm'],
        ['audio/webm', 'webm'],
        ['audio/mp4', 'mp4'],
        ['audio/ogg;codecs=opus', 'ogg'],
    ];

    function captureType() {
        if (typeof MediaRecorder === 'undefined') return null;
        return CAPTURE_TYPES.find(([type]) => MediaRecorder.isTypeSupported(type)) || null;
    }

    // getUserMedia is only defined in a secure context, so plain HTTP over the network cannot record.
    function canRecord() {
        return Boolean(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && captureType());
    }

    function clock(seconds) {
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${String(s).padStart(2, '0')}`;
    }

    const NEEDS_TLS =
        'Recording needs an HTTPS address, so reach the app through a TLS-terminating proxy or from ' +
        'the machine it runs on.';
    const SOFT_BUTTON =
        'inline-flex items-center gap-2 rounded-lg bg-surface0/70 px-3 py-1.5 text-sm text-subtext1 hover:bg-surface1';

    function sourceHtml(body) {
        return `<div data-source class="mt-2 flex flex-col items-center gap-3 rounded-xl bg-mantle/60 px-4 py-7">${body}</div>`;
    }

    function micHtml() {
        return `
            <button type="button" data-record
                    class="flex h-16 w-16 items-center justify-center rounded-full bg-mauve text-crust transition-colors hover:bg-lavender">
                <i data-lucide="mic-vocal" class="h-7 w-7"></i>
            </button>
            <span data-timer class="font-mono text-lg text-text">0:00</span>
            <p data-hint class="text-sm text-subtext0">Tap to start recording</p>`;
    }

    function clipHtml(again) {
        return `
            <div data-clip class="mt-2 hidden space-y-3 rounded-xl bg-mantle/60 p-4">
                <audio controls data-preview preload="metadata"></audio>
                <button type="button" data-again class="${SOFT_BUTTON}">
                    <i data-lucide="rotate-ccw" class="h-4 w-4"></i>
                    <span>${again}</span>
                </button>
            </div>`;
    }

    function recordHtml() {
        if (!canRecord()) {
            return `
                <div class="mt-2 rounded-xl bg-red/10 px-4 py-3 text-sm text-red">
                    This browser will not open the microphone here. ${NEEDS_TLS}
                </div>`;
        }
        return sourceHtml(micHtml()) + clipHtml('Record again');
    }

    function captureHtml(param) {
        const mic = canRecord() ? micHtml() : `<p class="text-center text-sm text-subtext0">${NEEDS_TLS}</p>`;
        const pick = `
            <button type="button" data-choose class="${SOFT_BUTTON}">
                <i data-lucide="folder-open" class="h-4 w-4"></i>
                <span>Pick an audio file</span>
            </button>
            <input type="file" data-file class="hidden" accept="${escapeHtml(param.accept || '')}">`;
        return sourceHtml(mic + pick) + clipHtml('Start over');
    }

    function wireClip(block, setFile) {
        const source = block.querySelector('[data-source]');
        const clip = block.querySelector('[data-clip]');
        const preview = block.querySelector('[data-preview]');
        let previewURL = null;

        function discard() {
            clip.classList.add('hidden');
            source.classList.remove('hidden');
            setFile(null);
        }

        block.querySelector('[data-again]').addEventListener('click', discard);
        block.closest('form').addEventListener('reset', discard);

        return function showClip(file) {
            if (previewURL) URL.revokeObjectURL(previewURL);
            previewURL = URL.createObjectURL(file);
            preview.src = previewURL;
            source.classList.add('hidden');
            clip.classList.remove('hidden');
            setFile(file);
        };
    }

    function createRecorder(name, handlers) {
        let media = null;
        let stream = null;
        let ticker = null;

        async function start() {
            try {
                stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch (error) {
                toast(`Could not open the microphone: ${error.message}`, 'error');
                return;
            }
            const [type, extension] = captureType();
            const chunks = [];
            media = new MediaRecorder(stream, { mimeType: type });
            media.addEventListener('dataavailable', (event) => {
                if (event.data.size) chunks.push(event.data);
            });
            media.addEventListener('stop', () => {
                stream.getTracks().forEach((track) => track.stop());
                stream = null;
                clearInterval(ticker);
                ticker = null;
                media = null;
                handlers.onStop(new File(chunks, `${name}.${extension}`, { type }));
            });
            media.start();

            const startedAt = Date.now();
            handlers.onStart();
            ticker = setInterval(() => handlers.onTick((Date.now() - startedAt) / 1000), 250);
        }

        return {
            recording: () => Boolean(media) && media.state === 'recording',
            toggle: () => (media && media.state === 'recording' ? media.stop() : start()),
        };
    }

    function wireMic(block, showClip, name) {
        const button = block.querySelector('[data-record]');
        if (!button) return;

        const timer = block.querySelector('[data-timer]');
        const hint = block.querySelector('[data-hint]');

        function paint(icon, message) {
            hint.textContent = message;
            button.innerHTML = `<i data-lucide="${icon}" class="h-7 w-7"></i>`;
            lucide.createIcons({ root: button });
        }

        const recorder = createRecorder(name, {
            onStart() {
                button.classList.remove('bg-mauve', 'hover:bg-lavender');
                button.classList.add('bg-red', 'hover:bg-maroon', 'animate-pulse');
                paint('circle-stop', 'Tap to stop');
            },
            onTick(seconds) {
                timer.textContent = clock(seconds);
            },
            onStop(file) {
                timer.textContent = '0:00';
                button.classList.remove('bg-red', 'hover:bg-maroon', 'animate-pulse');
                button.classList.add('bg-mauve', 'hover:bg-lavender');
                paint('mic-vocal', 'Tap to start recording');
                showClip(file);
            },
        });

        button.addEventListener('click', recorder.toggle);
    }

    function wireRecord(block, setFile) {
        if (!canRecord()) return;
        wireMic(block, wireClip(block, setFile), 'dictation');
    }

    function wireCapture(block, setFile) {
        const showClip = wireClip(block, setFile);
        wireMic(block, showClip, 'reference');

        const input = block.querySelector('[data-file]');
        block.querySelector('[data-choose]').addEventListener('click', () => input.click());
        input.addEventListener('change', () => {
            const file = input.files[0];
            // Clearing the input lets the same file be picked again after starting over.
            input.value = '';
            if (file) showClip(file);
        });
    }

    function chipHtml(term, index) {
        return `
            <span class="inline-flex items-center gap-1.5 rounded-lg bg-surface0/70 px-2.5 py-1 text-sm text-subtext1">
                <span class="font-mono">${escapeHtml(term)}</span>
                <button type="button" data-drop-term="${index}" class="text-overlay1 hover:text-red" title="Remove">
                    <i data-lucide="x" class="h-3.5 w-3.5"></i>
                </button>
            </span>`;
    }

    function correctionHtml(entry, index) {
        return `
            <div class="flex items-center gap-2 rounded-lg bg-surface0/50 px-2.5 py-1.5 text-sm">
                <span class="min-w-0 flex-1 truncate font-mono text-overlay1">${escapeHtml(entry.from)}</span>
                <i data-lucide="arrow-right" class="h-3.5 w-3.5 shrink-0 text-overlay0"></i>
                <span class="min-w-0 flex-1 truncate font-mono text-subtext1">${escapeHtml(entry.to)}</span>
                <button type="button" data-drop-correction="${index}" class="shrink-0 text-overlay1 hover:text-red" title="Remove">
                    <i data-lucide="x" class="h-3.5 w-3.5"></i>
                </button>
            </div>`;
    }

    const ADD_BUTTON =
        'shrink-0 rounded-lg bg-surface0/70 px-2.5 py-2 text-subtext1 hover:bg-surface1 hover:text-mauve';
    const TEXT_INPUT =
        'min-w-0 flex-1 rounded-lg bg-surface0/60 px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:ring-1 focus:ring-mauve/60';

    function lexiconHtml() {
        return `
            <div class="mt-3 space-y-4">
                <div class="space-y-2">
                    <div class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-overlay1">
                        <i data-lucide="book-a" class="h-3.5 w-3.5"></i>
                        <span>Vocabulary</span>
                    </div>
                    <div data-terms class="flex flex-wrap gap-2"></div>
                    <div class="flex items-center gap-2">
                        <input type="text" data-new-term placeholder="A word to spell exactly this way" class="${TEXT_INPUT}">
                        <button type="button" data-add-term class="${ADD_BUTTON}" title="Add">
                            <i data-lucide="plus" class="h-4 w-4"></i>
                        </button>
                    </div>
                </div>

                <div class="space-y-2">
                    <div class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-overlay1">
                        <i data-lucide="spell-check" class="h-3.5 w-3.5"></i>
                        <span>Known mishearings</span>
                    </div>
                    <div data-corrections class="space-y-1.5"></div>
                    <div class="flex items-center gap-2">
                        <input type="text" data-new-from placeholder="What it heard" class="${TEXT_INPUT}">
                        <input type="text" data-new-to placeholder="What you meant" class="${TEXT_INPUT}">
                        <button type="button" data-add-correction class="${ADD_BUTTON}" title="Add">
                            <i data-lucide="plus" class="h-4 w-4"></i>
                        </button>
                    </div>
                </div>
            </div>`;
    }

    function wireLexicon(block, setFile) {
        const terms = block.querySelector('[data-terms]');
        const corrections = block.querySelector('[data-corrections]');
        let state = { vocabulary: [], corrections: [] };

        function attach() {
            setFile(
                new File([JSON.stringify(state, null, 2)], 'lexicon.json', { type: 'application/json' }),
            );
        }

        function paint() {
            terms.innerHTML = state.vocabulary.length
                ? state.vocabulary.map(chipHtml).join('')
                : '<span class="text-sm text-overlay0">No words yet.</span>';
            corrections.innerHTML = state.corrections.length
                ? state.corrections.map(correctionHtml).join('')
                : '<span class="text-sm text-overlay0">No corrections yet.</span>';
            lucide.createIcons({ root: block });
            attach();
        }

        async function save() {
            try {
                state = await apiJSON('/api/lexicon', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(state),
                });
            } catch (error) {
                toast(`Could not save the vocabulary: ${error.message}`, 'error');
            }
            paint();
        }

        function addTerm() {
            const input = block.querySelector('[data-new-term]');
            if (!input.value.trim()) return;
            state.vocabulary.push(input.value.trim());
            input.value = '';
            save();
        }

        function addCorrection() {
            const from = block.querySelector('[data-new-from]');
            const to = block.querySelector('[data-new-to]');
            if (!from.value.trim() || !to.value.trim()) return;
            state.corrections.push({ from: from.value.trim(), to: to.value.trim() });
            from.value = '';
            to.value = '';
            save();
        }

        block.querySelector('[data-add-term]').addEventListener('click', addTerm);
        block.querySelector('[data-add-correction]').addEventListener('click', addCorrection);
        block.addEventListener('click', (event) => {
            const term = event.target.closest('[data-drop-term]');
            if (term) {
                state.vocabulary.splice(Number(term.dataset.dropTerm), 1);
                save();
                return;
            }
            const correction = event.target.closest('[data-drop-correction]');
            if (correction) {
                state.corrections.splice(Number(correction.dataset.dropCorrection), 1);
                save();
            }
        });
        // The widget sits inside the task form, where a bare Enter would submit the job instead.
        block.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter') return;
            event.preventDefault();
            if (event.target.matches('[data-new-term]')) addTerm();
            if (event.target.matches('[data-new-from], [data-new-to]')) addCorrection();
        });

        apiJSON('/api/lexicon')
            .then((loaded) => {
                state = loaded || state;
            })
            .catch((error) => toast(`Could not load the vocabulary: ${error.message}`, 'error'))
            .finally(paint);
    }

    function seedHtml() {
        return `
            <div class="mt-2 space-y-2">
                <div class="flex items-center gap-2">
                    <input type="text" inputmode="numeric" data-input="seed"
                           placeholder="A new seed every run" class="${TEXT_INPUT}">
                    <button type="button" data-lock class="${ADD_BUTTON}" title="Hold the last seed">
                        <i data-lucide="lock-open" class="h-4 w-4"></i>
                    </button>
                </div>
                <button type="button" data-previous class="hidden text-xs text-overlay1 hover:text-mauve">
                    Last run drew <span data-previous-seed class="font-mono"></span>
                </button>
            </div>`;
    }

    function wireSeed(block) {
        const input = block.querySelector('[data-input="seed"]');
        const lock = block.querySelector('[data-lock]');
        const previous = block.querySelector('[data-previous]');
        let last = null;

        function setLocked(locked) {
            input.readOnly = locked;
            input.classList.toggle('text-text', !locked);
            input.classList.toggle('text-mauve', locked);
            lock.innerHTML = `<i data-lucide="${locked ? 'lock' : 'lock-open'}" class="h-4 w-4"></i>`;
            lucide.createIcons({ root: lock });
        }

        lock.addEventListener('click', () => {
            const locking = !input.readOnly;
            if (locking && !input.value) {
                if (last === null) {
                    toast('No earlier generation to take a seed from.', 'error');
                    return;
                }
                input.value = last;
            }
            if (!locking) input.value = '';
            setLocked(locking);
        });

        previous.addEventListener('click', () => {
            input.value = last;
        });

        input.addEventListener('input', () => {
            input.value = input.value.replace(/[^0-9]/g, '');
        });

        block.closest('form').addEventListener('reset', () => setLocked(false));

        apiJSON('/api/jobs')
            .then((data) => {
                const drawn = (data.jobs || []).find((job) => Number.isInteger(job.result && job.result.seed));
                if (!drawn) return;
                last = drawn.result.seed;
                block.querySelector('[data-previous-seed]').textContent = last;
                previous.classList.remove('hidden');
            })
            .catch(() => {});
    }

    TinyAI.recorder = { canRecord, create: createRecorder, needsTLS: NEEDS_TLS, clock };

    TinyAI.widgets = {
        record: { html: recordHtml, wire: wireRecord },
        capture: { html: captureHtml, wire: wireCapture },
        lexicon: { html: lexiconHtml, wire: wireLexicon },
        seed: { html: seedHtml, wire: wireSeed },
    };
})();
