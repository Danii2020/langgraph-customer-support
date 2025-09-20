from ..prompts import EMAIL_CATEGORIZER_PROMPT
from ..structured_outputs import CategorizerEmailOutput
from .bedrock import llm_categorizer
from langchain_core.prompts import PromptTemplate

def categorize_email():
    email_categorizer_prompt = PromptTemplate(
        template=EMAIL_CATEGORIZER_PROMPT,
        input_variables=["email"]
    )
    return email_categorizer_prompt | llm_categorizer.with_structured_output(CategorizerEmailOutput)