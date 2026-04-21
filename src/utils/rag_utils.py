from langchain.tools.retriever import create_retriever_tool
from langchain_aws.retrievers import AmazonKnowledgeBasesRetriever
from dotenv import load_dotenv

import os

load_dotenv()

retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id=os.environ.get("KNOWLEDGE_BASE_ID", ""),
    retrieval_config={"vectorSearchConfiguration": {"numberOfResults": 4}},
    region_name=os.environ.get("AWS_REGION", "us-east-1"),
    min_score_confidence=0.5
)

retriever_tool = create_retriever_tool(
    retriever,
    "retrieve_prodcuts_and_services_information",
    "Search and return information about products or services."
)

def get_retriever_tool():
    return retriever_tool

