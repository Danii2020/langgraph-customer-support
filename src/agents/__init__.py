from .email_categorizer import categorize_email

AGENT_REGISTRY = {
    "email_categorizer": categorize_email()
}