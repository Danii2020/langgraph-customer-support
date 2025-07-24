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