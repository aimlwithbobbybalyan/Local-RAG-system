from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
import os

# config
DOCS_FOLDER   = "data"
CHROMA_FOLDER = "chroma_db"
MODEL_NAME    = "llama3.2:1b"
EMBED_MODEL   = "nomic-embed-text"
CHUNK_SIZE    = 512
CHUNK_OVERLAP = 50


def load_documents():
    documents = []
    if not os.path.exists(DOCS_FOLDER):
        os.makedirs(DOCS_FOLDER)
        print(f"created {DOCS_FOLDER} folder. Add your documents there!")
        return documents
    #documents uploading limit 
    files = [f for f in os.listdir(DOCS_FOLDER)
             if f.endswith((".pdf", ".txt", ".docx", ".md"))]
    if len(files) > 3:
        print("⚠️ Maximum 3 documents allowed at a time!")
        print(f"You have {len(files)} files. Please remove some from data/ folder.")
        return documents
    for filename in os.listdir(DOCS_FOLDER):
        filepath = os.path.join(DOCS_FOLDER, filename)
        if filename.endswith(".pdf"):
            print(f"Loading PDF: {filename}")
            loader = PyPDFLoader(filepath)
            documents.extend(loader.load())
        elif filename.endswith(".txt"):
            print(f"Loading TXT: {filename}")
            loader = TextLoader(filepath)
            documents.extend(loader.load())
        elif filename.endswith(".docx"):
            print(f"Loading DOCX: {filename}")
            loader = Docx2txtLoader(filepath)
            documents.extend(loader.load())
        else:
            print(f"sorry mate! {filename} is not supported yet.")
    print(f"Total pages loaded: {len(documents)}")
    return documents


def split_documents(documents):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size    = CHUNK_SIZE,
        chunk_overlap = CHUNK_OVERLAP
    )
    chunks = text_splitter.split_documents(documents)
    print(f"Total chunks created: {len(chunks)}")
    return chunks


def create_vectorstore(chunks):
    print(f"creating embedding and storing it in Chroma_DB....")
    embedding = OllamaEmbeddings(model=EMBED_MODEL)
    vectorstore = Chroma.from_documents(
        documents         = chunks,
        embedding         = embedding,
        persist_directory = CHROMA_FOLDER
    )
    print(f"vectorstores created and saved in {CHROMA_FOLDER} folder")
    return vectorstore


# picks the right prompt based on which tag is active in the UI
def build_prompt(tags):

    # --- style tags ---

    if "Teacher" in tags:
        template = """You are a helpful teacher. Use the context to answer.

Context: {context}

Question: {question}

Answer in this structure:
1. DEFINITION: Simple 2-3 line definition
2. EXPLANATION: Explain with a real life example
3. KEY POINTS: List main points clearly
4. SUMMARY: One sentence that wraps it all up

Simple words only. Real examples. No jargon.

Answer:"""

    elif "Technical" in tags:
        template = """You are a technical expert. Use the context to answer.

Context: {context}

Question: {question}

Answer in this structure:
1. DEFINITION: Exact technical definition
2. HOW IT WORKS: Technical mechanism or process
3. TYPES or PARAMETERS: List with technical detail
4. APPLICATIONS: Real world uses

Use correct technical terms. Be precise and detailed.

Answer:"""

    elif "Chat" in tags:
        template = """Use the context to answer the question naturally.

Context: {context}

Question: {question}

Answer like a helpful friend — casual, clear and short.
No headings needed. Just explain it simply.

Answer:"""

    elif "Bullet points" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Answer using bullet points only:
• What it is (1 line)
• Key point 1
• Key point 2
• Key point 3
• Key point 4
• Key point 5
Summary: one sentence

Keep each bullet short and clear.

Answer:"""

    elif "Summary" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Give a focused summary answer:
MAIN IDEA: (1 sentence)
KEY POINTS: (3-4 most important things)
TAKEAWAY: (1 sentence)

Be concise. Only the most important information.

Answer:"""

    elif "Cite sources" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Answer clearly, then at the end add:
SOURCE REFERENCE: which part of the document this came from.

Answer:"""

    # --- welcome screen chips ---

    elif "Explain simply" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Explain this as simply as possible.
Imagine explaining to a 15 year old.
Use everyday words and one real life example.
Maximum 5 lines.

Answer:"""

    elif "Quick summary" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Give a quick summary in this exact format:
MAIN IDEA: (1 sentence)
POINT 1: (1 sentence)
POINT 2: (1 sentence)
POINT 3: (1 sentence)
POINT 4: (1 sentence)
POINT 5: (1 sentence)

Answer:"""

    elif "Key points" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

List the most important key points:
KEY POINT 1: (one clear sentence)
KEY POINT 2: (one clear sentence)
KEY POINT 3: (one clear sentence)
KEY POINT 4: (one clear sentence)
KEY POINT 5: (one clear sentence)

Answer:"""

    # --- prompt suggestion chips ---

    elif "Summarize" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Summarize this document:
WHAT IT IS: (1 sentence)
MAIN TOPICS: (list 3-4 topics)
KEY TAKEAWAYS: (3 most important things)
ONE LINE SUMMARY: (final sentence)

