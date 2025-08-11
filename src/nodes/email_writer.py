from ..agents import AGENT_REGISTRY
from ..state import GraphState, Email

def _get_email_data(state: GraphState):
    """Extract common email data from state"""

    current_email = state.get("current_email")
    category = state.get("email_category")

    if not current_email or not category:
        print("No email or category found in state")
        return "", ""
    body = current_email.body if isinstance(current_email, Email) else ""
    return body, category

def _process_email_writer_result(result, state: GraphState):
    """Process the result from email writer and update state"""

    state["messages"] = result
    state["email_response"] = result
    return state

def query_or_email_node(state: GraphState):
    """Email writer node with RAG capabilities and empty context"""

    email_data = _get_email_data(state)
    if not email_data[0]:
        state["email_response"] = ""
        return state

    body, category = email_data

    result = AGENT_REGISTRY["query_or_email"].invoke({
        "email_content": body,
        "email_category": category,
        "context": ""
    })

    return _process_email_writer_result(result=result, state=state)

def email_writer_with_context_node(state: GraphState):
    """Email writer node with context from message history and structured output"""

    email_data = _get_email_data(state)
    if not email_data[0]:
        state["email_response"] = ""
        return state
    
    body, category = email_data

    context = state.get("messages")[-1].content if state.get("messages") else ""

    result = AGENT_REGISTRY["email_writer_with_context"].invoke({
        "email_content": body,
        "email_category": category,
        "context": context
    })

    state["email_response"] = result
    return state