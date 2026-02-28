"""Stripe webhook for handling payment events and triggering PDF delivery."""

import logging
import os
from flask import Blueprint, request, jsonify
from app.services.pdf_delivery import deliver_pdf

logger = logging.getLogger(__name__)

stripe_webhook = Blueprint('stripe_webhook', __name__)

# Stripe webhook secret from environment
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

try:
    import stripe
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')
except ImportError:
    logger.warning("Stripe library not installed. Webhook will not function.")
    stripe = None


@stripe_webhook.route('/webhook/stripe', methods=['POST'])
def handle_stripe_webhook():
    """Handle incoming Stripe webhook events."""
    if stripe is None:
        logger.error("Stripe library not available")
        return jsonify({'error': 'Stripe not configured'}), 500
    
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature', '')
    
    # Verify webhook signature
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {e}")
        return jsonify({'error': 'Invalid signature'}), 400
    
    # Handle the event
    event_type = event['type']
    
    if event_type == 'checkout.session.completed':
        session = event['data']['object']
        handle_checkout_completed(session)
    else:
        logger.info(f"Unhandled event type: {event_type}")
    
    return jsonify({'status': 'success'}), 200


def handle_checkout_completed(session):
    """Process a completed checkout session."""
    customer_email = session.get('customer_details', {}).get('email')
    customer_name = session.get('customer_details', {}).get('name', 'Customer')
    
    # Get the price/product ID from the session
    price_id = None
    product_id = None
    
    # Check metadata first (custom approach)
    metadata = session.get('metadata', {})
    product_key = metadata.get('product_key')
    
    # If not in metadata, we need to fetch line items
    if not product_key and stripe:
        try:
            line_items = stripe.checkout.Session.list_line_items(session['id'])
            if line_items.data:
                price_id = line_items.data[0].price.id
        except Exception as e:
            logger.error(f"Failed to fetch line items: {e}")
    
    if not customer_email:
        logger.error("No customer email in checkout session")
        return
    
    # Get product info from checkout module
    from app.routes.checkout import get_price_to_product_map
    price_to_product = get_price_to_product_map()
    
    # Find product by price_id or product_key
    product_info = None
    if price_id and price_id in price_to_product:
        product_info = price_to_product[price_id]
    elif product_key:
        from app.routes.checkout import PRODUCTS
        product_info = PRODUCTS.get(product_key)
    
    if not product_info:
        logger.error(f"Product not found: price_id={price_id}, product_key={product_key}")
        return
    
    logger.info(f"Checkout completed: email={customer_email}, product={product_info.get('name')}")
    
    # Trigger PDF delivery
    deliver_pdf(
        email=customer_email,
        name=customer_name,
        product_key=price_id or product_key,
        session_id=session.get('id')
    )
