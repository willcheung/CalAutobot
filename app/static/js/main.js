// Main JavaScript file for Calendar AI application
document.addEventListener('DOMContentLoaded', function() {
    // Initialize Feather icons
    if (typeof feather !== 'undefined') {
        feather.replace();
    }
    
    // Initialize mobile menu
    initializeMobileMenu();
    
    // Initialize email management
    initializeEmailManagement();
    
    // Auto-resize textarea
    const textareas = document.querySelectorAll('textarea');
    textareas.forEach(textarea => {
        textarea.addEventListener('input', autoResize);
        autoResize.call(textarea); // Initial resize
    });
    
    // Add fade-in animation to cards
    const cards = document.querySelectorAll('.event-card, .feature-card, .input-card');
    cards.forEach((card, index) => {
        card.style.animationDelay = `${index * 0.1}s`;
        card.classList.add('fade-in');
    });
    
    // Form validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!validateForm(this)) {
                e.preventDefault();
            }
        });
    });
    
    // Auto-dismiss alerts after 5 seconds (except calendar permission banner)
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent):not([data-calendar-banner])');
    alerts.forEach(alert => {
        setTimeout(() => {
            if (alert.parentNode) {
                alert.remove();
            }
        }, 5000);
    });
    
    // Confirm delete actions
    const deleteForms = document.querySelectorAll('.delete-form');
    deleteForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!confirm('Are you sure you want to delete this event?')) {
                e.preventDefault();
                return false;
            }
        });
    });
    
    // Loading states for forms
    const submitButtons = document.querySelectorAll('button[type="submit"]');
    submitButtons.forEach(button => {
        button.closest('form').addEventListener('submit', function() {
            button.disabled = true;
            const originalContent = Array.from(button.childNodes).map(node => node.cloneNode(true));
            
            // Clear and add spinner safely
            button.textContent = '';
            const spinner = document.createElement('span');
            spinner.className = 'spinner-border spinner-border-sm me-2';
            spinner.setAttribute('role', 'status');
            button.appendChild(spinner);
            button.appendChild(document.createTextNode('Processing...'));
            
            // Re-enable after 30 seconds as failsafe
            setTimeout(() => {
                button.disabled = false;
                button.textContent = '';
                originalContent.forEach(node => button.appendChild(node));
            }, 30000);
        });
    });
    
    // Smooth scrolling for anchor links
    const anchorLinks = document.querySelectorAll('a[href^="#"]');
    anchorLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href').substring(1);
            const targetElement = document.getElementById(targetId);
            
            if (targetElement) {
                e.preventDefault();
                targetElement.scrollIntoView({
                    behavior: 'smooth',
                    block: 'start'
                });
            }
        });
    });
    
    // Copy to clipboard functionality (for future use)
    const copyButtons = document.querySelectorAll('[data-copy]');
    copyButtons.forEach(button => {
        button.addEventListener('click', function() {
            const textToCopy = this.dataset.copy;
            navigator.clipboard.writeText(textToCopy).then(() => {
                showToast('Copied to clipboard!', 'success');
            }).catch(() => {
                showToast('Failed to copy to clipboard', 'error');
            });
        });
    });
    
    // Auto-save draft functionality for text input (future enhancement)
    const textInput = document.getElementById('text');
    if (textInput) {
        let saveTimeout;
        textInput.addEventListener('input', function() {
            clearTimeout(saveTimeout);
            saveTimeout = setTimeout(() => {
                saveDraft(this.value);
            }, 2000); // Save after 2 seconds of inactivity
        });
        
        // Load draft on page load
        loadDraft();
    }

    initAvailabilityCopyPopover();
    initVisibilityToggle();
    initEmailStack();

    // Toggle full booking descriptions
    document.querySelectorAll('[data-booking-toggle]').forEach(button => {
        button.addEventListener('click', () => {
            const notesContainer = button.closest('[data-booking-notes]');
            if (!notesContainer) {
                return;
            }

            const preview = notesContainer.querySelector('[data-booking-preview]');
            const full = notesContainer.querySelector('[data-booking-full]');
            if (!preview || !full) {
                return;
            }

            const isExpanded = !full.classList.contains('d-none');
            if (isExpanded) {
                full.classList.add('d-none');
                preview.classList.remove('d-none');
                button.textContent = 'More';
                button.setAttribute('aria-expanded', 'false');
            } else {
                full.classList.remove('d-none');
                preview.classList.add('d-none');
                button.textContent = 'Less';
                button.setAttribute('aria-expanded', 'true');
            }
        });
    });
});

