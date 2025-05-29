import re
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from io import BytesIO
import re
from datetime import datetime

def clean_input(input: str) -> str:
    """Clean the code input by removing special tokens and unwanted text"""
    # Remove special tokens
    input = re.sub(r'<\|eom_id\|>', '', input)
    input = re.sub(r'<\|eot_id\|>', '', input)
    input = re.sub(r'<\|.*?\|>', '', input)  # Remove any other special tokens

    # Remove any trailing newlines or whitespace
    input = input.strip()

    # Remove any text after common stop patterns
    stop_patterns = [
        'Observation:',
        'Human:',
        'Assistant:',
        'Thought:',
        'Action:',
        'Action Input:'
    ]

    for pattern in stop_patterns:
        if pattern in input:
            input = input.split(pattern)[0].strip()

    return input

def prepare_pdf_content(pdf_content: str):
    """
    Format LLM output to PDF content with proper Markdown conversion
    """
    # Remove special tokens first
    if "<|eot_id|>" in pdf_content:
        pdf_content = pdf_content.split("<|eot_id|>")[0]

    if "<|eom_id|>" in pdf_content:
        pdf_content = pdf_content.split("<|eom_id|>")[0]

    # Remove "Human:" and everything after it
    if "Human:" in pdf_content:
        pdf_content = pdf_content.split("Human:")[0].strip()

    # Process content line by line
    formatted_lines = []
    lines = pdf_content.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Handle Markdown headers
        if line.startswith('###'):
            # Level 3 header
            clean_line = line.replace('###', '').strip()
            formatted_lines.append(('subheading', clean_line))
        elif line.startswith('##'):
            # Level 2 header
            clean_line = line.replace('##', '').strip()
            formatted_lines.append(('heading', clean_line))
        elif line.startswith('#'):
            # Level 1 header
            clean_line = line.replace('#', '').strip()
            formatted_lines.append(('title', clean_line))
        # Handle bold text (markdown-style)
        elif '**' in line:
            # Replace markdown bold with HTML bold
            clean_line = line.replace('**', '<b>', 1)
            clean_line = clean_line.replace('**', '</b>', 1)
            formatted_lines.append(('body', clean_line))
        # Handle bullet points
        elif line.startswith('- '):
            clean_line = f"• {line[2:]}"
            formatted_lines.append(('body', clean_line))
        # Handle numbered lists
        elif re.match(r'^\d+\.', line):
            formatted_lines.append(('body', line))
        # Regular content
        else:
            formatted_lines.append(('body', line))

    return formatted_lines

def create_pdp_pdf(pdp_content: str, career_goal: str, target_date: str, filename: str) -> BytesIO:
    """
    Create a formatted PDF from PDP content
    """
    buffer = BytesIO()

    # Create PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18
    )

    # Get styles
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        textColor=HexColor('#2E86AB'),
        alignment=1  # Center alignment
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        spaceBefore=20,
        textColor=HexColor('#A23B72'),
        leftIndent=0
    )

    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading3'],
        fontSize=14,
        spaceAfter=8,
        spaceBefore=12,
        textColor=HexColor('#F18F01'),
        leftIndent=20
    )

    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontSize=11,
        spaceAfter=6,
        leftIndent=20,
        rightIndent=20
    )

    # Build PDF content
    story = []

    # Title
    story.append(Paragraph("Personal Development Plan", title_style))
    story.append(Spacer(1, 20))

    # Header information
    story.append(Paragraph(f"<b>Career Goal:</b> {career_goal}", body_style))
    story.append(Paragraph(f"<b>Target Date:</b> {target_date}", body_style))
    story.append(Paragraph(f"<b>Generated on:</b> {datetime.now().strftime('%B %d, %Y')}", body_style))
    story.append(Spacer(1, 20))

    # Process PDP content using prepare_pdf_content
    formatted_content = prepare_pdf_content(pdp_content)
    
    for content_type, line in formatted_content:
        if content_type == 'title':
            story.append(Paragraph(line, title_style))
        elif content_type == 'heading':
            story.append(Paragraph(line, heading_style))
        elif content_type == 'subheading':
            story.append(Paragraph(line, subheading_style))
        else:  # body
            story.append(Paragraph(line, body_style))

    # Build file
    doc.build(story)
    buffer.seek(0)
    return buffer