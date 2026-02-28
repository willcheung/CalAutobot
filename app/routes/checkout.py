"""Stripe checkout routes for CalAutobot product purchases."""

import logging
import os
from flask import Blueprint, request, jsonify, render_template, redirect, url_for

logger = logging.getLogger(__name__)

checkout_bp = Blueprint('checkout', __name__)

try:
    import stripe
    api_key = os.environ.get('STRIPE_SECRET_KEY', '')
    if not api_key:
        logger.error("STRIPE_SECRET_KEY environment variable is not set")
        stripe = None
    else:
        stripe.api_key = api_key
        logger.info(f"Stripe configured successfully (key starts with: {api_key[:12]}...)")
except ImportError as e:
    logger.warning(f"Stripe library not installed: {e}")
    stripe = None
except Exception as e:
    logger.error(f"Failed to configure Stripe: {e}")
    stripe = None

# Product configuration - maps product keys to Stripe price IDs
PRODUCTS = {
    'ai-ceo-guide': {
        'price_id': 'price_1T3SxPE2as0iCQbSkOcdH64i',
        'name': 'How I Work as an AI CEO',
        'price': 19.00,
        'description': 'The complete guide to building an AI-run business',
    },
}

# Stripe price ID to product mapping (for webhook)
PRICE_TO_PRODUCT = {
    'price_1T3SxPE2as0iCQbSkOcdH64i': {
        'filename': 'ai-ceo-guide.pdf',
        'name': 'How I Work as an AI CEO',
    },
}


@checkout_bp.route('/checkout')
def checkout_page():
    """Render the checkout page with product options."""
    return render_template('checkout.html', products=PRODUCTS)


@checkout_bp.route('/api/checkout/create-session', methods=['POST'])
def create_checkout_session():
    """Create a Stripe Checkout Session for a product."""
    if stripe is None:
        return jsonify({'error': 'Stripe not configured'}), 500
    
    data = request.get_json() or {}
    product_key = data.get('product_key', 'ai-ceo-guide')
    
    product = PRODUCTS.get(product_key)
    if not product:
        return jsonify({'error': 'Product not found'}), 404
    
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': product['price_id'],
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.host_url + 'checkout/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'checkout?canceled=true',
            metadata={
                'product_key': product_key,
            }
        )
        return jsonify({'url': session.url})
    except Exception as e:
        logger.error(f"Failed to create checkout session: {e}")
        return jsonify({'error': str(e)}), 500


@checkout_bp.route('/checkout/success')
def checkout_success():
    """Render the success page after a completed checkout."""
    session_id = request.args.get('session_id')
    return render_template('checkout_success.html', session_id=session_id)


def get_price_to_product_map():
    """Return the mapping of price IDs to product info."""
    return PRICE_TO_PRODUCT
