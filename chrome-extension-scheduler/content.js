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

  // 3. Track email opens (checkbox - get reference to compose state)
  const trackingCheckbox = document.createElement('div');
  trackingCheckbox.className = 'calautobot-item';
  trackingCheckbox.style.cssText = 'cursor: pointer;';
  trackingCheckbox.innerHTML = `
    <input type="checkbox" class="calautobot-menu-tracking-checkbox" style="margin-right: 12px; cursor: pointer;" />
    <span>Track email opens</span>
  `;

  // Will be initialized when dropdown opens
  trackingCheckbox._composeView = composeView;
  dropdown.appendChild(trackingCheckbox);

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

// --- Email Tracking Dashboard ---

async function showTrackingDropdown(dropdown) {
  const dropdownEl = createDashboardElement();
  dropdown.el.appendChild(dropdownEl);

  // Load tracking data
  loadTrackingData(dropdownEl);
}

function createDashboardElement() {
  const container = document.createElement('div');
  container.style.cssText = 'min-width: 450px; max-width: 500px; max-height: 600px; overflow-y: auto; padding: 0; background: white;';
  container.innerHTML = `
    <div id="tracking-dashboard-content">
      <div style="padding: 12px; margin-bottom: 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; text-align: center;">
        <a href="https://calautobot.com" target="_blank" style="
          display: inline-flex;
          align-items: center;
          gap: 8px;
          text-decoration: none;
          color: white;
        ">
          <h3 style="margin: 0; font-size: 15px; font-weight: 600; letter-spacing: 0.3px;">CalAutobot Email Tracking</h3>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
            <polyline points="15 3 21 3 21 9"></polyline>
            <line x1="10" y1="14" x2="21" y2="3"></line>
          </svg>
        </a>
      </div>
      <div style="padding: 12px; text-align: left;">
        <div id="tracking-loading" style="padding: 24px; color: #5f6368; text-align: center;">
          <div style="font-size: 12px;">Loading...</div>
        </div>
        <div id="tracking-error" style="display: none; padding: 24px; color: #d93025; text-align: center;">
          <div style="font-size: 12px;">Failed to load</div>
          <button id="retry-btn" style="margin-top: 12px; padding: 6px 12px; cursor: pointer; background: #1a73e8; color: white; border: none; border-radius: 4px; font-size: 12px;">Retry</button>
        </div>
        <div id="tracking-empty" style="display: none; padding: 24px; color: #5f6368; text-align: center;">
          <div style="font-size: 12px;">No tracked emails yet</div>
        </div>
        <div id="tracking-list" style="display: none; text-align: left;"></div>
      </div>
    </div>
  `;
  return container;
}

