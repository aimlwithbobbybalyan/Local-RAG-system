let started = false;
  let flipped  = false;
  let cardIdx  = 0;

  // ── FIX 1: Pre-populate cards so flip/next/prev work without Flask ──
  let cards = [];
  let summaryLoaded = false;
  let quizLoaded    = false;
  let flashLoaded   = false;
  let examLoaded    = false;

  // on page load — check status and load docs
  window.addEventListener('DOMContentLoaded', async () => {
    await checkStatus();
    await loadDocuments();
  });

  // check if ollama + flask are running
  async function checkStatus() {
    try {
      const res  = await fetch('/status');
      const data = await res.json();

      // Ollama indicator dots
      document.querySelectorAll('.hdot').forEach(d => {
        d.style.background = data.ollama ? '' : '#e03131';
        d.style.boxShadow  = data.ollama ? '' : '0 0 6px rgba(224,49,49,.6)';
      });

      // Always update all 4 stats live
      document.getElementById('statDocs').textContent       = data.docs   ?? 0;
      const counter = document.getElementById('docCounter');
      if (counter) { const n = data.docs ?? 0; counter.textContent = n+'/3'; counter.style.color = n>=3 ? '#e03131' : 'var(--muted)'; counter.style.borderColor = n>=3 ? '#e03131' : 'var(--border)'; }
      document.getElementById('statChunks').textContent     = data.chunks ?? 0;
      document.getElementById('statChunkSize').textContent  = data.chunk_size ?? 512;
      document.getElementById('statK').textContent          = 'k=' + (data.top_k ?? 5);

    } catch(e) { console.log('Flask not running yet'); }
  }

  // load documents into sidebar
  async function loadDocuments() {
    try {
      const res  = await fetch('/documents');
      const data = await res.json();
      const list = document.getElementById('docList');
      if (!list || !data.documents || data.documents.length === 0) return;
      list.innerHTML = '';
      data.documents.forEach((doc, i) => {
        const el = document.createElement('div');
        el.className = 'doc-item' + (i === 0 ? ' active' : '');
        el.setAttribute('onclick', 'selectDoc(this)');
        el.innerHTML = `
          <div class="doc-icon"></div>
          <div class="doc-info">
            <div class="doc-name">${doc.name}</div>
            <div class="doc-meta">Indexed · ${doc.size_kb} KB</div>
          </div>
          <div class="doc-del" onclick="event.stopPropagation();deleteDocument('${doc.name}',this.closest('.doc-item'))"></div>`;
        list.appendChild(el);
      });
    } catch(e) { console.log('Could not load documents'); }
  }

  // ── RIPPLE EFFECT — attach to all current + future buttons ──────────────
  function addRipple(e) {
    const btn  = e.currentTarget;
    const wave = document.createElement('span');
    wave.className = 'ripple-wave';
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 1.8;
    wave.style.cssText = `width:${size}px;height:${size}px;left:${e.clientX-rect.left-(size/2)}px;top:${e.clientY-rect.top-(size/2)}px`;
    btn.classList.add('ripple-btn');
    btn.appendChild(wave);
    wave.addEventListener('animationend', () => wave.remove());
  }
  function attachRipples(root = document) {
    root.querySelectorAll('button, .fn-btn, .quiz-retry-btn, .quiz-regen-btn, .exam-regen-btn, .upload-modal-btn').forEach(btn => {
      if (!btn._ripple) { btn.addEventListener('click', addRipple); btn._ripple = true; }
    });
  }
  document.addEventListener('DOMContentLoaded', () => {
    attachRipples();
    // re-attach whenever DOM changes (handles dynamically created buttons)
    const obs = new MutationObserver(() => attachRipples());
    obs.observe(document.body, { childList: true, subtree: true });
  });

  // ── UPLOAD OVERLAY ──────────────────────────────────────────────────────
  function openUploadOverlay() {
    document.getElementById('uploadOverlay').classList.add('open');
    // reset to default state
    document.getElementById('uploadOverlayContent').innerHTML = `
      <div class="upload-modal-icon">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
          <polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>
        </svg>
      </div>
      <div class="upload-modal-title">Upload your document</div>
      <div class="upload-modal-sub">Drag and drop here, or click below to browse.<br>Supports PDF, DOCX, TXT, MD — max 50MB</div>
      <div class="file-types" style="justify-content:center;margin-bottom:20px;">
        <div class="ftype pdf">PDF</div><div class="ftype txt">TXT</div><div class="ftype docx">DOCX</div><div class="ftype md">MD</div>
      </div>
      <button class="upload-modal-btn" onclick="triggerFileInput()">Choose File</button>`;
  }

  function closeUploadOverlay() {
    const overlay = document.getElementById('uploadOverlay');
    overlay.classList.add('closing');
    setTimeout(() => {
      overlay.classList.remove('open');
      overlay.classList.remove('closing');
    }, 260);
  }

  function triggerFileInput() {
    const input  = document.createElement('input');
    input.type   = 'file';
    input.accept = '.pdf,.txt,.docx,.md';
    input.onchange = e => { if (e.target.files[0]) handleUploadFromOverlay(e.target.files[0]); };
    input.click();
  }

  function handleUploadFromOverlay(file) {
    if (!file) return;
    handleUpload(file, true); // true = called from overlay
  }

  // trigger file picker — now opens overlay instead
  function simulateUpload() {
    openUploadOverlay();
  }

  // drag and drop support on the sidebar zone
  document.addEventListener('DOMContentLoaded', () => {
    const zone = document.querySelector('.upload-zone');
    if (!zone) return;
    zone.addEventListener('dragover', e => { e.preventDefault(); zone.style.borderColor='var(--accent)'; zone.classList.add('uploading'); });
    zone.addEventListener('dragleave', () => { zone.style.borderColor=''; zone.classList.remove('uploading'); });
    zone.addEventListener('drop', e => {
      e.preventDefault(); zone.style.borderColor=''; zone.classList.remove('uploading');
      if (e.dataTransfer.files[0]) handleUpload(e.dataTransfer.files[0]);
    });
  });

  // real file upload to /upload
  async function handleUpload(file, fromOverlay = false) {
    const pw = document.getElementById('progWrap');
    const pf = document.getElementById('progFill');
    const pl = document.getElementById('progLabel');
    const uploadZone = document.querySelector('.upload-zone');

    // Show progress in sidebar
    pw.style.display = 'block';
    pf.style.width   = '10%';
    pl.textContent   = 'Uploading...';
    if (uploadZone) uploadZone.classList.add('uploading');

    // Show loading state in overlay if open
    if (fromOverlay) {
      document.getElementById('uploadOverlayContent').innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;gap:14px;">
          <div style="width:56px;height:56px;border-radius:50%;border:3px solid var(--accent-mid);border-top-color:var(--accent);animation:spin .8s linear infinite;"></div>
          <div style="font-size:.95rem;font-weight:700;color:var(--text)" id="overlayStatusText">Uploading file...</div>
          <div style="font-size:.78rem;color:var(--muted)" id="overlayStatusSub">Please wait</div>
          <div style="width:200px;height:5px;background:var(--border);border-radius:3px;overflow:hidden;">
            <div id="overlayProgFill" style="height:100%;width:10%;background:linear-gradient(90deg,var(--accent),var(--purple));border-radius:3px;transition:width .2s;"></div>
          </div>
        </div>`;
    }

    const formData = new FormData();
    formData.append('file', file);

    let fake = 10;
    const iv = setInterval(() => {
      if (fake < 85) {
        fake += 3;
        pf.style.width = fake + '%';
        const opf = document.getElementById('overlayProgFill');
        if (opf) opf.style.width = fake + '%';
        const statusTexts = {
          30: ['Loading document...','Parsing file contents...'],
          55: ['Creating chunks...','Splitting into segments...'],
          75: ['Generating embeddings...','Running nomic-embed-text...'],
          86: ['Saving to ChromaDB...','Storing vector index...'],
        };
        let msg = 'Uploading...', sub = 'Please wait';
        if (fake >= 75) { msg='Saving to ChromaDB...'; sub='Almost done...'; }
        else if (fake >= 55) { msg='Generating embeddings...'; sub='Running nomic-embed-text'; }
        else if (fake >= 30) { msg='Creating chunks...'; sub='Splitting document into segments'; }
        if (fake < 30)  pl.textContent = 'Loading document...';
        else if (fake < 55) pl.textContent = 'Creating chunks...';
        else if (fake < 75) pl.textContent = 'Generating embeddings...';
        else pl.textContent = 'Saving to ChromaDB...';
        const stEl = document.getElementById('overlayStatusText');
        const sbEl = document.getElementById('overlayStatusSub');
        if (stEl) stEl.textContent = msg;
        if (sbEl) sbEl.textContent = sub;
      }
    }, 200);

    try {
      const res  = await fetch('/upload', { method:'POST', body:formData });
      const data = await res.json();
      clearInterval(iv);

      if (uploadZone) uploadZone.classList.remove('uploading');

      if (data.success) {
        pf.style.width = '100%';
        pl.textContent = `${data.filename} indexed! (${data.chunks} chunks)`;
        summaryLoaded = false; quizLoaded = false; flashLoaded = false; examLoaded = false;
        startCachePolling(); // poll until pre-generation is done

        // Show success state in overlay
        if (fromOverlay) {
          const box = document.getElementById('uploadModalBox');
          box.classList.add('done');
          document.getElementById('uploadOverlayContent').innerHTML = `
            <div class="upload-success-check">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--green)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </div>
            <div style="font-size:1rem;font-weight:800;color:var(--text);margin-bottom:6px;">${data.filename}</div>
            <div style="font-size:.82rem;color:var(--green);font-weight:600;margin-bottom:4px;">Successfully indexed!</div>
            <div style="font-size:.75rem;color:var(--muted)">${data.chunks} chunks stored in ChromaDB</div>`;
          // Close overlay after a moment and animate back
          setTimeout(() => closeUploadOverlay(), 1800);
        }

        // Add doc to sidebar with animation
        const list = document.getElementById('docList');
        const el   = document.createElement('div');
        el.className = 'doc-item';
        el.setAttribute('onclick', 'selectDoc(this)');
        el.innerHTML = `
          <div class="doc-icon"></div>
          <div class="doc-info">
            <div class="doc-name">${data.filename}</div>
            <div class="doc-meta">${data.chunks} chunks · indexed</div>
          </div>
          <div class="doc-del" onclick="event.stopPropagation();deleteDocument('${data.filename}',this.closest('.doc-item'))"></div>`;
        list.appendChild(el);

        await checkStatus();
        // Flash the stat cards
        document.querySelectorAll('.stat-val').forEach(v => { v.classList.remove('flash'); void v.offsetWidth; v.classList.add('flash'); });
        setTimeout(() => { pw.style.display='none'; pf.style.width='0%'; }, 2500);

      } else {
        if (fromOverlay) {
          document.getElementById('uploadOverlayContent').innerHTML = `
            <div style="font-size:2.5rem;margin-bottom:12px;">&#x26A0;</div>
            <div style="font-size:.9rem;font-weight:700;color:var(--text);margin-bottom:8px;">Upload failed</div>
            <div style="font-size:.8rem;color:var(--muted);margin-bottom:16px;">${data.error || 'Unknown error'}</div>
            <button class="upload-modal-btn" onclick="openUploadOverlay()">Try Again</button>`;
        }
        pl.textContent = 'Error: ' + (data.error || 'Upload failed');
      }
    } catch(e) {
      clearInterval(iv);
      if (uploadZone) uploadZone.classList.remove('uploading');
      if (fromOverlay) {
        document.getElementById('uploadOverlayContent').innerHTML = `
          <div style="font-size:2.5rem;margin-bottom:12px;">&#x26A0;</div>
          <div style="font-size:.9rem;font-weight:700;color:var(--text);margin-bottom:8px;">Server not reachable</div>
          <div style="font-size:.78rem;color:var(--muted);margin-bottom:16px;">Make sure app.py is running on port 5000.</div>
          <button class="upload-modal-btn" onclick="openUploadOverlay()">Try Again</button>`;
      }
      pl.textContent = 'Server error — is Flask running?';
    }
  }

  // close overlay on background click
  document.getElementById('uploadOverlay').addEventListener('click', function(e) {
    if (e.target === this) closeUploadOverlay();
  });

  // ── FLASHCARD 3D FLIP ANIMATION ─────────────────────────────────────────
  function flipCard(){
    if(cards.length===0) return;
    const fc = document.getElementById('flashcard');
    // Add a bounce-lift before the flip
    fc.style.transition = 'transform .55s cubic-bezier(.4,0,.2,1), box-shadow .3s ease';
    fc.classList.remove('flip-anim');
    void fc.offsetWidth;
    fc.classList.add('flip-anim');
    flipped = !flipped;
    // Swap content exactly at the midpoint of the flip (245ms into 500ms)
    setTimeout(() => {
      const lbl     = document.getElementById('fcLabel');
      const content = document.getElementById('fcContent');
      const hint    = document.querySelector('.fc-hint');
      if (flipped) {
        fc.style.background = '';
        fc.classList.add('is-answer');
        if (lbl)     lbl.textContent     = 'Answer';
        if (content) content.textContent = cards[cardIdx].answer;
        if (hint)    hint.textContent    = '↩ Click to see question';
      } else {
        fc.style.background = '';
        fc.classList.remove('is-answer');
        if (lbl)     lbl.textContent     = 'Question';
        if (content) content.textContent = cards[cardIdx].question;
        if (hint)    hint.textContent    = '👆 Click to reveal answer';
      }
    }, 245);
  }

  // ── SPIN KEYFRAME for upload spinner ───────────────────────────────────

  async function sendMessage() {
    const input = document.getElementById('chatInput');
    const text  = input.value.trim();
    if (!text) return;

    setTab(document.querySelectorAll('.tab')[0], 'chat');

    if (!started) {
      const w = document.getElementById('welcomeEl'); if (w) w.remove();
      const ps  = document.getElementById('promptSuggestions');
      const btn = document.getElementById('promptToggle');
      if (ps)  ps.classList.remove('open');
      if (btn) btn.classList.remove('open');
      started = true;
    }

    addMsg('user', text);
    input.value = ''; input.style.height = 'auto';
    showPipeline(); showThinking();

    const activeTags = [...document.querySelectorAll('.itag.on')].map(t => t.textContent.trim());

    // ── STREAMING CHAT ──────────────────────────────────────────────────
    try {
      const res = await fetch('/chat/stream', {
        method:  'POST',
        headers: { 'Content-Type':'application/json' },
        body:    JSON.stringify({ question:text, tags:activeTags })
      });

      if (!res.ok) throw new Error('Stream request failed');

      hideThinking(); hidePipeline();

      // FIX 1: use a direct reference, NOT getElementById with hardcoded id
      // so multiple messages never clash with each other
      const area   = document.getElementById('chatArea');
      const msgRow = document.createElement('div');
      msgRow.className = 'msg-row ai';
      msgRow.innerHTML = `${aiAva()}<div class="msg-body"><div class="bubble"></div></div>`;
      area.appendChild(msgRow);
      area.scrollTop = area.scrollHeight;

      // FIX 2: reference bubble directly from the element we just created
      const bubble = msgRow.querySelector('.bubble');
      let fullText = '';

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();

      // FIX 3: show a blinking cursor while tokens arrive
      bubble.innerHTML = '<span class="tw-cursor"></span>';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6).trim();
          if (payload === '[DONE]') break;
          try {
            const parsed = JSON.parse(payload);
            if (parsed.token) {
              fullText += parsed.token;
              // Show text + keep cursor at end while streaming
              bubble.innerHTML = formatAnswer(fullText) + '<span class="tw-cursor"></span>';
              area.scrollTop   = area.scrollHeight;
            }
            if (parsed.error) {
              bubble.innerHTML = 'Warning: ' + parsed.error;
            }
          } catch(e) { /* partial JSON chunk, skip */ }
        }
      }

      // FIX 4: remove cursor when done
      bubble.innerHTML = formatAnswer(fullText);
      area.scrollTop   = area.scrollHeight;
      addToHistory(text);

    } catch(streamErr) {
      // Fallback to non-streaming if stream fails or not supported
      hideThinking(); hidePipeline();
      try {
        const res  = await fetch('/chat', {
          method:  'POST',
          headers: { 'Content-Type':'application/json' },
          body:    JSON.stringify({ question:text, tags:activeTags })
        });
        const data = await res.json();
        if (data.error) {
          addAIMsg({ text:'Warning: ' + data.error, sources:[], conf:0 });
        } else {
          addAIMsg({ text:formatAnswer(data.answer), sources:data.sources||[], conf:data.confidence||85 });
          addToHistory(text);
        }
      } catch(e) {
        addAIMsg({ text:'Warning: Could not reach Flask. Make sure app.py is running!', sources:[], conf:0 });
      }
    }
  }

  // ── CACHE STATUS POLLING ─────────────────────────────────────────────────
  // After upload, poll /cache/status every 5s
  // Show a small "Generating study materials..." banner until ready
  let _cachePoller = null;

  function startCachePolling() {
    if (_cachePoller) clearInterval(_cachePoller);
    showCacheBanner('Generating study materials in background...');
    _cachePoller = setInterval(async () => {
      try {
        const res  = await fetch('/cache/status');
        const data = await res.json();
        if (data.all_ready) {
          clearInterval(_cachePoller); _cachePoller = null;
          showCacheBanner('Study materials ready! Quiz, Flashcards & Exam are instant.', true);
          setTimeout(hideCacheBanner, 3500);
        } else if (!data.generating) {
          clearInterval(_cachePoller); _cachePoller = null;
          hideCacheBanner();
        }
      } catch(e) { /* ignore */ }
    }, 5000);
  }

  function showCacheBanner(msg, success = false) {
    let b = document.getElementById('cacheBanner');
    if (!b) {
      b = document.createElement('div');
      b.id = 'cacheBanner';
      b.style.cssText = `
        position:fixed; bottom:20px; right:20px; z-index:999;
        padding:10px 18px; border-radius:10px; font-size:.78rem; font-weight:600;
        display:flex; align-items:center; gap:8px;
        box-shadow:0 4px 20px rgba(0,0,0,.15);
        animation:msgIn .3s ease;
        transition:background .3s, border-color .3s;
      `;
      document.body.appendChild(b);
    }
    if (success) {
      b.style.background = 'var(--green-soft)';
      b.style.border     = '1px solid var(--green)';
      b.style.color      = 'var(--green)';
      b.innerHTML        = `<span>✅</span> ${msg}`;
    } else {
      b.style.background = 'var(--accent-soft)';
      b.style.border     = '1px solid var(--accent-mid)';
      b.style.color      = 'var(--accent)';
      b.innerHTML        = `<span style="animation:spin .8s linear infinite;display:inline-block">⟳</span> ${msg}`;
    }
  }

  function hideCacheBanner() {
    const b = document.getElementById('cacheBanner');
    if (b) { b.style.opacity = '0'; setTimeout(() => b.remove(), 300); }
  }

  // convert plain text to HTML formatting
  function formatAnswer(text) {
    return text
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n[-•]\s/g, '<br>• ')
      .replace(/\n(\d+)\.\s/g, '<br>$1. ')
      .replace(/\n/g, '<br>');
  }

  // No fallback content — show upload prompt when Flask not running
  const FALLBACK_SUMMARY = {
    overview: "Upload a document to generate a summary.",
    key_points: ["Click '+ Add' in the sidebar to upload a PDF, DOCX, or TXT file."],
    concepts: []
  };

  function toggleSection(el) {
    const body  = el.nextElementSibling;
    const arrow = el.querySelector('.sum-section-arrow');
    body.classList.toggle('open');
    arrow.classList.toggle('open');
  }

  function renderSummary(wrap, header, d) {
    wrap.innerHTML = ''; if (header) wrap.appendChild(header);

    // ── Overview card ──
    const ov = document.createElement('div');
    ov.className = 'sum-overview';
    ov.innerHTML = `
      <div class="sum-overview-title"> What is this document about?</div>
      ${d.title ? `<div class="sum-overview-doc">${d.title}</div>` : ''}
      <p>${d.overview || ''}</p>`;
    wrap.appendChild(ov);

    // ── Sections (collapsible) ──
    if (d.sections && d.sections.length > 0) {
      const secWrap = document.createElement('div');
      secWrap.className = 'sum-card';
      secWrap.innerHTML = `<div class="sum-card-title"> Topics Covered</div>`;
      const secList = document.createElement('div');
      secList.className = 'sum-sections';
      d.sections.forEach((s, i) => {
        const sec = document.createElement('div');
        sec.className = 'sum-section';
        sec.innerHTML = `
          <div class="sum-section-head" onclick="toggleSection(this)">
            <div class="sum-section-title">
              <span class="sum-section-num">${i+1}</span>
              ${s.heading}
            </div>
            <span class="sum-section-arrow">▶</span>
          </div>
          <div class="sum-section-body">${s.summary}</div>`;
        secList.appendChild(sec);
      });
      // Auto-open the first section
      secList.firstChild.querySelector('.sum-section-body').classList.add('open');
      secList.firstChild.querySelector('.sum-section-arrow').classList.add('open');
      secWrap.appendChild(secList);
      wrap.appendChild(secWrap);
    }

    // ── Key points ──
    if (d.key_points && d.key_points.length > 0) {
      const kp = document.createElement('div');
      kp.className = 'sum-card';
      kp.innerHTML = `
        <div class="sum-card-title"> Key Points to Remember</div>
        <div class="key-points">${d.key_points.map(k=>`<div class="kp"><div class="kp-dot"></div>${k}</div>`).join('')}</div>`;
      wrap.appendChild(kp);
    }

    // ── Concepts ──
    if (d.concepts && d.concepts.length > 0) {
      const cc = document.createElement('div');
      cc.className = 'sum-card';
      cc.innerHTML = `
        <div class="sum-card-title"> Important Terms</div>
        <div class="concept-chips">${d.concepts.map(c=>`<div class="concept-chip" onclick="sendQ('Explain ${c} in simple words')">${c}</div>`).join('')}</div>
        <div style="font-size:.72rem;color:var(--muted);margin-top:4px;">Click any term to ask the AI to explain it</div>`;
      wrap.appendChild(cc);
    }
  }

  // load summary from /summary API
  // ── shared helpers for generate-button panels ──────────────────────────
  function panelReady(wrap, header, icon, title, sub, btnLabel, onGenerate) {
    wrap.innerHTML = ''; if (header) wrap.appendChild(header);
    const box = document.createElement('div');
    box.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:14px;padding:50px 20px;text-align:center;';
    box.innerHTML = `
      <div style="font-size:3rem">${icon}</div>
      <div style="font-size:1rem;font-weight:700;color:var(--text)">${title}</div>
      <div style="font-size:.8rem;color:var(--muted);max-width:300px;line-height:1.6">${sub}</div>`;
    const btn = document.createElement('button');
    btn.innerHTML = ` ${btnLabel}`;
    btn.style.cssText = 'padding:11px 30px;border-radius:10px;border:none;background:var(--accent);color:white;font-size:.88rem;font-weight:700;cursor:pointer;font-family:inherit;margin-top:4px;';
    btn.onclick = onGenerate;
    box.appendChild(btn);
    wrap.appendChild(box);
  }

  function panelLoading(wrap, header, icon, msg) {
    wrap.innerHTML = ''; if (header) wrap.appendChild(header);
    const box = document.createElement('div');
    box.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;padding:50px 20px;text-align:center;';
    box.innerHTML = `
      <div style="font-size:2.5rem">${icon}</div>
      <div style="font-size:.9rem;font-weight:600;color:var(--text)">${msg}</div>
      <div style="font-size:.75rem;color:var(--muted)">This may take 20–40 seconds...</div>
      <div style="width:200px;height:4px;background:var(--border);border-radius:4px;overflow:hidden;margin-top:4px">
        <div style="height:100%;width:40%;background:var(--accent);border-radius:4px;animation:shimmer 1.2s ease-in-out infinite"></div>
      </div>`;
    wrap.appendChild(box);
  }

  function panelError(wrap, header, msg, onRetry) {
    wrap.innerHTML = ''; if (header) wrap.appendChild(header);
    const box = document.createElement('div');
    box.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;padding:40px 20px;text-align:center;';
    box.innerHTML = `<div style="font-size:2rem">Warning:</div><div style="font-size:.82rem;color:var(--muted);max-width:300px">${msg}</div>`;
    const btn = document.createElement('button');
    btn.textContent = '↺ Try Again';
    btn.style.cssText = 'padding:8px 22px;border-radius:8px;border:none;background:var(--accent);color:white;font-size:.8rem;font-weight:700;cursor:pointer;font-family:inherit;';
    btn.onclick = onRetry;
    box.appendChild(btn);
    wrap.appendChild(box);
  }

  function panelNoDoc(wrap, header) {
    wrap.innerHTML = ''; if (header) wrap.appendChild(header);
    const box = document.createElement('div');
    box.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:12px;padding:50px 20px;text-align:center;';
    box.innerHTML = `
      <div style="font-size:2.5rem"></div>
      <div style="font-size:.9rem;font-weight:600;color:var(--text)">No document uploaded</div>
      <div style="font-size:.78rem;color:var(--muted)">Upload a PDF, DOCX or TXT file first using the sidebar.</div>`;
    wrap.appendChild(box);
  }

  async function doGenerateSummary() {
    const wrap   = document.getElementById('summaryPanel').querySelector('.summary-wrap');
    const header = wrap.querySelector('.panel-header');
    panelLoading(wrap, header, '', 'Reading your document...');
    try {
      const res  = await fetch('/summary', { method:'POST' });
      const data = await res.json();
      if (data.error) { panelError(wrap, header, data.error, () => { summaryLoaded=false; loadSummary(); }); return; }
      summaryLoaded = true;
      renderSummary(wrap, header, data.data);
    } catch(e) {
      panelError(wrap, header, 'Could not connect. Make sure Flask is running.', () => { summaryLoaded=false; loadSummary(); });
    }
  }

  async function loadSummary() {
    if (summaryLoaded) return;
    const wrap   = document.getElementById('summaryPanel').querySelector('.summary-wrap');
    const header = wrap.querySelector('.panel-header');
    try {
      const st = await fetch('/status'); const sd = await st.json();
      if (sd.chunks && sd.chunks > 0) {
        panelReady(wrap, header, '', 'Document ready!', 'Generate a full AI summary covering all key topics, concepts and important points from your document.', 'Generate Summary', doGenerateSummary);
      } else {
        panelNoDoc(wrap, header);
      }
    } catch(e) { panelNoDoc(wrap, header); }
  }

  const FALLBACK_QUIZ = { questions: [] };

  // ── QUIZ ENGINE ─────────────────────────────────────────────────────────
  let quizQuestions = [];
  let quizCurrent   = 0;
  let quizScore     = 0;
  let quizAnswered  = false;

  function getLetters() { return ['A','B','C','D']; }

  function showQuizQuestion() {
    const wrap = document.getElementById('quizWrap');
    const q    = quizQuestions[quizCurrent];
    const pct  = Math.round((quizCurrent / quizQuestions.length) * 100);
    const diff = quizCurrent < 5 ? 'easy' : quizCurrent < 11 ? 'medium' : 'hard';

    wrap.innerHTML = `
      <div class="quiz-header-bar">
        <div class="quiz-score-pill">Score &nbsp;<span class="quiz-score-val" id="quizScoreVal">${quizScore} / ${quizQuestions.length}</span></div>
        <button class="quiz-regen-btn" onclick="doGenerateQuiz()">↺ New Quiz</button>
      </div>

      <div class="quiz-progress-wrap">
        <div class="quiz-progress-top">
          <span class="quiz-progress-label">Question ${quizCurrent + 1} of ${quizQuestions.length}</span>
          <span class="quiz-progress-frac">${pct}% complete</span>
        </div>
        <div class="quiz-progress-track">
          <div class="quiz-progress-fill" style="width:${pct}%"></div>
        </div>
      </div>

      <div class="quiz-card">
        <div class="quiz-num">
          Q${quizCurrent + 1}
          <span class="quiz-difficulty ${diff}">${diff.toUpperCase()}</span>
        </div>
        <div class="quiz-q">${q.question}</div>
        <div class="quiz-opts" id="quizOpts">
          ${q.options.map((o, oi) => `
            <div class="quiz-opt" onclick="answerQuiz(this, ${oi})">
              <span class="opt-letter">${getLetters()[oi]}</span>
              <span>${o.replace(/^[A-D]\.\s*/,'')}</span>
            </div>`).join('')}
        </div>
        <div class="quiz-explanation" id="quizExp">
          <div class="quiz-exp-label"> Explanation</div>
          ${q.explanation || ''}
        </div>
      </div>

      <button class="quiz-next-btn" id="quizNextBtn" onclick="nextQuizQuestion()">
        ${quizCurrent + 1 < quizQuestions.length ? 'Next Question →' : 'See Results '}
      </button>`;

    quizAnswered = false;
  }

  function answerQuiz(el, chosenIdx) {
    if (quizAnswered) return;
    quizAnswered = true;
    const q    = quizQuestions[quizCurrent];
    const opts = document.querySelectorAll('.quiz-opt');
    opts.forEach(o => o.classList.add('disabled'));
    el.classList.add(chosenIdx === q.correct ? 'correct' : 'wrong');
    if (chosenIdx !== q.correct) opts[q.correct].classList.add('correct');
    if (chosenIdx === q.correct) quizScore++;
    document.getElementById('quizScoreVal').textContent = `${quizScore} / ${quizQuestions.length}`;
    const exp = document.getElementById('quizExp');
    if (exp) exp.classList.add('show');
    const btn = document.getElementById('quizNextBtn');
    if (btn) btn.classList.add('show');
  }

  function nextQuizQuestion() {
    quizCurrent++;
    if (quizCurrent >= quizQuestions.length) {
      showQuizResults();
    } else {
      showQuizQuestion();
    }
  }

  function showQuizResults() {
    const wrap   = document.getElementById('quizWrap');
    const total  = quizQuestions.length;
    const pct    = Math.round((quizScore / total) * 100);
    const wrong  = total - quizScore;
    const grade  = pct >= 80 ? ' Excellent!' : pct >= 60 ? ' Good Job!' : pct >= 40 ? ' Keep Studying' : ' Try Again!';
    const msg    = pct >= 80 ? "You have a strong grasp of this document's content."
                 : pct >= 60 ? "You understand most of the material. Review the missed questions."
                 : "Consider re-reading the document and retaking the quiz.";
    wrap.innerHTML = `
      <div class="quiz-results">
        <div class="quiz-results-circle">
          <div class="quiz-results-pct">${pct}%</div>
          <div class="quiz-results-lbl">Score</div>
        </div>
        <div class="quiz-results-title">${grade}</div>
        <div class="quiz-results-sub">${msg}</div>
        <div class="quiz-results-breakdown">
          <div class="qrb-card">
            <div class="qrb-val" style="color:var(--green)">${quizScore}</div>
            <div class="qrb-lbl">Correct</div>
          </div>
          <div class="qrb-card">
            <div class="qrb-val" style="color:#e03131">${wrong}</div>
            <div class="qrb-lbl">Wrong</div>
          </div>
          <div class="qrb-card">
            <div class="qrb-val" style="color:var(--accent)">${total}</div>
            <div class="qrb-lbl">Total</div>
          </div>
        </div>
        <button class="quiz-retry-btn" onclick="retryQuiz()">↺ Retry Quiz</button>
        <button class="quiz-retry-btn" style="background:var(--purple);margin-top:-6px" onclick="doGenerateQuiz()"> New Quiz</button>
      </div>`;
  }

  function retryQuiz() {
    quizCurrent = 0; quizScore = 0; quizAnswered = false;
    showQuizQuestion();
  }

  function renderQuiz(questions) {
    const wrap = document.getElementById('quizWrap');
    if (!questions || questions.length === 0) {
      wrap.innerHTML = `
        <div class="panel-header">
          <div class="panel-title"> Quiz Generator</div>
          <div class="panel-sub">15 questions covering your entire document</div>
        </div>
        <div style="text-align:center;padding:40px;color:var(--muted);font-size:.85rem;">
          <div style="font-size:2rem;margin-bottom:8px"></div>
          Upload a document to generate a quiz.
        </div>`;
      return;
    }
    quizQuestions = questions;
    quizCurrent   = 0;
    quizScore     = 0;
    quizAnswered  = false;
    showQuizQuestion();
  }

  // load quiz from /quiz API
  async function doGenerateQuiz() {
    const wrap = document.getElementById('quizWrap');
    const hdr  = wrap.querySelector('.panel-header');
    panelLoading(wrap, hdr, '', 'Generating quiz questions...');
    try {
      const res  = await fetch('/quiz', { method:'POST' });
      const data = await res.json();
      if (data.error || !data.data) {
        panelError(wrap, hdr, (data && data.error) || 'Could not generate quiz. Try again.', doGenerateQuiz);
        return;
      }
      quizLoaded = true;
      renderQuiz(data.data.questions || []);
    } catch(e) {
      panelError(wrap, hdr, 'Could not connect. Make sure Flask is running.', doGenerateQuiz);
    }
  }

  async function loadQuiz() {
    if (quizLoaded) return;
    const wrap = document.getElementById('quizWrap');
    const hdr  = wrap.querySelector('.panel-header');
    try {
      const st = await fetch('/status'); const sd = await st.json();
      if (sd.chunks && sd.chunks > 0) {
        panelReady(wrap, hdr, '', 'Ready to quiz you!', 'Generate 8 multiple choice questions covering all topics in your document — from easy to challenging.', 'Generate Quiz', doGenerateQuiz);
      } else {
        panelNoDoc(wrap, hdr);
      }
    } catch(e) { panelNoDoc(wrap, hdr); }
  }

  function renderFlashcardGrid() {
    cardIdx = 0; flipped = false;
    if (cards.length === 0) {
      document.getElementById('fcContent').textContent = 'Upload a document to generate flashcards';
      document.getElementById('fcCount').textContent = '0 / 0';
      const grid = document.querySelector('.flash-grid');
      if (grid) grid.innerHTML = '';
      return;
    }
    updateCard();
    var countEl = document.getElementById('fcCount');
    if (countEl) countEl.textContent = '1 / ' + cards.length;
    var grid = document.querySelector('.flash-grid');
    if (grid) grid.innerHTML = cards.map(function(c,i){ return '<div class="flash-mini" onclick="jumpCard('+i+')"><div class="flash-mini-q">'+c.question+'</div><div class="flash-mini-a">Click to study →</div></div>'; }).join('');
  }

  async function doGenerateFlashcards() {
    // Show loading state on the flashcard itself
    const fc  = document.getElementById('flashcard');
    const lbl = document.getElementById('fcLabel');
    const cnt = document.getElementById('fcContent');
    const cnt2 = document.getElementById('fcCount');
    if (lbl)  lbl.textContent  = 'GENERATING...';
    if (cnt)  cnt.textContent  = 'Reading your document and creating flashcards...';
    if (cnt2) cnt2.textContent = '⏳';
    const grid = document.querySelector('.flash-grid');
    if (grid) grid.innerHTML = '';
    try {
      const res  = await fetch('/flashcards', { method:'POST' });
      const data = await res.json();
      if (!data.error && data.data && (data.data.cards||[]).length > 0) {
        cards = data.data.cards;
        flashLoaded = true;
        renderFlashcardGrid();
      } else {
        if (lbl)  lbl.textContent  = 'ERROR';
        if (cnt)  cnt.textContent  = (data && data.error) || 'Could not generate. Try again.';
        if (cnt2) cnt2.textContent = '0 / 0';
      }
    } catch(e) {
      if (lbl)  lbl.textContent  = 'ERROR';
      if (cnt)  cnt.textContent  = 'Could not connect. Make sure Flask is running.';
      if (cnt2) cnt2.textContent = '0 / 0';
    }
  }

  async function loadFlashcards() {
    if (flashLoaded && cards.length > 0) { renderFlashcardGrid(); return; }
    // Show generate button on the flashcard face itself
    const lbl  = document.getElementById('fcLabel');
    const cnt  = document.getElementById('fcContent');
    const cnt2 = document.getElementById('fcCount');
    try {
      const st = await fetch('/status'); const sd = await st.json();
      if (sd.chunks && sd.chunks > 0) {
        if (lbl)  lbl.textContent  = 'FLASHCARDS';
        if (cnt)  cnt.innerHTML    = '<button onclick="doGenerateFlashcards()" style="padding:10px 26px;border-radius:10px;border:none;background:white;color:var(--accent);font-size:.88rem;font-weight:700;cursor:pointer;font-family:inherit;"> Generate Flashcards</button>';
        if (cnt2) cnt2.textContent = '0 / 0';
      } else {
        if (lbl)  lbl.textContent  = 'FLASHCARDS';
        if (cnt)  cnt.textContent  = 'Upload a document first, then generate flashcards.';
        if (cnt2) cnt2.textContent = '0 / 0';
      }
    } catch(e) {
      if (cnt) cnt.textContent = 'Could not connect to server.';
    }
  }

  // delete a document
  async function deleteDocument(filename, el) {
    if (!confirm(`Delete "${filename}"?`)) return;
    try {
      const res  = await fetch(`/document/${encodeURIComponent(filename)}`, { method:'DELETE' });
      const data = await res.json();
      if (data.success) {
        el.remove(); await checkStatus();
        summaryLoaded=false; quizLoaded=false; flashLoaded=false; cards=[]; examLoaded=false;
        activeDocFilter='all';
        const dl = document.getElementById('docList');
        const rem = dl ? [...dl.querySelectorAll('.doc-item')].map(d=>({name:d.querySelector('.doc-name').textContent})) : [];
        rebuildFilterPills(rem);
        // refresh whichever panel is currently open
        const activeTab = document.querySelector('.tab.active');
        if (activeTab) {
          const txt = activeTab.textContent.replace(/[^\w\s]/g,'').trim().toLowerCase();
          if (txt.includes('summary'))   loadSummary();
          if (txt.includes('quiz'))      loadQuiz();
          if (txt.includes('flash'))     loadFlashcards();
          if (txt.includes('exam'))      loadExam();
        }
      }
    } catch(e) { alert('Could not delete. Is Flask running?'); }
  }

  // delete entire index
  async function deleteIndex() {
    const btn = document.getElementById('delIndexBtn');
    if (!confirm('Delete chroma_db index? You will need to re-index your documents.')) return;
    btn.disabled = true;
    try {
      const res  = await fetch('/index', { method:'DELETE' });
      const data = await res.json();
      if (data.success) {
        document.querySelectorAll('.stat-val').forEach((v,i) => { if(i===1) v.textContent='0'; });
      }
    } catch(e) { console.log('Delete index error'); }
    finally { setTimeout(() => { btn.disabled=false; }, 2000); }
  }

  // add question to history
  function addToHistory(question) {
    const list = document.querySelector('.hist-list');
    if (!list) return;
    const el = document.createElement('div');
    el.className = 'hist-item';
    el.setAttribute('onclick', `sendQ('${question.replace(/'/g,"\\'")}')`);
    el.innerHTML = `<div class="hist-q">${question}</div><div class="hist-time">just now</div>`;
    list.prepend(el);
  }

  function clearHistory() { const l = document.querySelector('.hist-list'); if(l) l.innerHTML=''; }

  // ── EXAM ENGINE ──────────────────────────────────────────────────────────
  let examQuestions  = [];
  let examFilter     = 'All';

  function openExamPanel() {
    const tabs = document.querySelectorAll('.tab');
    // find exam tab (last one)
    for (let t of tabs) { if (t.textContent.includes('Exam')) { setTab(t, 'exam'); return; } }
  }

  function filterExam(difficulty, btn) {
    examFilter = difficulty;
    document.querySelectorAll('.exam-filter-btn').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    renderExamList();
  }

  function renderExamList() {
    const list = document.getElementById('examList');
    if (!list) return;
    const filtered = examFilter === 'All'
      ? examQuestions
      : examQuestions.filter(q => q.difficulty === examFilter);
    list.innerHTML = filtered.map((q, i) => `
      <div class="exam-q">
        <div class="exam-q-num">${String(i+1).padStart(2,'0')}</div>
        <div class="exam-q-body">
          <div class="exam-q-text">${q.question}</div>
          <span class="exam-q-diff ${q.difficulty}">${q.difficulty}</span>
          <span class="exam-q-ask" onclick="sendQ('${q.question.replace(/'/g,"\\'")}')">→ Ask AI this question</span>
        </div>
      </div>`).join('');
  }

  function renderExam(questions) {
    const wrap = document.getElementById('examWrap');
    const hdr  = wrap.querySelector('.panel-header');
    if (!questions || questions.length === 0) {
      panelError(wrap, hdr, 'No questions generated. Try again.', doGenerateExam);
      return;
    }
    examQuestions = questions;
    examFilter    = 'All';
    const easy   = questions.filter(q => q.difficulty === 'Easy').length;
    const medium = questions.filter(q => q.difficulty === 'Medium').length;
    const hard   = questions.filter(q => q.difficulty === 'Hard').length;

    wrap.innerHTML = '';
    if (hdr) wrap.appendChild(hdr);

    wrap.innerHTML += `
      <div class="exam-header-bar">
        <div class="exam-count-pill">Total &nbsp;<span class="exam-count-val">${questions.length} Questions</span></div>
        <button class="exam-regen-btn" onclick="doGenerateExam()">↺ Regenerate</button>
      </div>
      <div class="exam-filter-bar">
        <button class="exam-filter-btn on" onclick="filterExam('All',this)">All (${questions.length})</button>
        <button class="exam-filter-btn easy" onclick="filterExam('Easy',this)"> Easy (${easy})</button>
        <button class="exam-filter-btn medium" onclick="filterExam('Medium',this)"> Medium (${medium})</button>
        <button class="exam-filter-btn hard" onclick="filterExam('Hard',this)"> Hard (${hard})</button>
      </div>
      <div class="exam-list" id="examList"></div>`;
    renderExamList();
  }

  async function doGenerateExam() {
    const wrap = document.getElementById('examWrap');
    const hdr  = wrap.querySelector('.panel-header');
    panelLoading(wrap, hdr, '', 'Generating all exam questions...');
    try {
      const res  = await fetch('/exam', { method:'POST' });
      const data = await res.json();
      if (data.error || !data.data) {
        panelError(wrap, hdr, (data && data.error) || 'Could not generate. Try again.', doGenerateExam);
        return;
      }
      examLoaded = true;
      renderExam(data.data.questions || []);
    } catch(e) {
      panelError(wrap, hdr, 'Could not connect. Make sure Flask is running.', doGenerateExam);
    }
  }

  async function loadExam() {
    if (examLoaded) return;
    const wrap = document.getElementById('examWrap');
    const hdr  = wrap.querySelector('.panel-header');
    try {
      const st = await fetch('/status'); const sd = await st.json();
      if (sd.chunks && sd.chunks > 0) {
        panelReady(wrap, hdr, '', 'Ready to build your exam!',
          'Scans your entire document and generates every important question you could face in an exam — definitions, comparisons, applications and more, sorted by difficulty.',
          'Generate Exam Questions', doGenerateExam);
      } else {
        panelNoDoc(wrap, hdr);
      }
    } catch(e) { panelNoDoc(wrap, hdr); }
  }

  // tab switching — loads data when tab opens
  function setTab(el, name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    el.classList.add('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById(name+'Panel').classList.add('active');
    if (name === 'summary')   loadSummary();
    if (name === 'quiz')      loadQuiz();
    if (name === 'flashcard') loadFlashcards();
    if (name === 'exam')      loadExam();
  }

  function switchMode(el, name) {
    document.querySelectorAll('.mode-item').forEach(m => m.classList.remove('active'));
    el.classList.add('active');
    const map  = { chat:0, summary:1, quiz:2, flashcard:3, exam:4 };
    const tabs = document.querySelectorAll('.tab');
    setTab(tabs[map[name]], name);
  }

  function sendQ(q) { document.getElementById('chatInput').value=q; sendMessage(); }

  // sends a question with a specific tag forced ON
  function sendQWithTag(q, tag) {
    // turn on the matching tag if it exists
    document.querySelectorAll('.itag').forEach(t => {
      if (t.textContent.trim() === tag) t.classList.add('on');
    });
    document.getElementById('chatInput').value = q;
    sendMessage();
  }

  // ui helpers
  function autoResize(el)  { el.style.height='auto'; el.style.height=Math.min(el.scrollHeight,120)+'px'; }
  function handleKey(e)    { if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMessage();} }
  function toggleTag(el)   { el.classList.toggle('on'); }
  function selectDoc(el)   { document.querySelectorAll('.doc-item').forEach(d=>d.classList.remove('active')); el.classList.add('active'); }
  function clearChat()     { document.getElementById('chatArea').innerHTML=''; started=false; }
  function togglePrompts() { document.getElementById('promptSuggestions').classList.toggle('open'); document.getElementById('promptToggle').classList.toggle('open'); }

  // chat message rendering
  function addMsg(role, text) {
    const area = document.getElementById('chatArea');
    const el   = document.createElement('div');
    el.className = `msg-row ${role}`;
    el.innerHTML = `${role==='ai'?aiAva():'<div class="msg-ava user">U</div>'}<div class="msg-body"><div class="bubble">${text}</div></div>`;
    area.appendChild(el); area.scrollTop = area.scrollHeight;
  }

  function addAIMsg(r) {
    const area  = document.getElementById('chatArea');
    const el    = document.createElement('div');
    el.className = 'msg-row ai';
    const pills    = (r.sources||[]).map(s=>`<div class="src-pill"> ${s}</div>`).join('');
    const srcBlock = r.sources&&r.sources.length>0 ? `<div class="src-block"><div class="src-lbl">Sources used</div><div class="src-pills">${pills}</div></div>` : '';
    const confRow  = r.conf>0 ? `<div class="conf-row"><span>Confidence</span><div class="conf-track"><div class="conf-fill" style="width:${r.conf}%"></div></div><span>${r.conf}%</span></div>` : '';
    el.innerHTML = `${aiAva()}<div class="msg-body"><div class="bubble">${r.text}</div>${srcBlock}${confRow}</div>`;
    area.appendChild(el); area.scrollTop = area.scrollHeight;
  }

  function aiAva() {
    return `<div class="msg-ava ai"><svg viewBox="0 0 30 30" width="30" height="30"><defs><radialGradient id="ag" cx="32%" cy="28%" r="65%"><stop offset="0%" stop-color="#fff" stop-opacity="1"/><stop offset="100%" stop-color="#3b5bdb" stop-opacity=".2"/></radialGradient><clipPath id="ac"><circle cx="15" cy="15" r="11"/></clipPath></defs><circle cx="15" cy="15" r="15" fill="#0d1530"/><circle cx="15" cy="15" r="11" fill="url(#ag)" opacity=".87"/><g clip-path="url(#ac)" stroke="white" stroke-width=".4" opacity=".35"><line x1="9" y1="9" x2="15" y2="13"/><line x1="15" y1="13" x2="21" y2="8"/><line x1="15" y1="13" x2="19" y2="18"/><line x1="9" y1="9" x2="11" y2="17"/><line x1="11" y1="17" x2="19" y2="18"/></g><g clip-path="url(#ac)" fill="white"><circle cx="15" cy="13" r="1.8"/><circle cx="9" cy="9" r="1.2"/><circle cx="21" cy="8" r="1.1"/><circle cx="11" cy="17" r="1.2"/><circle cx="19" cy="18" r="1.3"/></g></svg></div>`;
  }

  // thinking animation
  let thinkEl = null;
  function showThinking() {
    const area = document.getElementById('chatArea');
    const wrap = document.createElement('div');
    wrap.className='msg-row ai'; wrap.id='thinkWrap';
    wrap.innerHTML=`${aiAva()}<div class="thinking-bubble"><div class="tdots"><span></span><span></span><span></span></div><span id="thinkTxt">Embedding your query...</span></div>`;
    area.appendChild(wrap); area.scrollTop=area.scrollHeight; thinkEl=wrap;
    const steps=['Embedding your query...','Searching vector database...','Retrieving top-4 chunks...','Reranking by relevance...','Reading document context...','Generating answer...','Almost done...'];
    let i=0;
    window._ti=setInterval(()=>{ i++; const el=document.getElementById('thinkTxt'); if(el&&i<steps.length)el.textContent=steps[i]; },500);
  }
  function hideThinking(){ clearInterval(window._ti); if(thinkEl){thinkEl.remove();thinkEl=null;} }

  // pipeline animation
  function showPipeline(){
    const pw=document.getElementById('pipelineWrap'); pw.style.display='flex';
    ['ps1','ps2','ps3','ps4'].forEach(id=>document.getElementById(id).className='ps');
    const fill=document.getElementById('pipelineBarFill'),pct=document.getElementById('pipelineBarPct'),est=document.getElementById('pipelineBarEst'),status=document.getElementById('pipelineStatus');
    const steps=[{id:'ps1',label:'Embedding query...',pct:15,est:'~25 sec remaining'},{id:'ps2',label:'Retrieving chunks...',pct:40,est:'~18 sec remaining'},{id:'ps3',label:'Reranking results...',pct:65,est:'~10 sec remaining'},{id:'ps4',label:'Generating answer...',pct:85,est:'~5 sec remaining'}];
    fill.style.width='0%'; pct.textContent='0%'; est.textContent='est. ~30 sec';
    let i=0;
    window._pi=setInterval(()=>{
      if(i>0) document.getElementById(steps[i-1].id).className='ps done';
      if(i<steps.length){ const s=steps[i]; document.getElementById(s.id).className='ps active'; status.textContent=s.label; fill.style.width=s.pct+'%'; pct.textContent=s.pct+'%'; est.textContent=s.est; i++; }
      else { clearInterval(window._pi); fill.style.width='95%'; pct.textContent='95%'; est.textContent='finalizing...'; status.textContent='Almost done...'; }
    },700);
  }
  function hidePipeline(){
    clearInterval(window._pi);
    const fill=document.getElementById('pipelineBarFill'),pct=document.getElementById('pipelineBarPct'),status=document.getElementById('pipelineStatus');
    if(fill){fill.style.width='100%'; pct.textContent='100%';}
    if(status) status.textContent='Done!';
    setTimeout(()=>{ document.getElementById('pipelineWrap').style.display='none'; },600);
  }

  // flashcard controls
  function updateCard(dir = 'next'){
    if(cards.length===0) return;
    const fc = document.getElementById('flashcard');
    // Reset to question side styling
    fc.style.background = '';
    fc.classList.remove('is-answer');
    // Slide out current card
    const slideOut = dir === 'next' ? 'translateX(-40px)' : 'translateX(40px)';
    fc.style.transition = 'opacity .18s ease, transform .18s ease';
    fc.style.opacity = '0';
    fc.style.transform = slideOut;
    setTimeout(() => {
      document.getElementById('fcLabel').textContent   = 'Question';
      document.getElementById('fcContent').textContent = cards[cardIdx].question;
      document.getElementById('fcCount').textContent   = `${cardIdx+1} / ${cards.length}`;
      const hint = document.querySelector('.fc-hint');
      if (hint) hint.textContent = '👆 Click to reveal answer';
      flipped = false;
      // Slide in from opposite direction
      const slideFrom = dir === 'next' ? 'translateX(40px)' : 'translateX(-40px)';
      fc.style.transform = slideFrom;
      fc.style.transition = 'none';
      void fc.offsetWidth;
      fc.style.transition = 'opacity .22s cubic-bezier(.34,1.2,.64,1), transform .28s cubic-bezier(.34,1.2,.64,1)';
      fc.style.opacity = '1';
      fc.style.transform = 'translateX(0)';
    }, 180);
  }
  function jumpCard(idx){ cardIdx=idx; flipped=false; updateCard('next'); }
  function nextCard(){ cardIdx=(cardIdx+1)%cards.length; flipped=false; updateCard('next'); }
  function prevCard(){ cardIdx=(cardIdx-1+cards.length)%cards.length; flipped=false; updateCard('prev'); }

  // dark mode — unchanged from prototype
  function toggleDark() {
    const body=document.body; body.classList.toggle('dark');
    const isDark=body.classList.contains('dark');
    localStorage.setItem('localrag-dark',isDark);
    const icon=document.getElementById('darkIcon'),label=document.getElementById('darkLabel');
    if(isDark){ icon.innerHTML='<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>'; if(label)label.textContent='Light mode'; }
    else { icon.innerHTML='<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>'; if(label)label.textContent='Dark mode'; }
  }
  if(localStorage.getItem('localrag-dark')==='true'){
    document.body.classList.add('dark');
    setTimeout(()=>{
      const icon=document.getElementById('darkIcon'),label=document.getElementById('darkLabel');
      if(icon) icon.innerHTML='<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>';
      if(label) label.textContent='Light mode';
    },100);
  }

  // dropdown menu — unchanged
  function toggleMenu(){ document.getElementById('dropdown').classList.toggle('open'); }
  document.addEventListener('click',function(e){ const wrap=document.getElementById('menuWrap'); if(wrap&&!wrap.contains(e.target)) document.getElementById('dropdown').classList.remove('open'); });

  // modals — unchanged
  const modalContent={
    help:{title:'Help — How to use LocalRAG',body:'<h4>Step 1 — Upload a document</h4>Click the upload zone or drag and drop a PDF, DOCX or TXT file.<h4>Step 2 — Wait for indexing</h4>LocalRAG chunks and embeds your document. Takes 1-2 min first time.<h4>Step 3 — Ask questions</h4>Type any question and press Enter.<h4>Style tags</h4><span class=\'modal-tag\'>Teacher</span> <span class=\'modal-tag\'>Chat</span> <span class=\'modal-tag\'>Technical</span><br><br>Toggle these to change how AI answers.<h4>Delete Index</h4>Click the dustbin next to Clear in History to delete chroma_db.'},
    about:{title:'About LocalRAG',body:'<h4>What is LocalRAG?</h4>A 100% offline AI document assistant. No internet, no cloud, no data sharing.<h4>Tech Stack</h4><span class=\'modal-tag\'>Python</span> <span class=\'modal-tag\'>Flask</span> <span class=\'modal-tag\'>Ollama</span> <span class=\'modal-tag\'>qwen2.5:3b</span> <span class=\'modal-tag\'>nomic-embed-text</span> <span class=\'modal-tag\'>ChromaDB</span><h4>Version</h4>LocalRAG v1.0.0 — College Project 2025<h4>Developer</h4>Built with purpose by a student passionate about AI and privacy.'},
    privacy:{title:'Privacy Policy',body:'<h4>Your data stays on your device</h4>LocalRAG runs 100% locally. Nothing ever leaves your laptop.<h4>No internet required</h4>Works completely offline after installation.<h4>No tracking</h4>No usage data or personal information collected.<h4>No accounts</h4>No sign-up, no login, no email required. Ever.'}
  };
  function showModal(type){ document.getElementById('dropdown').classList.remove('open'); const m=modalContent[type]; document.getElementById('modalTitle').textContent=m.title; document.getElementById('modalBody').innerHTML=m.body; document.getElementById('modalOverlay').classList.add('open'); }
  function closeModal(){ document.getElementById('modalOverlay').classList.remove('open'); }

  // ── SPLASH SCREEN — cinematic space intro ──────────────────────────────
  (function(){
    const splash = document.getElementById('splash');

    // 1. Twinkling star field — more stars, some bigger for depth
    const starsEl = document.getElementById('splashStars');
    for(let i = 0; i < 140; i++){
      const s = document.createElement('div'); s.className = 'star';
      const size = Math.random() < 0.08 ? Math.random()*2+1.5 : Math.random()*1.2+0.3;
      s.style.cssText = `width:${size}px;height:${size}px;top:${Math.random()*100}%;left:${Math.random()*100}%;animation-delay:${Math.random()*5}s;animation-duration:${2+Math.random()*5}s;opacity:${Math.random()*.3}`;
      starsEl.appendChild(s);
    }

    // 2. Shooting stars — fire 4 at staggered times during intro
    function shootStar(delay) {
      setTimeout(() => {
        const el = document.createElement('div'); el.className = 'shoot';
        const angle = -25 + Math.random() * 20; // roughly diagonal
        const dist  = 400 + Math.random() * 300;
        const startX = Math.random() * window.innerWidth;
        const startY = Math.random() * (window.innerHeight * 0.5);
        el.style.cssText = `
          left:${startX}px; top:${startY}px;
          --angle:${angle}deg;
          --dx:${Math.cos(angle*Math.PI/180)*dist}px;
          --dy:${Math.sin(angle*Math.PI/180)*dist + dist*0.4}px;
          animation-duration:${0.7 + Math.random()*0.4}s;
          animation-delay:0s;
        `;
        splash.appendChild(el);
        setTimeout(() => el.remove(), 1500);
      }, delay);
    }
    shootStar(400);
    shootStar(900);
    shootStar(1800);
    shootStar(2600);

    // 3. Tagline typewriter
    const text = 'Ask questions to your own documents...';
    const el = document.getElementById('splashTyped'); let i = 0;
    setTimeout(() => {
      const iv = setInterval(() => {
        if(i < text.length){ el.textContent += text[i]; i++; }
        else clearInterval(iv);
      }, 40);
    }, 1200);

    // 4. Progress bar
    const fill  = document.getElementById('splashFill');
    const label = document.getElementById('splashLabel');
    const steps = [
      {pct:8,  text:'Initializing...'},
      {pct:22, text:'Loading models...'},
      {pct:40, text:'Starting Ollama...'},
      {pct:58, text:'Loading qwen2.5:3b...'},
      {pct:74, text:'Loading embeddings...'},
      {pct:88, text:'Preparing interface...'},
      {pct:96, text:'Almost ready...'},
      {pct:100,text:'Ready!'}
    ];
    let si = 0;
    setTimeout(() => {
      const iv = setInterval(() => {
        if(si < steps.length){
          fill.style.width  = steps[si].pct + '%';
          label.textContent = steps[si].text;
          si++;
        } else {
          clearInterval(iv);
          // 5. Exit: logo zooms forward, text fades, splash dissolves
          setTimeout(() => {
            document.getElementById('splash').classList.add('hide');
            document.getElementById('mainApp').style.opacity = '1';
            setTimeout(() => { document.getElementById('splash').style.display = 'none'; }, 1050);
          }, 500);
        }
      }, 380);
    }, 1400);
  })();

  // ── STAR CANVAS — animated twinkling stars in background ──────────────
  (function initStars() {
    const canvas = document.getElementById('starCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let stars = [], W, H, raf;

    function resize() {
      const parent = canvas.parentElement;
      W = canvas.width  = parent.offsetWidth;
      H = canvas.height = parent.offsetHeight;
    }

    function makeStars(n) {
      stars = [];
      for (let i = 0; i < n; i++) {
        stars.push({
          x:     Math.random() * W,
          y:     Math.random() * H,
          r:     Math.random() * 1.4 + 0.3,
          alpha: Math.random(),
          speed: Math.random() * 0.004 + 0.001,
          phase: Math.random() * Math.PI * 2,
        });
      }
    }

    function draw(t) {
      ctx.clearRect(0, 0, W, H);
      const dark = document.body.classList.contains('dark');
      stars.forEach(s => {
        const a = 0.12 + 0.45 * (0.5 + 0.5 * Math.sin(t * s.speed * 1000 + s.phase));
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx.fillStyle = dark
          ? `rgba(160,180,255,${a})`
          : `rgba(59,91,219,${a * 0.55})`;
        ctx.fill();
      });
      raf = requestAnimationFrame(draw);
    }

    function start() {
      resize();
      makeStars(80);
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(draw);
    }

    window.addEventListener('resize', () => { resize(); makeStars(80); });
    // Start after splash finishes
    setTimeout(start, 2600);
    // Also restart when dark mode toggles
    const origToggle = window.toggleDark;
    window.toggleDark = function() { if(origToggle) origToggle(); setTimeout(() => cancelAnimationFrame(raf) || (raf = requestAnimationFrame(draw)), 50); };
  })();

  // ── TYPEWRITER — welcome heading ──────────────────────────────────────
  (function initTypewriter() {
    const line1El  = document.getElementById('twLine1');
    const line2El  = document.getElementById('twLine2');
    if (!line1El || !line2El) return;

    const phrases = [
      { l1: 'Ask anything about your documents', l2: 'I explain it simply!' },
      { l1: 'Upload a PDF, DOCX or TXT',         l2: 'And start learning instantly.' },
      { l1: 'Generate quizzes, flashcards',       l2: 'All from your own documents.' },
      { l1: '100% local. 100% private.',          l2: 'Nothing leaves your computer.' },
    ];

    let pi = 0; // phrase index

    const cursor = document.createElement('span');
    cursor.className = 'tw-cursor';

    function type(el, text, speed, done) {
      let i = 0;
      el.textContent = '';
      el.appendChild(cursor);
      const iv = setInterval(() => {
        el.textContent = text.slice(0, ++i);
        el.appendChild(cursor);
        if (i >= text.length) { clearInterval(iv); setTimeout(done, 60); }
      }, speed);
    }

    function erase(el, speed, done) {
      let txt = el.textContent;
      const iv = setInterval(() => {
        txt = txt.slice(0, -1);
        el.textContent = txt;
        if (txt.length === 0) { clearInterval(iv); done(); }
      }, speed / 2); // erase faster than type
    }

    function runCycle() {
      const { l1, l2 } = phrases[pi];
      // Type line 1
      type(line1El, l1, 42, () => {
        // Move cursor to line 2, type it
        line2El.appendChild(cursor);
        type(line2El, l2, 48, () => {
          // Pause, then erase both lines
          setTimeout(() => {
            erase(line2El, 28, () => {
              erase(line1El, 22, () => {
                pi = (pi + 1) % phrases.length;
                setTimeout(runCycle, 300);
              });
            });
          }, 2200);
        });
      });
    }

    // Start after splash (~2.6s) + small delay
    setTimeout(runCycle, 2800);
  })();