"""
prompts.py v2.0 — Optimised for speed + quality.
Changes from v1:
  - 4 quiz questions instead of 6  (faster, still covers key topics)
  - 4 flashcards instead of 6
  - 8 exam questions minimum instead of 12
  - Tighter prompt wording = less tokens wasted on format explanation
"""

SUMMARY_PROMPT = """You are an expert academic summarizer. Read the text carefully.

Use EXACTLY this format:
TITLE: [5-10 word descriptive title]
OVERVIEW: Write exactly 3 sentences.
  Sentence 1: Main subject, purpose, and scope.
  Sentence 2: ALL major topics, methods, and concepts covered.
  Sentence 3: Real-world importance and what reader will learn.

Rules:
- Mention every major topic in the overview.
- Do not start sentences with "This document".
- No opinions, no filler phrases.

Text: {context}
TITLE:"""


KEYPOINTS_PROMPT = """You are a study coach. Read the text and extract the 6 most important points.

Rules:
- Each point: COMPLETE SENTENCE of at least 12 words.
- Explain WHAT something is AND WHY it matters.
- Include facts or numbers from the text when available.
- Cover DIFFERENT topics.

Write EXACTLY:
POINTS:
- [complete sentence, 12+ words]
- [complete sentence, 12+ words]
- [complete sentence, 12+ words]
- [complete sentence, 12+ words]
- [complete sentence, 12+ words]
- [complete sentence, 12+ words]

Text: {context}
POINTS:"""


CONCEPTS_PROMPT = """Read the text and identify the 8 most important technical terms or concepts.

Rules:
- Only include terms that appear in the text.
- No generic words like "text", "document", "introduction".
- Prefer specific technical terms.

Write ONLY this single line:
TERMS: term1, term2, term3, term4, term5, term6, term7, term8

Text: {context}
TERMS:"""

CONCEPTS_PROMPT_SIMPLE = CONCEPTS_PROMPT
WHAT_ABOUT_PROMPT = SUMMARY_PROMPT


QUIZ_PROMPT = """You are a university professor. Write exactly 4 multiple choice questions.

Rules:
- Mix question types: Definition, How it works, Application, Cause-effect.
- Test UNDERSTANDING not memorization.
- Wrong options must be plausible.
- Cover DIFFERENT topics.

Use EXACTLY this format:
###
Q: [question]
A: [option]
B: [option]
C: [option]
D: [option]
ANSWER: [letter]
EXPLAIN: [one sentence: why correct answer is right]

Repeat ### block exactly 4 times.

Text: {context}
###"""


FLASHCARD_PROMPT = """Create exactly 4 study flashcards.

Rules:
- QUESTION must be specific and exam-quality.
- ANSWER: 2 sentences — (1) direct answer, (2) why it matters.
- Cover DIFFERENT topics.

Use EXACTLY this format:
###
Q: [exam-quality question]
A: [2 sentence answer]

Repeat ### block exactly 4 times.

Text: {context}
###"""


EXAM_PROMPT = """You are a university examiner. Generate exam questions from the text below.

Write exactly 8 numbered questions. Start easy, end hard.
Put the difficulty in brackets after the number.

Example format:
1. [Easy] Define the main concept discussed in the text.
2. [Easy] What are the key components mentioned?
3. [Medium] Explain how the process works step by step.
4. [Medium] Why is this topic important in real life?
5. [Medium] Compare and contrast the two approaches described.
6. [Hard] Analyse the cause and effect relationships in the text.
7. [Hard] How would you apply these concepts to solve a problem?
8. [Hard] Evaluate the advantages and limitations described.

Now generate 8 questions from this text:

Text: {context}

Questions:
1."""