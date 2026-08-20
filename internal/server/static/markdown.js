(function () {
    'use strict';

    const TinyAI = (window.TinyAI = window.TinyAI || {});

    function generateId(text) {
        return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)+/g, '');
    }

    function initMarked() {
        const renderer = {
            code(token) {
                const text = token.text;
                const language = token.lang;
                const validLang = hljs.getLanguage(language) ? language : 'plaintext';
                let highlighted = text;
                try {
                    highlighted = hljs.highlight(text, { language: validLang }).value;
                } catch {
                    // an unknown grammar falls back to the raw text rather than dropping the block
                }
                return `<pre><code class="hljs language-${validLang}">${highlighted}</code></pre>`;
            },
            heading(token) {
                const { tokens, depth } = token;
                const text = this.parser.parseInline(tokens);
                const slug = generateId(text.replace(/<[^>]*>/g, ''));
                return `<h${depth} id="${slug}">${text}</h${depth}>`;
            },
            image(token) {
                return `<img src="${token.href}" alt="${token.text || ''}" style="max-width:100%; border-radius:0.5rem;">`;
            },
            blockquote(token) {
                const body = this.parser.parse(token.tokens);
                const match = token.text.match(/^\[!(TIP|NOTE|INFO|WARNING|DANGER)\]/i);
                if (!match) {
                    return `<blockquote>${body}</blockquote>`;
                }
                const type = match[1].toLowerCase();
                const iconMap = {
                    tip: 'lightbulb',
                    info: 'info',
                    danger: 'triangle-alert',
                    warning: 'triangle-alert',
                    note: 'sticky-note',
                };
                const cleanBody = body.replace(/<p>\s*\[!(TIP|NOTE|INFO|WARNING|DANGER)\]\s*/i, '<p>');
                return `<div class="callout ${type}"><div class="callout-icon"><i data-lucide="${iconMap[type] || 'info'}"></i></div><div class="callout-content">${cleanBody}</div></div>`;
            },
        };
        marked.use({ renderer });
    }

    function addCopyButtons() {
        document.querySelectorAll('.markdown-body pre').forEach((block) => {
            if (block.querySelector('.copy-code-btn')) return;

            const codeEl = block.querySelector('code');
            if (!codeEl) return;

            const button = document.createElement('button');
            button.className = 'copy-code-btn';
            button.type = 'button';
            button.innerHTML = '<i data-lucide="copy" class="w-4 h-4"></i>';

            button.onclick = async (e) => {
                e.preventDefault();
                e.stopPropagation();
                try {
                    await navigator.clipboard.writeText(codeEl.textContent);
                } catch {
                    const textarea = document.createElement('textarea');
                    textarea.value = codeEl.textContent;
                    textarea.style.position = 'fixed';
                    textarea.style.opacity = '0';
                    document.body.appendChild(textarea);
                    textarea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textarea);
                }
                button.innerHTML = '<i data-lucide="check" class="w-4 h-4"></i>';
                button.classList.add('copied');
                lucide.createIcons({ root: button });
                setTimeout(() => {
                    button.innerHTML = '<i data-lucide="copy" class="w-4 h-4"></i>';
                    button.classList.remove('copied');
                    lucide.createIcons({ root: button });
                }, 2000);
            };

            block.appendChild(button);
        });
        lucide.createIcons();
    }

    function renderMarkdown(container, source) {
        container.innerHTML = marked.parse(source);
        addCopyButtons();
        lucide.createIcons();
    }

    TinyAI.initMarked = initMarked;
    TinyAI.renderMarkdown = renderMarkdown;
})();