function renderTrackingData(data, listEl, emptyEl, lastViewedAt = null) {
  if (!data.success || !data.requests || data.requests.length === 0) {
    emptyEl.style.display = 'block';
    listEl.style.display = 'none';
    return;
  }

  // Use lastViewedAt from parameter or from data
  // Ensure timestamp ends with 'Z' for proper UTC parsing
  let viewedAtStr = lastViewedAt || data.tracking_last_viewed_at;
  if (viewedAtStr && !viewedAtStr.endsWith('Z')) {
    viewedAtStr += 'Z';
  }
  const viewedAt = viewedAtStr ? new Date(viewedAtStr) : null;
  // console.log('CalAutobot: Rendering with tracking_last_viewed_at:', {
  //   raw: viewedAtStr,
  //   parsed: viewedAt?.toISOString(),
  //   source: lastViewedAt ? 'parameter' : 'data'
  // });

  // Render tracking list (grouped by gmail_thread_id)
  listEl.style.display = 'block';
  emptyEl.style.display = 'none';

  // Group requests by thread ID
  const threadGroups = new Map();
  data.requests.forEach(req => {
    const threadId = req.gmail_thread_id || `no-thread-${req.id}`;
    if (!threadGroups.has(threadId)) {
      threadGroups.set(threadId, []);
    }
    threadGroups.get(threadId).push(req);
  });

  // First, mark which requests have new opens since last viewed
  const allRequests = Array.from(threadGroups.values())
    .map(group => group.sort((a, b) => new Date(b.sent_at) - new Date(a.sent_at)))
    .flat();

  const requestsWithUnread = allRequests.map(req => {
    // If never viewed (viewedAt is null), treat all opened emails as unread
    // Otherwise, check if email was opened after last view
    const hasNewOpens = req.last_opened_at && (
      !viewedAt || new Date(req.last_opened_at) > viewedAt
    );
  // console.log(`CalAutobot: Unread check for "${req.subject}":`, {
  //     last_opened_at: req.last_opened_at,
  //     viewedAt: viewedAt?.toISOString(),
  //     isAfter: req.last_opened_at && viewedAt && new Date(req.last_opened_at) > viewedAt,
  //     hasNewOpens
  //   });
    return { ...req, isUnread: hasNewOpens };
  });

  // Sort: unread first (by last_opened_at DESC), then read (by last_opened_at or sent_at DESC)
  const sortedRequests = requestsWithUnread.sort((a, b) => {
    // Unread items always come first
    if (a.isUnread && !b.isUnread) return -1;
    if (!a.isUnread && b.isUnread) return 1;

    // Within same unread status, sort by last activity (last_opened_at or sent_at)
    const aTime = a.last_opened_at ? new Date(a.last_opened_at) : new Date(a.sent_at);
    const bTime = b.last_opened_at ? new Date(b.last_opened_at) : new Date(b.sent_at);
    return bTime - aTime;
  });

  listEl.innerHTML = requestsWithUnread.map(req => createTrackingCard(req)).join('');

  // Add event listeners to expand buttons (after DOM is updated)
  listEl.querySelectorAll('.expand-toggle').forEach(button => {
    button.addEventListener('click', function () {
      const cardId = this.getAttribute('data-card-id');
      toggleExpand(cardId);
    });
  });
}

