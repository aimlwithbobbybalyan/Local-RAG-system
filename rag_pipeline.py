from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader, UnstructuredMarkdownLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────
DOCS_FOLDER   = "data"
CHROMA_FOLDER = "chroma_db"
MODEL_NAME    = "qwen2.5:3b"        # upgraded from tinyllama — better instruction following
EMBED_MODEL   = "nomic-embed-text"  # stays — best-in-class for RAG retrieval at this size
CHUNK_SIZE    = 800                 # increased from 512 — qwen2.5:3b handles larger context well
CHUNK_OVERLAP = 100                 # increased from 50 — more overlap = better continuity across chunks


# ── DOCUMENT LOADING ──────────────────────────────────────────────────────────
def load_documents():
    documents = []
    if not os.path.exists(DOCS_FOLDER):
        os.makedirs(DOCS_FOLDER)
        print(f"Created {DOCS_FOLDER}/ folder. Add your documents there.")
        return documents

    files = [f for f in os.listdir(DOCS_FOLDER)
             if f.endswith((".pdf", ".txt", ".docx", ".md"))]

    if len(files) == 0:
        print("No documents found in data/ folder.")
        return documents

    if len(files) > 3:
        print(f"Warning: Maximum 3 documents allowed. You have {len(files)}. Remove some from data/.")
        return documents

    for filename in files:
        filepath = os.path.join(DOCS_FOLDER, filename)
        try:
            if filename.endswith(".pdf"):
                print(f"  Loading PDF  : {filename}")
                loader = PyPDFLoader(filepath)
            elif filename.endswith(".txt"):
                print(f"  Loading TXT  : {filename}")
                loader = TextLoader(filepath, encoding="utf-8")
            elif filename.endswith(".docx"):
                print(f"  Loading DOCX : {filename}")
                loader = Docx2txtLoader(filepath)
            elif filename.endswith(".md"):
                print(f"  Loading MD   : {filename}")
                loader = UnstructuredMarkdownLoader(filepath)
            else:
                print(f"  Skipping     : {filename} (unsupported)")
                continue
            documents.extend(loader.load())
        except Exception as e:
            print(f"  Could not load {filename}: {e}")

    print(f"  Total pages/sections loaded: {len(documents)}")
    return documents


# ── CHUNKING ──────────────────────────────────────────────────────────────────
def split_documents(documents):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size    = CHUNK_SIZE,
        chunk_overlap = CHUNK_OVERLAP,
        separators    = ["\n\n", "\n", ". ", " ", ""]  # paragraph -> sentence -> word
    )
    chunks = text_splitter.split_documents(documents)
    print(f"  Total chunks: {len(chunks)}  (size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP})")
    return chunks


# ── VECTOR STORE ──────────────────────────────────────────────────────────────
def create_vectorstore(chunks):
    print("  Generating embeddings with nomic-embed-text...")
    embedding = OllamaEmbeddings(model=EMBED_MODEL)
    vectorstore = Chroma.from_documents(
        documents         = chunks,
        embedding         = embedding,
        persist_directory = CHROMA_FOLDER
    )
    print(f"  Vectorstore saved to {CHROMA_FOLDER}/")
    return vectorstore


# ── PROMPT BUILDER ────────────────────────────────────────────────────────────
# Mirrors get_qa_chain() in app.py exactly — CLI and web give identical answers.
# Active tags: RAG mode, Teacher, Technical, Chat, Summary, Bullet points, Cite sources
# Active chips: Explain simply, 5 key points, Compare concepts, Revision notes