Answer:"""

    elif "Main topics" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

List the main topics covered:
TOPIC 1: (name + 1 sentence)
TOPIC 2: (name + 1 sentence)
TOPIC 3: (name + 1 sentence)
TOPIC 4: (name + 1 sentence)

Answer:"""

    elif "Key definitions" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

List important definitions from this document:
TERM 1: simple definition
TERM 2: simple definition
TERM 3: simple definition
TERM 4: simple definition
TERM 5: simple definition

Answer:"""

    elif "5 key points" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Give exactly 5 key points to remember:
1. (specific and clear)
2. (specific and clear)
3. (specific and clear)
4. (specific and clear)
5. (specific and clear)

Answer:"""

    elif "Exam questions" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

List important exam questions from this topic:
Q1: (likely exam question)
Q2: (likely exam question)
Q3: (likely exam question)
Q4: (likely exam question)
Q5: (likely exam question)

Focus on questions that test understanding.

Answer:"""

    elif "Compare concepts" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Compare the main concepts:
CONCEPT 1: (name + brief description)
CONCEPT 2: (name + brief description)
SIMILARITIES: (what they share)
DIFFERENCES: (how they differ)
WHEN TO USE EACH: (practical difference)

Answer:"""

    elif "Revision notes" in tags:
        template = """Use the context to answer the question.

Context: {context}

Question: {question}

Short revision notes:
TOPIC: (what this is about)
MUST KNOW:
• (most important point)
• (second important point)
• (third important point)
• (fourth important point)
REMEMBER: (one sentence — the most critical thing)

Answer:"""

    # default fallback
    else:
        template = """You are a helpful teacher. Use the context to answer.

Context: {context}

Question: {question}

Answer clearly:
1. DEFINITION: Simple 2-3 line definition
2. EXPLANATION: Explain with a real life example
3. KEY POINTS: Main points clearly listed
4. SUMMARY: One sentence summary

Answer:"""

    return PromptTemplate(
        template        = template,
        input_variables = ["context", "question"]
    )


# --- prompts for Summary, Quiz, Flashcard, Concepts tabs ---
# these are used directly in app.py, not through build_prompt()

SUMMARY_PROMPT = """Read this document and create a summary.

Text: {context}

Return ONLY this JSON:
{{
  "overview": "2-3 sentence overview of this document",
  "key_points": [
    "Most important point",
    "Second important point",
    "Third important point",
    "Fourth important point",
    "Fifth important point"
  ],
  "concepts": ["Concept1", "Concept2", "Concept3", "Concept4", "Concept5", "Concept6"]
}}"""


QUIZ_PROMPT = """Read this text and create 5 multiple choice questions.

Text: {context}

Return ONLY this JSON:
{{
  "questions": [
    {{
      "question": "Question here?",
      "options": ["A. option", "B. option", "C. option", "D. option"],
      "correct": 1
    }}
  ]
}}

correct = index of correct answer (0=A 1=B 2=C 3=D)"""


FLASHCARD_PROMPT = """Read this text and create 6 flashcards.

Text: {context}

Return ONLY this JSON:
{{
  "cards": [
    {{
      "question": "Short question?",
      "answer": "Short answer in 1-2 sentences."
    }}
  ]
}}"""


CONCEPTS_PROMPT = """Read this text and extract the most important concepts.

Text: {context}

Return ONLY this JSON:
{{
  "concepts": ["Concept1", "Concept2", "Concept3", "Concept4", "Concept5", "Concept6", "Concept7", "Concept8"]
}}

Each concept must be 1-3 words only."""


WHAT_ABOUT_PROMPT = """Read this document and answer what it is about.

Text: {context}

Answer in this structure:
TOPIC: What this document is about (1 line)
COVERS: Main subjects it explains (3-4 lines)
PURPOSE: Why this topic is important (1-2 lines)

Answer:"""


def ask_question(vectorstore, question, tags=None):
    if tags is None:
        tags = ["Teacher"]

    print(f"\nQuestion: {question}")
    print(f"Active tags: {tags}")

    llm    = Ollama(model=MODEL_NAME)
    prompt = build_prompt(tags)

    qa_chain = RetrievalQA.from_chain_type(
        llm                     = llm,
        chain_type              = "stuff",
        retriever               = vectorstore.as_retriever(search_kwargs={"k": 4}),
        return_source_documents = True,
        chain_type_kwargs       = {"prompt": prompt}
    )

    result = qa_chain.invoke({"query": question})

    print(f"\nAnswer: {result['result']}")
    print("\nSources:")
    for doc in result['source_documents']:
        print(f"{doc.metadata.get('source', 'unknown')}")

    return result


if __name__ == "__main__":
    if os.path.exists(CHROMA_FOLDER) and os.listdir(CHROMA_FOLDER):
        print("✅ Found existing index — skipping document loading!")
        embedding = OllamaEmbeddings(model=EMBED_MODEL)
        vectorstore = Chroma(
            persist_directory  = CHROMA_FOLDER,
            embedding_function = embedding
        )
        print("✅ Index loaded!\n")
    else:
        print("⏳ First time — building index...")
        docs        = load_documents()
        chunks      = split_documents(docs)
        vectorstore = create_vectorstore(chunks)

    while True:
        question = input("\nAsk your question (or type 'exit' to quit): ").strip()
        if question.lower() == "exit":
            print("Goodbye!")
            break
        if question == "":
            print("Please type a question!")
            continue
        ask_question(vectorstore, question) 