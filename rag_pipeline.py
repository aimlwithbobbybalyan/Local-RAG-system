from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader                                                                                                                                                                                                                                     
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OllamaEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.llms import Ollama
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate
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
    chunks=text_splitter.split_documents(documents)
    print(f" Total chunks created: {len(chunks)}")
    return chunks
# function 3 vectorstore() to convert chunk texts into vectors
def  create_vectorstore(chunks):
    print(f"creating embedding and storing it in Chroma_DB....")
    embedding = OllamaEmbeddings(model=EMBED_MODEL)
    vectorstore= Chroma.from_documents(
        documents=chunks,
        embedding=embedding,
        persist_directory=CHROMA_FOLDER
    )
    print(f"vectorstores created and saved in {CHROMA_FOLDER}folder")
    return vectorstore
def ask_question(vectorstore,question):
    print(f"\nQuestion:{question}")
    llm=Ollama(model=MODEL_NAME)
    prompt_template = """
    You are a helpful teacher who explains things clearly.
    Use the following information to answer the question.
    
    Always follow this structure when answering:
    
    1. DEFINITION
       Start with a simple one line definition
       of what is being asked
    
    2. SIMPLE EXPLANATION
       Explain it in simple everyday words
       Use real life examples
       Make anyone understand it
    
    3. TYPES or POINTS (if question asks for it)
       List them clearly one by one
       Explain each type simply with example
    
    4. SUMMARY
       End with one simple sentence
       summarizing the whole answer
    
    Rules:
    - Use simple everyday words
    - Always give real life examples
    - Avoid unnecessary technical words
    - Explain like teaching a friend
    
    Information: {context}
    
    Question: {question}
    
    Answer:
    """
    prompt=PromptTemplate(
        template=prompt_template,
        input_variables=["context","question"]

    )
    qa_chain = RetrievalQA.from_chain_type(
    llm=llm,
    chain_type="stuff",
    retriever= vectorstore.as_retriever(search_kwargs={"k":5}),
    return_source_documents=True,
    chain_type_kwargs={"prompt":prompt}

    )
    result=qa_chain.invoke({"query": question})
    print(f"\nAnswer: {result['result']}")
    print("\nSources:")
    for doc in result['source_documents']:
        print(f"{doc.metadata.get('source','unknown')}")
    return result
    
if __name__== "__main__":
    docs=load_documents()
    chunks=split_documents(docs)
    vectorstore=create_vectorstore(chunks)
    question=input("ask you  question:")
    ask_question(vectorstore,question)

 