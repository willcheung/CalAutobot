"""Product configuration for mapping Stripe price IDs to PDF files."""

import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# Products directory (project root /products/)
PRODUCTS_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'products')

# Product mapping: Stripe price_id or product_id -> PDF file info
PRODUCTS = {
    'price_1T6Kd2E2as0iCQbSoKJ2wgT8': {
        'filename': 'diary-of-an-ai-ceo.pdf',
        'name': 'Diary of an AI CEO',
        'price': 29.00,
    },
    'ai-ceo-guide': {
        'filename': 'diary-of-an-ai-ceo.pdf',
        'name': 'Diary of an AI CEO',
        'price': 29.00,
    },
}

# Default product for testing
DEFAULT_PRODUCT = {
    'filename': 'welcome.pdf',
    'name': 'CalAutobot Welcome Guide',
    'price': 0,
}


def get_product(product_key: str) -> Optional[Dict]:
    """
    Get product info by Stripe price ID or product ID.
    
    Args:
        product_key: Stripe price_id or product_id
    
    Returns:
        Dict with product info or None if not found
    """
    product = PRODUCTS.get(product_key)
    
    if not product:
        logger.warning(f"Product not found for key: {product_key}, using default")
        return DEFAULT_PRODUCT
    
    return product


def get_product_path(product_key: str) -> Optional[str]:
    """
    Get the full path to a product's PDF file.
    
    Args:
        product_key: Stripe price_id or product_id
    
    Returns:
        Full path to PDF file or None if not found
    """
    product = get_product(product_key)
    
    if not product:
        return None
    
    filename = product.get('filename')
    if not filename:
        logger.error(f"No filename for product: {product_key}")
        return None
    
    filepath = os.path.join(PRODUCTS_DIR, filename)
    
    if not os.path.exists(filepath):
        logger.error(f"PDF file not found: {filepath}")
        return None
    
    return filepath


def list_products() -> Dict[str, Dict]:
    """
    List all configured products.
    
    Returns:
        Dict of product_key -> product info
    """
    return PRODUCTS.copy()


def add_product(product_key: str, filename: str, name: str, price: float = 0):
    """
    Add or update a product configuration.
    
    Args:
        product_key: Stripe price_id or product_id
        filename: PDF filename in products/ directory
        name: Product display name
        price: Product price (for reference)
    """
    PRODUCTS[product_key] = {
        'filename': filename,
        'name': name,
        'price': price,
    }
    logger.info(f"Added product: {product_key} -> {filename}")
