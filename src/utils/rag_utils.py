from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain.tools.retriever import create_retriever_tool
from dotenv import load_dotenv

load_dotenv()

loader = TextLoader("src/data/data.txt")
documents = loader.load()
text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    chunk_size=100, chunk_overlap=50    
)
doc_splits = text_splitter.split_documents(documents)
breakpoint()

vectorestore = Chroma.from_documents(documents=doc_splits, embedding=OpenAIEmbeddings(), persist_directory="./chroma_db")

retriever = vectorestore.as_retriever(search_kwargs={"k": 3})

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_products_services_information",
    "Search and return information about products or services.",
)

def get_rag_tool():
    return retriever_tool