async function loadTrackingData(containerEl) {
  const loadingEl = containerEl.querySelector('#tracking-loading');
  const errorEl = containerEl.querySelector('#tracking-error');
  const emptyEl = containerEl.querySelector('#tracking-empty');
  const listEl = containerEl.querySelector('#tracking-list');

  try {
  // console.log('CalAutobot: Loading tracking data for user:', userEmail);

    // Try to load cached data first for instant display
    const cached = await chrome.storage.local.get(['cachedTrackingData']);
    if (cached.cachedTrackingData && cached.cachedTrackingData.requests) {
  // console.log('CalAutobot: Displaying cached data instantly - requests count:', cached.cachedTrackingData.requests.length);
      loadingEl.style.display = 'none';
      renderTrackingData(cached.cachedTrackingData, listEl, emptyEl);
    } else {
  // console.log('CalAutobot: No cached data available, showing loading state');
    }

    // Fetch fresh data in background to update cache
    const result = await sendMessageToBackground('FETCH_TRACKING_REQUESTS', {
      userEmail: userEmail
    });

  // console.log('CalAutobot: Tracking result:', result);

    if (!result.success) {
      throw new Error(result.error || 'Failed to fetch tracking data');
    }

    const data = result.data;
  // console.log('CalAutobot: Tracking data received - requests count:', data.requests?.length || 0);
  // console.log('CalAutobot: Full tracking data:', data);

    loadingEl.style.display = 'none';

    // Render fresh data with highlights based on CURRENT tracking_last_viewed_at
    renderTrackingData(data, listEl, emptyEl);

    // Mark dashboard as viewed in backend (clears unread count for NEXT open)
    const markViewedResult = await sendMessageToBackground('MARK_TRACKING_VIEWED', { userEmail });

    // Update cache with SERVER's new tracking_last_viewed_at for next dashboard open
    // IMPORTANT: Use server timestamp to avoid clock skew issues
    if (markViewedResult.success && markViewedResult.data.tracking_last_viewed_at) {
      const updatedData = { ...data, tracking_last_viewed_at: markViewedResult.data.tracking_last_viewed_at };
  // console.log('CalAutobot: Updating cache with new tracking_last_viewed_at:', markViewedResult.data.tracking_last_viewed_at);
      await chrome.storage.local.set({ cachedTrackingData: updatedData });
    } else {
      console.warn('CalAutobot: Failed to update cache - mark viewed result:', markViewedResult);
    }

  } catch (error) {
    console.error('Failed to load tracking data:', error);
    console.error('Error stack:', error.stack);
    console.error('Error message:', error.message);
    loadingEl.style.display = 'none';

    // Check if it's an authentication error
    const isAuthError = error.message && (
      error.message.includes('Not authenticated') ||
      error.message.includes('authentication') ||
      error.message.includes('unauthorized') ||
      error.message.includes('sign in') ||
      error.message.includes('OAuth2') ||
      error.message.includes('oauth')
    );

    if (isAuthError) {
      // Show sign-in UI instead of error (using same button as homepage)
      errorEl.innerHTML = `
        <div style="text-align: center; padding: 40px 20px;">
          <div style="font-size: 16px; color: #5f6368; margin-bottom: 24px;">Sign in to view your email tracking</div>
          <button id="signin-btn" style="
            display: inline-flex;
            align-items: center;
            gap: 12px;
            background: white;
            color: #3c4043;
            border: 1px solid #dadce0;
            border-radius: 4px;
            padding: 10px 24px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
            transition: all 0.2s;
            font-family: 'Google Sans', 'Roboto', Arial, sans-serif;
          " onmouseover="this.style.boxShadow='0 3px 6px rgba(0,0,0,0.16), 0 3px 6px rgba(0,0,0,0.23)'; this.style.borderColor='#d2e3fc'; this.style.background='#f8f9fa';" onmouseout="this.style.boxShadow='0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24)'; this.style.borderColor='#dadce0'; this.style.background='white';">
            <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false" style="flex-shrink: 0;">
              <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/>
              <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
              <path fill="#FBBC05" d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/>
              <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/>
            </svg>
            Sign in with Google
          </button>
        </div>
      `;
      errorEl.style.display = 'block';

      const signinBtn = errorEl.querySelector('#signin-btn');
      if (signinBtn) {
        signinBtn.addEventListener('click', async () => {
          try {
            // Reuse the same auth flow as "Insert availability"
            const authed = await ensureAuthenticated();
            if (authed) {
              // Redirect to onboarding page (same flow as "Insert availability")
              const onboardingUrl = 'https://calautobot.com/onboarding';
              window.open(onboardingUrl, '_blank');

              // Also reload tracking data after successful auth
              errorEl.style.display = 'none';
              loadingEl.style.display = 'block';
              loadTrackingData(containerEl);
            }
          } catch (err) {
            console.error('Sign in failed:', err);
            alert('Failed to sign in. Please try again.');
          }
        });
      }
    } else {
      // Show regular error with retry button
      errorEl.style.display = 'block';
      const errorMsg = errorEl.querySelector('div:nth-child(2)');
      if (errorMsg) {
        errorMsg.textContent = `Failed to load tracking data: ${error.message || 'Unknown error'}`;
      }

      const retryBtn = errorEl.querySelector('#retry-btn');
      if (retryBtn) {
        retryBtn.addEventListener('click', () => {
          errorEl.style.display = 'none';
          loadingEl.style.display = 'block';
          loadTrackingData(containerEl);
        });
      }
    }
  }
}

