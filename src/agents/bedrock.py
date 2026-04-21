import boto3
from langchain_aws import ChatBedrock
from dotenv import load_dotenv

import os

load_dotenv()

bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-2")

llm_writer = ChatBedrock(
    model=os.environ.get("LLM_WRITER", ""),
    client=bedrock_client
)

llm_categorizer = ChatBedrock(
    model=os.environ.get("LLM_CATEGORIZER", ""),
    client=bedrock_client
)





