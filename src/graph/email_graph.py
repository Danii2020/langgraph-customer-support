from langgraph.graph import START, StateGraph, END
from langgraph.prebuilt import tools_condition, ToolNode
from ..utils.rag_utils import retriever_tool
from ..nodes import NODES
from ..state import GraphState

def should_use_rag(state: GraphState) -> str:
    """
    Conditional edge function that determines whether to use RAG based on email category.

    Returns:
        "with_rag" if the category is product_enquiry or customer_complaint
        "without_rag" for other categories
    """
    category = state.get("email_category", "")

    # Categories that require RAG
    rag_categories = ["product_enquiry", "customer_complaint"]

    if category in rag_categories:
        return "with_rag"
    return "without_rag"

class EmailSupportGraph:
    def __init__(self):
        workflow = StateGraph(GraphState)
        # Add nodes
        workflow.add_node("load_email", NODES["email_listener"])
        workflow.add_node("categorize_email", NODES["email_categorizer"])
        workflow.add_node("retrieve", ToolNode([retriever_tool]))
        workflow.add_node("query_or_email", NODES["query_or_email"])
        workflow.add_node("write_email_with_context", NODES["email_writer_with_context"])
        workflow.add_node("send_email", NODES["email_sender"])
        # Add edges
        workflow.add_edge(START, "load_email")
        workflow.add_edge("load_email", "categorize_email")
        workflow.add_edge("categorize_email", "query_or_email")

        # Conditional edge based on category
        workflow.add_conditional_edges(
            "query_or_email",
            tools_condition,
            {
                "tools": "retrieve",
                END: "write_email_with_context"
            }
        )
        workflow.add_edge("retrieve", "write_email_with_context")
        workflow.add_edge("write_email_with_context", "send_email")
        workflow.add_edge("send_email", END)

        self.graph = workflow.compile()

