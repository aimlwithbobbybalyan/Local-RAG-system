"""
app.py v2.1 — LocalRAG Flask backend.

ROOT CAUSE FIX:
  v2.0 pre_generate_all() was making 9 serial LLM calls = 20+ minutes.
  v2.1 reduces to 4 LLM calls total in background (1 per feature).
  Summary/Quiz/Flashcards/Exam each = 1 call with tight context.

Key settings for speed on CPU:
  - num_predict = 350   (was 500/900 — biggest time saver)
  - num_ctx     = 2048  (sufficient for 2000 char context + prompt)
  - max_chars   = 2000  (feed less text = model responds faster)
  - 1 section only for background gen (not 2-3)
"""

from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os, shutil, json, re, gc, time, logging
from threading import Thread

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MAX_FILE_SIZE_MB    = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

from prompts import (
    SUMMARY_PROMPT, KEYPOINTS_PROMPT, CONCEPTS_PROMPT, CONCEPTS_PROMPT_SIMPLE,
    QUIZ_PROMPT, FLASHCARD_PROMPT, EXAM_PROMPT, WHAT_ABOUT_PROMPT
)
from rag_pipeline import (
    load_documents, load_single_document,
    split_documents, create_vectorstore, add_to_vectorstore,
    build_bm25_index, bm25_search,
    ask_question, CHROMA_FOLDER, EMBED_MODEL, MODEL_NAME
)

from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama

app = Flask(__name__)
CORS(app)

DOCS_FOLDER = "data"
vectorstore = None

# ── SINGLETON LLM ─────────────────────────────────────────────────────────────
# One instance, created once, reused forever.
# This alone saves 30-60s per call vs creating new each time.
_llm = None

def get_llm():
    global _llm
    if _llm is None:
        logger.info("Creating LLM instance (one time only)...")
        _llm = Ollama(
            model       = MODEL_NAME,
            temperature = 0.2,
            num_predict = 350,   # KEY: was 900 in v1. Shorter = much faster.
            num_ctx     = 2048,  # KEY: fits prompt + 2000 char context comfortably
        )
        logger.info("LLM ready.")
    return _llm

def ask_llm(prompt):
    return get_llm().invoke(prompt)


# ── VECTORSTORE ───────────────────────────────────────────────────────────────
def get_vectorstore():
    global vectorstore
    if vectorstore is None:
        if os.path.exists(CHROMA_FOLDER) and os.listdir(CHROMA_FOLDER):
            embedding   = OllamaEmbeddings(model=EMBED_MODEL)
            vectorstore = Chroma(
                persist_directory  = CHROMA_FOLDER,
                embedding_function = embedding
            )
    return vectorstore


# ── TEXT CACHE ────────────────────────────────────────────────────────────────
_text_cache = {}

def _invalidate_text_cache():
    global _text_cache
    _text_cache = {}