function createTrackingCard(req) {
  const hasOpened = req.first_opened_at !== null;
  const openedRecipients = req.recipients.filter(r => r.opened);

  // Format times
  const sentTime = formatDateTime(new Date(req.sent_at));
  const openTime = hasOpened ? formatDateTime(new Date(req.last_opened_at)) : null;

  // Build recipient display text for Line 1
  let recipientText = '';
  if (openedRecipients.length === 0) {
    // No one opened - show first recipient
    recipientText = req.recipients[0]?.name || req.recipients[0]?.email || 'Unknown';
  } else if (openedRecipients.length === 1) {
    // One person opened
    recipientText = openedRecipients[0].name || openedRecipients[0].email;
  } else if (openedRecipients.length === 2) {
    // Two people opened
    const name1 = openedRecipients[0].name || openedRecipients[0].email;
    const name2 = openedRecipients[1].name || openedRecipients[1].email;
    recipientText = `${name1}, ${name2}`;
  } else {
    // Three or more people opened
    const name1 = openedRecipients[0].name || openedRecipients[0].email;
    const name2 = openedRecipients[1].name || openedRecipients[1].email;
    const othersCount = openedRecipients.length - 2;
    recipientText = `${name1}, ${name2}, and ${othersCount} other${othersCount > 1 ? 's' : ''}`;
  }

  // Get device type and location from first open
  let deviceIcon = '🖥️'; // Desktop icon
  let deviceLabel = 'Desktop';
  let locationInfo = '📍 Unknown location';

  if (req.events && req.events.length > 0) {
    const firstEvent = req.events[0];

    // Determine device type (Mobile vs Desktop)
    const device = firstEvent.user_agent_parsed?.device || 'Desktop';
    if (device === 'Mobile' || device === 'Tablet') {
      deviceIcon = '📱';
      deviceLabel = 'Mobile';
    }

    // Format location
    if (firstEvent.city && firstEvent.country_code) {
      locationInfo = `📍 ${firstEvent.city}, ${firstEvent.country_code}`;
    } else if (firstEvent.country_code) {
      locationInfo = `📍 ${firstEvent.country_code}`;
    }
  }

  // Build expanded events HTML (collapsed by default)
  let expandedHtml = '';
  if (req.events && req.events.length > 0) {
    // Sort events by opened_at DESC
    const sortedEvents = [...req.events].sort((a, b) =>
      new Date(b.opened_at) - new Date(a.opened_at)
    );

    expandedHtml = `
      <div class="open-details" style="display: none; margin-top: 6px; padding-top: 4px; padding-left: 8px; border-left: 2px solid #e8eaed;">
        ${sortedEvents.map((event, idx) => {
      const eventTime = formatDateTime(new Date(event.opened_at));

      // Device info
      const device = event.user_agent_parsed?.device || 'Desktop';
      let deviceIconExp = '🖥️';
      let deviceLabelExp = 'Desktop';
      if (device === 'Mobile' || device === 'Tablet') {
        deviceIconExp = '📱';
        deviceLabelExp = 'Mobile';
      }

      // Location info
      let locationExp = '📍 Unknown location';
      if (event.city && event.country_code) {
        locationExp = `📍 ${event.city}, ${event.country_code}`;
      } else if (event.country_code) {
        locationExp = `📍 ${event.country_code}`;
      }

      return `
            <div style="font-size: 11px; color: #5f6368; padding: 3px 0;">
              ${eventTime} • ${deviceIconExp} ${deviceLabelExp} • ${locationExp}
            </div>
          `;
    }).join('')}
      </div>
    `;
  }

  const cardId = `tracking-card-${req.id}`;
  const isUnread = req.isUnread || false;

  return `
    <div class="tracking-card" id="${cardId}" style="
      padding: 8px 12px;
      margin-bottom: 0;
      font-size: 12px;
      line-height: 1.3;
      border-bottom: 1px solid #e8eaed;
      background: ${isUnread ? '#e8f0fe' : 'transparent'};
      border-left: ${isUnread ? '3px solid #1967d2' : '3px solid transparent'};
      margin-left: -12px;
      margin-right: -12px;
    ">
      <!-- Line 1: Recipient(s) opened Subject -->
      <div style="color: #202124; margin-bottom: 3px;">
        <strong style="color: #1967d2;">${recipientText}</strong> ${hasOpened ? 'opened' : 'received'}
        <strong>${req.subject || '(No subject)'}</strong>
      </div>

      <!-- Line 2: Time + Device + Location -->
      <div style="color: #5f6368; font-size: 11px; margin-bottom: 2px;">
        ${hasOpened ? openTime : sentTime} • ${deviceIcon} ${deviceLabel} • ${locationInfo}
        ${req.events && req.events.length > 1 ? `
          <button class="expand-toggle" data-card-id="${cardId}" data-open-count="${req.events.length}" style="
            background: none;
            border: none;
            color: #1967d2;
            cursor: pointer;
            padding: 0;
            margin-left: 4px;
            font-size: 11px;
          ">▼ ${req.events.length} opens</button>
        ` : ''}
      </div>

      <!-- Expanded details -->
      ${expandedHtml}
    </div>
  `;
}

