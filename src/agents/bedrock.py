import boto3
from langchain_aws import ChatBedrock
from dotenv import load_dotenv

load_dotenv()

bedrock_client = boto3.client("bedrock-runtime", region_name="us-east-2")

llm_writer = ChatBedrock(
    model="us.anthropic.claude-3-5-sonnet-20240620-v1:0",
    client=bedrock_client
)

llm_categorizer = ChatBedrock(
    model="us.amazon.nova-micro-v1:0",
    client=bedrock_client
)





