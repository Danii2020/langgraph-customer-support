import boto3
import os
from langchain_aws import ChatBedrock
from dotenv import load_dotenv

load_dotenv()

bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-2")

llm_writer = ChatBedrock(
    model=os.getenv("LLM_WRITER", ""),
    client=bedrock_client
)

llm_categorizer = ChatBedrock(
    model=os.getenv("LLM_CATEGORIZER", ""),
    client=bedrock_client
)





