from .email_categorizer import categorize_email
from .email_writer import query_or_email, write_email_with_context

AGENT_REGISTRY = {
    "email_categorizer": categorize_email(),
    "query_or_email": query_or_email(),
    "email_writer_with_context": write_email_with_context()
}