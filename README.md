# LangGraph Email Support Workflow with RAG 

A sophisticated email support system built with LangGraph that automatically categorizes incoming emails and generates intelligent responses using Retrieval-Augmented Generation (RAG) when needed.

## Features

- **Email Categorization**: Automatically classifies emails into categories (product_enquiry, customer_complaint, customer_feedback, unrelated)
- **Conditional RAG**: Uses vector database retrieval only for relevant categories (product_enquiry, customer_complaint)
- **Intelligent Response Generation**: Creates professional email responses with accurate company information
- **Error Handling**: Robust error handling for all components including vector database failures
- **Modular Architecture**: Clean separation of concerns with reusable components

## Architecture

```
Email Input → Categorization → Conditional RAG → Response Generation → Output
```

### Components

1. **Email Listener Node**: Loads and processes incoming emails
2. **Email Categorizer Node**: Classifies emails using AI
3. **Email Writer Node**: Generates responses with optional RAG context
4. **RAG Manager**: Handles vector database operations with ChromaDB
5. **Conditional Graph Logic**: Routes emails based on category

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd langgraph-gmail
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Add your OpenAI API key to .env
OPENAI_API_KEY=your_api_key_here
```

## Usage

### Basic Usage

Run the main workflow:
```bash
python main.py
```

### Comprehensive Testing

Test different email scenarios:
```bash
python test_workflow.py
```

### Custom Email Processing

```python
from src.graph.email_graph import EmailSupportGraph
from src.state import Email

# Create email
email = Email(
    id="custom_001",
    subject="Product Question",
    sender="customer@example.com",
    date="2024-01-15",
    body="What are your pricing plans?"
)

# Process through workflow
workflow = EmailSupportGraph()
result = workflow.graph.invoke({
    "current_email": email,
    "email_category": "",
    "email_response": None
})

print(f"Category: {result['email_category']}")
print(f"Response: {result['email_response']}")
```

## RAG Integration

### Vector Database

The system uses ChromaDB as the vector database with:
- **Embeddings**: OpenAI embeddings for semantic search
- **Sample Data**: Pre-populated with company information
- **Chunking**: Intelligent text splitting for optimal retrieval

### RAG Categories

RAG is automatically used for:
- `product_enquiry`: Retrieves product features, pricing, technical specs
- `customer_complaint`: Retrieves troubleshooting guides, support info

RAG is skipped for:
- `customer_feedback`: Direct response without additional context
- `unrelated`: Simple acknowledgment

### Customizing RAG Data

Update the sample data in `src/utils/rag_utils.py`:

```python
sample_data = [
    {
        "content": "Your company information here...",
        "metadata": {"type": "product", "category": "overview", "source": "docs"}
    }
]
```

## Error Handling

The system handles various error scenarios:

1. **Vector Database Unavailable**: Falls back to basic response generation
2. **No Relevant Information**: Acknowledges limitation and offers support
3. **RAG Tool Failures**: Logs errors and continues with available information
4. **Invalid Categories**: Validates input and provides appropriate fallbacks

## Configuration

### Environment Variables

- `OPENAI_API_KEY`: Required for AI model access
- `CHROMA_PERSIST_DIRECTORY`: Optional, defaults to `./chroma_db`

### Model Configuration

Update models in `src/agents/`:
- Email categorizer: `gpt-4o-mini`
- Email writer: `gpt-4o-mini`

### RAG Configuration

Adjust RAG parameters in `src/utils/rag_utils.py`:
- `chunk_size`: Text chunk size (default: 1000)
- `chunk_overlap`: Overlap between chunks (default: 200)
- `k`: Number of documents to retrieve (default: 3)

## Project Structure

```
langgraph-gmail/
├── main.py                 # Main workflow execution
├── test_workflow.py        # Comprehensive testing
├── requirements.txt        # Dependencies
├── src/
│   ├── agents/            # AI agents
│   │   ├── email_categorizer.py
│   │   ├── email_writer.py
│   │   └── __init__.py
│   ├── graph/             # LangGraph workflow
│   │   └── email_graph.py
│   ├── nodes/             # Graph nodes
│   │   ├── email_categorizer.py
│   │   ├── email_listener.py
│   │   ├── email_writer.py
│   │   └── __init__.py
│   ├── prompts/           # Prompt templates
│   │   ├── agents.py
│   │   └── __init__.py
│   ├── utils/             # Utilities
│   │   ├── gmail_utils.py
│   │   ├── rag_utils.py
│   │   └── __init__.py
│   ├── state.py           # State definitions
│   └── structured_outputs.py
└── README.md
```

## Testing

The system includes comprehensive tests for:

1. **Product Inquiries**: Tests RAG usage with pricing/feature questions
2. **Customer Complaints**: Tests RAG usage with technical issues
3. **Customer Feedback**: Tests direct response without RAG
4. **Unrelated Emails**: Tests basic acknowledgment

Run tests to verify all scenarios work correctly.

## Extending the System

### Adding New Categories

1. Update `EmailCategory` enum in `src/structured_outputs.py`
2. Add category to `should_use_rag` function in `src/graph/email_graph.py`
3. Update prompts in `src/prompts/agents.py`

### Adding New RAG Sources

1. Extend `RAGManager` in `src/utils/rag_utils.py`
2. Add new data sources to the vector database
3. Update retrieval logic as needed

### Custom Tools

Add new tools to the email writer agent:
1. Create tool function with `@tool` decorator
2. Add to agent in `src/agents/email_writer.py`
3. Update prompts to use new tools

## Performance Considerations

- **Caching**: ChromaDB persists data for faster subsequent queries
- **Chunking**: Optimized text splitting for better retrieval
- **Conditional Execution**: RAG only used when necessary
- **Error Recovery**: Graceful degradation on failures

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
