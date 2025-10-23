from langchain.tools.retriever import create_retriever_tool
from langchain_aws.retrievers import AmazonKnowledgeBasesRetriever
from dotenv import load_dotenv

load_dotenv()

retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id="EOYQCYSEAB",
    retrieval_config={"vectorSearchConfiguration": {"numberOfResults": 4}},
    region_name="us-east-2"
)

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_prodcuts_and_services_information",
    "Search and return information about products or services."
)

def get_retriever_tool():
    return retriever_tool

