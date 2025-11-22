const CONTROL_CLASS = 'calautobot-scheduler-controls';
const SEND_HOOK_ATTR = 'data-calautobot-send-hook';

let authStatus = { checked: false, authenticated: false };
let userEmail = null;

function extractGmailUserEmail() {
  const accountButton = document.querySelector('a[aria-label*="Google Account:"]');
  if (accountButton) {
    const label = accountButton.getAttribute('aria-label') || '';
    const match = label.match(/\(([^)]+@[^)]+)\)/);
    if (match && match[1]) {
      return match[1].trim().toLowerCase();
    }
  }
  const fallback = document.querySelector('[data-hovercard-id*="@"]');
  if (fallback && fallback.dataset.hovercardId) {
    return fallback.dataset.hovercardId.trim().toLowerCase();
  }
  return null;
}

async function sendMessageToBackground(action, payload = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action, payload }, (response) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
      } else if (response && response.success) {
        resolve(response);
      } else {
        reject(new Error(response?.error || 'Unknown error'));
      }
    });
  });
}

async function ensureAuthenticated() {
  if (authStatus.checked && authStatus.authenticated) {
    return true;
  }
  userEmail = extractGmailUserEmail();
  if (!userEmail) {
    alert('CalAutobot: Unable to detect your Gmail account email. Please open Gmail in the same profile and try again.');
    authStatus = { checked: true, authenticated: false };
    return false;
  }
  try {
    const response = await sendMessageToBackground('CHECK_AUTH', { userEmail });
    authStatus = {
      checked: true,
      authenticated: response.authenticated
    };
  } catch (err) {
    console.error('CalAutobot auth check failed', err);
    authStatus = { checked: true, authenticated: false };
  }
  if (!authStatus.authenticated) {
    const result = confirm(
      'CalAutobot: Please sign in first.\n\n' +
      'Click OK to open the sign-in page in a new tab.'
    );
    if (result) {
      // Detect timezone for better UX
      let timezone = 'UTC';
      try {
        timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      } catch (e) {
        // Fallback to UTC if detection fails
      }
      window.open(
        `https://calautobot.com/google_login?timezone=${encodeURIComponent(timezone)}`,
        '_blank'
      );
    }
  }
  return authStatus.authenticated;
}

async function fetchAvailabilityText() {
  const response = await sendMessageToBackground('FETCH_AVAILABILITY', { userEmail, count: '3' });
  return response.data;
}

async function fetchBookingLink() {
  const response = await sendMessageToBackground('FETCH_BOOKING_LINK', { userEmail });
  return response.data;
}

async function sendContactsToAPI(recipients) {
  if (!recipients || !recipients.length) {
    return;
  }
  try {
    await sendMessageToBackground('SEND_CONTACTS', { userEmail, contacts: recipients });
  } catch (err) {
    console.warn('Failed to sync contacts', err);
  }
}

function insertTextIntoEditor(editor, text) {
  if (!editor) return;
  editor.focus();
  // Don't force cursor to end. Trust the browser/user's last position.
  // If the selection is lost, focus() usually restores it or places it at the start/end.
  // But explicitly collapsing to end (as before) prevents inserting in the middle.
  document.execCommand('insertText', false, `${text}\n`);
}

function collectRecipients(composeRoot) {
  const chips = composeRoot.querySelectorAll('span[email]');
  const recipients = [];
  const seen = new Set();
  chips.forEach((chip) => {
    const email = chip.getAttribute('email');
    if (!email) return;
    const normalized = email.trim().toLowerCase();
    if (!normalized || seen.has(normalized)) return;
    seen.add(normalized);
    const name = chip.getAttribute('name') || chip.textContent || undefined;
    recipients.push({ email: normalized, name: name || undefined });
  });
  return recipients;
}