// Helper function to auto-resize textareas
function autoResize() {
    this.style.height = 'auto';
    this.style.height = this.scrollHeight + 'px';
}

// Form validation function
function validateForm(form) {
    let isValid = true;
    const requiredFields = form.querySelectorAll('[required]');
    
    requiredFields.forEach(field => {
        if (!field.value.trim()) {
            field.classList.add('is-invalid');
            isValid = false;
        } else {
            field.classList.remove('is-invalid');
        }
    });
    
    // Date validation
    const startDate = form.querySelector('[name="start_date"]');
    const endDate = form.querySelector('[name="end_date"]');
    
    if (startDate && endDate && startDate.value && endDate.value) {
        if (new Date(startDate.value) > new Date(endDate.value)) {
            endDate.classList.add('is-invalid');
            showToast('End date cannot be before start date', 'error');
            isValid = false;
        } else {
            endDate.classList.remove('is-invalid');
        }
    }
    
    // Time validation
    const startTime = form.querySelector('[name="start_time"]');
    const endTime = form.querySelector('[name="end_time"]');
    
    if (startTime && endTime && startTime.value && endTime.value && 
        startDate && endDate && startDate.value === endDate.value) {
        if (startTime.value >= endTime.value) {
            endTime.classList.add('is-invalid');
            showToast('End time must be after start time', 'error');
            isValid = false;
        } else {
            endTime.classList.remove('is-invalid');
        }
    }
    
    return isValid;
}

// Toast notification function
function showToast(message, type = 'info') {
    const toastContainer = getOrCreateToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `alert alert-${type} alert-dismissible fade show`;
    
    // Safely add message as text content
    toast.textContent = message;
    
    // Add close button
    const closeButton = document.createElement('button');
    closeButton.type = 'button';
    closeButton.className = 'btn-close';
    closeButton.setAttribute('data-bs-dismiss', 'alert');
    toast.appendChild(closeButton);
    
    toastContainer.appendChild(toast);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
        if (toast.parentNode) {
            toast.remove();
        }
    }, 5000);
}

