from langchain_community.document_loaders import PyPDFLoader, LextLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chain import RetrievalQA
import os
#config--------
DOCS_FOLDER ="data"
CHROMA_FOLDER ="chroma_db"
MODEL_NAME ="llama3.2:3b"
EMBED_MODEL ="llama3.2:3b"
CHUNK_SIZE =512
CHUNK_OVERLAP =50