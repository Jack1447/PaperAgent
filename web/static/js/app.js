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
            if (paperMap[uid]) { currentPaperId = uid; showView("detail"); renderDetail(uid); }
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
            cm.innerHTML += `<div class="chat-msg ${m.role}"><div class="chat-bubble">${html}</div></div>`;
        }
        const typing = cm.querySelector(".chat-typing");
        if (typing) typing.remove();
        cm.scrollTop = cm.scrollHeight;
    }

    function showTyping() {
        cm.innerHTML += `<div class="chat-msg assistant chat-typing"><div class="chat-bubble typing-indicator"><span></span><span></span><span></span></div></div>`;
        cm.scrollTop = cm.scrollHeight;
    }

    async function doSendChat(uid) {
        const msg = ci.value.trim();
        if (!msg) return;

        if (!chatCache[uid]) chatCache[uid] = [];
        chatCache[uid].push({ role: "user", content: msg });
        renderChat(uid);

        ci.value = ""; ci.disabled = true; cs.disabled = true;
        showTyping();

        try {
            const data = await apiPost("/api/ask", { paper_id: uid, question: msg });
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

    // Sidebar toggle
    sbt.addEventListener("click", () => {
        sbar.classList.toggle("collapsed");
    });

    // New search button
    snew.addEventListener("click", () => {
        papers = []; subtopics = []; paperMap = {};
        summaryCache = {}; reviewCache = {}; chatCache = {};
        rebuildPaperList();
        st.style.display = "none";
        sc.innerHTML = "";
        es.style.display = "block";
        si.value = "";
        si.focus();
    });

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