function initEmailStack() {
    const stackSection = document.querySelector('.email-stack');
    if (!stackSection) {
        return;
    }

    const scroller = stackSection.querySelector('.email-stack__scroller');
    const cards = Array.from(stackSection.querySelectorAll('.email-stack__card'));
    if (!scroller || cards.length === 0) {
        return;
    }

    const steps = cards.length - 1;
    if (steps <= 0) {
        return;
    }

    const styles = getComputedStyle(stackSection);
    const stackGap = parseFloat(styles.getPropertyValue('--email-stack-gap')) || 72;
    const leadIn = 0.2;
    const stackSpacing = stackGap * 0.85;
    const stackBaseOffset = -stackGap * 0.65;
    const focusOffset = -stackGap * 2.4;
    const entryOffset = stackGap * 1.4;
    const clamp = (value, min, max) => Math.min(Math.max(value, min), max);

    function render(progress) {
        const clamped = clamp(progress, 0, 1);
        const normalized = clamped <= leadIn ? 0 : (clamped - leadIn) / (1 - leadIn);
        const active = normalized * steps;
        const stage = Math.floor(active);
        const fraction = active - stage;
        const stackedCount = Math.max(stage, 0);
        const stackTopOffset = stackBaseOffset - (stackedCount > 0 ? (stackedCount - 1) * stackSpacing : 0);

        cards.forEach((card, index) => {
            let translate = 0;
            let scale = 1;

            if (index < stage) {
                const orderFromTop = (stage - 1) - index;
                translate = stackTopOffset + orderFromTop * stackSpacing;
                scale = Math.max(0.9, 1 - Math.min(orderFromTop + 1, 4) * 0.04);
                card.style.zIndex = String(10 + index);
            } else if (index === stage) {
                const eased = fraction;
                translate = (1 - eased) * entryOffset + eased * focusOffset;
                scale = 1 - eased * 0.02;
                card.style.zIndex = String(100);
            } else {
                const aheadIndex = index - stage;
                translate = entryOffset * (aheadIndex + (1 - fraction));
                scale = 1 - Math.min(aheadIndex, 3) * 0.04;
                card.style.zIndex = String(50 - index);
            }

            card.style.setProperty('--stack-translate', `${translate}px`);
            card.style.setProperty('--stack-scale', scale.toFixed(3));
            card.style.setProperty('--stack-opacity', '1');
        });
    }

    let rafId = null;

    function update() {
        const rect = scroller.getBoundingClientRect();
        const total = scroller.offsetHeight - window.innerHeight;
        const progress = total <= 0 ? 0 : clamp((window.innerHeight - rect.top) / total, 0, 1);
        render(progress);
        rafId = window.requestAnimationFrame(update);
    }

    if (typeof IntersectionObserver === 'undefined') {
        render(0);
        rafId = window.requestAnimationFrame(update);
        return;
    }

    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                if (rafId === null) {
                    rafId = window.requestAnimationFrame(update);
                }
            } else if (rafId !== null) {
                window.cancelAnimationFrame(rafId);
                rafId = null;
            }
        });
    }, { threshold: 0, root: null });

    observer.observe(scroller);
    stackSection.style.setProperty('--email-stack-card-count', cards.length);
    render(0);

    window.addEventListener('resize', () => {
        stackSection.style.setProperty('--email-stack-card-count', cards.length);
    }, { passive: true });
}

