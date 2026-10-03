import * as params from '@params';

const resList = document.getElementById('searchResults');
const sInput = document.getElementById('searchInput');
const searchBox = document.getElementById('searchbox');
const statusEl = document.getElementById('searchStatus');

let fuse;
let indexFailed = false;

const STRINGS = (document.documentElement.lang || '').toLowerCase().startsWith('en')
    ? {
        hint: 'Type a keyword to search',
        loading: 'Loading the search index…',
        failed: 'The search index failed to load; please refresh.',
        none: (q) => `Nothing matches “${q}”. Try another keyword.`,
        top: (n) => `Showing the ${n} most relevant results`,
        count: (n) => (n === 1 ? '1 result' : `${n} results`),
    }
    : {
        hint: '输入关键词开始搜索',
        loading: '正在加载索引…',
        failed: '搜索索引加载失败，请刷新页面重试',
        none: (q) => `没有找到与“${q}”相关的资讯，换个关键词试试`,
        top: (n) => `显示最相关的 ${n} 条结果`,
        count: (n) => `找到 ${n} 条结果`,
    };
let currentElement = null;
let firstResult = null;
let lastResult = null;

const defaultFuseOptions = {
    distance: 1000,
    threshold: 0.35,
    ignoreLocation: true,
    minMatchCharLength: 1,
    keys: [
        { name: 'title', weight: 0.5 },
        { name: 'content', weight: 0.35 },
        { name: 'summary', weight: 0.1 },
        { name: 'permalink', weight: 0.05 },
    ],
};

const buildFuseOptions = () => {
    if (!params.fuseOpts) {
        return defaultFuseOptions;
    }

    return {
        isCaseSensitive: params.fuseOpts.iscasesensitive ?? false,
        includeScore: params.fuseOpts.includescore ?? false,
        includeMatches: params.fuseOpts.includematches ?? false,
        minMatchCharLength: params.fuseOpts.minmatchcharlength ?? 1,
        shouldSort: params.fuseOpts.shouldsort ?? true,
        findAllMatches: params.fuseOpts.findallmatches ?? false,
        keys: params.fuseOpts.keys ?? defaultFuseOptions.keys,
        location: params.fuseOpts.location ?? 0,
        threshold: params.fuseOpts.threshold ?? defaultFuseOptions.threshold,
        distance: params.fuseOpts.distance ?? defaultFuseOptions.distance,
        ignoreLocation: params.fuseOpts.ignorelocation ?? defaultFuseOptions.ignoreLocation,
    };
};

const debounce = (fn, delay) => {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => fn(...args), delay);
    };
};

const setStatus = (text) => {
    if (statusEl) {
        statusEl.textContent = text;
    }
};

// 查询词同步到地址栏（?q=），可分享链接；点开结果再返回时仍保留结果
const syncQueryToURL = (query) => {
    const url = new URL(window.location.href);
    if (query) {
        url.searchParams.set('q', query);
    } else {
        url.searchParams.delete('q');
    }
    window.history.replaceState(null, '', url);
};

const reset = () => {
    currentElement = null;
    firstResult = null;
    lastResult = null;
    resList.innerHTML = '';
    sInput.value = '';
    syncQueryToURL('');
    setStatus(fuse ? STRINGS.hint : '');
    sInput.focus();
};

const setActiveResult = (element) => {
    document.querySelectorAll('.focus').forEach((item) => item.classList.remove('focus'));

    if (!element) {
        return;
    }

    element.focus();
    element.parentElement?.classList.add('focus');
    currentElement = element;
};

const snippetFrom = (text, limit = 120) => {
    if (!text) {
        return '';
    }
    const cleaned = String(text).replace(/\s+/g, ' ').trim();
    if (cleaned.length <= limit) {
        return cleaned;
    }
    return `${cleaned.slice(0, limit)}…`;
};