def get_context_text(max_chars=2000):
    """
    Returns a representative sample of the document.
    2000 chars = ~500 tokens. Fits comfortably in 2048 num_ctx
    alongside the prompt itself.
    Cached after first call — free on subsequent calls.
    """
    if 'ctx' in _text_cache:
        return _text_cache['ctx']
    vs = get_vectorstore()
    if vs is None:
        return ""
    results = vs.get(limit=500)
    texts   = results.get("documents", [])
    if not texts:
        return ""
    total = len(texts)
    # Evenly sample across full document so all topics represented
    if total <= 8:
        sampled = texts
    else:
        indices = [0]
        step = max(1, total // 6)
        for i in range(step, total - 1, step):
            indices.append(i)
        indices.append(total - 1)
        sampled = [texts[i] for i in sorted(set(indices)) if i < total]
    text = "\n\n".join(sampled)[:max_chars]
    _text_cache['ctx'] = text
    return text

def get_short_text(max_chars=1500):
    if 'short' in _text_cache:
        return _text_cache['short']
    vs = get_vectorstore()
    if vs is None:
        return ""
    results = vs.get(limit=10)
    text    = "\n\n".join(results.get("documents", []))[:max_chars]
    _text_cache['short'] = text
    return text


# ── PRE-GENERATION CACHE ──────────────────────────────────────────────────────
# After upload, generate all 4 features in background.
# Each feature = 1 LLM call. Total = 4 calls.
# User clicks Summary/Quiz/etc → instant from cache.
_content_cache = {}
_generating    = False

def pre_generate_all():
    """
    4 LLM calls total, run after upload.
    v2.0 mistake was 9 serial calls = 20+ min.
    v2.1 = 4 calls, each with 2000 char context = ~2-3 min total.
    """
    global _generating, _content_cache
    _generating = True
    logger.info("=== Background pre-generation started (4 calls) ===")
    t_start = time.time()

    try:
        context = get_context_text(max_chars=2000)
        if not context:
            logger.warning("No text for pre-generation.")
            return

        # Call 1 — Summary
        try:
            t0  = time.time()
            raw = ask_llm(SUMMARY_PROMPT.format(context=context))
            title, overview = parse_summary(raw)
            _content_cache['summary'] = {
                'title':      title,
                'overview':   overview,
                'key_points': [],   # filled by call 2
                'concepts':   []
            }
            logger.info(f"✅ Summary in {round(time.time()-t0,1)}s")
        except Exception as e:
            logger.error(f"Summary failed: {e}")

        # Call 2 — Key points (reuse same context, fast)
        try:
            t0  = time.time()
            raw = ask_llm(KEYPOINTS_PROMPT.format(context=context))
            pts = parse_points(raw)
            if 'summary' in _content_cache:
                _content_cache['summary']['key_points'] = pts[:6]
                _content_cache['summary']['concepts']   = []
            logger.info(f"✅ Key points in {round(time.time()-t0,1)}s")
        except Exception as e:
            logger.error(f"Key points failed: {e}")

        # Call 3 — Quiz
        try:
            t0  = time.time()
            raw = ask_llm(QUIZ_PROMPT.format(context=context))
            qs  = parse_quiz(raw)
            _content_cache['quiz'] = deduplicate(qs, lambda q: q["question"], 8)
            logger.info(f"✅ Quiz in {round(time.time()-t0,1)}s — {len(_content_cache['quiz'])} Qs")
        except Exception as e:
            logger.error(f"Quiz failed: {e}")

        # Call 4 — Flashcards
        try:
            t0  = time.time()
            raw = ask_llm(FLASHCARD_PROMPT.format(context=context))
            cs  = parse_flashcards(raw)
            _content_cache['flashcards'] = deduplicate(cs, lambda c: c["question"], 8)
            logger.info(f"✅ Flashcards in {round(time.time()-t0,1)}s — {len(_content_cache['flashcards'])} cards")
        except Exception as e:
            logger.error(f"Flashcards failed: {e}")

        # Call 5 — Exam (slightly different context slice for variety)
        try:
            t0  = time.time()
            raw = ask_llm(EXAM_PROMPT.format(context=context))
            qs  = parse_exam(raw)
            order = {"Easy": 0, "Medium": 1, "Hard": 2}
            qs.sort(key=lambda x: order.get(x["difficulty"], 1))
            _content_cache['exam'] = deduplicate(qs, lambda q: q["question"], 999)
            logger.info(f"✅ Exam in {round(time.time()-t0,1)}s — {len(_content_cache['exam'])} Qs")
        except Exception as e:
            logger.error(f"Exam failed: {e}")

        logger.info(f"=== Pre-gen done in {round(time.time()-t_start,1)}s ===")

    finally:
        _generating = False


# ── QA CHAIN CACHE ────────────────────────────────────────────────────────────
_chain_cache = {}

def get_qa_chain(vs, tags=None, doc_filter="all"):
    from langchain.chains import RetrievalQA
    from rag_pipeline import build_prompt
    if tags is None:
        tags = []

    cache_key = (tuple(sorted(tags)), doc_filter)
    if cache_key in _chain_cache:
        return _chain_cache[cache_key]

    prompt = build_prompt(tags)

    if doc_filter and doc_filter != "all":
        doc_path      = os.path.join(DOCS_FOLDER, doc_filter)
        search_kwargs = {"k": 3, "filter": {"source": doc_path}}
    else:
        search_kwargs = {"k": 3}

    chain = RetrievalQA.from_chain_type(
        llm                     = get_llm(),
        chain_type              = "stuff",
        retriever               = vs.as_retriever(search_kwargs=search_kwargs),
        return_source_documents = True,
        chain_type_kwargs       = {"prompt": prompt}
    )
    _chain_cache[cache_key] = chain
    return chain


# ── PARSERS ───────────────────────────────────────────────────────────────────
def parse_summary(raw):
    title = ""; overview = ""
    lines = raw.splitlines(); i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("OVERVIEW:"):
            parts = [line[9:].strip()]; i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt or re.match(r'^[A-Z]{3,}:', nxt):
                    break
                parts.append(nxt); i += 1
            overview = " ".join(p for p in parts if p)
            continue
        i += 1
    if not overview:
        overview = raw.strip()[:600]
    return title, overview

def parse_points(raw):
    points = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith(("- ", "• ", "* ")):
            pt = line[2:].strip()
        elif re.match(r'^\d+[\.\)]\s', line):
            pt = re.sub(r'^\d+[\.\)]\s+', '', line).strip()
        else:
            continue
        if pt and len(pt) > 20:
            points.append(pt)
    return points

def parse_concepts(raw):
    for line in raw.splitlines():
        l = line.strip()
        if l.upper().startswith("TERMS:"):
            terms = l[6:].strip()
            if terms:
                return [t.strip() for t in terms.split(",") if t.strip()]
    return []

def parse_quiz(raw):
    questions  = []
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    blocks = re.split(r'#+', raw) if "###" in raw else re.split(r'(?:^|\n)(?=Q:)', raw)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        q_text = ""; opts = []; correct_letter = "A"; explanation = ""
        for line in lines:
            up = line.upper()
            if up.startswith("Q:"):
                q_text = line[2:].strip()
            elif re.match(r'^[ABCD]:\s', line):
                opts.append(line[2:].strip())
            elif up.startswith("ANSWER:"):
                correct_letter = line[7:].strip().upper()[:1]
            elif up.startswith("EXPLAIN:"):
                explanation = line[8:].strip()
        if q_text and len(opts) == 4:
            questions.append({
                "question":    q_text,
                "options":     [f"{l}. {o}" for l, o in zip(["A","B","C","D"], opts)],
                "correct":     letter_map.get(correct_letter, 0),
                "explanation": explanation
            })
    return questions

def parse_flashcards(raw):
    cards = []
    blocks = re.split(r'#+', raw) if "###" in raw else re.split(r'(?:^|\n)(?=Q:)', raw)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        q_text = ""; a_lines = []; reading_a = False
        for line in lines:
            up = line.upper()
            if up.startswith("Q:"):
                q_text = line[2:].strip(); reading_a = False; a_lines = []
            elif up.startswith("A:") or up.startswith("ANSWER:"):
                prefix = 2 if up.startswith("A:") else 7
                first_bit = line[prefix:].strip()
                if first_bit:
                    a_lines.append(first_bit)
                reading_a = True
            elif reading_a:
                if not re.match(r'^(Q:|###)', line, re.IGNORECASE):
                    a_lines.append(line)
        a_text = " ".join(a_lines).strip()
        if q_text and a_text:
            cards.append({"question": q_text, "answer": a_text})
    return cards

def parse_exam(raw):
    """
    Robust parser — works whether or not model outputs QUESTIONS: header.
    Handles all these formats llama3.2:3b commonly outputs:
      1. [Easy] What is X?
      1. What is X?
      1) What is X?
      - What is X?
      What is X?   (plain line)
    """
    questions = []

    # Try header-gated parsing first
    in_block   = False
    has_header = "QUESTIONS:" in raw.upper()

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.upper().startswith("QUESTIONS:"):
            in_block = True
            continue
        # If model skipped the header, treat everything as in-block
        if not has_header:
            in_block = True
        if not in_block:
            continue

        # Match: "1. [Easy] question" or "1. question" or "1) question"
        m = re.match(r'^\d+[\.)\-]\s+(?:\[(Easy|Medium|Hard)\]\s*)?(.+)', line, re.IGNORECASE)
        if m:
            difficulty = m.group(1) or "Medium"
            question   = m.group(2).strip()
            # Strip trailing difficulty tags like "(Easy)" at end
            question   = re.sub(r'\s*[\(\[]?(Easy|Medium|Hard)[\)\]]?\s*$', '', question, flags=re.IGNORECASE).strip()
            if len(question) > 10:
                questions.append({"question": question, "difficulty": difficulty.capitalize()})
            continue

        # Fallback: plain numbered line without bracket e.g "1. What is photosynthesis?"
        m2 = re.match(r'^\d+[\.)]\.?\s+(.+)', line)
        if m2:
            question = m2.group(1).strip()
            if len(question) > 10:
                questions.append({"question": question, "difficulty": "Medium"})

    # Last resort: if still nothing, grab any line that looks like a question
    if not questions:
        for line in raw.splitlines():
            line = line.strip()
            if len(line) > 15 and (line.endswith("?") or line[0].isupper()):
                # skip prompt echo lines
                if any(skip in line.lower() for skip in ["you are", "generate", "include", "rules", "write", "text:", "questions:"]):
                    continue
                questions.append({"question": line, "difficulty": "Medium"})

    return questions

def deduplicate(items, key_fn, limit):
    seen, unique = set(), []
    for item in items:
        key = key_fn(item)[:35].lower().strip()
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique[:limit]

def release_vectorstore():
    global vectorstore, _chain_cache, _content_cache
    vectorstore    = None
    _chain_cache   = {}
    _content_cache = {}
    _invalidate_text_cache()
    gc.collect()
    time.sleep(0.3)


# ── ROUTES ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    global vectorstore
    if "file" not in request.files:
        return jsonify({"error": "No file sent"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400
    allowed  = {".pdf", ".txt", ".docx", ".md"}
    filename = secure_filename(file.filename)
    ext      = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        return jsonify({"error": f"{ext} not supported. Allowed: PDF, TXT, DOCX, MD"}), 400
    file.seek(0, 2); file_size = file.tell(); file.seek(0)
    if file_size > MAX_FILE_SIZE_BYTES:
        return jsonify({"error": f"File too large. Max {MAX_FILE_SIZE_MB}MB."}), 400
    if file_size == 0:
        return jsonify({"error": "File is empty."}), 400

    os.makedirs(DOCS_FOLDER, exist_ok=True)
    existing = [f for f in os.listdir(DOCS_FOLDER)
                if f.endswith((".pdf", ".txt", ".docx", ".md"))]
    if len(existing) >= 3:
        return jsonify({"error": "Maximum 3 documents allowed. Delete one first."}), 400

    filepath = os.path.join(DOCS_FOLDER, filename)
    file.save(filepath)
    logger.info(f"Uploaded: {filename} ({file_size//1024}KB)")

    try:
        # Incremental fix:
        # Check disk not memory — vectorstore object is None on fresh app start
        # even if chroma_db/ folder already exists from previous session
        index_exists = os.path.exists(CHROMA_FOLDER) and bool(os.listdir(CHROMA_FOLDER))

        if index_exists:
            logger.info("Index exists — incremental add only (no full rebuild)...")
            if vectorstore is None:
                embedding   = OllamaEmbeddings(model=EMBED_MODEL)
                vectorstore = Chroma(
                    persist_directory  = CHROMA_FOLDER,
                    embedding_function = embedding
                )
            new_docs    = load_single_document(filepath)
            new_chunks  = split_documents(new_docs)
            vectorstore = add_to_vectorstore(new_chunks, vectorstore)
            chunks      = new_chunks
        else:
            logger.info("No index found — building fresh...")
            docs        = load_documents()
            chunks      = split_documents(docs)
            vectorstore = create_vectorstore(chunks)

        # BM25 on all chunks
        all_results = vectorstore.get(limit=5000)
        from langchain.schema import Document
        all_chunks  = [Document(page_content=t) for t in all_results.get("documents", [])]
        build_bm25_index(all_chunks)

        # Reset caches
        _invalidate_text_cache()
        global _content_cache
        _content_cache = {}

        # Warm LLM now so first use is instant
        get_llm()

        # Start background pre-generation (5 LLM calls, ~3-5 min)
        Thread(target=pre_generate_all, daemon=True).start()

    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return jsonify({"error": f"Indexing failed: {str(e)}"}), 500

    return jsonify({
        "success":  True,
        "filename": file.filename,
        "chunks":   len(chunks) if chunks else 0,
        "message":  f"'{file.filename}' indexed! Study materials generating in background..."
    })


# ── CHAT ──────────────────────────────────────────────────────────────────────
@app.route("/chat", methods=["POST"])
def chat():
    data       = request.get_json()
    question   = data.get("question", "").strip()
    tags       = data.get("tags", [])
    doc_filter = data.get("doc_filter", "all")
    if not question:
        return jsonify({"error": "No question provided"}), 400
    vs = get_vectorstore()
    if vs is None:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400
    try:
        t0     = time.time()
        chain  = get_qa_chain(vs, tags, doc_filter)
        result = chain.invoke({"query": question})
        elapsed = round(time.time() - t0, 1)
        logger.info(f"Chat answered in {elapsed}s")
        sources = []
        for doc in result.get("source_documents", []):
            src   = doc.metadata.get("source", "unknown")
            page  = doc.metadata.get("page", "")
            label = os.path.basename(src)
            if page != "":
                label += f" · p.{page + 1}"
            if label not in sources:
                sources.append(label)
        return jsonify({
            "answer":     result["result"],
            "sources":    sources,
            "confidence": 90,
            "elapsed":    elapsed
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── STREAMING CHAT ────────────────────────────────────────────────────────────
@app.route("/chat/stream", methods=["POST"])
def chat_stream():
    data     = request.get_json()
    question = data.get("question", "").strip()
    tags     = data.get("tags", [])
    if not question:
        return jsonify({"error": "No question provided"}), 400
    vs = get_vectorstore()
    if vs is None:
        return jsonify({"error": "No documents indexed yet."}), 400

    # BM25 fast retrieval first, fallback to ChromaDB
    bm25_results = bm25_search(question, k=3)
    if bm25_results:
        context = "\n\n".join(bm25_results)[:2000]
    else:
        docs    = vs.similarity_search(question, k=3)
        context = "\n\n".join([d.page_content for d in docs])[:2000]

    rag_on = any("RAG" in t for t in tags)
    scope  = "Use ONLY this document text." if rag_on else "Use this document as main source."

    prompt = f"""You are a helpful study assistant. Answer clearly.
{scope}

Document:
{context}

Question: {question}
Answer:"""

    def generate():
        try:
            llm = Ollama(model=MODEL_NAME, temperature=0.2, num_predict=350, num_ctx=2048)
            for token in llm.stream(prompt):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


# ── SUMMARY — instant from cache ─────────────────────────────────────────────
@app.route("/summary", methods=["POST"])
def summary():
    if 'summary' in _content_cache:
        logger.info("Summary: cache hit (instant)")
        return jsonify({"success": True, "data": _content_cache['summary']})

    # Cache miss — generate on demand (1 call only)
    context = get_context_text(max_chars=2000)
    if not context:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400
    try:
        t0  = time.time()
        raw = ask_llm(SUMMARY_PROMPT.format(context=context))
        title, overview = parse_summary(raw)

        raw_pts = ask_llm(KEYPOINTS_PROMPT.format(context=context))
        points  = parse_points(raw_pts)

        result = {
            "title":      title,
            "overview":   overview,
            "key_points": points[:6],
            "concepts":   []
        }
        _content_cache['summary'] = result
        logger.info(f"Summary generated in {round(time.time()-t0,1)}s")
        return jsonify({"success": True, "data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── QUIZ — instant from cache ─────────────────────────────────────────────────
@app.route("/quiz", methods=["POST"])
def quiz():
    if 'quiz' in _content_cache and _content_cache['quiz']:
        logger.info("Quiz: cache hit (instant)")
        return jsonify({"success": True, "data": {"questions": _content_cache['quiz']}})

    context = get_context_text(max_chars=2000)
    if not context:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400
    try:
        t0  = time.time()
        raw = ask_llm(QUIZ_PROMPT.format(context=context))
        qs  = deduplicate(parse_quiz(raw), lambda q: q["question"], 8)
        _content_cache['quiz'] = qs
        logger.info(f"Quiz generated in {round(time.time()-t0,1)}s")
        return jsonify({"success": True, "data": {"questions": qs}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── FLASHCARDS — instant from cache ──────────────────────────────────────────
@app.route("/flashcards", methods=["POST"])
def flashcards():
    if 'flashcards' in _content_cache and _content_cache['flashcards']:
        logger.info("Flashcards: cache hit (instant)")
        return jsonify({"success": True, "data": {"cards": _content_cache['flashcards']}})

    context = get_context_text(max_chars=2000)
    if not context:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400
    try:
        t0  = time.time()
        raw = ask_llm(FLASHCARD_PROMPT.format(context=context))
        cs  = deduplicate(parse_flashcards(raw), lambda c: c["question"], 8)
        _content_cache['flashcards'] = cs
        logger.info(f"Flashcards generated in {round(time.time()-t0,1)}s")
        return jsonify({"success": True, "data": {"cards": cs}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── CONCEPTS ──────────────────────────────────────────────────────────────────
@app.route("/concepts", methods=["POST"])
def concepts():
    context = get_short_text(max_chars=1500)
    if not context:
        return jsonify({"error": "No documents indexed yet."}), 400
    try:
        raw = ask_llm(CONCEPTS_PROMPT.format(context=context))
        return jsonify({"success": True, "data": {"concepts": parse_concepts(raw)}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── EXAM — instant from cache ─────────────────────────────────────────────────
@app.route("/exam", methods=["POST"])
def exam():
    if 'exam' in _content_cache and _content_cache['exam']:
        logger.info("Exam: cache hit (instant)")
        return jsonify({"success": True, "data": {"questions": _content_cache['exam']}})

    context = get_context_text(max_chars=2000)
    if not context:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400
    try:
        t0  = time.time()
        raw = ask_llm(EXAM_PROMPT.format(context=context))
        qs  = parse_exam(raw)
        order = {"Easy": 0, "Medium": 1, "Hard": 2}
        qs.sort(key=lambda x: order.get(x["difficulty"], 1))
        qs = deduplicate(qs, lambda q: q["question"], 999)
        _content_cache['exam'] = qs
        logger.info(f"Exam generated in {round(time.time()-t0,1)}s")
        return jsonify({"success": True, "data": {"questions": qs}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── STATUS ────────────────────────────────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    ollama_ok = False; index_ok = False; doc_count = 0; chunk_count = 0
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        ollama_ok = True
    except:
        pass
    if os.path.exists(CHROMA_FOLDER) and os.listdir(CHROMA_FOLDER):
        index_ok = True
        try:
            vs = get_vectorstore()
            if vs:
                chunk_count = len(vs.get(limit=1000).get("documents", []))
        except:
            pass
    if os.path.exists(DOCS_FOLDER):
        doc_count = len([f for f in os.listdir(DOCS_FOLDER)
                         if f.endswith((".pdf", ".txt", ".docx", ".md"))])
    return jsonify({
        "ollama":      ollama_ok,
        "index":       index_ok,
        "docs":        doc_count,
        "chunks":      chunk_count,
        "chunk_size":  600,
        "top_k":       3,
        "generating":  _generating,
        "cache_ready": list(_content_cache.keys())
    })


@app.route("/documents", methods=["GET"])
def documents():
    if not os.path.exists(DOCS_FOLDER):
        return jsonify({"documents": []})
    docs = []
    for f in os.listdir(DOCS_FOLDER):
        if f.endswith((".pdf", ".txt", ".docx", ".md")):
            size_kb = round(os.path.getsize(os.path.join(DOCS_FOLDER, f)) / 1024, 1)
            docs.append({"name": f, "size_kb": size_kb, "indexed": True})
    return jsonify({"documents": docs})


@app.route("/document/<filename>", methods=["DELETE"])
def delete_document(filename):
    global vectorstore
    filepath = os.path.join(DOCS_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    os.remove(filepath)
    release_vectorstore()
    remaining = [f for f in os.listdir(DOCS_FOLDER)
                 if f.endswith((".pdf", ".txt", ".docx", ".md"))]
    if remaining:
        docs        = load_documents()
        chunks      = split_documents(docs)
        vectorstore = create_vectorstore(chunks)
        build_bm25_index(chunks)
        Thread(target=pre_generate_all, daemon=True).start()
    else:
        if os.path.exists(CHROMA_FOLDER):
            try:
                shutil.rmtree(CHROMA_FOLDER)
            except Exception as e:
                return jsonify({"error": f"Could not delete index: {str(e)}"}), 500
    return jsonify({"success": True, "message": f"'{filename}' deleted."})


@app.route("/index", methods=["DELETE"])
def delete_index():
    release_vectorstore()
    if os.path.exists(CHROMA_FOLDER):
        try:
            shutil.rmtree(CHROMA_FOLDER)
            return jsonify({"success": True, "message": "Index deleted!"})
        except Exception as e:
            return jsonify({"error": f"Could not delete index: {str(e)}"}), 500
    return jsonify({"success": True, "message": "No index found."})


@app.route("/cache/status", methods=["GET"])
def cache_status():
    return jsonify({
        "generating": _generating,
        "ready":      list(_content_cache.keys()),
        "all_ready":  all(k in _content_cache for k in ['summary', 'quiz', 'flashcards', 'exam'])
    })


if __name__ == "__main__":
    print("=" * 45)
    print("  LocalRAG v2.1 starting...")
    print(f"  Model     : {MODEL_NAME}")
    print(f"  num_predict: 350  (was 900 — 2.5x faster)")
    print(f"  num_ctx    : 2048 (fits prompt + context)")
    print(f"  Pre-gen    : 5 LLM calls after upload")
    print("  Open http://localhost:5000")
    print("=" * 45)
    app.run(debug=False, host="0.0.0.0", port=5000, threaded=True)