function initAvailabilityCopyPopover() {
    const template = document.getElementById('copy-times-popover-template');
    const copyButtons = document.querySelectorAll('.copy-timeslot-btn');
    if (!template || copyButtons.length === 0) {
        return;
    }

    let popover;
    let activeDay = null;
    let currentButton = null;

    function ensurePopover() {
        if (popover) {
            return popover;
        }
        const instance = template.content.firstElementChild.cloneNode(true);
        document.body.appendChild(instance);
        popover = instance;
        popover.classList.add('d-none');

        const cancelBtn = popover.querySelector('.copy-cancel');
        const applyBtn = popover.querySelector('.copy-apply');
        const selectAll = popover.querySelector('.copy-select-all');
        const checkboxes = Array.from(popover.querySelectorAll('.copy-target'));

        cancelBtn.addEventListener('click', closePopover);
        applyBtn.addEventListener('click', () => applyCopy(checkboxes));

        selectAll.addEventListener('change', () => {
            checkboxes.forEach(cb => {
                if (cb.disabled) {
                    return;
                }
                cb.checked = selectAll.checked;
            });
        });

        checkboxes.forEach(cb => {
            cb.addEventListener('change', () => {
                const eligible = checkboxes.filter(item => !item.disabled);
                if (eligible.length === 0) {
                    selectAll.checked = false;
                    return;
                }
                const allChecked = eligible.every(item => item.checked);
                selectAll.checked = allChecked;
            });
        });

        return popover;
    }

    function applyCopy(checkboxes) {
        if (activeDay === null) {
            closePopover();
            return;
        }

        const sourceStart = document.querySelector(`[name="day-${activeDay}-start"]`);
        const sourceEnd = document.querySelector(`[name="day-${activeDay}-end"]`);
        if (!sourceStart || !sourceEnd) {
            closePopover();
            return;
        }

        checkboxes.forEach(cb => {
            if (!cb.checked || cb.disabled) {
                return;
            }
            const targetDay = parseInt(cb.value, 10);
            if (Number.isNaN(targetDay)) {
                return;
            }
            const startInput = document.querySelector(`[name="day-${targetDay}-start"]`);
            const endInput = document.querySelector(`[name="day-${targetDay}-end"]`);
            const toggle = document.getElementById(`day-${targetDay}-enabled`);
            if (startInput && endInput) {
                startInput.value = sourceStart.value;
                endInput.value = sourceEnd.value;
            }
            if (toggle) {
                toggle.checked = true;
            }
        });

        closePopover();
    }

    function positionPopover(button) {
        const instance = ensurePopover();
        instance.classList.remove('d-none');
        const rect = button.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        const top = rect.bottom + scrollTop + 8;
        let left = rect.left + scrollLeft - (instance.offsetWidth / 2) + (rect.width / 2);
        const maxLeft = document.documentElement.clientWidth - instance.offsetWidth - 16;
        left = Math.max(16, Math.min(left, maxLeft));

        instance.style.top = `${top}px`;
        instance.style.left = `${left}px`;
    }

    function closePopover() {
        if (!popover) {
            return;
        }
        popover.classList.add('d-none');
        activeDay = null;
        currentButton = null;
    }

    function updateCheckboxStates() {
        const instance = ensurePopover();
        const checkboxes = Array.from(instance.querySelectorAll('.copy-target'));
        const selectAll = instance.querySelector('.copy-select-all');
        checkboxes.forEach(cb => {
            const value = parseInt(cb.value, 10);
            if (value === activeDay) {
                cb.disabled = true;
                cb.checked = false;
            } else {
                cb.disabled = false;
                cb.checked = false;
            }
        });
        if (selectAll) {
            selectAll.checked = false;
        }
    }

    copyButtons.forEach(button => {
        button.addEventListener('click', event => {
            event.preventDefault();
            event.stopPropagation();
            const day = parseInt(button.dataset.day, 10);
            if (Number.isNaN(day)) {
                return;
            }
            activeDay = day;
            currentButton = button;
            ensurePopover();
            updateCheckboxStates();
            positionPopover(button);
        });
    });

    document.addEventListener('click', event => {
        if (!popover || popover.classList.contains('d-none')) {
            return;
        }
        if (popover.contains(event.target) || (currentButton && currentButton.contains(event.target))) {
            return;
        }
        closePopover();
    });

    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') {
            closePopover();
        }
    });
}

function initVisibilityToggle() {
    const toggles = document.querySelectorAll('.visibility-toggle');
    if (toggles.length === 0) {
        return;
    }

    toggles.forEach(toggle => {
        const hiddenInput = toggle.querySelector('input[type="hidden"]');
        const pill = toggle.querySelector('.visibility-pill');
        function updateState(isPublic) {
            toggle.dataset.state = isPublic ? 'public' : 'hidden';
            if (pill) {
                pill.textContent = isPublic ? 'Public' : 'Hidden';
            }
            toggle.setAttribute('title', isPublic ? 'Hide from profile' : 'Show on profile');
            if (hiddenInput) {
                hiddenInput.value = isPublic ? 'true' : 'false';
            }
        }

        const initial = toggle.dataset.initial === 'public';
        updateState(initial);

        toggle.addEventListener('click', event => {
            event.preventDefault();
            const isPublic = hiddenInput.value !== 'true';
            updateState(isPublic);
        });
    });
}

// Get or create toast container
function getOrCreateToastContainer() {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '9999';
        container.style.maxWidth = '300px';
        document.body.appendChild(container);
    }
    return container;
}

// Draft saving functionality
function saveDraft(content) {
    if (content.trim()) {
        localStorage.setItem('calendar-ai-draft', content);
    } else {
        localStorage.removeItem('calendar-ai-draft');
    }
}

