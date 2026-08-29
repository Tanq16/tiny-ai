(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});
    const { escapeHtml, formatBytes, apiJSON, toast } = TinyAI;

    const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tiff'];
    const ACCEPT = `.${IMAGE_EXTS.join(',.')},.mp3,.wav,.flac,.m4a,.opus,.ogg,.aac,.webm,.mp4`;
    const ACCEPT_EXTS = ACCEPT.split(',').map((entry) => entry.slice(1));
    const PASTE_EXTS = {
        'image/png': 'png',
        'image/jpeg': 'jpg',
        'image/webp': 'webp',
        'image/bmp': 'bmp',
        'image/gif': 'gif',
        'image/tiff': 'tiff',
        'audio/mpeg': 'mp3',
        'audio/wav': 'wav',
        'audio/x-wav': 'wav',
        'audio/flac': 'flac',
        'audio/mp4': 'm4a',
        'audio/ogg': 'ogg',
        'audio/opus': 'opus',
        'audio/aac': 'aac',
        'audio/webm': 'webm',
    };

    const ICON_BUTTON =
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surface0/70 text-subtext1 ' +
        'transition-colors hover:bg-surface1 hover:text-mauve disabled:cursor-not-allowed disabled:opacity-40';
    const SEND_BUTTON =
        'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-mauve text-crust ' +
        'transition-colors hover:bg-lavender disabled:cursor-not-allowed disabled:opacity-40';

    function extensionOf(name) {
        return String(name).split('.').pop().toLowerCase();
    }

    function isImage(name) {
        return IMAGE_EXTS.includes(extensionOf(name));
    }

    function namePasted(file, ordinal) {
        if (file.name && ACCEPT_EXTS.includes(extensionOf(file.name))) return file;
        const ext = PASTE_EXTS[file.type];
        return ext ? new File([file], `pasted-${ordinal}.${ext}`, { type: file.type }) : null;
    }

    function inputURL(jobId, name) {
        return `/api/jobs/${encodeURIComponent(jobId)}/inputs/${encodeURIComponent(name)}?inline=1`;
    }

    function attachmentHtml(jobId, name) {
        const url = inputURL(jobId, name);
        if (isImage(name)) {
            return `<img src="${escapeHtml(url)}" alt="${escapeHtml(name)}" class="max-h-56 rounded-lg">`;
        }
        return `<audio controls preload="metadata" src="${escapeHtml(url)}"></audio>`;
    }

    function paneHtml() {
        return `
            <div class="space-y-3">
                <div data-thread class="min-h-[16rem] max-h-[60vh] space-y-4 overflow-y-auto rounded-xl bg-mantle p-4">
                    <p data-empty class="py-10 text-center text-sm text-overlay0">
                        Say something to load the model and start.
                    </p>
                </div>

                <div data-composer class="rounded-xl bg-mantle p-3">
                    <div data-chips class="mb-2 hidden flex-wrap gap-2"></div>
                    <div class="flex items-end gap-2">
                        <textarea data-message rows="1" placeholder="Message the model"
                                  class="max-h-40 min-h-9 w-full flex-1 resize-none rounded-lg bg-surface0/60 px-3 py-2 text-sm text-text placeholder:text-overlay0 focus:outline-none focus:ring-1 focus:ring-mauve/60"></textarea>
                        <button type="button" data-attach class="${ICON_BUTTON}" title="Attach a picture or a recording">
                            <i data-lucide="paperclip" class="h-4 w-4"></i>
                        </button>
                        <button type="button" data-mic class="${ICON_BUTTON}" title="Record a voice message">
                            <i data-lucide="mic" class="h-4 w-4"></i>
                        </button>
                        <button type="button" data-send class="${SEND_BUTTON}" title="Send">
                            <i data-lucide="send-horizontal" class="h-4 w-4"></i>
                        </button>
                        <input type="file" data-picker multiple class="hidden" accept="${ACCEPT}">
                    </div>
                    <p data-note class="mt-2 hidden text-xs text-overlay1"></p>
                </div>

                <div class="flex items-center justify-between gap-3">
                    <span data-status class="text-xs text-overlay1"></span>
                    <button type="button" data-finish
                            class="inline-flex items-center gap-2 rounded-lg bg-surface0/70 px-3 py-1.5 text-sm text-subtext1 hover:bg-surface1">
                        <i data-lucide="check-check" class="h-4 w-4"></i>
                        <span>Finish chat</span>
                    </button>
                </div>
            </div>`;
    }

    function chipHtml(index, file) {
        const icon = isImage(file.name) ? 'image' : 'audio-lines';
        return `
            <span class="inline-flex max-w-full items-center gap-2 rounded-lg bg-surface0/70 px-2.5 py-1 text-xs text-subtext1">
                <i data-lucide="${icon}" class="h-3.5 w-3.5 shrink-0 text-mauve"></i>
                <span class="min-w-0 truncate">${escapeHtml(file.name)}</span>
                <span class="shrink-0 text-overlay0">${escapeHtml(formatBytes(file.size))}</span>
                <button type="button" data-drop="${index}" class="shrink-0 text-overlay1 hover:text-red" title="Remove">
                    <i data-lucide="x" class="h-3.5 w-3.5"></i>
                </button>
            </span>`;
    }

    function mount(host, job, onUpdate) {
        host.innerHTML = paneHtml();
        lucide.createIcons({ root: host });

        const q = (selector) => host.querySelector(selector);
        const thread = q('[data-thread]');
        const composer = q('[data-composer]');
        const chips = q('[data-chips]');
        const input = q('[data-message]');
        const picker = q('[data-picker]');
        const micButton = q('[data-mic]');
        const sendButton = q('[data-send]');
        const note = q('[data-note]');
        const status = q('[data-status]');

        let attachments = [];
        let pasted = 0;
        let streaming = null;
        let waiting = false;
        let live = true;

        function atBottom() {
            return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 40;
        }

        function scroll(wasAtBottom) {
            if (wasAtBottom) thread.scrollTop = thread.scrollHeight;
        }

        function addNode(node) {
            const wasAtBottom = atBottom();
            const empty = q('[data-empty]');
            if (empty) empty.remove();
            thread.appendChild(node);
            scroll(wasAtBottom);
            return node;
        }

        function setNote(message) {
            note.textContent = message || '';
            note.classList.toggle('hidden', !message);
        }

        function setStatus(message) {
            status.textContent = message || '';
        }

        function setWaiting(value) {
            waiting = value;
            sendButton.disabled = waiting || !live;
            micButton.disabled = waiting || !live || !TinyAI.recorder.canRecord();
            q('[data-attach]').disabled = waiting || !live;
            input.disabled = !live;
            setStatus(waiting ? 'Thinking' : '');
        }

        function paintChips() {
            chips.innerHTML = attachments.map((file, index) => chipHtml(index, file)).join('');
            chips.classList.toggle('hidden', !attachments.length);
            chips.classList.toggle('flex', Boolean(attachments.length));
            lucide.createIcons({ root: chips });
        }

        function userTurn(text, files) {
            const media = (files || []).map((name) => attachmentHtml(job.id, name)).join('');
            const node = document.createElement('div');
            node.className = 'flex justify-end';
            node.innerHTML = `
                <div class="max-w-[85%] space-y-2 rounded-xl rounded-br-sm bg-surface0/70 px-3.5 py-2.5">
                    ${media ? `<div class="space-y-2">${media}</div>` : ''}
                    ${text ? `<p class="whitespace-pre-wrap break-words text-sm text-text">${escapeHtml(text)}</p>` : ''}
                </div>`;
            addNode(node);
        }

        function errorTurn(message) {
            const node = document.createElement('div');
            node.className = 'rounded-xl bg-red/10 px-3.5 py-2.5 text-sm text-red';
            node.textContent = message;
            addNode(node);
        }

        function streamingNode() {
            if (streaming) return streaming;
            const node = document.createElement('div');
            node.className = 'markdown-body max-w-none whitespace-pre-wrap break-words';
            streaming = addNode(node);
            streaming.dataset.buffer = '';
            return streaming;
        }

        function assistantDelta(text) {
            const node = streamingNode();
            const wasAtBottom = atBottom();
            node.dataset.buffer += text;
            node.textContent = node.dataset.buffer;
            scroll(wasAtBottom);
        }

        function assistantTurn(text) {
            const wasAtBottom = atBottom();
            const node = streamingNode();
            node.classList.remove('whitespace-pre-wrap', 'break-words');
            node.removeAttribute('data-buffer');
            TinyAI.renderMarkdown(node, text);
            streaming = null;
            scroll(wasAtBottom);
        }

        function clearAttachments() {
            attachments = [];
            paintChips();
        }

        async function send() {
            const text = input.value.trim();
            if (!text && !attachments.length) return;

            const payload = new FormData();
            payload.append('text', text);
            attachments.forEach((file) => payload.append('file', file));
            setWaiting(true);
            try {
                await apiJSON(`/api/jobs/${encodeURIComponent(job.id)}/messages`, { method: 'POST', body: payload });
            } catch (error) {
                toast(error.message, 'error');
                setWaiting(false);
                return;
            }
            input.value = '';
            input.style.height = '';
            clearAttachments();
            if (onUpdate) onUpdate();
        }

        const recorder = TinyAI.recorder.create('recording', {
            onStart() {
                micButton.classList.add('bg-red', 'text-crust', 'hover:bg-maroon');
                micButton.classList.remove('bg-surface0/70', 'text-subtext1');
                micButton.title = 'Stop recording';
            },
            onTick(seconds) {
                setStatus(`Recording ${TinyAI.recorder.clock(seconds)}`);
            },
            onStop(file) {
                micButton.classList.remove('bg-red', 'text-crust', 'hover:bg-maroon');
                micButton.classList.add('bg-surface0/70', 'text-subtext1');
                micButton.title = 'Record a voice message';
                setStatus('');
                attachments.push(file);
                paintChips();
            },
        });

        micButton.addEventListener('click', recorder.toggle);
        q('[data-attach]').addEventListener('click', () => picker.click());
        picker.addEventListener('change', () => {
            attachments.push(...picker.files);
            picker.value = '';
            paintChips();
        });
        input.addEventListener('paste', (event) => {
            const dropped = Array.from(event.clipboardData ? event.clipboardData.files : []);
            if (!dropped.length) return;
            event.preventDefault();
            const kept = dropped.map((file) => namePasted(file, ++pasted)).filter(Boolean);
            if (kept.length < dropped.length) toast('Only pictures and recordings can be attached', 'error');
            if (!kept.length) return;
            attachments.push(...kept);
            paintChips();
        });
        chips.addEventListener('click', (event) => {
            const drop = event.target.closest('[data-drop]');
            if (!drop) return;
            attachments.splice(Number(drop.dataset.drop), 1);
            paintChips();
        });

        sendButton.addEventListener('click', send);
        input.addEventListener('keydown', (event) => {
            if (event.key !== 'Enter' || event.shiftKey) return;
            event.preventDefault();
            if (!sendButton.disabled) send();
        });
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = `${input.scrollHeight}px`;
        });

        q('[data-finish]').addEventListener('click', async (event) => {
            event.currentTarget.disabled = true;
            try {
                await apiJSON(`/api/jobs/${encodeURIComponent(job.id)}/finish`, { method: 'POST' });
            } catch (error) {
                toast(error.message, 'error');
                event.currentTarget.disabled = false;
            }
        });

        if (!TinyAI.recorder.canRecord()) setNote(TinyAI.recorder.needsTLS);
        setWaiting(false);

        return {
            apply(event) {
                switch (event.event) {
                    case 'chat':
                        if (event.role === 'user') {
                            userTurn(event.message, event.files);
                            setWaiting(true);
                            return;
                        }
                        if (event.role === 'error') errorTurn(event.message);
                        else assistantTurn(event.message || '');
                        streaming = null;
                        setWaiting(false);
                        return;
                    case 'delta':
                        assistantDelta(event.message || '');
                        return;
                    case 'progress':
                        if (event.message && !waiting) setStatus(event.message);
                        return;
                    case 'start':
                        if (event.data && event.data.audio === false) {
                            micButton.disabled = true;
                            setNote(`${event.data.model} has no audio encoder, so it reads pictures but cannot listen.`);
                        }
                        return;
                    default:
                }
            },
            setLive(value) {
                live = value;
                composer.classList.toggle('hidden', !live);
                q('[data-finish]').classList.toggle('hidden', !live);
                q('[data-finish]').classList.toggle('inline-flex', live);
                setWaiting(waiting && live);
                if (!live) {
                    streaming = null;
                    setStatus('This chat is closed. Its history stays here until the job is deleted.');
                }
            },
        };
    }

    TinyAI.chatPane = mount;
})();