const renderResults = (results) => {
    if (!Array.isArray(results) || results.length === 0) {
        resList.innerHTML = '';
        firstResult = lastResult = currentElement = null;
        return;
    }

    const fragment = document.createDocumentFragment();

    for (const result of results) {
        const item = result.item;
        const li = document.createElement('li');

        const textWrap = document.createElement('div');
        textWrap.className = 'result-text';

        const titleEl = document.createElement('div');
        titleEl.className = 'result-title';
        titleEl.textContent = item.title;
        textWrap.appendChild(titleEl);

        const metaBits = [];
        if (item.summary) {
            metaBits.push(item.summary);
        }
        const contentSnippet = snippetFrom(item.content);
        // Avoid duplicating summary-only page blurbs when content is empty-ish
        if (contentSnippet && contentSnippet !== item.summary && contentSnippet !== item.title) {
            metaBits.push(contentSnippet);
        }
        if (metaBits.length) {
            const metaEl = document.createElement('div');
            metaEl.className = 'result-meta';
            metaEl.textContent = metaBits.join(' — ');
            textWrap.appendChild(metaEl);
        }

        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '24');
        svg.setAttribute('height', '24');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.classList.add('feather', 'feather-chevrons-right');
        svg.innerHTML = '<polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline>';

        const link = document.createElement('a');
        link.className = 'entry-link';
        link.href = item.permalink;
        link.setAttribute('aria-label', item.title);

        li.appendChild(textWrap);
        li.appendChild(svg);
        li.appendChild(link);
        fragment.appendChild(li);
    }

    resList.innerHTML = '';
    resList.appendChild(fragment);
    firstResult = resList.firstElementChild;
    lastResult = resList.lastElementChild;
};

const performSearch = () => {
    const query = sInput.value.trim();
    syncQueryToURL(query);

    if (!fuse) {
        setStatus(indexFailed ? STRINGS.failed : STRINGS.loading);
        return;
    }

    if (!query) {
        renderResults([]);
        setStatus(STRINGS.hint);
        return;
    }

    const limit = params.fuseOpts?.limit || 50;
    const results = fuse.search(query, { limit });
    renderResults(results);
    if (results.length === 0) {
        setStatus(STRINGS.none(query));
    } else if (results.length >= limit) {
        setStatus(STRINGS.top(limit));
    } else {
        setStatus(STRINGS.count(results.length));
    }
};

const resolveIndexURL = () => {
    if (searchBox?.dataset.indexUrl) {
        return searchBox.dataset.indexUrl;
    }
    if (typeof params.indexURL === 'string' && params.indexURL) {
        return params.indexURL;
    }
    return new URL('../index.json', window.location.href).href;
};

const initSearch = async () => {
    if (!sInput || !resList) {
        return;
    }

    sInput.disabled = false;
    setStatus(STRINGS.loading);
    const initialQuery = new URLSearchParams(window.location.search).get('q');
    if (initialQuery && !sInput.value) {
        sInput.value = initialQuery;
    }
    sInput.focus();

    try {
        const response = await fetch(resolveIndexURL());
        if (!response.ok) {
            throw new Error(`Search index load failed: ${response.status}`);
        }

        const data = await response.json();
        if (data) {
            fuse = new Fuse(data, buildFuseOptions());
        }
    } catch (error) {
        indexFailed = true;
        console.error(error);
    }
    // 索引加载期间已输入的关键词（或 ?q= 带入的）在加载完成后立即出结果
    performSearch();
};

window.addEventListener('load', initSearch);

sInput?.addEventListener('input', debounce(performSearch, 150));

sInput?.addEventListener('search', () => {
    if (!sInput.value) {
        reset();
    }
});

document.addEventListener('keydown', (event) => {
    const { key } = event;
    const active = document.activeElement;
    const isInSearchBox = searchBox?.contains(active);

    if (key === 'Escape') {
        reset();
        return;
    }

    if (!firstResult || !isInSearchBox) {
        return;
    }

    if (key === 'ArrowDown') {
        event.preventDefault();

        if (active === sInput) {
            setActiveResult(firstResult.querySelector('.entry-link'));
        } else if (active?.parentElement !== lastResult) {
            setActiveResult(active?.parentElement?.nextElementSibling?.querySelector('.entry-link'));
        }
    } else if (key === 'ArrowUp') {
        event.preventDefault();

        if (active?.parentElement === firstResult) {
            setActiveResult(sInput);
        } else if (active !== sInput) {
            setActiveResult(active?.parentElement?.previousElementSibling?.querySelector('.entry-link'));
        }
    } else if (key === 'ArrowRight') {
        if (active?.matches?.('.entry-link')) {
            active.click();
        }
    }
});
