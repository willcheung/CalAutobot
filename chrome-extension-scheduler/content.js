const CONTROL_CLASS = 'calautobot-scheduler-controls';

let authStatus = { checked: false, authenticated: false };
let userEmail = null;

// --- Auth & API Helpers ---

function extractGmailUserEmail() {
  // InboxSDK provides user info, but we might need this before SDK loads or as fallback
  const accountButton = document.querySelector('a[aria-label*="Google Account:"]');
  if (accountButton) {
    const label = accountButton.getAttribute('aria-label') || '';
    const match = label.match(/\(([^)]+@[^)]+)\)/);
    if (match && match[1]) {
      return match[1].trim().toLowerCase();
    }
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

  // Try to get email from SDK if possible, otherwise fallback to DOM
  if (!userEmail) {
    userEmail = extractGmailUserEmail();
  }

  if (!userEmail) {
    // If we are inside InboxSDK load, we might get it from sdk.User.getEmailAddress()
    // But for now, let's assume DOM worked or we'll fail gracefully
    console.warn('CalAutobot: Could not detect user email yet.');
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
    try {
      const loginResp = await sendMessageToBackground('LOGIN');
      if (loginResp && loginResp.authenticated) {
        authStatus = { checked: true, authenticated: true };
      }
    } catch (err) {
      console.error('Login error:', err);
      alert('Unable to sign in. Please try again later.');
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

// --- UI Helpers ---

function createDropdown(composeView, setButtonLoading = () => { }) {
  const dropdown = document.createElement('div');
  dropdown.className = 'calautobot-dropdown';
  // Position will be handled by the button click or a library
  // For now, we'll style it to appear near the cursor or button

  // Helper to set loading state (we'll need to pass the button element if we want to change its icon)
  // For now, we'll just show a spinner in the dropdown or use a global loading indicator

  const createItem = (text, iconPath, onClick) => {
    const item = document.createElement('div');
    item.className = 'calautobot-item';
    item.innerHTML = `
      <svg viewBox="0 0 24 24"><path d="${iconPath}"/></svg>
      ${text}
    `;
    item.addEventListener('click', async (e) => {
      e.stopPropagation();
      // Close dropdown
      if (dropdown.parentElement) dropdown.parentElement.removeChild(dropdown);

      setButtonLoading(true);
      try {
        await onClick();
      } catch (err) {
        console.error(err);
      } finally {
        setButtonLoading(false);
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

        // Show "Inserting..." status?
        const data = await fetchAvailabilityText();
        composeView.insertTextIntoBodyAtCursor(data.text);
      } catch (err) {
        console.error(err);
        if (!err.message || !err.message.includes('reconnect your calendar')) {
          alert(err.message || 'Unable to fetch availability.');
        }
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
        composeView.insertTextIntoBodyAtCursor(`Book with me: ${data.booking_link}`);
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
    <span><span style="white-space: nowrap">CC <span class="calautobot-email-highlight">Cal@CalAutobot.com</span></span>, let AI handle booking</span>
  `;
  // Make it interactive
  infoItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    // Close dropdown
    if (dropdown.parentElement) dropdown.parentElement.removeChild(dropdown);

    try {
      const ccRecipients = composeView.getCcRecipients();
      const currentEmails = ccRecipients.map(r => r.emailAddress);
      const botEmail = 'Cal@CalAutobot.com';

      if (!currentEmails.includes(botEmail)) {
        composeView.setCcRecipients([...currentEmails, botEmail]);
      }
    } catch (err) {
      console.error('Failed to add CC:', err);
    }
  });
  dropdown.appendChild(infoItem);

  return dropdown;
}

// --- InboxSDK Initialization ---

InboxSDK.load(2, 'sdk_scheduler_142f817c3e').then((sdk) => {

  // Inject dynamic CSS for the icon URL to ensure it resolves correctly
  const iconUrl = chrome.runtime.getURL('icons/icon48.png');
  const style = document.createElement('style');
  style.textContent = `
    .calautobot-icon {
      background-image: url('${iconUrl}') !important;
    }
  `;
  document.head.appendChild(style);

  // Get user email from SDK if possible
  const user = sdk.User.getEmailAddress();
  if (user) {
    userEmail = user;
  }

  sdk.Compose.registerComposeViewHandler((composeView) => {

    // Generate a unique class for this specific button instance to find it later
    const uniqueClass = 'calautobot-id-' + Math.random().toString(36).substr(2, 9);

    // Generate unique compose ID for tracking state
    const composeId = 'compose-' + Math.random().toString(36).substr(2, 9);

    // 1. Add Button
    composeView.addButton({
      title: 'CalAutobot',
      iconClass: `calautobot-icon ${uniqueClass}`,
      hasDropdown: true,
      onClick: (event) => {
        // Find the specific icon element using our unique class
        const iconEl = document.querySelector(`.${uniqueClass}`);

        const setButtonLoading = (loading) => {
          if (iconEl) {
            if (loading) iconEl.classList.add('calautobot-loading');
            else iconEl.classList.remove('calautobot-loading');
          }
        };

        // If hasDropdown is true, event.dropdown is the DropdownView
        // We can set its content
        if (event.dropdown) {
          const dropdownContent = createDropdown(composeView, setButtonLoading);
          // We need to style the dropdown to not conflict with SDK styles or use SDK's way
          // SDK dropdown expects us to set content on event.dropdown.el
          event.dropdown.el.appendChild(dropdownContent);

          // Ensure our dropdown is visible (our CSS might have .calautobot-dropdown { display: none } by default)
          dropdownContent.style.display = 'block';
          dropdownContent.style.position = 'static'; // SDK handles positioning
          dropdownContent.style.boxShadow = 'none'; // SDK handles shadow
          dropdownContent.style.border = 'none'; // SDK handles border
        }
      },
    });

    // 2. Add Tracking Toggle
    (async () => {
      try {
        const trackingEnabled = await isTrackingEnabled();

        // Create tracking toggle element
        const trackingToggle = composeView.addStatusBar({
          height: 20,
          orderHint: 0,
        });

        const toggleContainer = document.createElement('div');
        toggleContainer.className = 'calautobot-tracking-toggle';
        toggleContainer.innerHTML = `
          <label class="calautobot-tracking-label">
            <input type="checkbox" class="calautobot-tracking-checkbox" ${trackingEnabled ? 'checked' : ''} />
            <svg class="calautobot-tracking-icon" viewBox="0 0 24 24" width="16" height="16">
              <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
            </svg>
            <span class="calautobot-tracking-text">Track email opens</span>
          </label>
        `;

        const checkbox = toggleContainer.querySelector('.calautobot-tracking-checkbox');

        // Store initial state
        await storeComposeTracking(composeId, {
          enabled: trackingEnabled,
          trackingId: null, // Will be generated on send
        });

        // Handle checkbox change
        checkbox.addEventListener('change', async (e) => {
          const enabled = e.target.checked;
          await setTrackingEnabled(enabled);
          await storeComposeTracking(composeId, {
            enabled: enabled,
            trackingId: null,
          });
        });

        trackingToggle.el.appendChild(toggleContainer);
      } catch (err) {
        console.warn('CalAutobot: Failed to add tracking toggle', err);
      }
    })();

    // 3. Intercept Send to sync contacts and inject tracking pixel
    composeView.on('presending', async (event) => {
      try {
        const authed = await ensureAuthenticated();
        if (!authed) return;

        const to = composeView.getToRecipients();
        const cc = composeView.getCcRecipients();
        const bcc = composeView.getBccRecipients();
        const allRecipients = [...to, ...cc, ...bcc];

        // Exclude the bot email and map to backend format
        const recipients = allRecipients
          .filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
          .map(r => ({
            email: r.emailAddress,
            name: r.name
          }));

        // Sync contacts to API
        await sendContactsToAPI(recipients);

        // Check if tracking is enabled for this compose
        const trackingState = await getComposeTracking(composeId);
        if (trackingState && trackingState.enabled) {
          try {
            // Generate tracking ID
            const trackingId = generateTrackingId();

            // Get email body HTML
            const bodyHtml = composeView.getHTMLContent();

            // Inject tracking pixel
            const modifiedHtml = injectTrackingPixel(bodyHtml, trackingId);

            // Update email body with pixel
            composeView.setBodyHTML(modifiedHtml);

            // Store tracking ID for post-send API call
            await storeComposeTracking(composeId, {
              enabled: true,
              trackingId: trackingId,
            });

            console.log('CalAutobot: Tracking pixel injected', trackingId);
          } catch (err) {
            console.error('CalAutobot: Failed to inject tracking pixel', err);
          }
        }
      } catch (err) {
        console.warn('CalAutobot: Failed to process presending', err);
      }
    });

    // 4. After Send - Create tracking request
    composeView.on('sent', async (event) => {
      try {
        const trackingState = await getComposeTracking(composeId);
        if (!trackingState || !trackingState.trackingId) {
          return; // Tracking not enabled for this email
        }

        const authed = await ensureAuthenticated();
        if (!authed) return;

        // Get recipients
        const to = composeView.getToRecipients();
        const cc = composeView.getCcRecipients();
        const bcc = composeView.getBccRecipients();

        const toRecipients = to
          .filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
          .map(r => ({ email: r.emailAddress, name: r.name || '' }));
        const ccRecipients = cc
          .filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
          .map(r => ({ email: r.emailAddress, name: r.name || '' }));
        const bccRecipients = bcc
          .filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
          .map(r => ({ email: r.emailAddress, name: r.name || '' }));

        // Get subject
        const subject = composeView.getSubject() || '(no subject)';

        // Get thread ID if available
        const threadId = composeView.getThreadID();

        // Create tracking request via API
        await createTrackingRequest({
          trackingId: trackingState.trackingId,
          subject: subject,
          recipients: toRecipients,
          ccRecipients: ccRecipients,
          bccRecipients: bccRecipients,
          gmailThreadId: threadId || null,
          userEmail: userEmail,
        });

        console.log('CalAutobot: Tracking request created', trackingState.trackingId);

        // Clear compose tracking state
        await clearComposeTracking(composeId);
      } catch (err) {
        console.error('CalAutobot: Failed to create tracking request', err);
        // Clean up compose tracking even on error
        await clearComposeTracking(composeId);
      }
    });

  });
});

