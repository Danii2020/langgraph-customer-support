from src.agents.email_writer import write_email
from langchain_core.messages import AIMessage, ToolMessage

response = write_email().invoke({
    "email_category": "product_enquiry",
    "email_content": "Cuál es el precio del iPhone 15?"
})
breakpoint()
last_msg = response.messages[-1]

if isinstance(last_msg, ToolMessage):
    # The model *did* invoke a tool
    for call in last_msg.tool_calls:  # type: List[ToolCall]
        print("Tool requested:", call.tool_name)
        print("With input:", call.tool_input)
elif isinstance(last_msg, AIMessage) and last_msg.tool_calls:
    # In some versions, AIMessage itself may bear a .tool_calls list
    for call in last_msg.tool_calls:
        print("Tool requested:", call.tool_name)
else:
    print("No tools were called; pure LLM response:")
    print(last_msg.content)