def build_prompt(tags=None):
    if tags is None:
        tags = []

    rag_on    = any("RAG"       in t for t in tags)
    teacher   = any("Teacher"   in t for t in tags)
    technical = any("Technical" in t for t in tags)
    chat_mode = any("Chat"      in t for t in tags)
    summary   = any("Summary"   in t for t in tags)
    bullets   = any("Bullet"    in t for t in tags)
    cite      = any("Cite"      in t for t in tags)
    explain   = any("Explain"   in t for t in tags)
    keypoints = any("key point" in t.lower() for t in tags)
    compare   = any("Compare"   in t for t in tags)
    revision  = any("Revision"  in t for t in tags)

    # ── Style ─────────────────────────────────────────────────────────────────

    if teacher:
        style = (
            "You are an outstanding teacher known for making complex topics completely clear to any student. "
            "Answer in this EXACT structure — fill every section completely:\n\n"
            "1. DEFINITION: One clear simple sentence. What is this exactly? Plain everyday language.\n\n"
            "2. EXPLANATION: How it works in 3-4 sentences. Build from basics. Use cause-and-effect language "
            "('because', 'this means that', 'as a result'). No jargon.\n\n"
            "3. REAL-LIFE EXAMPLE: One concrete vivid example anyone can picture. "
            "Example: 'Think of RAM like your desk — the bigger the desk, the more books you can have open at once.'\n\n"
            "4. KEY TYPES / COMPONENTS: For each type or component write — "
            "Name: one sentence explaining what makes it distinct and when it is used.\n\n"
            "5. WHY IT MATTERS: One sentence on real-world importance or consequence.\n\n"
            "6. EXAM SUMMARY: The single most important fact a student must never forget.\n\n"
            "Rules: Fill every section. Write complete sentences. Never skip a section."
        )

    elif technical:
        style = (
            "You are a senior technical expert. Answer with full precision and depth.\n\n"
            "1. TECHNICAL DEFINITION: Precise definition using correct technical terminology. "
            "State the domain and formal definition.\n\n"
            "2. WORKING PRINCIPLE: Step-by-step technical explanation. "
            "Name every step. Example: 'Step 1: Input is normalised. Step 2: Weights initialised...'\n\n"
            "3. TYPES / CLASSIFICATIONS: For each type — Name: specific technical characteristics "
            "and exact conditions under which it is preferred over alternatives.\n\n"
            "4. KEY PARAMETERS & SPECIFICATIONS: Important values, formulas, thresholds, complexity. "
            "Example: 'Time complexity O(n log n). Learning rate: 0.001-0.01.'\n\n"
            "5. ADVANTAGES & LIMITATIONS: 2-3 measurable strengths, 1-2 known limitations or trade-offs.\n\n"
            "6. REAL-WORLD APPLICATIONS: 3-4 specific named applications with technical context.\n\n"
            "7. TECHNICAL SUMMARY: One precise sentence capturing the core principle and key constraint."
        )

    elif chat_mode:
        style = (
            "Answer like a smart friendly study buddy texting a friend. "
            "Natural, clear, conversational — like explaining over coffee, not a textbook. "
            "4-5 short clear sentences. No bullet points, no headings. "
            "If the concept is tricky, use one quick analogy to make it click."
        )

    elif summary:
        style = (
            "Give a well-structured summary in this EXACT format:\n\n"
            "OVERVIEW: One direct sentence that answers immediately.\n\n"
            "KEY POINTS:\n"
            "- [Complete sentence, specific fact, at least 12 words]\n"
            "- [Complete sentence, specific fact, at least 12 words]\n"
            "- [Complete sentence, specific fact, at least 12 words]\n"
            "- [Complete sentence, specific fact, at least 12 words]\n"
            "- [Complete sentence, specific fact, at least 12 words]\n\n"
            "TAKEAWAY: The most important thing to understand about this topic.\n\n"
            "Every bullet must be a complete sentence. Never just a label."
        )

    elif explain:
        style = (
            "Explain this as simply as possible to a 16-year-old with no background knowledge. "
            "Use only everyday words. No jargon. "
            "Structure: one sentence saying what it is, two sentences explaining how it works, "
            "one real-life analogy anyone can relate to. Maximum 5 lines total."
        )

    elif keypoints:
        style = (
            "Give exactly 5 key points to remember. Each must be a complete sentence of at least "
            "12 words that explains what something IS and WHY it matters — not just its name.\n\n"
            "1. [complete sentence]\n"
            "2. [complete sentence]\n"
            "3. [complete sentence]\n"
            "4. [complete sentence]\n"
            "5. [complete sentence]"
        )

    elif compare:
        style = (
            "Compare the main concepts in this EXACT structure:\n\n"
            "CONCEPT 1 - Name: what it is and how it works in 2 sentences.\n"
            "CONCEPT 2 - Name: what it is and how it works in 2 sentences.\n"
            "SIMILARITIES: What they share — at least 2 specific points.\n"
            "DIFFERENCES: How they differ — at least 3 specific contrasts.\n"
            "WHEN TO USE EACH: The practical decision rule — which situation calls for each one."
        )

    elif revision:
        style = (
            "Short focused revision notes in this EXACT format:\n\n"
            "TOPIC: What this is about in one line.\n\n"
            "MUST KNOW:\n"
            "- [most important point — complete sentence]\n"
            "- [second important point — complete sentence]\n"
            "- [third important point — complete sentence]\n"
            "- [fourth important point — complete sentence]\n"
            "- [fifth important point — complete sentence]\n\n"
            "REMEMBER: The single most critical fact — the one thing that must not be forgotten."
        )

    else:
        style = (
            "Answer clearly, helpfully, and completely in 4-6 sentences. "
            "Start by directly answering the question in the first sentence. "
            "Then provide supporting explanation, context, or examples. "
            "End with the most important takeaway or practical implication."
        )

    # ── Format modifiers ──────────────────────────────────────────────────────

    fmt = ""
    if bullets:
        fmt += (
            "\n\nFORMAT - Bullet Points Mode:\n"
            "Write your ENTIRE answer as bullet points. No paragraphs.\n"
            "Each bullet must be a COMPLETE SENTENCE of at least 12 words.\n"
            "Start each bullet with the key term then explain it fully.\n"
            "Aim for 6-10 detailed bullets. Every bullet adds new information."
        )
    if cite:
        fmt += (
            "\n\nCITATION: After your complete answer add on a new line:\n"
            "Sources: [name the specific section, heading, chapter, or page "
            "where this information came from in the document]"
        )

    # ── Scope ─────────────────────────────────────────────────────────────────

    scope = (
        "Use ONLY the document text provided below. Do not use outside knowledge."
        if rag_on else
        "Use the document below as your main source. You may add brief general knowledge if helpful."
    )

    template = f"""{style}

{scope}{fmt}

Document:
{{context}}

Question: {{question}}
Answer:"""

    return PromptTemplate(
        template        = template,
        input_variables = ["context", "question"]
    )


