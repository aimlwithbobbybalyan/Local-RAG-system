from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from werkzeug.utils import secure_filename
import os, shutil, json, re, gc, time, logging

# ── LOGGING ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── UPLOAD LIMITS ─────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 50
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# ── PROMPTS: Single source of truth in prompts.py ─────────────────────────────
from prompts import (
    SUMMARY_PROMPT, KEYPOINTS_PROMPT, CONCEPTS_PROMPT, CONCEPTS_PROMPT_SIMPLE,
    QUIZ_PROMPT, FLASHCARD_PROMPT, EXAM_PROMPT, WHAT_ABOUT_PROMPT
)

from rag_pipeline import (
    load_documents,
    split_documents,
    create_vectorstore,
    ask_question,
    CHROMA_FOLDER,
    EMBED_MODEL,
)



CONCEPTS_PROMPT    = CONCEPTS_PROMPT_SIMPLE
WHAT_ABOUT_PROMPT  = SUMMARY_PROMPT

from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama

app = Flask(__name__)
CORS(app)

DOCS_FOLDER = "data"
MODEL_NAME  = "qwen2.5:3b"   # upgraded from llama3.2:1b — better instruction following, structured output
vectorstore = None


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


# FIX: create_vectorstore did not exist in rag_pipeline — defined here
def create_vectorstore(chunks):
    global vectorstore
    embedding   = OllamaEmbeddings(model=EMBED_MODEL)
    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embedding,
        persist_directory=CHROMA_FOLDER
    )
    return vectorstore


def get_all_text(max_chars=14000):
    vs = get_vectorstore()
    if vs is None:
        return ""
    results = vs.get(limit=80)
    texts   = results.get("documents", [])
    return "\n\n".join(texts)[:max_chars]

def get_short_text(max_chars=5000):
    """Medium context for concept extraction — qwen2.5:3b handles more"""
    vs = get_vectorstore()
    if vs is None:
        return ""
    results = vs.get(limit=20)
    texts   = results.get("documents", [])
    return "\n\n".join(texts)[:max_chars]


