import os
import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from openai import OpenAI
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, HttpUrl, validator
import uuid
import tempfile

load_dotenv()

app = FastAPI(title="Article Downloader API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

class ArticleRequest(BaseModel):
    url: str
    email: str

    @validator('url')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError('URL must start with http:// or https://')
        return v

    @validator('email')
    def validate_email(cls, v):
        if '@' not in v or '.' not in v:
            raise ValueError('Invalid email format')
        return v

def create_pdf(content, output_path):
    doc = SimpleDocTemplate(output_path, pagesize=letter)
    styles = getSampleStyleSheet()
    story = []
    
    # Add content to PDF
    p = Paragraph(content, styles["Normal"])
    story.append(p)
    
    # Build PDF
    doc.build(story)

def send_email(sender_email, sender_password, recipient_email, subject, body, pdf_path):
    # Create message
    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = recipient_email
    msg['Subject'] = subject
    
    # Add body
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach PDF
    with open(pdf_path, 'rb') as f:
        pdf = MIMEApplication(f.read(), _subtype='pdf')
        pdf.add_header('Content-Disposition', 'attachment', filename='article.pdf')
        msg.attach(pdf)
    
    # Send email
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(sender_email, sender_password)
        smtp.send_message(msg)

def process_article(url: str) -> str:
    client = OpenAI()
    
    try:
        page = requests.get(url)
        page.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch article: {str(e)}")
    
    soup = BeautifulSoup(page.content, "html.parser")
    
    removed_tags = soup.find_all(lambda tag: tag.name in ['style','script', 'img', 'path'])
    
    for tag in removed_tags:
        tag.decompose()
    
    text_only = soup.get_text()
    
    try:
        response = client.responses.create(
            model="gpt-4",
            instructions="""
            I am going to pass you text from an articles website that I cleaned a little using beautiful soup. 
            Return only the article content and title in a clean format, clean any remaining html or anything else that doesn't belong. 
            If the article seems to be locked behind a login report that the content can't be accessed.
            """,
            input=text_only
        )
        return response.output_text
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process article content: {str(e)}")

@app.post("/process-article")
async def process_article_endpoint(request: ArticleRequest):
    # Get email credentials
    sender_email = os.getenv('EMAIL_USER')
    sender_password = os.getenv('EMAIL_PASSWORD')
    
    if not sender_email or not sender_password:
        raise HTTPException(
            status_code=500,
            detail="Email configuration is missing. Please set EMAIL_USER and EMAIL_PASSWORD in your .env file"
        )
    
    # Process the article
    article_content = process_article(request.url)
    
    # Create a temporary file for the PDF
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
        pdf_path = temp_file.name
    
    try:
        # Create PDF
        create_pdf(article_content, pdf_path)
        
        # Send email
        send_email(
            sender_email,
            sender_password,
            request.email,
            f"Article from {request.url}",
            "Please find the attached article.",
            pdf_path
        )
        
        return {"message": "Article has been processed and sent to your email!"}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process or send article: {str(e)}")
    
    finally:
        # Clean up the temporary PDF file
        if os.path.exists(pdf_path):
            os.unlink(pdf_path)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)







