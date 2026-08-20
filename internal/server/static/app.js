(function () {
    'use strict';

    const TinyAI = window.TinyAI;
    const { escapeHtml, relativeTime, stateMeta, groupColor, isTerminal, apiJSON, toast } = TinyAI;

    const views = {
        launcher: document.getElementById('view-launcher'),
        form: document.getElementById('view-form'),
        job: document.getElementById('view-job'),
    };
    const jobsList = document.getElementById('jobs-list');
    const sidebar = document.getElementById('sidebar');
    const searchBox = document.getElementById('search-box');
    const searchInput = document.getElementById('task-search');

    let catalog = { groups: [], tasks: [] };
    let jobs = [];
    let poller = null;
    let query = '';

    function showView(name) {
        Object.entries(views).forEach(([key, node]) => node.classList.toggle('hidden', key !== name));
        searchBox.classList.toggle('hidden', name !== 'launcher');
        searchBox.classList.toggle('flex', name === 'launcher');
        window.scrollTo({ top: 0 });
    }

    function taskCard(task) {
        const color = groupColor(task.group);
        return `
            <a href="#/task/${escapeHtml(task.id)}"
               class="flex flex-col gap-3 rounded-xl bg-mantle p-4 transition-colors hover:bg-surface0/50">
                <div class="flex items-center gap-3">
                    <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-${color}/15 text-${color}">
                        <i data-lucide="${escapeHtml(task.icon)}" class="h-5 w-5"></i>
                    </div>
                    <div class="min-w-0">
                        <h3 class="truncate font-display text-sm font-semibold text-text">${escapeHtml(task.title)}</h3>
                        <p class="truncate font-mono text-[11px] text-overlay1">${escapeHtml(task.engine)}</p>
                    </div>
                </div>
                <p class="text-sm leading-relaxed text-subtext0">${escapeHtml(task.description)}</p>
            </a>`;
    }

    function matchesQuery(task) {
        if (!query) return true;
        return [task.title, task.engine, task.description, task.group].join(' ').toLowerCase().includes(query);
    }

    function renderLauncher() {
        const groups = catalog.groups.length ? catalog.groups : [...new Set(catalog.tasks.map((t) => t.group))];
        const visible = catalog.tasks.filter(matchesQuery);
        const sections = groups
            .map((group) => {
                const tasks = visible.filter((task) => task.group === group);
                if (!tasks.length) return '';
                return `
                    <section class="space-y-3">
                        <div class="flex items-center gap-2">
                            <span class="h-2 w-2 rounded-full bg-${groupColor(group)}"></span>
                            <h2 class="font-display text-sm font-semibold uppercase tracking-wide text-subtext1">${escapeHtml(group)}</h2>
                            <span class="text-xs text-overlay0">${tasks.length}</span>
                        </div>
                        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 min-[1800px]:grid-cols-4 min-[2400px]:grid-cols-5">${tasks
                            .map(taskCard)
                            .join('')}</div>
                    </section>`;
            })
            .join('');

        const empty = query
            ? `<p class="text-sm text-overlay1">Nothing matches ${escapeHtml(query)}.</p>`
            : '<p class="text-sm text-overlay1">No tasks are registered.</p>';
        views.launcher.innerHTML = `
            <div class="space-y-7">
                <div>
                    <h1 class="font-display text-2xl font-bold">Tasks</h1>
                    <p class="mt-1 text-sm text-subtext0">Local models, run on this machine.</p>
                </div>
                ${sections || empty}
            </div>`;
        lucide.createIcons({ root: views.launcher });
    }

    function jobRow(job) {
        const meta = stateMeta(job.state);
        const activeJob = location.hash === `#/job/${job.id}`;
        const fraction = job.progress && typeof job.progress.fraction === 'number' ? job.progress.fraction : null;
        const progress =
            !isTerminal(job.state) && fraction !== null
                ? `<div class="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-surface0"><div class="h-full rounded-full bg-${meta.color}" style="width:${Math.round(
                      fraction * 100,
                  )}%"></div></div>`
                : '';
        return `
            <a href="#/job/${escapeHtml(job.id)}"
               class="flex items-start gap-2.5 px-3 py-2.5 transition-colors hover:bg-surface0/50 ${activeJob ? 'bg-surface0/60' : ''}">
                <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-${meta.color}"></span>
                <span class="min-w-0 flex-1">
                    <span class="block truncate text-sm text-text">${escapeHtml(job.title || job.task)}</span>
                    <span class="block text-[11px] text-overlay1">${escapeHtml(meta.label)} · ${escapeHtml(
                        relativeTime(job.createdAt),
                    )}</span>
                    ${progress}
                </span>
            </a>`;
    }

    function renderJobs() {
        if (!jobs.length) {
            jobsList.innerHTML = '<p class="px-4 py-6 text-center text-xs text-overlay0">No jobs yet.</p>';
            return;
        }
        jobsList.innerHTML = jobs.map(jobRow).join('');
    }

    function schedulePoll() {
        if (poller) clearTimeout(poller);
        if (!jobs.some((job) => !isTerminal(job.state))) return;
        poller = setTimeout(loadJobs, 5000);
    }

    async function loadJobs() {
        try {
            const body = await apiJSON('/api/jobs');
            jobs = (body && body.jobs) || [];
            renderJobs();
        } catch {
            // the sidebar is secondary; a failed refresh retries on the next poll
        }
        schedulePoll();
    }

    async function submitJob(payload) {
        const job = await apiJSON('/api/jobs', { method: 'POST', body: payload });
        loadJobs();
        location.hash = `#/job/${job.id}`;
    }

    function route() {
        const hash = location.hash || '#/';
        renderJobs();

        if (hash.startsWith('#/task/')) {
            const task = catalog.tasks.find((entry) => entry.id === decodeURIComponent(hash.slice(7)));
            if (!task) {
                location.hash = '#/';
                return;
            }
            TinyAI.jobView.close();
            TinyAI.renderTaskForm(views.form, task, submitJob);
            showView('form');
            return;
        }

        if (hash.startsWith('#/job/')) {
            TinyAI.jobView.open(views.job, decodeURIComponent(hash.slice(6)), loadJobs);
            showView('job');
            return;
        }

        TinyAI.jobView.close();
        showView('launcher');
    }

    async function boot() {
        TinyAI.initMarked();
        lucide.createIcons();
        document.getElementById('jobs-refresh').addEventListener('click', loadJobs);
        document.getElementById('sidebar-toggle').addEventListener('click', () => sidebar.classList.toggle('hidden'));
        searchInput.addEventListener('input', () => {
            query = searchInput.value.trim().toLowerCase();
            renderLauncher();
        });
        window.addEventListener('hashchange', route);

        try {
            catalog = await apiJSON('/api/tasks');
        } catch (error) {
            views.launcher.innerHTML = `<div class="rounded-xl bg-red/10 p-6 text-sm text-red">Could not load the task catalog: ${escapeHtml(
                error.message,
            )}</div>`;
            toast('The server is not reachable.', 'error');
            return;
        }

        renderLauncher();
        route();
        loadJobs();
    }

    boot();
})();
