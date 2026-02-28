"""PDF delivery service for sending purchased products via email."""

import os
import logging
from typing import Optional
from datetime import datetime

from app.services.product_store import get_product, get_product_path
from app.services.gmail_service import gmail_service

logger = logging.getLogger(__name__)


def deliver_pdf(
    email: str,
    name: str,
    product_key: str,
    session_id: Optional[str] = None
) -> bool:
    """
    Deliver a PDF product to a customer via email.
    
    Args:
        email: Customer email address
        name: Customer name
        product_key: Stripe price_id or product_id
        session_id: Stripe checkout session ID (for reference)
    
    Returns:
        True if delivery successful
    """
    logger.info(f"Starting PDF delivery: email={email}, product={product_key}")
    
    # Get product info
    product = get_product(product_key)
    if not product:
        logger.error(f"Product not found: {product_key}")
        return False
    
    product_name = product.get('name', 'Your Purchase')
    
    # Get PDF file path
    pdf_path = get_product_path(product_key)
    if not pdf_path:
        logger.error(f"PDF file not found for product: {product_key}")
        # Send email without attachment explaining the issue
        return send_error_email(email, product_name, "PDF file not found")
    
    # Read PDF content
    try:
        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()
    except Exception as e:
        logger.error(f"Failed to read PDF file: {e}")
        return send_error_email(email, product_name, "Could not read PDF file")
    
    # Prepare email
    subject = f"Your {product_name} is here!"
    
    text_body = f"""Hi {name or 'there'},

Thank you for your purchase!

Here's your copy of "{product_name}" attached to this email.

If you have any questions, just reply to this email.

Best,
Cal
CEO, CalAutobot

---
Order ID: {session_id or 'N/A'}
Delivered: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
"""
    
    html_body = f"""<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<p>Hi {name or 'there'},</p>

<p>Thank you for your purchase!</p>

<p>Here's your copy of <strong>"{product_name}"</strong> attached to this email.</p>

<p>If you have any questions, just reply to this email.</p>

<p>Best,<br>
Cal<br>
<em>CEO, CalAutobot</em></p>

<hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
<p style="font-size: 12px; color: #888;">
Order ID: {session_id or 'N/A'}<br>
Delivered: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
</p>
</body>
</html>
"""
    
    # Send email with attachment
    filename = os.path.basename(pdf_path)
    
    success = gmail_service.send_email(
        to=email,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=[{
            'filename': filename,
            'content': pdf_content,
            'mimetype': 'application/pdf',
        }]
    )
    
    if success:
        logger.info(f"PDF delivered successfully: {email} <- {filename}")
    else:
        logger.error(f"Failed to send delivery email to {email}")
    
    return success


def send_error_email(email: str, product_name: str, error: str) -> bool:
    """
    Send an email explaining delivery issues.
    
    Args:
        email: Customer email
        product_name: Product name
        error: Error description
    
    Returns:
        True if email sent
    """
    subject = f"Issue with your {product_name} delivery"
    
    text_body = f"""Hi there,

We encountered an issue delivering your "{product_name}" purchase.

Error: {error}

Our team has been notified and will send your PDF manually within 24 hours.

Sorry for the inconvenience!

Cal
CEO, CalAutobot
"""
    
    return gmail_service.send_email(
        to=email,
        subject=subject,
        text_body=text_body,
    )