function loadDraft() {
    const textInput = document.getElementById('text');
    const draft = localStorage.getItem('calendar-ai-draft');
    
    if (textInput && draft && !textInput.value.trim()) {
        textInput.value = draft;
        autoResize.call(textInput);
        
        // Show notification about loaded draft
        showToast('Draft loaded from previous session', 'info');
    }
}

function clearDraft() {
    localStorage.removeItem('calendar-ai-draft');
}

// Utility function to format dates for display
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
    });
}

// Utility function to format times for display
function formatTime(timeString) {
    const [hours, minutes] = timeString.split(':');
    const date = new Date();
    date.setHours(parseInt(hours), parseInt(minutes));
    
    return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });
}

// Event listener for real-time form field updates
document.addEventListener('input', function(e) {
    if (e.target.classList.contains('is-invalid')) {
        e.target.classList.remove('is-invalid');
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl/Cmd + Enter to submit forms
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const activeForm = document.activeElement.closest('form');
        if (activeForm) {
            const submitButton = activeForm.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.click();
            }
        }
    }
    
    // Escape to close modals or go back
    if (e.key === 'Escape') {
        const backButton = document.querySelector('.btn[href*="bookings"]');
        if (backButton && window.location.pathname.includes('edit')) {
            window.history.back();
        }
    }
});

// Function to start Google login with timezone detection
window.startGoogleLogin = function() {
    try {
        // Get timezone name
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        
        // Create the login URL with timezone parameter
        const loginUrl = '/google_login';
        const redirectUrl = `${loginUrl}?timezone=${encodeURIComponent(timezone)}`;
        
        window.location.href = redirectUrl;
    } catch (error) {
        console.error('Error detecting timezone:', error);
        // Fallback to login without timezone
        window.location.href = '/google_login';
    }
}

window.connectGoogleCalendar = function() {
    try {
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const connectUrl = '/google_login/calendar';
        const redirectUrl = `${connectUrl}?timezone=${encodeURIComponent(timezone)}`;
        window.location.href = redirectUrl;
    } catch (error) {
        console.error('Error detecting timezone:', error);
        window.location.href = '/google_login/calendar';
    }
}

// Function to copy email address
window.copyEmailAddress = function(email, button) {
    const emailToCopy = (email || 'go@CalAutobot.com').trim();
    return navigator.clipboard.writeText(emailToCopy).then(() => {
        showToast('Email copied to clipboard!', 'success');

        const targetButton = button instanceof Element
            ? button
            : document.querySelector(`.copy-email-btn[data-email="${emailToCopy.toLowerCase()}"]`) ||
              (!email ? document.querySelector('.copy-email-btn[data-email="go@calautobot.com"]') : null);

        if (targetButton && typeof feather !== 'undefined') {
            const swapIcon = (iconName) => {
                if (!feather.icons[iconName]) return;
                targetButton.innerHTML = feather.icons[iconName].toSvg({ width: 18, height: 18 });
            };

            swapIcon('check');

            setTimeout(() => {
                swapIcon('copy');
            }, 2000);
        }
    }).catch(() => {
        showToast(`Failed to copy email. Please copy manually: ${emailToCopy}`, 'error');
    });
};

// Legacy function for backwards compatibility
window.copyEmail = function(email, button) {
    return window.copyEmailAddress(email, button);
};

// Initialize tooltips (if Bootstrap tooltips are needed in the future)
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// Performance: Lazy load non-critical features
window.addEventListener('load', function() {
    // Initialize tooltips after page load
    if (typeof bootstrap !== 'undefined') {
        initializeTooltips();
    }
    
    // Refresh Feather icons in case any were added dynamically
    if (typeof feather !== 'undefined') {
        feather.replace();
    }
});

// Error handling for failed AJAX requests (future use)
window.addEventListener('unhandledrejection', function(e) {
    console.error('Unhandled promise rejection:', e.reason);
    showToast('An unexpected error occurred. Please try again.', 'error');
});