def get_spread_text(max_chars=6000):
    """Sample chunks evenly from start/middle/end so ALL topics are covered."""
    vs = get_vectorstore()
    if vs is None:
        return ""
    results = vs.get(limit=500)
    texts   = results.get("documents", [])
    if not texts:
        return ""
    total = len(texts)
    if total <= 15:
        return "\n\n".join(texts)[:max_chars]
    indices = [0, 1, 2]
    step = max(1, total // 8)
    for i in range(step, total - 3, step):
        indices.append(i)
    indices += [total-3, total-2, total-1]
    indices = sorted(set(indices))
    sampled = [texts[i] for i in indices if i < total]
    return "\n\n".join(sampled)[:max_chars]


def get_sections(section_chars=3500, max_sections=3):
    """Split doc into N equal sections for multi-call generation."""
    vs = get_vectorstore()
    if vs is None:
        return []
    results = vs.get(limit=500)
    texts   = results.get("documents", [])
    if not texts:
        return []
    total    = len(texts)
    sections = []
    sec_size = max(1, total // max_sections)
    for i in range(0, total, sec_size):
        chunk = "\n\n".join(texts[i:i+sec_size])[:section_chars]
        sections.append(chunk)
        if len(sections) >= max_sections:
            break
    return sections

def safe_json(raw):
    """Strip markdown fences and extract first JSON object"""
    raw = re.sub(r"```json|```", "", raw).strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except:
        return None


# LLM cache keyed by max_tokens — qwen2.5:3b loads once per token setting
_llm_cache = {}

def ask_llm(prompt, max_tokens=800):
    global _llm_cache
    if max_tokens not in _llm_cache:
        _llm_cache[max_tokens] = Ollama(
            model       = MODEL_NAME,
            temperature = 0.1,
            num_predict = max_tokens,
            num_ctx     = 4096,   # qwen2.5:3b context window
        )
    return _llm_cache[max_tokens].invoke(prompt)


def release_vectorstore():
    # close vectorstore and release file locks on Windows
    global vectorstore
    vectorstore = None
    gc.collect()
    time.sleep(0.5)


# serve the UI
@app.route("/")
def index():
    return render_template("index.html")


# upload and index a file
@app.route("/upload", methods=["POST"])
def upload():
    global vectorstore

    if "file" not in request.files:
        return jsonify({"error": "No file sent"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    allowed = {".pdf", ".txt", ".docx", ".md"}
    filename = secure_filename(file.filename)
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        return jsonify({"error": f"{ext} files are not supported. Allowed: PDF, TXT, DOCX, MD"}), 400

    # Check file size before saving
    file.seek(0, 2)  # seek to end
    file_size = file.tell()
    file.seek(0)     # reset
    if file_size > MAX_FILE_SIZE_BYTES:
        return jsonify({"error": f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB."}), 400
    if file_size == 0:
        return jsonify({"error": "File is empty."}), 400

    os.makedirs(DOCS_FOLDER, exist_ok=True)

    # max 3 docs check
    existing = [f for f in os.listdir(DOCS_FOLDER)
                if f.endswith((".pdf", ".txt", ".docx", ".md"))]
    if len(existing) >= 3:
        return jsonify({"error": "Maximum 3 documents allowed. Please delete one first."}), 400

    filepath = os.path.join(DOCS_FOLDER, filename)
    file.save(filepath)
    logger.info(f"Uploaded file: {filename} ({file_size // 1024}KB)")

    try:
        docs        = load_documents()
        chunks      = split_documents(docs)
        vectorstore = create_vectorstore(chunks)
    except Exception as e:
        return jsonify({"error": f"Indexing failed: {str(e)}"}), 500

    return jsonify({
        "success":  True,
        "filename": file.filename,
        "chunks":   len(chunks) if chunks else 0,
        "message":  f"'{file.filename}' indexed successfully!"
    })


# main chat endpoint
# Cached QA chain — built once after first upload, reused for all chat questions
_qa_chain = None

def get_qa_chain(vs, tags=None, doc_filter="all"):
    """Build QA chain with tag-aware prompt and optional per-document filter."""
    from langchain_community.llms import Ollama as OllamaChat
    from langchain.chains import RetrievalQA
    from langchain.prompts import PromptTemplate
    if tags is None:
        tags = []

    chat_llm = OllamaChat(
        model       = MODEL_NAME,
        temperature = 0.2,
        num_predict = 900,
        num_ctx     = 4096,
    )

    rag_on    = any("RAG" in t     for t in tags)
    teacher   = any("Teacher"   in t for t in tags)
    technical = any("Technical" in t for t in tags)
    chat_mode = any("Chat"      in t for t in tags)
    summary   = any("Summary"   in t for t in tags)
    bullets   = any("Bullet"    in t for t in tags)
    cite      = any("Cite"      in t for t in tags)

    if teacher:
        style = (
            "You are an outstanding teacher known for making complex topics completely clear to any student. "
            "A student has asked you a question from a document they are studying. Give a thorough, structured answer that leaves zero confusion.\n\n"
            "Answer in this EXACT structure — fill every section completely:\n"
            "1. DEFINITION: One clear, simple sentence — what is this exactly? Use plain everyday language. Avoid jargon.\n"
            "   Example: 'Gradient descent is a mathematical method used to find the lowest point of an error curve by taking small steps in the downhill direction.'\n\n"
            "2. EXPLANATION: Explain how it works or what it means in 3-4 sentences. Imagine explaining to a smart 16-year-old. "
            "Build from basics — do not assume prior knowledge. Use cause-and-effect language ('because', 'this means that', 'as a result').\n\n"
            "3. REAL-LIFE EXAMPLE: Give one concrete, vivid, relatable example that anyone can picture. "
            "For instance, if explaining RAM: 'Think of RAM like your physical desk — the bigger the desk, the more books and papers you can have open at once without going to the shelf. When you close a program, you clear desk space.'\n\n"
            "4. KEY TYPES / COMPONENTS: For each important type, subtype, or component, write on its own line: "
            "Name: one sentence explaining what makes it distinct and when it is used. Never just list names.\n\n"
            "5. WHY IT MATTERS: One sentence explaining the real-world importance, consequence, or application of this concept. "
            "Example: 'Without gradient descent, training modern neural networks with billions of parameters would be computationally impossible.'\n\n"
            "6. EXAM SUMMARY: One final sentence — the single most important fact about this topic that a student must never forget.\n\n"
            "Rules: Fill every section. Write complete sentences. Be thorough. Never skip a section. "
            "If information for a section is not in the document, use your general knowledge to complete it."
        )
    elif technical:
        style = (
            "You are a senior technical expert and researcher with deep domain expertise. "
            "Answer with full technical precision, depth, and accuracy. Do not simplify unless asked.\n\n"
            "Answer in this EXACT structure — every section must be fully detailed:\n"
            "1. TECHNICAL DEFINITION: A precise, complete definition using correct technical terminology. "
            "State the domain (e.g., machine learning, digital electronics, organic chemistry) and the formal definition.\n\n"
            "2. WORKING PRINCIPLE: Explain step-by-step exactly how this works at a technical level. "
            "Include the internal mechanism, algorithm, process, or physical principle. Be specific — name the steps.\n"
            "Example format: 'Step 1: Input data is normalised. Step 2: Weights are initialised randomly. Step 3: Forward pass computes predictions...'\n\n"
            "3. TYPES / CLASSIFICATIONS: For each type or variant, write: Name: one sentence with its specific technical characteristics and the exact conditions under which it is used instead of alternatives.\n\n"
            "4. KEY PARAMETERS & SPECIFICATIONS: List important values, formulas, thresholds, or technical constraints. "
            "Example: 'Time complexity: O(n log n). Space complexity: O(n). Learning rate typically: 0.001–0.01. Convergence condition: |gradient| < epsilon.'\n\n"
            "5. TECHNICAL ADVANTAGES & LIMITATIONS: State 2-3 specific, measurable technical strengths and 1-2 known limitations, failure modes, or trade-offs with numbers where possible.\n\n"
            "6. REAL-WORLD APPLICATIONS: Give 3-4 specific named applications with technical context. "
            "Example: 'Used in Google PageRank to rank 60 billion web pages by iterating the eigenvector of the web graph adjacency matrix.'\n\n"
            "7. TECHNICAL SUMMARY: One precise sentence capturing the core technical principle and its most important constraint or property.\n\n"
            "Rules: Be maximally detailed. Use correct technical terms throughout. If the document does not contain enough detail, supplement with accurate technical knowledge."
        )
    elif chat_mode:
        style = (
            "You are a smart, friendly study buddy. Answer like you are texting a friend who just asked you something confusing. "
            "Keep it natural, clear, and conversational — like a smart person explaining over coffee, not a textbook. "
            "Write 4-5 short, clear sentences. No bullet points, no headings, no formal structure. "
            "If the concept is tricky, use one quick analogy to make it click. "
            "Example tone: 'So basically, gradient descent is like being blindfolded on a hill — you just keep feeling which direction is downhill and take small steps that way until you hit the bottom. "
            "That bottom is where the model has the least error. Pretty simple idea, surprisingly powerful.'"
        )
    elif summary:
        style = (
            "Give a well-structured, detailed summary answer in this EXACT format:\n\n"
            "OVERVIEW: One direct sentence that answers the question immediately.\n\n"
            "KEY POINTS:\n"
            "- [Complete sentence — specific fact or explanation, at least 12 words, not just a label]\n"
            "- [Complete sentence — specific fact or explanation, at least 12 words]\n"
            "- [Complete sentence — specific fact or explanation, at least 12 words]\n"
            "- [Complete sentence — specific fact or explanation, at least 12 words]\n"
            "- [Complete sentence — specific fact or explanation, at least 12 words]\n\n"
            "TAKEAWAY: One sentence — the most important thing to understand or remember about this topic.\n\n"
            "Rules: Every bullet must be a complete sentence with real information. "
            "Never write a bullet that is just a topic name like '- Machine Learning' — always explain it."
        )
    else:
        style = (
            "Answer clearly, helpfully, and completely in 4-6 sentences. "
            "Start by directly answering the question in the first sentence. "
            "Then provide supporting explanation, context, or examples in the following sentences. "
            "End with one sentence that gives the most important takeaway or practical implication. "
            "Use plain, precise language — clear enough for a student, detailed enough to be genuinely useful."
        )

    fmt = ""
    if bullets:
        fmt += (
            "\n\nFORMAT RULES — Bullet Points Mode:\n"
            "- Write your ENTIRE answer as bullet points. No paragraphs.\n"
            "- Each bullet must be a COMPLETE SENTENCE of at least 12 words.\n"
            "- Start each bullet with the key term or concept, then explain it fully.\n"
            "- Example of a BAD bullet: '- Machine learning is useful'\n"
            "- Example of a GOOD bullet: '- Machine learning enables computers to learn patterns from data automatically, eliminating the need to manually program rules for every situation.'\n"
            "- Aim for 6-10 detailed bullets that together give a complete, thorough answer.\n"
            "- Every bullet must add new information — no repetition."
        )
    if cite:
        fmt += (
            "\n\nCITATION RULE: After your complete answer, add this section on a new line:\n"
            "Sources: [name the specific section, topic heading, chapter, or page of the document where this information was found. "
            "If multiple sources, list each one. Example: 'Sources: Section 3 - Supervised Learning, Section 5 - Neural Networks']"
        )

    scope = ("Use ONLY the document text provided below. Do not use outside knowledge."
             if rag_on else
             "Use the document below as your main source. You may add brief general knowledge if helpful.")

    doc_note = f"\n[Filtering to document: {doc_filter}]" if doc_filter and doc_filter != "all" else ""

    template = f"""{style}

{scope}{fmt}{doc_note}

Document:
{{context}}

Question: {{question}}
Answer:"""

    prompt = PromptTemplate(template=template, input_variables=["context", "question"])

    if doc_filter and doc_filter != "all":
        doc_path      = os.path.join(DOCS_FOLDER, doc_filter)
        search_kwargs = {"k": 4, "filter": {"source": doc_path}}
    else:
        search_kwargs = {"k": 4}

    return RetrievalQA.from_chain_type(
        llm=chat_llm,
        chain_type="stuff",
        retriever=vs.as_retriever(search_kwargs=search_kwargs),
        return_source_documents=True,
        chain_type_kwargs={"prompt": prompt}
    )


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
        return jsonify({"error": "No documents indexed yet. Please upload a file first!"}), 400

    try:
        chain   = get_qa_chain(vs, tags, doc_filter)
        result  = chain.invoke({"query": question})
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
            "confidence": 90
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── PLAIN TEXT PARSERS ────────────────────────────────────────────────────

def parse_summary(raw):
    """Extract TITLE and OVERVIEW — handles multi-line overview."""
    title    = ""
    overview = ""
    lines    = raw.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.upper().startswith("TITLE:"):
            title = line[6:].strip()
        elif line.upper().startswith("OVERVIEW:"):
            parts = [line[9:].strip()]
            # collect continuation lines until blank or next label
            i += 1
            while i < len(lines):
                nxt = lines[i].strip()
                if not nxt or re.match(r'^[A-Z]{3,}:', nxt):
                    break
                parts.append(nxt)
                i += 1
            overview = " ".join(p for p in parts if p)
            continue
        i += 1
    if not overview:
        overview = raw.strip()[:600]
    return title, overview


def parse_points(raw):
    """Extract bullet points — complete sentences, skip short term-only lines."""
    points = []
    for line in raw.splitlines():
        line = line.strip()
        # Accept: - / • / 1. / 1)
        if line.startswith("- ") or line.startswith("• ") or line.startswith("* "):
            pt = line[2:].strip()
        elif re.match(r'^\d+[\.\)]\s', line):
            pt = re.sub(r'^\d+[\.\)]\s+', '', line).strip()
        else:
            continue
        # Skip very short lines (just a term name, not a sentence)
        if pt and len(pt) > 20:
            points.append(pt)
    return points


def parse_concepts(raw):
    """Extract concept terms — from TERMS: line or bullet list."""
    for line in raw.splitlines():
        l = line.strip()
        if l.upper().startswith("TERMS:"):
            terms = l[6:].strip()
            if terms:
                return [t.strip() for t in terms.split(",") if t.strip()]
    # fallback: bullet list
    concepts = []
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("• ") or line.startswith("* "):
            t = line[2:].strip()
            if t:
                concepts.append(t)
    return concepts


def parse_quiz(raw):
    """Parse quiz blocks separated by ### — robust multi-line support."""
    questions  = []
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    # Support both ### separator and plain Q: splits
    if "###" in raw:
        blocks = re.split(r'#+', raw)
    else:
        blocks = re.split(r'(?:^|\n)(?=Q:)', raw)
    for block in blocks:
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        q_text = ""
        opts   = []
        correct_letter = "A"
        explanation    = ""
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
    """
    Parse flashcard blocks separated by ###.
    Captures multi-line answers correctly.
    """
    cards = []
    # Support both ### separator and plain Q: splits
    if "###" in raw:
        blocks = re.split(r'#+', raw)
    else:
        blocks = re.split(r'(?:^|\n)(?=Q:)', raw)
    for block in blocks:
        lines  = [l.strip() for l in block.splitlines() if l.strip()]
        q_text = ""
        a_lines = []
        reading_a = False
        for line in lines:
            up = line.upper()
            if up.startswith("Q:"):
                q_text    = line[2:].strip()
                reading_a = False
                a_lines   = []
            elif up.startswith("A:") or up.startswith("ANSWER:"):
                prefix    = 2 if up.startswith("A:") else 7
                first_bit = line[prefix:].strip()
                if first_bit:
                    a_lines.append(first_bit)
                reading_a = True
            elif reading_a:
                # continuation of the answer
                if not re.match(r'^(Q:|###)', line, re.IGNORECASE):
                    a_lines.append(line)
        a_text = " ".join(a_lines).strip()
        if q_text and a_text:
            cards.append({"question": q_text, "answer": a_text})
    return cards


# summary — spread text for overview, sections for key points (covers whole doc)
@app.route("/summary", methods=["POST"])
def summary():
    spread_text = get_spread_text(max_chars=6000)
    if not spread_text:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400

    sections = get_sections(section_chars=3000, max_sections=3)
    result   = {"title": "", "overview": "", "key_points": [], "concepts": []}

    # Call 1: title + overview (whole-doc perspective)
    try:
        raw = ask_llm(SUMMARY_PROMPT.format(context=spread_text), max_tokens=400)
        title, overview = parse_summary(raw)
        result["title"]    = title
        result["overview"] = overview
    except Exception as e:
        logger.error(f"Summary overview generation failed: {e}")
        result["overview"] = "Could not generate overview."

    # Call 2: key points from each section — merge for full coverage
    all_points = []
    for sec in sections:
        try:
            raw    = ask_llm(KEYPOINTS_PROMPT.format(context=sec), max_tokens=900)
            points = parse_points(raw)
            all_points.extend(points)
        except Exception as e:
            logger.error(f"Key points generation failed for section: {e}")
    seen, unique = set(), []
    for p in all_points:
        key = p[:40].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    result["key_points"] = unique[:12]

    # Call 3: concepts from spread text (whole doc)
    try:
        raw = ask_llm(CONCEPTS_PROMPT_SIMPLE.format(context=spread_text), max_tokens=200)
        result["concepts"] = parse_concepts(raw)
    except Exception as e:
        logger.error(f"Concepts generation failed: {e}")

    return jsonify({"success": True, "data": result})


# quiz — one call per section to cover whole document
@app.route("/quiz", methods=["POST"])
def quiz():
    sections = get_sections(section_chars=3500, max_sections=3)
    if not sections:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400

    all_questions = []
    for sec in sections:
        try:
            raw = ask_llm(QUIZ_PROMPT.format(context=sec), max_tokens=1100)
            qs  = parse_quiz(raw)
            all_questions.extend(qs)
        except Exception as e:
            logger.error(f"Quiz generation failed for section: {e}")

    if not all_questions:
        return jsonify({"error": "Could not generate quiz. Try again."}), 500

    seen, unique = set(), []
    for q in all_questions:
        key = q["question"][:30].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)
    return jsonify({"success": True, "data": {"questions": unique[:10]}})


# flashcards — one call per section to cover whole document
@app.route("/flashcards", methods=["POST"])
def flashcards():
    sections = get_sections(section_chars=3000, max_sections=3)
    if not sections:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400

    all_cards = []
    for sec in sections:
        try:
            raw   = ask_llm(FLASHCARD_PROMPT.format(context=sec), max_tokens=1000)
            cards = parse_flashcards(raw)
            all_cards.extend(cards)
        except Exception as e:
            logger.error(f"Flashcard generation failed for section: {e}")

    if not all_cards:
        return jsonify({"error": "Could not generate flashcards. Try again."}), 500

    seen, unique = set(), []
    for c in all_cards:
        key = c["question"][:30].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return jsonify({"success": True, "data": {"cards": unique[:12]}})


# key concepts
@app.route("/concepts", methods=["POST"])
def concepts():
    doc_text = get_short_text()
    if not doc_text:
        return jsonify({"error": "No documents indexed yet."}), 400
    try:
        raw      = ask_llm(CONCEPTS_PROMPT.format(context=doc_text))
        concepts_list = parse_concepts(raw)
        return jsonify({"success": True, "data": {"concepts": concepts_list}})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# check ollama + index status
@app.route("/status", methods=["GET"])
def status():
    ollama_ok   = False
    index_ok    = False
    doc_count   = 0
    chunk_count = 0

    # FIX: was llm.invoke("hi") which loads the full model into RAM just to check status.
    # Use a lightweight HTTP ping to Ollama's API endpoint instead.
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
        "chunk_size":  512,   # matches CHUNK_SIZE in rag_pipeline.py
        "top_k":       5      # matches k=5 in ask_question retriever
    })


# list documents for sidebar
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


# delete a specific document
@app.route("/document/<filename>", methods=["DELETE"])
def delete_document(filename):
    global vectorstore
    filepath = os.path.join(DOCS_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    os.remove(filepath)
    release_vectorstore()  # close connection before deleting index

    remaining = [f for f in os.listdir(DOCS_FOLDER)
                 if f.endswith((".pdf", ".txt", ".docx", ".md"))]
    if remaining:
        docs        = load_documents()
        chunks      = split_documents(docs)
        vectorstore = create_vectorstore(chunks)
    else:
        if os.path.exists(CHROMA_FOLDER):
            try:
                shutil.rmtree(CHROMA_FOLDER)
            except Exception as e:
                return jsonify({"error": f"Could not delete index: {str(e)}"}), 500

    return jsonify({"success": True, "message": f"'{filename}' deleted."})


# delete entire chroma index
@app.route("/index", methods=["DELETE"])
def delete_index():
    release_vectorstore()  # close connection before deleting
    if os.path.exists(CHROMA_FOLDER):
        try:
            shutil.rmtree(CHROMA_FOLDER)
            return jsonify({"success": True, "message": "Index deleted!"})
        except Exception as e:
            return jsonify({"error": f"Could not delete index: {str(e)}"}), 500
    return jsonify({"success": True, "message": "No index found."})


def parse_exam(raw):
    """Parse numbered exam questions from QUESTIONS: block."""
    questions = []
    in_block  = False
    for line in raw.splitlines():
        line = line.strip()
        if line.upper().startswith("QUESTIONS:"):
            in_block = True
            continue
        if not in_block:
            continue
        # Match: 1. [Easy] question   OR   1. question
        m = re.match(r'^\d+[\.\)]\s+(?:\[(Easy|Medium|Hard)\]\s*)?(.+)', line, re.IGNORECASE)
        if m:
            difficulty = m.group(1) or "Medium"
            question   = m.group(2).strip()
            if len(question) > 10:
                questions.append({"question": question, "difficulty": difficulty.capitalize()})
    return questions


# exam questions — covers whole document, all topics
@app.route("/exam", methods=["POST"])
def exam():
    sections = get_sections(section_chars=3500, max_sections=4)
    if not sections:
        return jsonify({"error": "No documents indexed yet. Upload a file first!"}), 400

    all_questions = []
    for sec in sections:
        try:
            raw = ask_llm(EXAM_PROMPT.format(context=sec), max_tokens=1200)
            qs  = parse_exam(raw)
            all_questions.extend(qs)
        except Exception as e:
            logger.error(f"Exam question generation failed for section: {e}")

    if not all_questions:
        return jsonify({"error": "Could not generate exam questions. Try again."}), 500

    # Deduplicate
    seen, unique = set(), []
    for q in all_questions:
        key = q["question"][:35].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(q)

    # Sort: Easy first, then Medium, then Hard
    order = {"Easy": 0, "Medium": 1, "Hard": 2}
    unique.sort(key=lambda x: order.get(x["difficulty"], 1))

    return jsonify({"success": True, "data": {"questions": unique}})


if __name__ == "__main__":
    print("=" * 45)
    print("  LocalRAG starting...")
    print(f"  Model: {MODEL_NAME}")
    print("  Open http://localhost:5000")
    print("=" * 45)
    app.run(debug=True, host="0.0.0.0", port=5000)