# ── GENERATION PROMPTS FOR TABS ───────────────────────────────────────────────
# Single source of truth — all prompts defined in prompts.py
from prompts import (
    SUMMARY_PROMPT, KEYPOINTS_PROMPT, CONCEPTS_PROMPT, CONCEPTS_PROMPT_SIMPLE,
    QUIZ_PROMPT, FLASHCARD_PROMPT, EXAM_PROMPT, WHAT_ABOUT_PROMPT
)


# ── QA FUNCTION ───────────────────────────────────────────────────────────────
def ask_question(vectorstore, question, tags=None):
    if tags is None:
        tags = ["Teacher"]

    print(f"\n  Question : {question}")
    print(f"  Tags     : {tags}")

    llm = Ollama(
        model       = MODEL_NAME,
        temperature = 0.2,
        num_predict = 900,
        num_ctx     = 4096,
    )
    prompt   = build_prompt(tags)
    qa_chain = RetrievalQA.from_chain_type(
        llm                     = llm,
        chain_type              = "stuff",
        retriever               = vectorstore.as_retriever(search_kwargs={"k": 5}),
        return_source_documents = True,
        chain_type_kwargs       = {"prompt": prompt}
    )

    result = qa_chain.invoke({"query": question})
    print(f"\n  Answer:\n{result['result']}")
    print("\n  Sources:")
    for doc in result["source_documents"]:
        src  = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "")
        label = os.path.basename(src)
        if page != "":
            label += f" · p.{page + 1}"
        print(f"    {label}")

    return result


# ── CLI ENTRY POINT ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print(f"  LocalRAG Pipeline")
    print(f"  Model : {MODEL_NAME}")
    print(f"  Embed : {EMBED_MODEL}")
    print("=" * 50)

    if os.path.exists(CHROMA_FOLDER) and os.listdir(CHROMA_FOLDER):
        print("\nExisting index found — loading...")
        embedding   = OllamaEmbeddings(model=EMBED_MODEL)
        vectorstore = Chroma(
            persist_directory  = CHROMA_FOLDER,
            embedding_function = embedding
        )
        print("Index loaded.\n")
    else:
        print("\nNo index found — building from documents in data/...")
        docs = load_documents()
        if not docs:
            print("No documents loaded. Add files to data/ and try again.")
            exit(1)
        chunks      = split_documents(docs)
        vectorstore = create_vectorstore(chunks)
        print("Index built.\n")

    print("Tags you can use: Teacher, Technical, Chat, Summary, Bullet points, Cite sources")
    print("Default tag is Teacher. Type 'exit' to quit.\n")

    while True:
        question = input("Ask a question: ").strip()
        if question.lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        if not question:
            continue
        ask_question(vectorstore, question, tags=["Teacher"])