// Service worker registration (future PWA enhancement)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        // Service worker code would go here for offline functionality
    });
}

// Email management functions
function initializeEmailManagement() {
    const addEmailForm = document.getElementById('add-email-form');
    
    if (addEmailForm) {
        addEmailForm.addEventListener('submit', handleAddEmail);
    }
    
    // Use event delegation for remove buttons (including dynamically added ones)
    document.addEventListener('click', function(e) {
        if (e.target.closest('.remove-email-ajax')) {
            handleRemoveEmail(e);
        }
    });
}

function handleAddEmail(e) {
    e.preventDefault();
    
    const form = e.target;
    const formData = new FormData(form);
    const emailInput = document.getElementById('email-input');
    const addButton = document.getElementById('add-email-btn');
    const messageDiv = document.getElementById('email-form-message');
    
    // Disable form elements
    emailInput.disabled = true;
    addButton.disabled = true;
    addButton.textContent = '';
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm';
    spinner.setAttribute('role', 'status');
    addButton.appendChild(spinner);
    
    // Clear previous messages
    messageDiv.style.display = 'none';
    messageDiv.className = 'mt-2';
    
    fetch(form.action, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Clear the input
            emailInput.value = '';
            
            // Show success message
            showEmailMessage(data.message, 'success');
            
            // Add the new email to the list
            addEmailToList(data.email);
            
        } else {
            showEmailMessage(data.error, 'danger');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showEmailMessage('An error occurred. Please try again.', 'danger');
    })
    .finally(() => {
        // Re-enable form elements
        emailInput.disabled = false;
        addButton.disabled = false;
        addButton.textContent = '';
        const icon = document.createElement('i');
        icon.setAttribute('data-feather', 'plus');
        addButton.appendChild(icon);
        feather.replace();
    });
}

function handleRemoveEmail(e) {
    e.preventDefault();
    
    // Find the actual button that was clicked
    const button = e.target.closest('.remove-email-ajax');
    if (!button) return;
    
    const emailId = button.dataset.emailId;
    const emailItem = button.closest('[data-email-id]');
    const emailTextElement = emailItem.querySelector('.email-text');
    const emailText = emailTextElement ? emailTextElement.textContent : 'this email';
    
    if (!confirm(`Are you sure you want to remove ${emailText}?`)) {
        return;
    }
    
    // Disable button
    button.disabled = true;
    const originalContent = Array.from(button.childNodes).map(node => node.cloneNode(true));
    
    // Clear and add spinner safely
    button.textContent = '';
    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm';
    spinner.setAttribute('role', 'status');
    button.appendChild(spinner);
    
    fetch(`/remove_email/${emailId}`, {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Remove the email item from the list
            removeEmailFromList(emailId);
            showEmailMessage(data.message, 'success');
        } else {
            showEmailMessage(data.error, 'danger');
            // Re-enable button on error
            button.disabled = false;
            button.textContent = '';
            originalContent.forEach(node => button.appendChild(node));
            feather.replace();
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showEmailMessage('An error occurred. Please try again.', 'danger');
        // Re-enable button on error
        button.disabled = false;
        button.textContent = '';
        originalContent.forEach(node => button.appendChild(node));
        feather.replace();
    });
}

function showEmailMessage(message, type) {
    const messageDiv = document.getElementById('email-form-message');
    messageDiv.className = `mt-2 alert alert-${type} alert-sm`;
    messageDiv.textContent = message;
    messageDiv.style.display = 'block';
    
    // Auto-hide after 5 seconds
    setTimeout(() => {
        messageDiv.style.display = 'none';
    }, 5000);
}

