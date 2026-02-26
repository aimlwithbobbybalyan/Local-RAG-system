from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
import os
#config--------
DOCS_FOLDER ="data"
CHROMA_FOLDER ="chroma_db"
MODEL_NAME ="llama3.2:3b"
EMBED_MODEL ="llama3.2:3b"
CHUNK_SIZE =512
CHUNK_OVERLAP =50
#creating function callled load documents to load_documents 
def load_documents():
    documents=[]
    if not os.path.exists(DOCS_FOLDER):
        os.makedir(DOCS_FOLDER)
        print(f"created {DOCS_FOLDER} folder. Add your documents there!")
        return documents
    for filename in os.listdir(DOCS_FOLDER):
        filepath = os.path.join(DOCS_FOLDER,filename)
        
        if filename.endswith(".pdf"):
            print(f"Loading PDF:{filename}")
            loader=PyPDFLoader(filepath)
            document.extend(loader.load())
        
        
        elif filename.endswith(".txt"):
            print(f"Loading TXT:{filename}")
            loader=TextLoader(filepath)
            document.extend(loader.load())
        
        elif filename.endswith(".docx"):
            print(f"Loading DOCX:{filename}")
            loader=Docx2txtLoader(filepath)
            document.extend(loader.load())

        else:
            print(f"sorry mate! {filename} is not supported yet. please upload pdf, word or txt files ")
    
    print(f"Total pages loaded: {len(documents)}")
    return documents