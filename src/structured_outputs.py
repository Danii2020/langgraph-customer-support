from pydantic import BaseModel, Field
from enum import Enum

class EmailCategory(str, Enum):
    product_enquiry = "product_enquiry"
    customer_complaint = "customer_complaint"
    customer_feedback = "customer_feedback"
    unrelated = "unrelated"

class CategorizerEmailOutput(BaseModel):
    category: EmailCategory = Field(..., description="The category assigned to the email, indicating its type based on predefined rules.")

class EmailWriterOutput(BaseModel):
    subject: str = Field(..., description="Subject line for the response email")
    body: str = Field(..., description="Body content of the response email")