function addEmailToList(emailData) {
    const container = document.getElementById('additional-emails-container');
    const noEmailsMessage = document.getElementById('no-emails-message');
    
    // Hide "no emails" message if it exists
    if (noEmailsMessage) {
        noEmailsMessage.style.display = 'none';
    }
    
    // Add "Additional:" label if this is the first additional email
    let additionalLabel = container.querySelector('small.text-muted');
    if (!additionalLabel) {
        additionalLabel = document.createElement('small');
        additionalLabel.className = 'text-muted d-block mb-2';
        additionalLabel.textContent = 'Additional:';
        container.insertBefore(additionalLabel, container.firstChild);
    }
    
    // Create new email item safely using DOM methods
    const emailItem = document.createElement('div');
    emailItem.className = 'email-item mb-2';
    emailItem.setAttribute('data-email-id', emailData.id);
    
    // Create email text span
    const emailSpan = document.createElement('span');
    emailSpan.className = 'email-text';
    emailSpan.textContent = emailData.email; // Safe: uses textContent instead of innerHTML
    
    // Create remove button
    const removeButton = document.createElement('button');
    removeButton.type = 'button';
    removeButton.className = 'btn btn-sm btn-outline-danger email-remove-btn remove-email-ajax';
    removeButton.setAttribute('data-email-id', emailData.id);
    removeButton.setAttribute('title', 'Remove email');
    
    // Create icon for button
    const icon = document.createElement('i');
    icon.setAttribute('data-feather', 'x');
    removeButton.appendChild(icon);
    
    // Assemble email item
    emailItem.appendChild(emailSpan);
    emailItem.appendChild(document.createTextNode(' '));
    emailItem.appendChild(removeButton);
    
    // Event listener will be handled by event delegation
    
    // Append to container
    container.appendChild(emailItem);
    
    // Refresh feather icons
    feather.replace();
}

function removeEmailFromList(emailId) {
    const emailItem = document.querySelector(`[data-email-id="${emailId}"]`);
    if (emailItem) {
        emailItem.remove();
    }
    
    // Check if there are any additional emails left
    const container = document.getElementById('additional-emails-container');
    const remainingEmails = container.querySelectorAll('.email-item[data-email-id]');
    
    if (remainingEmails.length === 0) {
        // Remove the "Additional:" label
        const additionalLabel = container.querySelector('small.text-muted');
        if (additionalLabel) {
            additionalLabel.remove();
        }
        
        // Show "no emails" message
        const noEmailsMessage = document.createElement('small');
        noEmailsMessage.className = 'text-muted';
        noEmailsMessage.id = 'no-emails-message';
        noEmailsMessage.textContent = 'No additional emails added yet.';
        container.appendChild(noEmailsMessage);
    }
}

function initializeMobileMenu() {
    const menuToggle = document.getElementById('mobileMenuToggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebarBackdrop');
    
    if (!menuToggle || !sidebar || !backdrop) {
        return; // Elements don't exist on this page
    }
    
    // Toggle sidebar on hamburger click
    menuToggle.addEventListener('click', function() {
        toggleSidebar();
    });
    
    // Close sidebar when backdrop is clicked
    backdrop.addEventListener('click', function() {
        closeSidebar();
    });
    
    // Close sidebar when a link is clicked (for navigation)
    const sidebarLinks = sidebar.querySelectorAll('.sidebar-link');
    sidebarLinks.forEach(link => {
        link.addEventListener('click', function() {
            // Don't close for external links
            if (!this.hasAttribute('target')) {
                closeSidebar();
            }
        });
    });
    
    // Close sidebar on ESC key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && sidebar.classList.contains('sidebar-open')) {
            closeSidebar();
        }
    });
    
    function toggleSidebar() {
        sidebar.classList.toggle('sidebar-open');
        backdrop.classList.toggle('backdrop-visible');
        
        // Prevent body scroll when sidebar is open
        if (sidebar.classList.contains('sidebar-open')) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
    }
    
    function closeSidebar() {
        sidebar.classList.remove('sidebar-open');
        backdrop.classList.remove('backdrop-visible');
        document.body.style.overflow = '';
    }
}
