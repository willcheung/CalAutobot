"""
User Knowledge Service

Manages user-uploaded knowledge/context that enhances the scheduling AI.
"""

import logging
from typing import Dict, List, Optional

from app import db
from app.models import UserKnowledge, User

logger = logging.getLogger(__name__)


# Knowledge categories with descriptions
KNOWLEDGE_CATEGORIES = {
    'preference': 'Scheduling preferences (e.g., "I prefer morning meetings")',
    'contact_context': 'Context about specific contacts (e.g., "John is a VIP client")',
    'meeting_template': 'Meeting type guidelines (e.g., "Sales calls need 30 min")',
    'general': 'General context about you or your business',
    'availability': 'Availability rules (e.g., "No meetings on Fridays")',
}


def get_user_knowledge(user_id: int, active_only: bool = True) -> List[UserKnowledge]:
    """
    Get all knowledge entries for a user.
    
    Args:
        user_id: User ID
        active_only: Only return active entries
        
    Returns:
        List of UserKnowledge objects
    """
    query = UserKnowledge.query.filter_by(user_id=user_id)
    
    if active_only:
        query = query.filter_by(is_active=True)
    
    return query.order_by(UserKnowledge.category, UserKnowledge.created_at.desc()).all()


def get_knowledge_by_category(user_id: int, category: str) -> List[UserKnowledge]:
    """
    Get knowledge entries for a specific category.
    
    Args:
        user_id: User ID
        category: Category to filter by
        
    Returns:
        List of UserKnowledge objects
    """
    return UserKnowledge.query.filter_by(
        user_id=user_id,
        category=category,
        is_active=True
    ).order_by(UserKnowledge.created_at.desc()).all()


def create_knowledge_entry(
    user_id: int,
    title: str,
    content: str,
    category: str = 'general'
) -> UserKnowledge:
    """
    Create a new knowledge entry.
    
    Args:
        user_id: User ID
        title: Entry title
        content: Entry content
        category: Entry category
        
    Returns:
        Created UserKnowledge object
    """
    entry = UserKnowledge(
        user_id=user_id,
        title=title,
        content=content,
        category=category
    )
    
    db.session.add(entry)
    db.session.commit()
    
    logger.info(f"Created knowledge entry '{title}' for user {user_id}")
    return entry


def update_knowledge_entry(
    entry_id: int,
    user_id: int,
    title: Optional[str] = None,
    content: Optional[str] = None,
    category: Optional[str] = None,
    is_active: Optional[bool] = None
) -> Optional[UserKnowledge]:
    """
    Update an existing knowledge entry.
    
    Args:
        entry_id: Entry ID
        user_id: User ID (for authorization)
        title: New title (optional)
        content: New content (optional)
        category: New category (optional)
        is_active: New active status (optional)
        
    Returns:
        Updated UserKnowledge object or None if not found
    """
    entry = UserKnowledge.query.filter_by(id=entry_id, user_id=user_id).first()
    
    if not entry:
        return None
    
    if title is not None:
        entry.title = title
    if content is not None:
        entry.content = content
    if category is not None:
        entry.category = category
    if is_active is not None:
        entry.is_active = is_active
    
    db.session.commit()
    logger.info(f"Updated knowledge entry {entry_id}")
    return entry


def delete_knowledge_entry(entry_id: int, user_id: int) -> bool:
    """
    Delete a knowledge entry.
    
    Args:
        entry_id: Entry ID
        user_id: User ID (for authorization)
        
    Returns:
        True if deleted, False if not found
    """
    entry = UserKnowledge.query.filter_by(id=entry_id, user_id=user_id).first()
    
    if not entry:
        return False
    
    db.session.delete(entry)
    db.session.commit()
    
    logger.info(f"Deleted knowledge entry {entry_id}")
    return True


def format_knowledge_for_agent(user_id: int, max_entries: int = 10) -> str:
    """
    Format user knowledge for inclusion in agent context.
    
    Args:
        user_id: User ID
        max_entries: Maximum number of entries to include
        
    Returns:
        Formatted string for agent context
    """
    entries = get_user_knowledge(user_id, active_only=True)[:max_entries]
    
    if not entries:
        return ""
    
    sections = []
    current_category = None
    
    for entry in entries:
        if entry.category != current_category:
            current_category = entry.category
            category_desc = KNOWLEDGE_CATEGORIES.get(current_category, current_category)
            sections.append(f"\n[{current_category.upper()}] - {category_desc}")
        
        sections.append(f"- {entry.title}: {entry.content}")
    
    return "\n".join(sections)


def get_knowledge_context_dict(user_id: int) -> Dict[str, str]:
    """
    Get knowledge as a dictionary organized by category.
    
    Args:
        user_id: User ID
        
    Returns:
        Dict with category keys and formatted content values
    """
    entries = get_user_knowledge(user_id, active_only=True)
    
    result = {}
    for category in KNOWLEDGE_CATEGORIES.keys():
        category_entries = [e for e in entries if e.category == category]
        if category_entries:
            result[category] = "\n".join([f"- {e.title}: {e.content}" for e in category_entries])
    
    return result