function buildDropdownControls(editor, composeRoot) {
  const container = document.createElement('div');
  container.className = 'calautobot-container';

  // Main button
  const btn = document.createElement('button');
  btn.className = 'calautobot-btn';
  btn.innerHTML = `
    CalAutobot
    <svg width="18" height="18" viewBox="0 0 24 24">
      <path d="M7 10l5 5 5-5z"/>
    </svg>
  `;
  btn.type = 'button';

  // Dropdown menu
  const dropdown = document.createElement('div');
  dropdown.className = 'calautobot-dropdown';

  // Helper to set loading state
  const setLoading = (isLoading) => {
    if (isLoading) {
      btn.disabled = true;
      btn.innerHTML = `
        <div class="calautobot-spinner"></div>
        Processing...
      `;
    } else {
      btn.disabled = false;
      btn.innerHTML = `
        CalAutobot
        <svg width="18" height="18" viewBox="0 0 24 24">
          <path d="M7 10l5 5 5-5z"/>
        </svg>
      `;
    }
  };

  // Helper to create items
  const createItem = (text, iconPath, onClick) => {
    const item = document.createElement('div');
    item.className = 'calautobot-item';
    item.innerHTML = `
      <svg viewBox="0 0 24 24"><path d="${iconPath}"/></svg>
      ${text}
    `;
    item.addEventListener('click', async (e) => {
      e.stopPropagation();
      dropdown.classList.remove('show');
      setLoading(true);
      try {
        await onClick();
      } finally {
        setLoading(false);
      }
    });
    return item;
  };

  // 1. Insert Availability
  dropdown.appendChild(createItem(
    'Insert availability',
    'M19 3h-1V1h-2v2H8V1H6v2H5c-1.11 0-1.99.9-1.99 2L3 19c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H5V8h14v11zM7 10h5v5H7z',
    async () => {
      try {
        const authed = await ensureAuthenticated();
        if (!authed) return;
        const data = await fetchAvailabilityText();
        insertTextIntoEditor(editor, data.text);
      } catch (err) {
        console.error(err);
        alert(err.message || 'Unable to fetch availability.');
      }
    }
  ));

  // 2. Insert Booking Link
  dropdown.appendChild(createItem(
    'Insert booking link',
    'M3.9 12c0-1.71 1.39-3.1 3.1-3.1h4V7H7c-2.76 0-5 2.24-5 5s2.24 5 5 5h4v-1.9H7c-1.71 0-3.1-1.39-3.1-3.1zM8 13h8v-2H8v2zm9-6h-4v1.9h4c1.71 0 3.1 1.39 3.1 3.1s-1.39 3.1-3.1 3.1h-4V17h4c2.76 0 5-2.24 5-5s-2.24-5-5-5z',
    async () => {
      try {
        const authed = await ensureAuthenticated();
        if (!authed) return;
        const data = await fetchBookingLink();
        insertTextIntoEditor(editor, `Book with me: ${data.booking_link}`);
      } catch (err) {
        console.error(err);
        alert(err.message || 'Unable to fetch booking link.');
      }
    }
  ));

  // Divider
  const divider = document.createElement('div');
  divider.className = 'calautobot-divider';
  dropdown.appendChild(divider);

  // 3. Static Info Text
  const infoItem = document.createElement('div');
  infoItem.className = 'calautobot-info-item';
  infoItem.innerHTML = `
    <svg viewBox="0 0 24 24"><path d="M9 21c0 .55.45 1 1 1h4c.55 0 1-.45 1-1v-1H9v1zm3-19C8.14 2 5 5.14 5 9c0 2.38 1.19 4.47 3 5.74V17c0 .55.45 1 1 1h6c.55 0 1-.45 1-1v-2.26c1.81-1.27 3-3.36 3-5.74 0-3.86-3.14-7-7-7zm2.85 11.1l-.85.6V16h-4v-2.3l-.85-.6A4.997 4.997 0 0 1 7 9c0-2.76 2.24-5 5-5s5 2.24 5 5c0 1.63-.8 3.16-2.15 4.1z"/></svg>
    <span><span style="white-space: nowrap">CC <span class="calautobot-email-highlight">Cal@CalAutobot.com</span></span> Let AI handle booking</span>
  `;
  // Prevent click from closing dropdown if user tries to select text
  infoItem.addEventListener('click', (e) => {
    e.stopPropagation();
  });
  dropdown.appendChild(infoItem);

  // Toggle logic
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.classList.toggle('show');
  });

  // Close on outside click
  document.addEventListener('click', () => {
    dropdown.classList.remove('show');
  });

  container.appendChild(btn);
  container.appendChild(dropdown);
  return container;
}

