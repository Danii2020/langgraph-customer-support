from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from ..state import Email
import os
import base64
import datetime
import email.mime.text
import email.mime.multipart
from email.mime.text import MIMEText
import uuid

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify'
]

def get_gmail_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('gmail', 'v1', credentials=creds)

def parse_email_message(message) -> Email:
    """
    Extracts email data from a Gmail API message resource.
    Returns a dict with id, subject, sender, date, and body.
    """
    headers_list = message.get('payload', {}).get('headers', [])
    headers = {header['name'].lower(): header['value'] for header in headers_list}
    subject = headers.get('subject', 'No Subject')
    sender = headers.get('from', 'No Sender')
    date = headers.get('date', 'No Date')
    message_id = headers.get("message-id")
    references = headers.get("references", "")
    body = ''
    payload = message.get('payload', {})
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain':
                body = part.get('body', {}).get('data', '')
                break
    else:
        body = payload.get('body', {}).get('data', '')
    if body:
        try:
            body = base64.urlsafe_b64decode(body).decode('utf-8')
        except Exception:
            body = ''
    return Email(
        id=message["id"],
        subject=subject,
        sender=sender,
        date=date,
        body=body,
        message_id=message_id,
        references=references,
        thread_id=message["threadId"]
    )

def get_most_recent_email() -> Email | str:
    service = get_gmail_service()
    today = datetime.datetime.now().date()
    query = f'after:{today.strftime("%Y/%m/%d")}' # after:18/07/2025
    try:
        results = service.users().messages().list(userId='me', q=query, maxResults=1).execute()
        email_message_data = results.get('messages', [])[0]
        if not email_message_data:
            return ""
        message = service.users().messages().get(userId='me', id=email_message_data['id']).execute()
        return parse_email_message(message=message)
    except Exception as error:
        print(f'An error occurred: {error}')
        return ""

def send_reply_email(original_email: Email, reply_email: Email) -> bool:
    """
    Send a reply email to the original sender that will appear as a threaded reply.
    
    Args:
        original_email: The original Email object to reply to
        reply_email: The Email object containing the reply content
    
    Returns:
        bool: True if email was sent successfully, False otherwise
    """
    try:
        service = get_gmail_service()
        
        # Extract sender email from original email
        sender_email = original_email.sender
        if '<' in sender_email and '>' in sender_email:
            sender_email = sender_email.split('<')[1].split('>')[0]
        
        print(f"Reply will be sent to: {sender_email}")
        
        # Use the subject from the reply email, or create a "Re:" subject if needed
        reply_subject = reply_email.subject
        if not reply_subject.startswith('Re:'):
            # Check if the original subject already has "Re:" to avoid duplication
            original_subject = original_email.subject
            if original_subject.startswith('Re:'):
                # Original already has "Re:", use it as is
                reply_subject = original_subject
            else:
                # Add "Re:" prefix to original subject
                reply_subject = f"Re: {original_subject}"
        
        # Use Message-ID and References from the original email object
        message_id = original_email.message_id
        references = original_email.references
        thread_id = original_email.thread_id
        
        # If no Message-ID found, create one based on the Gmail message ID
        if not message_id:
            message_id = f"<{original_email.id}@gmail.com>"
        
        # Create the reply message with proper threading
        message = create_reply_message_with_thread(
            to=sender_email,
            subject=reply_subject,
            message_text=reply_email.body,
            original_message_id=message_id,
            original_references=references,
            thread_id=thread_id
        )
        
        # Send the email with thread ID
        sent_message = service.users().messages().send(userId='me', body=message).execute()
        
        print(f"Threaded reply email sent successfully. Message ID: {sent_message['id']}")
        return True
        
    except Exception as error:
        print(f'An error occurred while sending reply email: {error}')
        return False

def create_message(to: str, subject: str, message_text: str) -> dict:
    """
    Create a message for an email.
    
    Args:
        to: Email address of the recipient
        subject: The subject of the email message
        message_text: The text of the email message
    
    Returns:
        An object containing a base64url encoded email object
    """
    message = MIMEText(message_text)
    message['to'] = to
    message['subject'] = subject
    
    # Encode the message in base64url format
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    return {'raw': raw_message}

def create_reply_message_with_thread(to: str, subject: str, message_text: str, original_message_id: str, original_references: str = None, thread_id: str = None) -> dict:
    """
    Create a reply message that will appear as a threaded reply with proper thread ID.
    
    Args:
        to: Email address of the recipient
        subject: The subject of the email message
        message_text: The text of the email message
        original_message_id: The Message-ID of the original email
        original_references: The References header from the original email (optional)
        thread_id: The thread ID to associate the reply with
    
    Returns:
        An object containing a base64url encoded email object with thread ID
    """
    message = MIMEText(message_text)
    message['to'] = to
    message['subject'] = subject
    
    # Set threading headers
    if original_message_id:
        message['In-Reply-To'] = original_message_id
        # Combine existing references with the original message ID
        if original_references:
            references = f"{original_references} {original_message_id}".strip()
        else:
            references = original_message_id
        message['References'] = references
        
        # Generate a new Message-ID for this reply
        message['Message-ID'] = f"<{uuid.uuid4()}@gmail.com>"
    
    # Construct email body with thread ID
    body = {
        'raw': base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    }
    
    # Add thread ID if available
    if thread_id:
        body['threadId'] = thread_id
    
    return body    
