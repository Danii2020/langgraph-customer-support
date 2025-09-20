from pydantic import BaseModel, Field
from typing_extensions import TypedDict, Annotated
from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

class Email(BaseModel):
    id: str = Field("", description="Unique identifier of the email")
    subject: str = Field(..., description="Subject of the email")
    sender: str = Field(..., description="Sender email address")
    date: str = Field(..., description="Date when the email was sent")
    body: str = Field(..., description="Body content of the email")
    message_id: str = Field("", description="Message identifier of the email")
    references: str = Field("", description="References of the email")
    thread_id: str = Field("", description="Thread identifier of the email")

class GraphState(TypedDict):
    current_email: Email | str
    email_category: str
    email_response: Email | str
    messages: Annotated[list[AnyMessage], add_messages]