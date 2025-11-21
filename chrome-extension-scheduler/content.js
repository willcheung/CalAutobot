const API_BASE = 'https://calautobot.com';
const CONTROL_CLASS = 'calautobot-scheduler-controls';
const SEND_HOOK_ATTR = 'data-calautobot-send-hook';
let authStatus = { checked: false, authenticated: false };

async function ensureAuthenticated() {
  if (authStatus.checked) {
    return authStatus.authenticated;
  }
  try {
    const resp = await fetch(`${API_BASE}/api/user/info`, { credentials: 'include' });
    if (!resp.ok) {
      throw new Error('auth check failed');
    }
    const data = await resp.json();
    authStatus = {
      checked: true,
      authenticated: Boolean(data && data.authenticated)
    };
  } catch (err) {
    console.error('CalAutobot auth check failed', err);
    authStatus = { checked: true, authenticated: false };
  }
  return authStatus.authenticated;
}

async function fetchAvailabilityText() {
  const url = new URL(`${API_BASE}/api/extension/availability_text`);
  url.searchParams.set('count', '3');
  const resp = await fetch(url.toString(), { credentials: 'include' });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || 'Unable to fetch availability');
  }
  return resp.json();
}

async function fetchBookingLink() {
  const resp = await fetch(`${API_BASE}/api/extension/booking_link`, {
    credentials: 'include'
  });
  if (!resp.ok) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.error || 'Unable to fetch booking link');
  }
  return resp.json();
}

async function sendContactsToAPI(recipients) {
  if (!recipients || !recipients.length) {
    return;
  }
  try {
    await fetch(`${API_BASE}/api/extension/contacts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ contacts: recipients })
    });
  } catch (err) {
    console.warn('Failed to sync contacts', err);
  }
}

function insertTextIntoEditor(editor, text) {
  if (!editor) return;
  editor.focus();
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(editor);
  range.collapse(false);
  selection.removeAllRanges();
  selection.addRange(range);
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

function buildControls(editor) {
  const container = document.createElement('div');
  container.className = CONTROL_CLASS;

  const availabilityBtn = document.createElement('button');
  availabilityBtn.textContent = 'Insert availability';
  availabilityBtn.type = 'button';
  availabilityBtn.addEventListener('click', async () => {
    try {
      const authed = await ensureAuthenticated();
      if (!authed) {
        alert('Please sign in to calautobot.com in this browser first.');
        return;
      }
      availabilityBtn.disabled = true;
      availabilityBtn.textContent = 'Fetching…';
      const data = await fetchAvailabilityText();
      insertTextIntoEditor(editor, data.text);
    } catch (err) {
      console.error(err);
      alert(err.message || 'Unable to fetch availability.');
    } finally {
      availabilityBtn.disabled = false;
      availabilityBtn.textContent = 'Insert availability';
    }
  });

  const bookingBtn = document.createElement('button');
  bookingBtn.textContent = 'Insert booking link';
  bookingBtn.type = 'button';
  bookingBtn.addEventListener('click', async () => {
    try {
      const authed = await ensureAuthenticated();
      if (!authed) {
        alert('Please sign in to calautobot.com in this browser first.');
        return;
      }
      bookingBtn.disabled = true;
      bookingBtn.textContent = 'Fetching…';
      const data = await fetchBookingLink();
      insertTextIntoEditor(editor, `Book with me: ${data.booking_link}`);
    } catch (err) {
      console.error(err);
      alert(err.message || 'Unable to fetch booking link.');
    } finally {
      bookingBtn.disabled = false;
      bookingBtn.textContent = 'Insert booking link';
    }
  });

  container.appendChild(availabilityBtn);
  container.appendChild(bookingBtn);
  return container;
}

function injectControlsForEditor(editor) {
  if (!editor) return;
  const composeRoot = editor.closest('div[role="presentation"]') || editor.parentElement;
  if (!composeRoot) return;
  attachSendInterceptor(composeRoot);
  if (composeRoot.querySelector(`.${CONTROL_CLASS}`)) return;

  const controls = buildControls(editor);
  const referenceNode = editor.parentElement;
  if (referenceNode) {
    referenceNode.insertBefore(controls, editor);
  } else {
    composeRoot.appendChild(controls);
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