/**
 * Toggle expand/collapse for tracking card
 */
function toggleExpand(cardId) {
  const card = document.getElementById(cardId);
  if (!card) return;

  const details = card.querySelector('.open-details');
  const button = card.querySelector('.expand-toggle');

  if (!details || !button) return;

  const isExpanded = details.style.display === 'block';
  details.style.display = isExpanded ? 'none' : 'block';

  // Get the open count from the button's data attribute
  const openCount = button.getAttribute('data-open-count');
  button.textContent = isExpanded ? `▼ ${openCount} opens` : `▲ ${openCount} opens`;
}

/**
 * Format date/time: relative + absolute in parentheses
 * E.g., "2 hours ago (Oct 17, 9:01 PM)"
 * @param {Date} date - Date to format
 * @returns {string} Formatted date string
 */
function formatDateTime(date) {
  const now = new Date();
  const diffMs = now - date;
  const diffHours = diffMs / (1000 * 60 * 60);

  // Format absolute time
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const month = months[date.getMonth()];
  const day = date.getDate();
  let hours = date.getHours();
  const minutes = date.getMinutes().toString().padStart(2, '0');
  const ampm = hours >= 12 ? 'PM' : 'AM';
  hours = hours % 12 || 12;
  const absoluteTime = `${month} ${day}, ${hours}:${minutes} ${ampm}`;

  // If less than 24 hours, show relative time with absolute in parentheses
  if (diffHours < 24) {
    const diffMinutes = Math.floor(diffMs / (1000 * 60));

    let relativeTime;
    if (diffMinutes < 1) {
      relativeTime = 'just now';
    } else if (diffMinutes < 60) {
      relativeTime = `${diffMinutes} minute${diffMinutes !== 1 ? 's' : ''} ago`;
    } else {
      const hrs = Math.floor(diffMinutes / 60);
      relativeTime = `${hrs} hour${hrs !== 1 ? 's' : ''} ago`;
    }

    return `${relativeTime} (${absoluteTime})`;
  }

  // If 24 hours or more, show only absolute time
  return absoluteTime;
}

