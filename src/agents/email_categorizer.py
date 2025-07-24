from ..prompts import EMAIL_CATEGORIZER_PROMPT
from ..structured_outputs import CategorizerEmailOutput
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from dotenv import load_dotenv

load_dotenv()

def categorize_email():
    email_categorizer_prompt = PromptTemplate(
        template=EMAIL_CATEGORIZER_PROMPT,
        input_variables=["email"]
    )
    llm = ChatOpenAI(model="gpt-4o-mini")
    return email_categorizer_prompt | llm.with_structured_output(CategorizerEmailOutput)