EMAIL_CATEGORIZER_TASK = """
Instructions:
    1. Review the provided email content thoroughly.
    2. Use the following rules to assign the correct category:
      - **product_enquiry**: When the email seeks information about a product feature, benefit, service, or pricing.
      - **customer_complaint**: When the email communicates dissatisfaction or a complaint.
      - **customer_feedback**: When the email provides feedback or suggestions regarding a product or service.
      - **unrelated**: When the email content does not match any of the above categories.
EMAIL CONTENT:
{email}

Notes:
    Base your categorization strictly on the email content provided; avoid making assumptions or overgeneralizing.
"""

GENERATE_RAG_QUERIES_TASK = """
Instructions:

1. Carefully read and analyze the email content provided.
2. Identify the main intent or problem expressed in the email.
3. Construct up to three concise, relevant questions that best represent the customer’s intent or information needs.
4. Include only relevant questions. Do not exceed three questions.
5. If a single question suffices, provide only that.

EMAIL CONTENT:
{email}

Notes:
    Focus exclusively on the email content to generate the questions; do not include unrelated or speculative information.
    Ensure the questions are specific and actionable for retrieving the most relevant answer.
    Use clear and professional language in your queries.
"""

EMAIL_WRITER_TASK = """
Instructions:
    1. Analyze the original email content and category
    2. If the category is is product_enquiry or customer_complaint, use the retriever tool to query to the vector db for information
    that might be relevant and add it to your context to write the best email possible. If the category is different DO NOT use the
    retriever.
    3. Craft a clear, professional subject line that reflects the response content
    4. Write a comprehensive email body that:
       - Acknowledges the customer's inquiry
       - Provides specific, accurate information
       - Addresses any concerns or questions raised
       - Offers next steps or additional support if needed
       - Maintains a helpful, professional tone
    5. Use the following structure to create the email:
        - id: The email id
        - subject: Subject of the email
        - sender: Sender email address (in this case, eedani116@gmail.com, make sure to use 
        Cellfone SA <eedani116@gmail.com>)
        - date: Date when the email was sent
        - body: Body content of the email

Guidelines:
    - Do not use your own knowledge if you are not sure about information about the product
    instead, rely on the retriever tool to query the database, for example, if the question
    is about an iPhone, use the tool and qeury to the db to search for reliable information.
    - If there is additional context retrieved from the knowledge base, use it to write the best
    email possible.
    - Be concise but thorough
    - Use clear, professional language
    - Avoid technical jargon unless necessary
    - Show empathy and understanding
    - Provide actionable information
    - If you don't have specific information, acknowledge the limitation and offer to connect
    them with the right team
    - Finally, don't use any personal name and phone number at the end of the email, for the name of
    the company use "Cellfone SA".
    - Make sure to write the email in Spanish, not English.

Original Email Category: {email_category}
Original Email Content: {email_content}
Additional context: {context}
"""

GENERATE_RAG_ANSWER_TASK = """

Instructions:
    1. Carefully read the question and the provided context.
    2. Analyze the context to identify relevant information that directly addresses the question.
    3. Formulate a clear and precise response based only on the context. Do not infer or assume information that is not explicitly stated.
    4. If the context does not contain sufficient information to answer the question, respond with: "I don't know."
    5. Use simple, professional language that is easy for users to understand.

Question:
    {question}

Context:
    {context}
Notes:
    Stay within the boundaries of the provided context; avoid introducing external information.
    If multiple pieces of context are relevant, synthesize them into a cohesive and accurate response.
    Prioritize user clarity and ensure your answers directly address the question without unnecessary elaboration.
"""