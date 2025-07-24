from .email_categorizer import email_categorizer_node
from .email_listener import email_listener_node

NODES = {
    "email_listener": email_listener_node,
    "email_categorizer": email_categorizer_node
}