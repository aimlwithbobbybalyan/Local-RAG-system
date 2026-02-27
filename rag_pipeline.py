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
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50
#creating function callled load documents to load_documents 
def load_documents():
    documents=[]
    if not os.path.exists(DOCS_FOLDER):
        os.makedirs(DOCS_FOLDER)
        print(f"created {DOCS_FOLDER} folder. Add your documents there!")
        return documents
    for filename in os.listdir(DOCS_FOLDER):
        filepath = os.path.join(DOCS_FOLDER,filename)
        
        if filename.endswith(".pdf"):
            print(f"Loading PDF:{filename}")
            loader=PyPDFLoader(filepath)
            documents.extend(loader.load())
        
        
        elif filename.endswith(".txt"):
            print(f"Loading TXT:{filename}")
            loader=TextLoader(filepath)
            documents.extend(loader.load())
        
        elif filename.endswith(".docx"):
            print(f"Loading DOCX:{filename}")
            loader=Docx2txtLoader(filepath)
            documents.extend(loader.load())

        else:
            print(f"sorry mate! {filename} is not supported yet. please upload pdf, word or txt files ")
    
    print(f"Total pages loaded: {len(documents)}")
    return documents

def split_documents(documents):
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size= CHUNK_SIZE,
        chunk_overlap= CHUNK_OVERLAP
    )
    chunk=text_splitter.split_documents(documents)
    print(f" Total chunks created: {len(chunk)}")
    return chunk
# function 3 vectorstore() to convert chunk texts into vectors
def  create_vectorstore(chunk):
    print(f"creating embedding and storing it in Chroma_DB....")
    embedding = OllamaEmbeddings(model=EMBED_MODEL)
    vectorstore= Chroma.from_documents(
        documents=chunks,
        embedding=embedding,
        persist_directory=CHROMA_FOLDER
    )
    print(f"vectorstores created and saved in {CHROMA_FOLDER}folder")
if __name__== "__main__":
    docs=load_documents()
    chunks=split_documents(docs)
    vectorstore=create_vectorstore(chunks)