function waitForElement(root, selector, timeout = 2000) {
  return new Promise((resolve) => {
    if (root.querySelector(selector)) {
      return resolve(true);
    }
    const observer = new MutationObserver((mutations, obs) => {
      if (root.querySelector(selector)) {
        obs.disconnect();
        resolve(true);
      }
    });
    observer.observe(root, { childList: true, subtree: true });
    setTimeout(() => {
      observer.disconnect();
      resolve(false);
    }, timeout);
  });
}

function injectControlsForEditor(editor) {
  if (!editor) return;

  // Traverse up to find the main compose container.
  let composeRoot = editor.closest('div[role="dialog"]') ||
    editor.closest('table[role="presentation"]') ||
    editor.closest('table');

  if (!composeRoot) {
    // Fallback: go up 4-5 levels
    composeRoot = editor.parentElement.parentElement.parentElement.parentElement;
  }

  if (!composeRoot) return;

  attachSendInterceptor(composeRoot);
  if (composeRoot.querySelector('.calautobot-container')) return;

  // Strategy 1: Exact text match + role button (most robust)
  const buttons = Array.from(composeRoot.querySelectorAll('div[role="button"]'));
  let sendButton = buttons.find(b => b.textContent.trim().startsWith('Send'));

  // Strategy 2: data-tooltip
  if (!sendButton) {
    sendButton = composeRoot.querySelector('div[role="button"][data-tooltip*="Send"]');
  }

  if (sendButton) {
    console.log('CalAutobot: Found Send button', sendButton);

    // The footer is a table row (tr). The Send button is in a td.
    // We should insert a new td after the Send button's td.
    const sendCell = sendButton.closest('td');
    const sendRow = sendCell ? sendCell.parentElement : null;

    if (sendCell && sendRow && sendRow.tagName === 'TR') {
      const controls = buildDropdownControls(editor, composeRoot);

      // Create a new cell
      const newCell = document.createElement('td');
      newCell.className = 'gU'; // Reuse Gmail's class for consistent spacing
      newCell.style.verticalAlign = 'middle'; // Ensure alignment
      newCell.appendChild(controls);

      // Insert after the send cell
      sendCell.insertAdjacentElement('afterend', newCell);
    } else {
      // Fallback: Insert after the button's immediate wrapper (likely div.dC)
      const controls = buildDropdownControls(editor, composeRoot);
      const wrapper = sendButton.parentElement; // div.dC
      if (wrapper) {
        wrapper.parentElement.insertBefore(controls, wrapper.nextSibling);
      } else {
        sendButton.parentElement.appendChild(controls);
      }
    }
  } else {
    console.log('CalAutobot: Send button not found in root', composeRoot);
    // Fallback to toolbar
    const toolbar = composeRoot.querySelector('div[aria-label="Formatting options"]') ||
      composeRoot.querySelector('tr.btC');

    const controls = buildDropdownControls(editor, composeRoot);
    if (toolbar) {
      if (toolbar.tagName === 'TR') {
        const lastCell = toolbar.lastElementChild;
        if (lastCell) lastCell.appendChild(controls);
        else toolbar.appendChild(controls);
      } else {
        toolbar.parentElement.appendChild(controls);
      }
    } else {
      editor.parentElement.appendChild(controls);
    }
  }
}

function attachSendInterceptor(composeRoot) {
  const sendButton = composeRoot.querySelector('div[role="button"][data-tooltip*="Send"]');
  if (!sendButton || sendButton.getAttribute(SEND_HOOK_ATTR)) return;
  sendButton.setAttribute(SEND_HOOK_ATTR, 'true');
  sendButton.addEventListener('click', () => {
    ensureAuthenticated().then((authed) => {
      if (!authed) return;
      const contacts = collectRecipients(composeRoot);
      sendContactsToAPI(contacts);
    });
  });
}

function scanForEditors() {
  const editors = document.querySelectorAll('div[aria-label="Message Body"].Am.Al.editable');
  editors.forEach((editor) => {
    injectControlsForEditor(editor);
  });
}

const observer = new MutationObserver(() => {
  scanForEditors();
});

function init() {
  scanForEditors();
  observer.observe(document.body, { subtree: true, childList: true });
}

document.addEventListener('DOMContentLoaded', init);
setTimeout(init, 3000);
