(() => {
    const PLACEHOLDER = '—';
    const CONTACT_FIELDS = ['display_name', 'timezone', 'company', 'job_title', 'email', 'phone_number'];

    function placeholderFor(element) {
        const hint = element.dataset.placeholder;
        return (hint && hint.trim()) || PLACEHOLDER;
    }

    function setDisplayedValue(element, value) {
        const normalized = typeof value === 'string' ? value.trim() : '';
        const placeholder = placeholderFor(element);
        element.dataset.value = normalized;

        if (!normalized) {
            element.textContent = placeholder;
            element.classList.add('contact-editable-placeholder');
        } else {
            element.textContent = normalized;
            element.classList.remove('contact-editable-placeholder');
        }
    }

    function focusValue(element) {
        const stored = element.dataset.value || '';
        element.textContent = stored;
        element.classList.remove('contact-editable-placeholder');
        requestAnimationFrame(() => {
            const range = document.createRange();
            range.selectNodeContents(element);
            range.collapse(false);
            const selection = window.getSelection();
            if (selection) {
                selection.removeAllRanges();
                selection.addRange(range);
            }
        });
    }

    function revertValue(element) {
        const original = element.dataset.originalValue || '';
        setDisplayedValue(element, original);
    }

    function updateAvatar(row) {
        const avatar = row.querySelector('.contact-avatar');
        if (!avatar) {
            return;
        }
        const nameCell = row.querySelector('[data-field="display_name"]');
        const emailCell = row.querySelector('[data-field="email"]');
        const source =
            (nameCell && (nameCell.dataset.value || nameCell.textContent || '')) ||
            (emailCell && (emailCell.dataset.value || emailCell.textContent || '')) ||
            '';
        const initial = source.trim().charAt(0).toUpperCase() || '?';
        avatar.textContent = initial;
    }

    function collectRowValues(row) {
        const values = {};
        CONTACT_FIELDS.forEach((field) => {
            const cell = row.querySelector(`[data-field="${field}"]`);
            values[field] = cell ? (cell.dataset.value || '').trim() : '';
        });
        return values;
    }

    function applyContactData(row, contact) {
        if (!row || !contact) {
            return;
        }
        row.dataset.contactId = contact.id;
        CONTACT_FIELDS.forEach((field) => {
            const cell = row.querySelector(`[data-field="${field}"]`);
            if (!cell) {
                return;
            }
            cell.dataset.contactId = contact.id;
            const value = contact[field] || '';
            setDisplayedValue(cell, value);
            cell.dataset.originalValue = value;
        });
        row.classList.remove('contacts-row-pending');
        const followBadge = row.querySelector('[data-role="followup-count"]');
        if (followBadge) {
            followBadge.textContent = (contact.follow_up_count ?? 0).toString();
        }
        const lastInteractionCell = row.querySelector('[data-role="last-interaction"]');
        if (lastInteractionCell) {
            const target = lastInteractionCell.querySelector('[data-role="last-interaction-text"]') || lastInteractionCell;
            const hasValue = Boolean(contact.last_interaction_at);
            target.textContent = hasValue ? contact.last_interaction_at : '—';
            target.classList.toggle('text-muted', !hasValue);
        }
        updateAvatar(row);
    }

    async function ensureContact(element, pendingValue) {
        const row = element.closest('tr');
        if (!row) {
            return null;
        }
        const payload = collectRowValues(row);
        payload[element.dataset.field] = pendingValue;

        if (!payload.display_name && !payload.email) {
            revertValue(element);
            element.classList.add('contact-editable--error');
            setTimeout(() => element.classList.remove('contact-editable--error'), 1200);
            if (typeof showToast === 'function') {
                showToast('Add a name or email before saving.', 'warning');
            }
            return null;
        }

        if (payload.email) {
            payload.email = payload.email.toLowerCase();
        }

        try {
            const response = await fetch('/contacts', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(payload),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const message = data.error || 'Unable to create contact.';
                revertValue(element);
                element.classList.add('contact-editable--error');
                setTimeout(() => element.classList.remove('contact-editable--error'), 1200);
                if (typeof showToast === 'function') {
                    showToast(message, 'error');
                }
                return null;
            }

            if (data.contact) {
                applyContactData(row, data.contact);
                return data.contact.id;
            }
            return null;
        } catch (error) {
            revertValue(element);
            element.classList.add('contact-editable--error');
            setTimeout(() => element.classList.remove('contact-editable--error'), 1200);
            if (typeof showToast === 'function') {
                showToast('Network error while creating contact.', 'error');
            }
            return null;
        }
    }

    async function saveValue(element, value) {
        let contactId = element.dataset.contactId;
        const field = element.dataset.field;

        if (!field) {
            revertValue(element);
            return;
        }

        element.classList.add('contact-editable--saving');
        element.contentEditable = 'false';

        if (!contactId) {
            const newId = await ensureContact(element, value);
            element.classList.remove('contact-editable--saving');
            element.contentEditable = 'true';
            if (newId) {
                element.dataset.contactId = newId;
                element.classList.add('contact-editable--saved');
                setTimeout(() => element.classList.remove('contact-editable--saved'), 900);
            }
            return;
        }

        try {
            const response = await fetch(`/contacts/${contactId}`, {
                method: 'PATCH',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ field, value }),
            });

            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                const message = payload.error || 'Unable to save change.';
                revertValue(element);
                element.classList.add('contact-editable--error');
                setTimeout(() => element.classList.remove('contact-editable--error'), 1200);
                if (typeof showToast === 'function') {
                    showToast(message, 'error');
                }
                return;
            }

            const updatedValue = typeof payload.value === 'string' ? payload.value : '';
            setDisplayedValue(element, updatedValue);
            element.dataset.originalValue = updatedValue;
            element.classList.add('contact-editable--saved');
            setTimeout(() => element.classList.remove('contact-editable--saved'), 900);

            if (field === 'display_name' || field === 'email') {
                updateAvatar(element.closest('tr'));
            }
        } catch (error) {
            if (error.name !== 'AbortError') {
                revertValue(element);
                element.classList.add('contact-editable--error');
                setTimeout(() => element.classList.remove('contact-editable--error'), 1200);
                if (typeof showToast === 'function') {
                    showToast('Network error while saving change.', 'error');
                }
            }
        } finally {
            element.classList.remove('contact-editable--saving');
            element.contentEditable = 'true';
        }
    }

    function handleFocus(event) {
        const element = event.currentTarget;
        element.dataset.originalValue = element.dataset.value || '';
        focusValue(element);
    }

    function handleKeydown(event) {
        const element = event.currentTarget;
        if (event.key === 'Enter') {
            event.preventDefault();
            element.blur();
        } else if (event.key === 'Escape') {
            event.preventDefault();
            revertValue(element);
            element.blur();
        }
    }

    function handleInput(event) {
        const element = event.currentTarget;
        if (element.textContent && element.textContent.includes('\n')) {
            element.textContent = element.textContent.replace(/\s+/g, ' ');
        }
    }

    function handleBlur(event) {
        const element = event.currentTarget;
        const rawValue = element.textContent.trim();
        const normalized = rawValue || '';
        const original = element.dataset.originalValue || '';

        if (!normalized) {
            setDisplayedValue(element, '');
        }

        if (normalized === original) {
            setDisplayedValue(element, original);
            return;
        }

        saveValue(element, normalized);
    }

    function attachEditable(element) {
        if (element.dataset.editableBound === 'true') {
            return;
        }
        element.dataset.editableBound = 'true';
        const initial = element.dataset.value;
        const startingValue = typeof initial === 'string' ? initial : element.textContent.trim();
        setDisplayedValue(element, startingValue);
        element.dataset.originalValue = startingValue || '';

        element.addEventListener('focus', handleFocus);
        element.addEventListener('keydown', handleKeydown);
        element.addEventListener('input', handleInput);
        element.addEventListener('blur', handleBlur);
    }

    function insertNewContactRow() {
        const template = document.getElementById('contactRowTemplate');
        const tableBody = document.querySelector('#contactsTable tbody');
        if (!template || !tableBody) {
            return;
        }

        const emptyState = tableBody.querySelector('.empty-state');
        if (emptyState) {
            const emptyRow = emptyState.closest('tr');
            if (emptyRow) {
                emptyRow.remove();
            }
        }

        const clone = template.content.firstElementChild.cloneNode(true);
        clone.classList.add('contacts-row-pending');
        tableBody.insertBefore(clone, tableBody.firstElementChild || null);

        const editables = clone.querySelectorAll('.contact-editable[contenteditable="true"]');
        editables.forEach(attachEditable);
        updateAvatar(clone);

        const firstEditable = editables[0];
        if (firstEditable) {
            firstEditable.focus();
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const editableCells = document.querySelectorAll('.contact-editable[contenteditable="true"]');
        editableCells.forEach(attachEditable);

        document.querySelectorAll('#contactsTable tbody tr').forEach(updateAvatar);

        const addBtn = document.getElementById('addContactBtn');
        if (addBtn) {
            addBtn.addEventListener('click', insertNewContactRow);
        }
    });
})();
