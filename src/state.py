from pydantic import BaseModel, Field
from typing_extensions import TypedDict

class Email(BaseModel):
    id: str = Field(..., description="Unique identifier of the email")
    subject: str = Field(..., description="Subject of the email")
    sender: str = Field(..., description="Sender email address")
    date: str = Field(..., description="Date when the email was sent")
    body: str = Field(..., description="Body content of the email")

class GraphState(TypedDict):
    current_email: Email | str
    email_category: str