/* PaperAgent — Frontend Application */
(function () {
    "use strict";

    // ── State ──
    let papers = [];
    let subtopics = [];
    let paperMap = {};
    let currentPaperId = null;
    let summaryCache = {};
    let reviewCache = {};
    let chatCache = {};
    let currentPanel = "summary";

    // ── localStorage helpers ──
    function lsGet(key, fallback) { try { const v = localStorage.getItem("pa_" + key); return v ? JSON.parse(v) : fallback; } catch (_) { return fallback; } }
    function lsSet(key, val) { try { localStorage.setItem("pa_" + key, JSON.stringify(val)); } catch (_) {} }
    let visitedPapers = new Set(lsGet("visited", []));
    let searchHistory = lsGet("history", []);
    let notesCache = lsGet("notes", {});
    let _currentQuery = "";
    let _summaryPending = {};  // uid → Promise, so review waits for summary

    // ── Compare state ──
    let comparePanelOpen = false;
    let selectedCompareIds = new Set();   // uids selected for comparison (current session)
    function compareHistKey() { return "compare_" + (_currentQuery || ""); }
    function getCompareHistory() { return lsGet(compareHistKey(), []); }
    function setCompareHistory(arr) { lsSet(compareHistKey(), arr); }
    function getComparablePapers() {
        return papers.filter(p => visitedPapers.has(p.uid) && summaryCache[p.uid]);
    }

    // ── Snapshot save/restore ──
    function saveSnapshot() {
        if (!_currentQuery) return;
        const snap = {
            papers: papers,          // already plain dicts from SSE
            subtopics: subtopics,
            summaryCache: summaryCache,
            reviewCache: reviewCache,
            chatCache: chatCache,
        };
        lsSet("snap_" + _currentQuery, snap);
    }

    function restoreSnapshot(query) {
        const snap = lsGet("snap_" + query, null);
        if (!snap) return false;
        hideLoading();
        papers = snap.papers || [];
        subtopics = snap.subtopics || [];
        summaryCache = snap.summaryCache || {};
        reviewCache = snap.reviewCache || {};
        chatCache = snap.chatCache || {};
        paperMap = {};
        for (const p of papers) paperMap[p.uid] = p;
        _currentQuery = query;
        selectedCompareIds.clear();
        if (comparePanelOpen) renderCompare();
        rebuildPaperList();
        if (subtopics.length) renderSubtopics();
        si.value = query;
        es.style.display = papers.length ? "none" : "block";
        st.style.display = papers.length ? "flex" : "none";
        sp.textContent = papers.length;
        addHistory(query);  // reorder & mark active
        return true;
    }

    function markVisited(uid) {
        if (visitedPapers.has(uid)) return;
        visitedPapers.add(uid);
        lsSet("visited", [...visitedPapers]);
        updateCardMarker(uid);
    }
    function updateCardMarker(uid) {
        const card = pl.querySelector(`.paper-card[data-uid="${uid}"]`);
        if (card) card.classList.add("visited");
    }
    function addHistory(query) {
        searchHistory = searchHistory.filter(q => q !== query);
        searchHistory.unshift(query);
        if (searchHistory.length > 20) searchHistory = searchHistory.slice(0, 20);
        lsSet("history", searchHistory);
        renderSearchHistory();
    }

    if (typeof marked !== "undefined") {
        marked.setOptions({ breaks: true, gfm: true });
    }
    function md(text) {
        if (!text) return "";
        try { return marked.parse(text); } catch (_) { return escapeHtml(text); }
    }

    // ── DOM refs ──
    const $ = (id) => document.getElementById(id);
    const S = $("view-search"), V = $("view-detail");
    const si = $("search-input"), mr = $("max-results");
    const ab = $("arxiv-btn"), ap = $("arxiv-popover"), ai = $("arxiv-input"), aa = $("arxiv-add-btn");
    const recPanel = $("recommend-panel"), recClose = $("recommend-close");
    const recContent = $("recommend-content"), recKeywords = $("recommend-keywords");
    const recMemory = $("recommend-memory"), memToggle = $("memory-toggle");
    const recEmpty = $("recommend-empty"), recGenBtn = $("recommend-gen-btn");
    const pl = $("paper-list"), es = $("empty-state"), st = $("stats"), sp = $("stat-papers");
    const sc = $("subtopics-container");
    const sbar = $("search-sidebar"), sbt = $("sidebar-toggle-btn");
    const snew = $("sidebar-new-search"), shl = $("sidebar-history-list");
    const li = $("loading-inline"), ss = $("search-status");
    const bk = $("back-btn");
    const dt = $("detail-title"), dm = $("detail-meta");
    const sidebar = $("detail-sidebar");
    const panelAbstract = $("panel-abstract"), panelSummary = $("panel-summary"), panelReview = $("panel-review"), panelChat = $("panel-chat"), panelPdf = $("panel-pdf");
    const summaryLoading = $("summary-loading"), reviewLoading = $("review-loading");
    const cm = $("chat-messages"), ci = $("chat-input"), cs = $("chat-send-btn");
    const ciBtn = $("chat-image-btn"), ciInput = $("chat-image-input");
    const ciPreview = $("chat-image-preview"), ciThumb = $("chat-image-thumb"), ciRemove = $("chat-image-remove");
    let selectedChatImage = null;
    const ne = $("notes-editor"), np = $("notes-preview"), ns = $("notes-saved-inline"), npt = $("notes-preview-toggle");
    // PDF viewer
    const pf = $("pdf-frame"), pph = $("pdf-placeholder");
    // Translation
    const translateInput = $("translate-input"), btnTranslate = $("btn-translate"), translateResult = $("translate-result");
    const notesContent = $("notes-content"), translateContent = $("translate-content");
    const notesTabBtns = document.querySelectorAll(".notes-tab");
    const btnTranslateCopy = $("btn-translate-copy");
    const ubtn = $("btn-upload-pdf"), uf = $("upload-file-input"), ust = $("upload-status");

    // ── Helpers ──
    function showLoading(msg) {
        li.innerHTML = `<div class="spinner"></div><span>${msg}</span>`;
        li.classList.add("active");
    }
    function hideLoading() { li.classList.remove("active"); }
    function status(msg, type) {
        ss.innerHTML = `<div class="status-msg ${type}">${msg}</div>`;
        setTimeout(() => { ss.innerHTML = ""; }, 4000);
    }
    function escapeHtml(text) {
        const d = document.createElement("div"); d.textContent = text; return d.innerHTML;
    }
    function showView(v) {
        S.classList.toggle("active", v === "search");
        V.classList.toggle("active", v === "detail");
        if (v === "search") window.scrollTo({ top: 0 });
    }

    // ── Hash routing ──
    function navigate(h) { window.location.hash = h; }
    function handleRoute() {
        const hash = window.location.hash.slice(1) || "search";
        if (hash === "search") { showView("search"); currentPaperId = null; }
        else if (hash.startsWith("paper/")) {
            const uid = hash.slice(6);
            if (paperMap[uid]) { currentPaperId = uid; clearChatImage(); showView("detail"); renderDetail(uid); }
            else { navigate("search"); }
        }
    }
    window.addEventListener("hashchange", handleRoute);

    // ── API ──
    async function apiPost(url, data) {
        const fd = new FormData();
        for (const [k, v] of Object.entries(data)) fd.append(k, v);
        const r = await fetch(url, { method: "POST", body: fd });
        if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "请求失败"); }
        return r.json();
    }

    // ── SSE Search (streaming) ──
    function doSearch(query) {
        const maxResults = Math.max(1, Math.min(20, parseInt(mr.value, 10) || 15));

        papers = []; subtopics = []; paperMap = {};
        summaryCache = {}; reviewCache = {}; chatCache = {};
        pl.innerHTML = ""; sc.innerHTML = "";
        es.style.display = "none"; st.style.display = "none";
        _currentQuery = query;
        selectedCompareIds.clear();
        if (comparePanelOpen) renderCompare();
        addHistory(query);
        showLoading("正在规划研究主题...");

        const fd = new FormData();
        fd.append("query", query);
        fd.append("max_results", maxResults);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/api/search-stream");

        let lastProcessedIndex = 0;
        let buffer = "";

        xhr.onprogress = () => {
            buffer += xhr.responseText.slice(lastProcessedIndex);
            lastProcessedIndex = xhr.responseText.length;

            const parts = buffer.split("\n\n");
            buffer = parts.pop() || "";

            for (const part of parts) {
                const lines = part.split("\n");
                let event = "message";
                let dataStr = "";
                for (const line of lines) {
                    if (line.startsWith("event: ")) event = line.slice(7);
                    else if (line.startsWith("data: ")) dataStr = line.slice(6);
                }
                if (!dataStr) continue;
                try { handleSSEEvent(event, JSON.parse(dataStr)); }
                catch (_) {}
            }
        };

        xhr.onload = () => {
            hideLoading();
            if (papers.length) { status(`检索完成，共 ${papers.length} 篇论文`, "success"); saveSnapshot(); }
        };
        xhr.onerror = () => {
            hideLoading();
            status("请求失败，请检查网络", "error");
        };
        xhr.send(fd);
    }

    function handleSSEEvent(event, data) {
        if (event === "status") {
            showLoading(data.msg || "处理中...");
        } else if (event === "subtopics") {
            subtopics = data;
        } else if (event === "paper") {
            hideLoading();  // papers arrived, stop spinner
            const p = data;
            if (!paperMap[p.uid]) {
                papers.push(p);
                paperMap[p.uid] = p;
                appendPaperCard(p);
            }
            st.style.display = "flex"; sp.textContent = papers.length;
        } else if (event === "done") {
            hideLoading();
            if (subtopics.length) renderSubtopics();
            saveSnapshot();
        } else if (event === "error") {
            hideLoading();
            status(data.msg || "检索失败", "error");
        }
    }

    function appendPaperCard(p) {
        const abs = p.abstract || "(暂无摘要)";
        const truncated = abs.length > 400;
        const display = truncated ? escapeHtml(abs).slice(0, 400) + "..." : escapeHtml(abs);
        let meta = `${escapeHtml(p.authors)} · ${p.year}`;
        if (p.citations) meta += ` · 引用 ${p.citations}`;
        if (p.sources && p.sources.length) meta += ` · ${p.sources.join(", ")}`;

        const div = document.createElement("div");
        div.className = "paper-card entering";
        div.dataset.uid = p.uid;
        const isVisited = visitedPapers.has(p.uid);
        if (isVisited) div.classList.add("visited");
        div.innerHTML = `<div class="paper-card-title">${escapeHtml(p.title)}${isVisited ? ' <span class="visited-badge">已读</span>' : ''}</div>
            <div class="paper-card-meta">${meta}${p.has_pdf ? ' · <span class="pdf-badge">PDF</span>' : ''}</div>
            <div class="paper-card-abstract" id="abs-${p.uid}">${display}</div>
            ${truncated ? `<button class="paper-card-toggle" data-uid="${p.uid}">展开完整摘要</button>` : ""}`;
        pl.appendChild(div);

        requestAnimationFrame(() => {
            div.classList.remove("entering");
            div.classList.add("entered");
        });

        const toggle = div.querySelector(".paper-card-toggle");
        if (toggle) toggle.addEventListener("click", (e) => {
            e.stopPropagation();
            const el = document.getElementById(`abs-${p.uid}`);
            if (!el) return;
            if (el.classList.contains("expanded")) {
                el.classList.remove("expanded");
                el.textContent = escapeHtml(p.abstract).slice(0, 400) + "...";
                toggle.textContent = "展开完整摘要";
            } else {
                el.classList.add("expanded");
                el.textContent = escapeHtml(p.abstract);
                toggle.textContent = "收起摘要";
            }
        });

        div.addEventListener("click", (e) => {
            if (e.target.closest(".paper-card-toggle")) return;
            navigate(`paper/${p.uid}`);
        });
    }

    function renderSubtopics() {
        let h = `<details class="subtopics"><summary>检索规划</summary><ol>`;
        for (const t of subtopics) {
            h += `<li><strong>${escapeHtml(t.name || "")}</strong>`;
            if (t.description) h += `<div style="color:#667085">${escapeHtml(t.description)}</div>`;
            if (t.keywords && t.keywords.length) h += `<div style="color:#667085;font-size:.8rem">关键词: ${t.keywords.map(escapeHtml).join(", ")}</div>`;
            h += `</li>`;
        }
        h += `</ol></details>`;
        sc.innerHTML = h;
    }

    // ── Reset ──
    async function doReset() {
        try { await apiPost("/api/reset", {}); } catch (_) {}
        si.value = ""; papers = []; subtopics = []; paperMap = {};
        summaryCache = {}; reviewCache = {}; chatCache = {};
        pl.innerHTML = ""; sc.innerHTML = ""; es.style.display = "block"; st.style.display = "none";
    }

    // ── Add arXiv ──
    async function doAddArxiv(link) {
        showLoading("正在添加论文...");
        try {
            const data = await apiPost("/api/add-paper", { link });
            hideLoading();
            papers = data.papers || [];
            paperMap = {};
            for (const p of papers) paperMap[p.uid] = p;
            rebuildPaperList();
            status("已添加论文", "success");
            ai.value = ""; ap.classList.remove("open");
        } catch (e) { hideLoading(); status(e.message, "error"); }
    }

    function rebuildPaperList() {
        pl.innerHTML = "";
        for (const p of papers) appendPaperCard(p);
        if (papers.length) { es.style.display = "none"; st.style.display = "flex"; sp.textContent = papers.length; }
    }

    // ── Search history ──
    function renderSearchHistory() {
        if (!searchHistory.length) { shl.innerHTML = '<div style="color:#8895a7;font-size:.78rem;padding:8px 12px">暂无历史记录</div>'; return; }
        shl.innerHTML = searchHistory.map((q, i) =>
            `<div class="history-item${i === 0 ? ' active' : ''}" data-query="${q.replace(/"/g, '&quot;')}">${escapeHtml(q)}</div>`
        ).join("");
    }

    // ── Notes ──
    let _notesTimer = null;

    function loadNotes(uid) {
        ne.value = notesCache[uid] || "";
        np.style.display = "none";
        ne.style.display = "";
        npt.classList.remove("active");
    }

    function toggleNotesPreview() {
        const isPreview = np.style.display !== "none";
        if (isPreview) {
            np.style.display = "none";
            ne.style.display = "";
            npt.classList.remove("active");
        } else {
            np.innerHTML = md(ne.value) || '<div style="color:#bbb">暂无笔记</div>';
            np.style.display = "";
            ne.style.display = "none";
            npt.classList.add("active");
        }
    }

    function autoSaveNotes() {
        if (!currentPaperId) return;
        notesCache[currentPaperId] = ne.value;
        lsSet("notes", notesCache);
        ns.classList.add("show");
        clearTimeout(_notesTimer);
        _notesTimer = setTimeout(() => ns.classList.remove("show"), 1200);
    }

    // ── PDF Panel ──
    function renderPdfPanel(uid) {
        const p = paperMap[uid];
        pf.style.display = "none";
        pph.style.display = "";
        if (!p) {
            pph.textContent = "未找到论文信息";
            return;
        }
        if (p.has_pdf) {
            showPdf(uid);
            return;
        }
        const isArxiv = p.arxiv_id && !p.arxiv_id.startsWith("no-id:");
        if (_summaryPending[uid]) {
            pph.innerHTML = '<span style="display:flex;align-items:center;gap:8px"><div class="spinner"></div>正在下载 PDF...</span>';
        } else if (isArxiv && summaryCache[uid]) {
            pph.textContent = "PDF 自动下载失败，请手动上传";
        } else if (isArxiv) {
            pph.textContent = "PDF 尚未下载，请等待总结生成";
        } else {
            pph.textContent = "该论文来自 Google Scholar，请手动上传 PDF";
        }
    }

    function showPdf(uid) {
        pph.style.display = "none";
        pf.style.display = "";
        const url = `/api/pdf/${uid}?t=${Date.now()}`;
        if (pf.src !== url) pf.src = url;
    }

    // ── Notes / Translate Tabs ──
    let _lastTranslation = "";

    notesTabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const tab = btn.dataset.ntab;
            notesTabBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            if (tab === "notes") {
                notesContent.style.display = "";
                translateContent.style.display = "none";
                npt.style.display = "";
            } else {
                notesContent.style.display = "none";
                translateContent.style.display = "";
                npt.style.display = "none";
                btnTranslateCopy.classList.remove("visible");
            }
        });
    });

    btnTranslate.addEventListener("click", async () => {
        const text = translateInput.value.trim();
        if (!text) return;
        btnTranslate.disabled = true;
        btnTranslate.textContent = "翻译中...";
        translateResult.innerHTML = '<span style="color: var(--gray-400); display:flex; align-items: center; gap: 8px;"><div class="spinner"></div>翻译中...</span>';
        try {
            const data = await apiPost("/api/translate", { text });
            _lastTranslation = data.translated || "";
            translateResult.textContent = _lastTranslation || "(翻译为空)";
            btnTranslateCopy.classList.add("visible");
            btnTranslateCopy.classList.remove("copied");
            btnTranslateCopy.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>复制`;
        } catch (e) {
            translateResult.textContent = "翻译失败，请稍后重试";
            _lastTranslation = "";
            btnTranslateCopy.classList.remove("visible");
        } finally {
            btnTranslate.disabled = false;
            btnTranslate.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 8l6 6M13 8l-6 6M5 12h14"/><circle cx="12" cy="12" r="10"/></svg>翻译`;
        }
    });

    btnTranslateCopy.addEventListener("click", async () => {
        if (!_lastTranslation) return;
        try {
            await navigator.clipboard.writeText(_lastTranslation);
            btnTranslateCopy.classList.add("copied");
            btnTranslateCopy.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>已复制`;
            setTimeout(() => {
                btnTranslateCopy.classList.remove("copied");
                btnTranslateCopy.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>复制`;
            }, 2000);
        } catch (_) {}
    });

    // ================================================================
    // DETAIL VIEW — sidebar + panels
    // ================================================================

    function switchPanel(name) {
        currentPanel = name;
        // Sidebar buttons
        const btns = sidebar.querySelectorAll(".sidebar-btn");
        btns.forEach(b => b.classList.toggle("active", b.dataset.panel === name));
        // Panels
        panelAbstract.style.display = name === "abstract" ? "" : "none";
        panelSummary.style.display = name === "summary" ? "" : "none";
        panelReview.style.display = name === "review" ? "" : "none";
        panelChat.style.display = name === "chat" ? "" : "none";
        panelPdf.style.display = name === "pdf" ? "" : "none";
        if (name === "chat") renderChat(currentPaperId);
        if (name === "pdf") renderPdfPanel(currentPaperId);
    }

    function renderDetail(uid) {
        const p = paperMap[uid];
        if (!p) { navigate("search"); return; }

        markVisited(uid);
        // Topbar - always visible (title + meta only)
        dt.textContent = p.title;
        let meta = `${p.authors} · ${p.year}`;
        if (p.citations) meta += ` · 引用 ${p.citations}`;
        dm.textContent = meta;

        // PDF status indicator
        if (p.has_pdf) {
            ubtn.style.display = "none";
            ust.textContent = "已缓存 PDF";
        } else {
            ubtn.style.display = "";
            ust.textContent = "";
        }

        if (!chatCache[uid]) chatCache[uid] = [];
        // Show loading in chat until summary is ready
        if (!summaryCache[uid]) {
            cm.innerHTML = '<div class="chat-loading">总结正在生成中，生成完成后即可提问...</div>';
        } else {
            cm.innerHTML = '';
        }

        // Notes panel (always-visible right column)
        loadNotes(uid);

        // Abstract panel
        panelAbstract.innerHTML = `<div style="font-size:.9rem;line-height:1.75;color:#444;white-space:pre-wrap">${escapeHtml(p.abstract || "(暂无摘要)")}</div>`;

        // Summary panel
        if (summaryCache[uid]) {
            panelSummary.innerHTML = summaryCache[uid];
        } else {
            panelSummary.innerHTML = "";
            panelSummary.appendChild(summaryLoading);
            summaryLoading.classList.remove("done");
        }

        // Review panel
        if (reviewCache[uid]) {
            panelReview.innerHTML = reviewCache[uid];
        } else {
            panelReview.innerHTML = "";
            panelReview.appendChild(reviewLoading);
            reviewLoading.classList.remove("done");
        }

        // Default: show summary
        switchPanel("summary");

        // Auto-generate — summary first, then review (review needs the PDF chunks)
        if (!summaryCache[uid]) {
            _summaryPending[uid] = doGenerateSummary(uid);
        }
        if (!reviewCache[uid]) {
            // Wait for summary to finish before generating review
            const waitSummary = _summaryPending[uid] || Promise.resolve();
            waitSummary.then(() => doGenerateReview(uid));
        }
    }

    // ── Generate summary ──
    async function doGenerateSummary(uid) {
        let hasPdf = false;
        try {
            const data = await apiPost("/api/summarize-one", { paper_id: uid });
            summaryCache[uid] = md(data.summary || "");
            hasPdf = !!data.has_pdf;
        } catch (_) {
            // API failed but PDF may have been downloaded; check next request
        } finally {
            delete _summaryPending[uid];
        }
        // Always update PDF status if available
        if (hasPdf && paperMap[uid]) {
            paperMap[uid].has_pdf = true;
            _updatePdfStatus(uid);
        }
        if (summaryCache[uid]) {
            panelSummary.innerHTML = summaryCache[uid];
            if (currentPaperId === uid && cm.querySelector(".chat-loading")) {
                renderChat(uid);
            }
        } else {
            summaryLoading.innerHTML = `<div class="spinner" style="display:none"></div><span>生成失败，请重试</span>`;
            summaryLoading.classList.add("done");
        }
        saveSnapshot();
    }

    function _updatePdfStatus(uid) {
        if (currentPaperId !== uid) return;
        ubtn.style.display = "none";
        ust.textContent = "已缓存 PDF";
        // Refresh PDF panel if open
        if (panelPdf.style.display !== "none") {
            renderPdfPanel(uid);
        }
        // Also update the paper card badge if visible
        const card = pl.querySelector(`.paper-card[data-uid="${uid}"]`);
        if (card) {
            const meta = card.querySelector(".paper-card-meta");
            if (meta && !meta.querySelector(".pdf-badge")) {
                const badge = document.createElement("span");
                badge.className = "pdf-badge";
                badge.textContent = "PDF";
                meta.insertAdjacentHTML("beforeend", " · ");
                meta.appendChild(badge);
            }
        }
    }

    // ── Generate review ──
    async function doGenerateReview(uid) {
        try {
            const data = await apiPost("/api/review", { paper_id: uid });
            reviewCache[uid] = md(data.review || "");
        } catch (_) {}
        if (reviewCache[uid]) {
            panelReview.innerHTML = reviewCache[uid];
        } else {
            reviewLoading.innerHTML = `<div class="spinner" style="display:none"></div><span>生成失败，请重试</span>`;
            reviewLoading.classList.add("done");
        }
        saveSnapshot();
    }

    // ── Chat ──
    function renderChat(uid) {
        const msgs = chatCache[uid] || [];
        cm.innerHTML = "";
        for (const m of msgs) {
            const html = m.role === "assistant" ? md(m.content) : escapeHtml(m.content);
            const img = m.image ? `<img class="chat-img" src="${m.image}" alt="图片">` : "";
            cm.innerHTML += `<div class="chat-msg ${m.role}"><div class="chat-bubble">${img}${html}</div></div>`;
        }
        const typing = cm.querySelector(".chat-typing");
        if (typing) typing.remove();
        cm.scrollTop = cm.scrollHeight;
    }

    function showTyping() {
        cm.innerHTML += `<div class="chat-msg assistant chat-typing"><div class="chat-bubble typing-indicator"><span></span><span></span><span></span></div></div>`;
        cm.scrollTop = cm.scrollHeight;
    }

    function clearChatImage() {
        selectedChatImage = null;
        ciInput.value = "";
        ciThumb.src = "";
        ciPreview.style.display = "none";
    }

    function onSelectChatImage(file) {
        if (!file) return;
        const okTypes = ["image/png", "image/jpeg", "image/webp"];
        if (!okTypes.includes(file.type)) { alert("仅支持 png / jpg / webp 格式图片"); return; }
        if (file.size > 8 * 1024 * 1024) { alert("图片大小不能超过 8MB"); return; }
        selectedChatImage = file;
        ciThumb.src = URL.createObjectURL(file);
        ciPreview.style.display = "";
    }

    async function doSendChat(uid) {
        const msg = ci.value.trim();
        const file = selectedChatImage;
        if (!msg && !file) return;

        if (!chatCache[uid]) chatCache[uid] = [];
        const localEntry = { role: "user", content: msg };
        if (file) localEntry.image = URL.createObjectURL(file);
        chatCache[uid].push(localEntry);
        renderChat(uid);

        ci.value = ""; ci.disabled = true; cs.disabled = true;
        clearChatImage();
        showTyping();

        try {
            const fd = new FormData();
            fd.append("paper_id", uid);
            fd.append("question", msg);
            if (file) fd.append("image", file);
            const r = await fetch("/api/ask", { method: "POST", body: fd });
            if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "请求失败"); }
            const data = await r.json();
            chatCache[uid] = data.history;
            renderChat(uid);
            saveSnapshot();
        } catch (e) {
            chatCache[uid].push({ role: "assistant", content: "请求失败: " + e.message });
            renderChat(uid);
        } finally {
            ci.disabled = false; cs.disabled = false; ci.focus();
        }
    }

    // ================================================================
    // Event bindings
    // ================================================================

    // Sidebar navigation
    sidebar.addEventListener("click", (e) => {
        const btn = e.target.closest(".sidebar-btn[data-panel]");
        if (btn) switchPanel(btn.dataset.panel);
    });

    // Notes — auto-save on input (debounced 600ms)
    ne.addEventListener("input", () => {
        clearTimeout(_notesTimer);
        _notesTimer = setTimeout(autoSaveNotes, 600);
    });

    // Notes — preview toggle
    npt.addEventListener("click", toggleNotesPreview);

    // PDF upload
    ubtn.addEventListener("click", () => uf.click());
    uf.addEventListener("change", async () => {
        const file = uf.files[0];
        if (!file || !currentPaperId) { uf.value = ""; return; }
        ubtn.disabled = true;
        ust.textContent = "上传中...";

        const fd = new FormData();
        fd.append("paper_id", currentPaperId);
        fd.append("file", file);

        try {
            const r = await fetch("/api/upload-pdf", { method: "POST", body: fd });
            const data = await r.json();
            if (!r.ok) { ust.textContent = data.error || "上传失败"; return; }
            summaryCache[currentPaperId] = md(data.summary || "");
            panelSummary.innerHTML = summaryCache[currentPaperId];
            reviewCache[currentPaperId] = null;
            if (paperMap[currentPaperId]) paperMap[currentPaperId].has_pdf = true;
            _updatePdfStatus(currentPaperId);
            saveSnapshot();
            ust.textContent = `已解析 ${data.page_count || "?"} 页`;
            setTimeout(() => { ust.textContent = "已缓存 PDF"; }, 3000);
        } catch (e) {
            ust.textContent = "上传失败";
        } finally {
            ubtn.disabled = false;
            uf.value = "";
        }
    });

    si.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { const q = si.value.trim(); if (q) doSearch(q); }
    });

    // ── Recommend ──
    function parseRecommendKeywords(text) {
        const m = text.match(/##\s*推荐检索关键词\s*\n([\s\S]*?)(?:\n##\s|\n#\s|$)/);
        if (!m) return [];
        return m[1]
            .split("\n")
            .map((l) => l.replace(/^[-*]\s*/, "").trim())
            .filter((l) => l && !l.startsWith("#"));
    }

    function stripKeywordSection(text) {
        return text
            .replace(/##\s*推荐检索关键词[\s\S]*?(?=\n##\s|\n#\s|$)/, "")
            .replace(/\n{3,}/g, "\n\n")
            .trim();
    }

    function renderRecommendation(text) {
        recContent.innerHTML = md(stripKeywordSection(text));
        const kws = parseRecommendKeywords(text);
        recKeywords.innerHTML = "";
        for (const kw of kws) {
            const chip = document.createElement("span");
            chip.className = "recommend-kw";
            chip.textContent = kw;
            chip.title = "用该关键词发起检索";
            chip.addEventListener("click", () => { si.value = kw; doSearch(kw); });
            recKeywords.appendChild(chip);
        }
    }

    function showRecommendIdle() {
        recPanel.style.display = "";
        recMemory.style.display = "none";
        memToggle.textContent = "查看记忆文档";
        recKeywords.innerHTML = "";
        recContent.innerHTML = "";
        recEmpty.style.display = "";
    }

    async function doRecommend() {
        recPanel.style.display = "";
        recMemory.style.display = "none";
        memToggle.textContent = "查看记忆文档";
        recKeywords.innerHTML = "";
        recEmpty.style.display = "none";
        recGenBtn.disabled = true;
        recContent.innerHTML = '<div style="color:#98a2b3">正在生成个性化推荐...</div>';
        try {
            const r = await fetch("/api/recommend", { method: "POST" });
            if (!r.ok) { const e = await r.json().catch(() => ({ detail: r.statusText })); throw new Error(e.detail || "推荐失败"); }
            const data = await r.json();
            renderRecommendation(data.recommendation || "(暂无推荐)");
        } catch (e) {
            recContent.innerHTML = `<div style="color:#dc2626">${escapeHtml(e.message || "推荐失败")}</div>`;
        } finally {
            recGenBtn.disabled = false;
        }
    }

    async function toggleMemory() {
        if (recMemory.style.display !== "none") {
            recMemory.style.display = "none";
            memToggle.textContent = "查看记忆文档";
            return;
        }
        memToggle.textContent = "隐藏记忆文档";
        recMemory.style.display = "";
        recMemory.innerHTML = '<div style="color:#98a2b3">加载中...</div>';
        try {
            const r = await fetch("/api/memory");
            const data = await r.json();
            recMemory.innerHTML = data.memory ? md(data.memory) : '<div style="color:#98a2b3">暂无记忆文档</div>';
        } catch (e) {
            recMemory.innerHTML = `<div style="color:#dc2626">加载失败</div>`;
        }
    }

    recClose.addEventListener("click", () => { recPanel.style.display = "none"; });
    memToggle.addEventListener("click", toggleMemory);
    recGenBtn.addEventListener("click", doRecommend);

    // Sidebar toggle
    sbt.addEventListener("click", () => {
        sbar.classList.toggle("collapsed");
    });

    // New search button
    function newSearch() {
        papers = []; subtopics = []; paperMap = {};
        summaryCache = {}; reviewCache = {}; chatCache = {};
        rebuildPaperList();
        st.style.display = "none";
        sc.innerHTML = "";
        es.style.display = "block";
        si.value = "";
        si.focus();
        showRecommendIdle();
    }
    snew.addEventListener("click", newSearch);

    // Header (logo + title) → new search
    const appHeader = $("app-header");
    if (appHeader) appHeader.addEventListener("click", newSearch);

    // History item click
    shl.addEventListener("click", (e) => {
        const item = e.target.closest(".history-item");
        if (!item) return;
        const q = item.dataset.query;
        if (!restoreSnapshot(q)) { si.value = q; doSearch(q); }
    });

    // arXiv popover
    ab.addEventListener("click", (e) => { e.stopPropagation(); ap.classList.toggle("open"); });
    document.addEventListener("click", (e) => {
        if (!ap.contains(e.target) && e.target !== ab) ap.classList.remove("open");
    });
    aa.addEventListener("click", () => { const l = ai.value.trim(); if (l) doAddArxiv(l); else status("请输入 arXiv 链接或 ID", "error"); });
    ai.addEventListener("keydown", (e) => { if (e.key === "Enter") { const l = ai.value.trim(); if (l) doAddArxiv(l); } });

    // Search history chips (old inline) — removed

    bk.addEventListener("click", () => navigate("search"));

    cs.addEventListener("click", () => { if (currentPaperId) doSendChat(currentPaperId); });
    ci.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && currentPaperId) { e.preventDefault(); doSendChat(currentPaperId); }
    });
    ciBtn.addEventListener("click", () => ciInput.click());
    ciInput.addEventListener("change", () => onSelectChatImage(ciInput.files[0]));
    ciRemove.addEventListener("click", clearChatImage);

    // ── Compare panel ──
    const cmpToggle = $("compare-toggle-btn"), cmpPanel = $("compare-panel"), cmpDivider = $("compare-divider");
    const cmpClose = $("compare-close-btn"), cmpRun = $("compare-run-btn"), cmpResult = $("compare-result");
    const cmpCandList = $("compare-candidate-list"), cmpCandCount = $("compare-candidate-count");
    const cmpSelList = $("compare-selected-list"), cmpSelCount = $("compare-selected-count");
    const cmpHistList = $("compare-history-list");
    const cmpHistHead = $("compare-history-head"), cmpCandHead = $("compare-candidates-head");
    const viewSearch = $("view-search");

    const CHECK_SVG = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    const X_SVG = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    function scrollToPaperCard(uid) {
        const card = pl.querySelector(`.paper-card[data-uid="${uid}"]`);
        if (!card) return;
        card.scrollIntoView({ behavior: "smooth", block: "center" });
        card.style.transition = "box-shadow .2s";
        card.style.boxShadow = "0 0 0 3px rgba(37,99,235,.4)";
        setTimeout(() => { card.style.boxShadow = ""; }, 1200);
    }

    function toggleComparePanel() {
        comparePanelOpen = !comparePanelOpen;
        viewSearch.classList.toggle("compare-open", comparePanelOpen);
        cmpToggle.classList.toggle("active", comparePanelOpen);
        if (comparePanelOpen) {
            const w = lsGet("compare_width", null);
            if (w) cmpPanel.style.flexBasis = w;
            renderCompare();
        }
    }

    function renderCompare() {
        renderCompareCandidates();
        renderCompareSelected();
        renderCompareHistory();
        updateRunButton();
    }

    function renderCompareCandidates() {
        const list = getComparablePapers();
        cmpCandCount.textContent = list.length;
        if (!list.length) {
            cmpCandList.innerHTML = '<div class="compare-empty">暂无可对比论文。请先点击论文查看详情并生成摘要。</div>';
            return;
        }
        cmpCandList.innerHTML = "";
        for (const p of list) {
            const checked = selectedCompareIds.has(p.uid);
            const row = document.createElement("div");
            row.className = "compare-row";
            row.innerHTML = `
                <div class="compare-row-check${checked ? ' checked' : ''}" data-uid="${p.uid}">${CHECK_SVG}</div>
                <span class="compare-row-title" data-uid="${p.uid}" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</span>`;
            row.querySelector(".compare-row-check").addEventListener("click", () => toggleCompareSelect(p.uid));
            row.querySelector(".compare-row-title").addEventListener("click", () => scrollToPaperCard(p.uid));
            cmpCandList.appendChild(row);
        }
    }

    function renderCompareSelected() {
        const ids = [...selectedCompareIds];
        cmpSelCount.textContent = ids.length;
        if (!ids.length) {
            cmpSelList.innerHTML = '<div class="compare-empty">勾选左侧候选论文加入对比列表。</div>';
            return;
        }
        cmpSelList.innerHTML = "";
        for (const uid of ids) {
            const p = paperMap[uid];
            if (!p) continue;
            const row = document.createElement("div");
            row.className = "compare-row";
            row.innerHTML = `
                <span class="compare-row-title" data-uid="${uid}" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</span>
                <button class="compare-row-remove" data-uid="${uid}">${X_SVG}</button>`;
            row.querySelector(".compare-row-title").addEventListener("click", () => scrollToPaperCard(uid));
            row.querySelector(".compare-row-remove").addEventListener("click", () => toggleCompareSelect(uid));
            cmpSelList.appendChild(row);
        }
    }

    function toggleCompareSelect(uid) {
        if (selectedCompareIds.has(uid)) selectedCompareIds.delete(uid);
        else selectedCompareIds.add(uid);
        renderCompareCandidates();
        renderCompareSelected();
        updateRunButton();
    }

    function updateRunButton() {
        cmpRun.disabled = selectedCompareIds.size < 2;
    }

    function renderCompareHistory() {
        const hist = getCompareHistory();
        if (!hist.length) {
            cmpHistList.innerHTML = '<div class="compare-empty">暂无对比历史。</div>';
            return;
        }
        cmpHistList.innerHTML = "";
        hist.forEach((h, i) => {
            const item = document.createElement("div");
            item.className = "compare-history-item";
            item.innerHTML = `<div class="ch-date">${h.date}</div><div class="ch-titles">${escapeHtml(h.titles)}</div>`;
            item.addEventListener("click", () => { cmpResult.innerHTML = h.html; });
            cmpHistList.appendChild(item);
        });
    }

    async function runCompare() {
        const ids = [...selectedCompareIds];
        if (ids.length < 2) return;
        cmpRun.disabled = true;
        cmpResult.innerHTML = '<div class="compare-result-loading"><div class="spinner"></div>正在对比分析...</div>';
        try {
            const data = await apiPost("/api/compare", { paper_ids: ids.join(",") });
            const html = md(data.comparison || "");
            cmpResult.innerHTML = html;
            // save to session history
            const titles = ids.map(u => (paperMap[u] && paperMap[u].title) || u).join("、");
            const hist = getCompareHistory();
            hist.unshift({
                date: new Date().toLocaleString("zh-CN", { hour12: false }),
                titles: titles,
                html: html,
            });
            if (hist.length > 20) hist.length = 20;
            setCompareHistory(hist);
            renderCompareHistory();
        } catch (e) {
            cmpResult.innerHTML = `<div class="compare-empty" style="color:#dc2626">${escapeHtml(e.message || "对比分析失败")}</div>`;
        } finally {
            updateRunButton();
        }
    }

    // Section collapse
    function bindCompareSection(head) {
        if (!head) return;
        head.addEventListener("click", () => head.parentElement.classList.toggle("collapsed"));
    }

    // Divider drag resize
    function initCompareResize() {
        let dragging = false;
        cmpDivider.addEventListener("mousedown", (e) => {
            dragging = true;
            cmpDivider.classList.add("dragging");
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
            e.preventDefault();
        });
        document.addEventListener("mousemove", (e) => {
            if (!dragging) return;
            const total = viewSearch.clientWidth;
            const sidebar = $("search-sidebar").offsetWidth;
            const usable = total - sidebar;
            let w = total - e.clientX;          // distance from right edge
            const minW = usable * 0.25, maxW = usable * 0.6;
            w = Math.max(minW, Math.min(maxW, w));
            cmpPanel.style.flexBasis = w + "px";
        });
        document.addEventListener("mouseup", () => {
            if (!dragging) return;
            dragging = false;
            cmpDivider.classList.remove("dragging");
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
            lsSet("compare_width", cmpPanel.style.flexBasis);
        });
    }

    if (cmpToggle) {
        cmpToggle.addEventListener("click", toggleComparePanel);
        cmpClose.addEventListener("click", toggleComparePanel);
        cmpRun.addEventListener("click", runCompare);
        bindCompareSection(cmpHistHead);
        bindCompareSection(cmpCandHead);
        initCompareResize();
    }

    // ── Init ──
    async function loadState() {
        // 1. Try server state first
        let query = "";
        try {
            const r = await fetch("/api/state");
            const data = await r.json();
            query = data.query || "";
            if (data.papers && data.papers.length) {
                papers = data.papers;
                paperMap = {};
                for (const p of papers) {
                    paperMap[p.uid] = p;
                    if (p.has_summary && p.summary) {
                        summaryCache[p.uid] = md(p.summary);
                    }
                    if (p.has_review && p.review) {
                        reviewCache[p.uid] = md(p.review);
                    }
                }
                subtopics = data.subtopics || [];
                rebuildPaperList();
                if (subtopics.length) renderSubtopics();
                si.value = query;
            }
            if (data.chat_by_paper) {
                chatCache = data.chat_by_paper;
            }
        } catch (_) {}
        // 2. Try snapshot for richer state (has generated summaries/reviews not in session.json)
        if (query && lsGet("snap_" + query, null)) {
            restoreSnapshot(query);
        } else {
            _currentQuery = query;
        }
        renderSearchHistory();
        handleRoute();
    }
    loadState();
})();
