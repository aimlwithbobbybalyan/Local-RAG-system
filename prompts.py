"""
prompts.py — Single source of truth for all LLM prompts.
Import from here in both app.py and rag_pipeline.py.
Never define prompts in two places — update here and both files stay in sync.
"""

SUMMARY_PROMPT = """You are an expert academic summarizer. Read the ENTIRE text carefully from start to finish. Your job is to produce a title and overview that captures EVERY major topic, concept, and section in the text — nothing should be left out.

Use EXACTLY this format, no extra text, no preamble:
TITLE: [a clear descriptive title of 5-10 words that reflects the full scope of the document]
OVERVIEW: Write exactly 3 sentences that together cover the WHOLE document.
  Sentence 1: State the main subject, purpose, and scope of this document.
  Sentence 2: List ALL the major topics, methods, components, and concepts covered — do not skip any.
  Sentence 3: Explain the real-world importance of this subject and what a reader will understand after studying it.

Critical rules:
- The OVERVIEW must mention every major topic found in the text, not just the first one or the most obvious one.
- If the text covers 5 topics, all 5 must appear somewhere in the overview.
- Do not start sentences with "This document" — vary your openings.
- Write factually. No opinions. No filler phrases like "In conclusion".

Text: {context}
TITLE:"""


KEYPOINTS_PROMPT = """You are a senior study coach preparing a student for a university exam. Read the ENTIRE text and extract the 8 most important points a student absolutely must understand.

Rules for every point:
- Write a COMPLETE SENTENCE of at least 15 words.
- Explain WHAT something is AND HOW it works or WHY it matters.
- Include facts, numbers, or examples from the text whenever available.
- Cover DIFFERENT topics — never write two points about the same concept.

Write in EXACTLY this format:
POINTS:
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]
- [complete sentence with explanation, at least 15 words]

Text: {context}
POINTS:"""


CONCEPTS_PROMPT = """Read the text carefully and identify the 10 most important technical terms, concepts, methods, or topics that a student must know to understand this subject.

Selection rules:
- Only include terms that actually appear and are explained or used in the text.
- Include a balanced mix: key definitions, named algorithms or methods, important processes, and core ideas.
- Do NOT include generic words like "text", "document", "example", "introduction", "conclusion".
- Prefer specific technical terms over vague category names.

Write ONLY this single line:
TERMS: term1, term2, term3, term4, term5, term6, term7, term8, term9, term10

Text: {context}
TERMS:"""

# Alias used in some routes
CONCEPTS_PROMPT_SIMPLE = CONCEPTS_PROMPT
WHAT_ABOUT_PROMPT = SUMMARY_PROMPT


QUIZ_PROMPT = """You are a university professor writing a high-quality multiple choice exam. Read the text carefully and write exactly 6 exam questions based ONLY on the content in this text.

Rules:
- Use a MIX of question types: Definition, How it works, Comparison, Application, Cause and effect.
- Every question must test UNDERSTANDING, not just memorization.
- Wrong answer options must be PLAUSIBLE.
- Cover DIFFERENT topics — never write 2 questions about the same concept.
- EXPLAIN must say why the correct answer is right AND why the most tempting wrong answer is wrong.

Use EXACTLY this format:
###
Q: [question text]
A: [option one]
B: [option two]
C: [option three]
D: [option four]
ANSWER: [correct letter A, B, C, or D]
EXPLAIN: [one sentence: why correct answer is right AND why the main wrong option is wrong]

Repeat the ### block exactly 6 times.

Text: {context}
###"""


FLASHCARD_PROMPT = """You are creating professional study flashcards for a university student. Create exactly 6 flashcards covering the most important concepts across the WHOLE text.

Rules:
- The QUESTION must be specific and focused on ONE concept — exam-quality, not trivial.
- The ANSWER must be 2-3 complete sentences: (1) directly answer, (2) explain the mechanism, (3) include a real example.
- Cover DIFFERENT topics — never make 2 cards about the same concept.

Use EXACTLY this format:
###
Q: [specific, exam-quality question]
A: [2-3 sentence answer with explanation and example]

Repeat the ### block exactly 6 times.

Text: {context}
###"""


EXAM_PROMPT = """You are a university examiner. Read the ENTIRE text and generate every important exam question a student must prepare. Cover every topic, concept, definition, process, and application.

Include ALL of these question types:
- DEFINE, EXPLAIN, DIFFERENCE/COMPARE, WHY, HOW, LIST, APPLY, CAUSE-EFFECT

Rules:
- Generate at least 12 questions, more if the text covers many topics.
- Every important topic must appear in at least one question.
- Order questions from foundational (Easy) to advanced (Hard).
- Mark difficulty after each number.

Write in EXACTLY this format:
QUESTIONS:
1. [Easy] [question]
2. [Easy] [question]
3. [Medium] [question]
...continue until ALL topics are covered

Text: {context}
QUESTIONS:"""