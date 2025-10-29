(() => {
    const PLACEHOLDER = '—';
    const CONTACT_FIELDS = ['display_name', 'company', 'job_title', 'email', 'phone_number'];
    const COLUMN_COUNT = 9;
    const EMPTY_STATE_HTML = `
        <div class="empty-state">
            <i data-feather="users" class="empty-icon"></i>
            <h3 class="mt-3">No contacts yet</h3>
            <p class="text-muted mb-0">
                Contacts will appear once your assistant engages with invitees or public bookings are created.
            </p>
        </div>
    `;

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
            const displayValue =
                (contact.last_interaction_display && contact.last_interaction_display.trim()) ||
                (typeof contact.last_interaction_at === 'string' ? contact.last_interaction_at.trim() : '');
            const hasValue = Boolean(displayValue);
            target.textContent = hasValue ? displayValue : '—';
            target.classList.toggle('text-muted', !hasValue);
        }
    }

    async function createContact(row, payload, triggerElement) {
        if (!row) {
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
                if (triggerElement) {
                    triggerElement.classList.add('contact-editable--error');
                    setTimeout(() => triggerElement.classList.remove('contact-editable--error'), 1200);
                }
                if (typeof showToast === 'function') {
                    showToast(message, 'error');
                }
                return null;
            }

            if (data.contact) {
                applyContactData(row, data.contact);
                row.classList.remove('contacts-row-missing-required');
                return data.contact.id;
            }
            return null;
        } catch (error) {
            if (triggerElement) {
                triggerElement.classList.add('contact-editable--error');
                setTimeout(() => triggerElement.classList.remove('contact-editable--error'), 1200);
            }
            if (typeof showToast === 'function') {
                showToast('Network error while creating contact.', 'error');
            }
            return null;
        }
    }

    function markRowMissingEmail(row) {
        if (!row) {
            return;
        }
        row.classList.add('contacts-row-missing-required');
        const emailCell = row.querySelector('[data-field="email"]');
        if (emailCell) {
            emailCell.classList.add('contact-editable--warning');
        }
        if (typeof showToast === 'function' && row.dataset.emailWarningShown !== 'true') {
            showToast('Add an email to save this contact.', 'warning');
            row.dataset.emailWarningShown = 'true';
        }
    }

    function clearMissingEmailState(row) {
        if (!row) {
            return;
        }
        row.classList.remove('contacts-row-missing-required');
        delete row.dataset.emailWarningShown;
        const emailCell = row.querySelector('[data-field="email"]');
        if (emailCell) {
            emailCell.classList.remove('contact-editable--warning');
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

        const row = element.closest('tr');
        if (!contactId) {
            if (row) {
                const payload = collectRowValues(row);
                payload[field] = value;
                element.dataset.value = value;
                element.dataset.originalValue = value;
                setDisplayedValue(element, value);

                if (!payload.email) {
                    markRowMissingEmail(row);
                    element.classList.remove('contact-editable--saving');
                    element.contentEditable = 'true';
                    return;
                }

                clearMissingEmailState(row);
                const newId = await createContact(row, payload, element);
                element.classList.remove('contact-editable--saving');
                element.contentEditable = 'true';
                if (newId) {
                    element.dataset.contactId = newId;
                    element.classList.add('contact-editable--saved');
                    setTimeout(() => element.classList.remove('contact-editable--saved'), 900);
                }
            } else {
                element.classList.remove('contact-editable--saving');
                element.contentEditable = 'true';
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

    function attachDeleteButton(button) {
        if (!button || button.dataset.deleteBound === 'true') {
            return;
        }
        button.dataset.deleteBound = 'true';
        button.addEventListener('click', handleDeleteClick);
    }

    function handleDeleteClick(event) {
        event.preventDefault();
        const button = event.currentTarget;
        const row = button.closest('tr');
        if (!row) {
            return;
        }
        const contactId = row.dataset.contactId;
        if (contactId && typeof window.confirm === 'function') {
            const confirmed = window.confirm('Delete this contact?');
            if (!confirmed) {
                return;
            }
        }
        deleteContact(row, button);
    }

    async function deleteContact(row, button) {
        const contactId = row.dataset.contactId;

        const removeRow = () => {
            row.remove();
            ensureEmptyState();
            if (typeof showToast === 'function') {
                showToast('Contact deleted.', 'success');
            }
        };

        if (!contactId) {
            removeRow();
            return;
        }

        if (button.disabled) {
            return;
        }

        button.disabled = true;
        button.classList.add('opacity-50');

        try {
            const response = await fetch(`/contacts/${contactId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                },
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                const message = payload.error || 'Unable to delete contact.';
                throw new Error(message);
            }
            removeRow();
        } catch (error) {
            button.disabled = false;
            button.classList.remove('opacity-50');
            if (typeof showToast === 'function') {
                showToast(error.message || 'Unable to delete contact.', 'error');
            }
        }
    }

    function ensureEmptyState() {
        const tableBody = document.querySelector('#contactsTable tbody');
        if (!tableBody) {
            return;
        }
        const hasContactRows = tableBody.querySelector('tr[data-contact-id]');
        const existingEmpty = tableBody.querySelector('.empty-state');
        if (!hasContactRows && !existingEmpty) {
            const row = document.createElement('tr');
            const cell = document.createElement('td');
            cell.colSpan = COLUMN_COUNT;
            cell.className = 'text-center py-5';
            cell.innerHTML = EMPTY_STATE_HTML.trim();
            row.appendChild(cell);
            tableBody.appendChild(row);
            if (window.feather && typeof window.feather.replace === 'function') {
                window.feather.replace();
            }
        }
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
        const deleteBtn = clone.querySelector('.contact-delete-btn');
        attachDeleteButton(deleteBtn);

        if (window.feather && typeof window.feather.replace === 'function') {
            window.feather.replace();
        }

        const firstEditable = editables[0];
        if (firstEditable) {
            firstEditable.focus();
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        const editableCells = document.querySelectorAll('.contact-editable[contenteditable="true"]');
        editableCells.forEach(attachEditable);

        const deleteButtons = document.querySelectorAll('.contact-delete-btn');
        deleteButtons.forEach(attachDeleteButton);

        ensureEmptyState();

        const searchInput = document.querySelector('input[name="q"][type="search"]');
        if (searchInput) {
            const clearUrl = searchInput.dataset.clearUrl;
            const redirectToClear = () => {
                if (clearUrl) {
                    window.location.href = clearUrl;
                } else {
                    const form = searchInput.closest('form');
                    if (form) {
                        form.submit();
                    }
                }
            };
            const handlePotentialClear = () => {
                if (searchInput.value === '') {
                    redirectToClear();
                }
            };
            searchInput.addEventListener('search', handlePotentialClear);
        }

        const addBtn = document.getElementById('addContactBtn');
        if (addBtn) {
            addBtn.addEventListener('click', insertNewContactRow);
        }
    });
})();