function getTimeAgo(date) {
  const seconds = Math.floor((new Date() - date) / 1000);

  const intervals = {
    year: 31536000,
    month: 2592000,
    week: 604800,
    day: 86400,
    hour: 3600,
    minute: 60
  };

  for (const [unit, secondsInUnit] of Object.entries(intervals)) {
    const interval = Math.floor(seconds / secondsInUnit);
    if (interval >= 1) {
      return `${interval} ${unit}${interval !== 1 ? 's' : ''} ago`;
    }
  }

  return 'just now';
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

  // Add Toolbar Button for Email Tracking Dashboard
  // Using addToolbarButtonForApp - places button in top-right toolbar area
  // console.log('CalAutobot: Adding tracking toolbar button...');
  let trackingButton = null;
  let updateTrackingBadge = null; // Will be defined after button creation

  try {
    trackingButton = sdk.Toolbars.addToolbarButtonForApp({
      title: 'Email Tracking',
      iconUrl: chrome.runtime.getURL('icons/icon48.png'),
      onClick: function (event) {
  // console.log('CalAutobot: Tracking button clicked', event);

        // Reset badge when opened (updates lastDashboardCheck timestamp)
        chrome.storage.local.set({
          lastDashboardCheck: new Date().toISOString(),
          unreadTrackingCount: 0
        });

        // Clear badge immediately
        updateTrackingBadge(0);

        showTrackingDropdown(event.dropdown);
      }
    });
  // console.log('CalAutobot: Tracking toolbar button added successfully');

    // Style the button to look like Gmail's native buttons (white background with border)
    setTimeout(() => {
      const icon = document.querySelector('img[src*="icon48.png"]');
      if (icon) {
        const appButton = icon.closest('.inboxsdk__appButton') || icon.parentElement?.parentElement;
        if (appButton) {
          appButton.style.cssText = `
            background: white !important;
            border: 1px solid #dadce0 !important;
            border-radius: 20px !important;
            padding: 8px 16px !important;
            margin: 0 8px !important;
            cursor: pointer !important;
            transition: background-color 0.2s, box-shadow 0.2s !important;
          `;

          // Add hover effect
          appButton.addEventListener('mouseenter', () => {
            appButton.style.backgroundColor = '#f8f9fa';
            appButton.style.boxShadow = '0 1px 2px 0 rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15)';
          });
          appButton.addEventListener('mouseleave', () => {
            appButton.style.backgroundColor = 'white';
            appButton.style.boxShadow = 'none';
          });
        }
      }
    }, 500);

    // Add custom badge element to button (InboxSDK doesn't have built-in badge support)
    updateTrackingBadge = function (count) {
      // Find the app button container
      const icon = document.querySelector('img[src*="icon48.png"]');
      if (!icon) return;

      // Find the app button container (parent of icon)
      const appButton = icon.closest('.inboxsdk__appButton') || icon.parentElement?.parentElement;
      if (!appButton) return;

      // Remove existing badge
      const existingBadge = appButton.querySelector('.calautobot-badge');
      if (existingBadge) {
        existingBadge.remove();
      }

      // Add new badge if count > 0
      if (count > 0) {
        const badge = document.createElement('span');
        badge.className = 'calautobot-badge';
        badge.textContent = count > 99 ? '99+' : count.toString();
        badge.style.cssText = `
          display: inline-flex;
          align-items: center;
          justify-content: center;
          margin-left: 6px;
          background: #1a73e8;
          color: white;
          border-radius: 50%;
          width: 20px;
          height: 20px;
          font-size: 11px;
          font-weight: bold;
          text-align: center;
          box-shadow: 0 1px 2px rgba(0,0,0,0.2);
          vertical-align: middle;
        `;

        // Append to app button container (will appear after title text)
        appButton.appendChild(badge);
      }
    }

    // Initialize badge from storage
    chrome.storage.local.get(['unreadTrackingCount'], (result) => {
      const count = result.unreadTrackingCount || 0;
      if (count > 0) {
        updateTrackingBadge(count);
      }
    });

    // Listen for badge updates from background script
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
      if (message.action === 'UPDATE_TRACKING_BADGE') {
        updateTrackingBadge(message.count);
      }
    });

  } catch (err) {
    console.error('CalAutobot: Failed to add tracking button', err);
  }

  sdk.Compose.registerComposeViewHandler((composeView) => {

    // Generate a unique class for this specific button instance to find it later
    const uniqueClass = 'calautobot-id-' + Math.random().toString(36).substr(2, 9);

    // Tracking state for this compose (simple in-memory object like needle)
    const trackingState = {
      enabled: false,
      trackingId: null,
      recipients: { to: [], cc: [], bcc: [] },  // Capture recipients in real-time
      subject: null,
      threadId: null
    };

    // Pre-generate tracking ID when compose opens (so it's ready if tracking is enabled)
    trackingState.trackingId = generateTrackingId();

    // Default tracking to enabled (will be overridden by toggle if it loads successfully)
    trackingState.enabled = true;

    // Flag to track if pixel has been injected
    let pixelInjected = false;

    // Function to inject pixel into body (called multiple times to ensure it sticks)
    const ensurePixelInjected = () => {
      if (!trackingState.enabled || !trackingState.trackingId) return;

      try {
        const currentHtml = composeView.getHTMLContent();
        if (!currentHtml.includes('tracking/pixel')) {
          const modifiedHtml = injectTrackingPixel(currentHtml, trackingState.trackingId);
          composeView.setBodyHTML(modifiedHtml);
  // console.log('CalAutobot: Pixel injected into compose body');
        }
      } catch (err) {
        console.warn('CalAutobot: Failed to ensure pixel injected', err);
      }
    };

    // Capture recipients in real-time as they change (BEFORE presending)
    // This is critical because Gmail clears recipients before presending fires
    const updateRecipients = () => {
      try {
        const to = composeView.getToRecipients();
        const cc = composeView.getCcRecipients();
        const bcc = composeView.getBccRecipients();

        const newRecipients = {
          to: to.filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
            .map(r => ({ email: r.emailAddress, name: r.name || '' })),
          cc: cc.filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
            .map(r => ({ email: r.emailAddress, name: r.name || '' })),
          bcc: bcc.filter(r => r.emailAddress.toLowerCase() !== 'cal@calautobot.com')
            .map(r => ({ email: r.emailAddress, name: r.name || '' }))
        };

        const newTotal = newRecipients.to.length + newRecipients.cc.length + newRecipients.bcc.length;
        const currentTotal = trackingState.recipients.to.length +
          trackingState.recipients.cc.length +
          trackingState.recipients.bcc.length;

        // Only update if new recipients exist, OR if we don't have any captured yet
        // This prevents Gmail from clearing our captured recipients before send
        if (newTotal > 0 || currentTotal === 0) {
          trackingState.recipients = newRecipients;
          trackingState.subject = composeView.getSubject() || '(no subject)';
          trackingState.threadId = composeView.getThreadID();

          // console.log('CalAutobot: Recipients updated:', {
          //   to: trackingState.recipients.to.length,
          //   cc: trackingState.recipients.cc.length,
          //   bcc: trackingState.recipients.bcc.length,
          //   total: newTotal
          // });
        } else {
  // console.log('CalAutobot: Ignoring empty recipients update (keeping captured recipients)');
        }
      } catch (err) {
        console.warn('CalAutobot: Failed to update recipients', err);
      }
    };

    // Update recipients whenever they change
    composeView.on('recipientsChanged', updateRecipients);

    // Also capture on compose open (for replies with existing recipients)
    updateRecipients();

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

          // Initialize tracking checkbox from current state
          const checkbox = dropdownContent.querySelector('.calautobot-menu-tracking-checkbox');
          if (checkbox) {
            checkbox.checked = trackingState.enabled;

            // Handle checkbox toggle
            checkbox.parentElement.addEventListener('click', async (e) => {
              e.stopPropagation();
              checkbox.checked = !checkbox.checked;
              trackingState.enabled = checkbox.checked;
              await setTrackingEnabled(checkbox.checked);
  // console.log('CalAutobot: Tracking toggled:', checkbox.checked ? 'ON' : 'OFF');
              if (checkbox.checked) {
                ensurePixelInjected();
              }
            });
          }
        }
      },
    });

    // 2. Initialize tracking state
    (async () => {
      const trackingEnabled = await isTrackingEnabled();
      trackingState.enabled = trackingEnabled;
  // console.log('CalAutobot: Tracking initialized with ID:', trackingState.trackingId, 'enabled:', trackingState.enabled);

      // Inject pixel immediately if tracking is enabled
      if (trackingEnabled) {
        setTimeout(ensurePixelInjected, 100);
      }
    })();

    // 3. Intercept Send to sync contacts and inject tracking pixel
    composeView.on('presending', async (event) => {
      try {
        // Update subject one final time (in case it was changed after recipients were set)
        trackingState.subject = composeView.getSubject() || '(no subject)';
        trackingState.threadId = composeView.getThreadID();

        // Recipients are already captured via recipientsChanged event
        // DO NOT call updateRecipients() here - Gmail clears them before this fires!

        const authed = await ensureAuthenticated();
        if (!authed) return;

        // Build flat list of all recipients for contact sync
        const allRecipients = [
          ...trackingState.recipients.to,
          ...trackingState.recipients.cc,
          ...trackingState.recipients.bcc
        ];

        // console.log('CalAutobot: Presending - using captured recipients:', {
        //   to: trackingState.recipients.to.length,
        //   cc: trackingState.recipients.cc.length,
        //   bcc: trackingState.recipients.bcc.length,
        //   total: allRecipients.length
        // });

        // Safety check - warn if no recipients captured
        if (allRecipients.length === 0) {
          console.warn('CalAutobot: No recipients captured! Tracking may not work properly.');
          console.warn('CalAutobot: This may happen if you send too quickly after adding recipients.');
        }

        // Sync contacts to API
        await sendContactsToAPI(allRecipients);

        // Check if tracking is enabled for this compose
        if (trackingState.enabled && trackingState.trackingId) {
          try {
  // console.log('CalAutobot: Injecting tracking pixel with ID:', trackingState.trackingId);

            // Get email body HTML
            const bodyHtml = composeView.getHTMLContent();
  // console.log('CalAutobot: Original HTML length:', bodyHtml.length);

            // Inject tracking pixel
            const modifiedHtml = injectTrackingPixel(bodyHtml, trackingState.trackingId);
  // console.log('CalAutobot: Modified HTML length:', modifiedHtml.length);
  // console.log('CalAutobot: Modified HTML snippet:', modifiedHtml.substring(modifiedHtml.length - 200));

            // Update email body with pixel
            composeView.setBodyHTML(modifiedHtml);

            // Verify the change took effect
            const verifyHtml = composeView.getHTMLContent();
  // console.log('CalAutobot: Verified HTML length:', verifyHtml.length);
  // console.log('CalAutobot: Pixel present in verified HTML:', verifyHtml.includes('tracking/pixel'));

  // console.log('CalAutobot: Tracking pixel injected successfully');
  // console.log('CalAutobot: Note - If you see ERR_BLOCKED_BY_CLIENT, this is expected (self-tracking prevention). Recipients will see the pixel normally.');
          } catch (err) {
            console.error('CalAutobot: Failed to inject tracking pixel', err);
          }
        } else {
  // console.log('CalAutobot: Tracking not enabled, skipping pixel injection');
        }
      } catch (err) {
        console.warn('CalAutobot: Failed to process presending', err);
      }
    });

    // 4. After Send - Create tracking request
    composeView.on('sent', async (event) => {
      try {
  // console.log('CalAutobot: Email sent');

        if (!trackingState.enabled) {
  // console.log('CalAutobot: Tracking disabled by user, skipping tracking request');
          return;
        }

        if (!trackingState.trackingId) {
          console.error('CalAutobot: Tracking enabled but trackingId is missing! This should not happen.');
          return;
        }

        const authed = await ensureAuthenticated();
        if (!authed) {
          console.error('CalAutobot: Not authenticated, cannot create tracking request');
          return;
        }

        // Use recipients captured in real-time
        const toRecipients = trackingState.recipients.to;
        const ccRecipients = trackingState.recipients.cc;
        const bccRecipients = trackingState.recipients.bcc;
        const totalRecipients = toRecipients.length + ccRecipients.length + bccRecipients.length;

        if (totalRecipients === 0) {
          console.error('CalAutobot: No recipients found! Cannot create tracking request.');
          console.error('CalAutobot: This may happen if recipients were cleared before we could capture them.');
          return;
        }

        // console.log('CalAutobot: Creating tracking request with params:', {
        //   trackingId: trackingState.trackingId,
        //   subject: trackingState.subject,
        //   recipientCount: toRecipients.length,
        //   ccCount: ccRecipients.length,
        //   bccCount: bccRecipients.length,
        //   totalRecipients,
        //   userEmail
        // });

        // Create tracking request via API
        const result = await createTrackingRequest({
          trackingId: trackingState.trackingId,
          subject: trackingState.subject,
          recipients: toRecipients,
          ccRecipients: ccRecipients,
          bccRecipients: bccRecipients,
          gmailThreadId: trackingState.threadId || null,
          userEmail: userEmail,
        });

  // console.log('CalAutobot: Tracking request created successfully', result);
      } catch (err) {
        console.error('CalAutobot: Failed to create tracking request', err);
        console.error('CalAutobot: Error stack:', err.stack);
      }
    });

  });
});

