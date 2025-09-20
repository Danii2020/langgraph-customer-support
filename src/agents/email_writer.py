from ..utils.rag_utils import get_retriever_tool
from ..prompts import EMAIL_WRITER_PROMPT
from ..state import Email
from .bedrock import llm_writer
from langchain_core.prompts import PromptTemplate

def _create_email_writer_chain(use_rag: bool, use_structured_output: bool):
    """Create an email writer chain with configurable RAG and structured output"""
    llm = llm_writer
    if use_rag:
        llm = llm.bind_tools([get_retriever_tool()])
    
    email_writer_prompt_template = PromptTemplate(
        template=EMAIL_WRITER_PROMPT,
        input_variables=["email_category", "email_content", "context"]
    )

    email_writer_chain = email_writer_prompt_template | llm

    if use_structured_output:
        email_writer_chain = email_writer_prompt_template | llm.with_structured_output(Email) # type: ignore
    
    return email_writer_chain

def query_or_email():
    """Create an email writer agent with RAG capabilities and raw output"""
    return _create_email_writer_chain(use_rag=True, use_structured_output=False)

def write_email_with_context():
    """Create an email writer agent with structured output (no RAG but context)"""
    return _create_email_writer_chain(use_rag=False, use_structured_output=True)