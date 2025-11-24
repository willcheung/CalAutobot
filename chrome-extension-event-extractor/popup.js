// Calendar AI Chrome Extension - Popup Script

class CalendarAIPopup {
  constructor() {
    this.apiBaseUrl = 'https://calautobot.com';
    this.user = null;
    this.authToken = null;
    this.isLoading = true; // Start in loading state
    this.init();
  }

  async init() {
    await this.checkAuthStatus();
    this.setupEventListeners();
    // updateUI is called within checkAuthStatus callbacks or finally blocks
  }

  async checkAuthStatus() {
    try {
      console.log('🔍 Checking authentication status...');
      this.isLoading = true;
      this.updateUI();

      // Try to get token non-interactively
      chrome.identity.getAuthToken({ interactive: false }, async (token) => {
        if (chrome.runtime.lastError || !token) {
          console.log('🔓 No token found or error:', chrome.runtime.lastError);
          this.user = null;
          this.authToken = null;
          this.isLoading = false;
          this.updateUI();
          return;
        }

        console.log('🔐 Token found, fetching user info...');
        this.authToken = token;
        await this.fetchUserInfo(token);
      });

    } catch (error) {
      console.log('Session check error:', error);
      this.user = null;
      this.authToken = null;
      this.isLoading = false;
      this.updateUI();
    }
  }

  async fetchUserInfo(token) {
    try {
      const response = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      });

      if (response.ok) {
        const userData = await response.json();
        this.user = {
          email: userData.email,
          username: userData.name || userData.email,
          picture: userData.picture,
          authenticated: true
        };
        console.log('✅ User info fetched:', this.user.email);

        // Check if user granted calendar scope by trying to verify token with Google
        try {
          const tokenInfoResp = await fetch(`https://www.googleapis.com/oauth2/v3/tokeninfo?access_token=${token}`);
          if (tokenInfoResp.ok) {
            const tokenInfo = await tokenInfoResp.json();
            const scopes = tokenInfo.scope ? tokenInfo.scope.split(' ') : [];
            const hasCalendarScope = scopes.some(scope =>
              scope.includes('calendar') || scope.includes('https://www.googleapis.com/auth/calendar.app.created')
            );

            if (!hasCalendarScope) {
              console.log('⚠️ Calendar permission not granted');
              this.user.needsCalendarPermission = true;
            }
          }
        } catch (err) {
          console.warn('Failed to verify token scopes:', err);
        }

        this.isLoading = false;
        this.updateUI();
      } else {
        console.log('❌ Failed to fetch user info, invalidating token');
        this.user = null;
        this.authToken = null;
        // Token might be invalid, remove it
        chrome.identity.removeCachedAuthToken({ token: token });
        this.isLoading = false;
        this.updateUI();
      }
    } catch (error) {
      console.error('Error fetching user info:', error);
      this.user = null;
      this.authToken = null;
      this.isLoading = false;
      this.updateUI();
    }
  }

  setupEventListeners() {
    // Authentication
    document.getElementById('authBtn').addEventListener('click', () => this.handleAuth());
    document.getElementById('signOutBtn').addEventListener('click', () => this.signOut());

    // Text processing
    document.getElementById('processTextBtn').addEventListener('click', () => this.processText());

    // Screenshot
    document.getElementById('screenshotBtn').addEventListener('click', () => this.takeScreenshot());

    // Quick actions
    document.getElementById('bookingsBtn').addEventListener('click', () => this.openSettings());

    // Copy email button
    document.getElementById('copyEmailBtn').addEventListener('click', () => this.copyEmail());
  }

  updateUI() {
    const authStatus = document.getElementById('authStatus');
    const authBtn = document.getElementById('authBtn');
    const signOutBtn = document.getElementById('signOutBtn');
    const mainSection = document.querySelector('.main-section');
    const processTextBtn = document.getElementById('processTextBtn');
    const screenshotBtn = document.getElementById('screenshotBtn');
    const textInput = document.getElementById('textInput');
    const privacyDisclaimer = document.getElementById('privacyDisclaimer');

    if (this.isLoading) {
      authStatus.textContent = 'Signing in...';
      authStatus.className = 'auth-status processing';
      authBtn.innerHTML = '<span class="loading"></span>Signing in...';
      authBtn.style.display = 'flex';
      authBtn.disabled = true;
      signOutBtn.style.display = 'none';
      mainSection.classList.remove('show');
      privacyDisclaimer.style.display = 'none';
      return;
    }

    authBtn.disabled = false; // Re-enable button

    if (this.user) {
      privacyDisclaimer.style.display = 'none'; // Hide disclaimer when signed in

      if (this.user.needsCalendarPermission) {
        // Authenticated but needs calendar permission
        authStatus.textContent = 'Almost there! Grant calendar access.';
        authStatus.className = 'auth-status unauthenticated';
        authBtn.innerHTML = '<span>Grant calendar access</span>';
        authBtn.style.display = 'flex';
        signOutBtn.style.display = 'block'; // Allow sign out
        mainSection.classList.remove('show');
      } else {
        // Fully authenticated with calendar scope
        authStatus.textContent = `Signed in as ${this.user.email}`;
        authStatus.className = 'auth-status authenticated';
        authBtn.style.display = 'none'; // Hide main auth button
        signOutBtn.style.display = 'block'; // Show bottom sign out
        mainSection.classList.add('show');
        processTextBtn.disabled = false;
        screenshotBtn.disabled = false;
        textInput.disabled = false;
      }
    } else {
      privacyDisclaimer.style.display = 'block'; // Show disclaimer when not signed in
      authStatus.className = 'auth-status unauthenticated';
      authStatus.textContent = 'Not signed in';
      authBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 18 18">
          <path fill="#4285F4" d="M16.51 8H8.98v3h4.3c-.18 1-.74 1.48-1.6 2.04v2.01h2.6a7.8 7.8 0 0 0 2.38-5.88c0-.57-.05-.66-.15-1.18z"/>
          <path fill="#34A853" d="M8.98 17c2.16 0 3.97-.72 5.3-1.94l-2.6-2.04a4.8 4.8 0 0 1-7.18-2.53H1.83v2.07A8 8 0 0 0 8.98 17z"/>
          <path fill="#FBBC05" d="M4.5 10.49a4.8 4.8 0 0 1 0-3.07V5.35H1.83a8 8 0 0 0 0 7.28l2.67-2.14z"/>
          <path fill="#EA4335" d="M8.98 3.58c1.32 0 2.5.45 3.44 1.35l2.54-2.59a7.81 7.81 0 0 0-5.98-2.26 8 8 0 0 0-7.15 4.42l2.67 2.14c.63-1.89 2.39-3.06 4.48-3.06z"/>
        </svg>
        <span>Sign in with Google</span>
      `;
      authBtn.style.display = 'flex';
      signOutBtn.style.display = 'none';
      mainSection.classList.remove('show');
      processTextBtn.disabled = true;
      screenshotBtn.disabled = true;
      textInput.disabled = true;
    }
  }

  async handleAuth() {
    if (this.user && this.user.needsCalendarPermission) {
      // Re-authenticate to get calendar permission
      this.showStatus('Requesting calendar access...', 'processing');
      // Clear the old token first
      if (this.authToken) {
        chrome.identity.removeCachedAuthToken({ token: this.authToken }, () => {
          this.signIn(); // Trigger sign-in again to get new permissions
        });
      } else {
        this.signIn();
      }
    } else if (!this.user) {
      // Initial sign in
      this.signIn();
    }
    // If already fully authenticated, button should be hidden anyway
  }

  signIn() {
    this.showStatus('Signing in...', 'processing');
    chrome.identity.getAuthToken({ interactive: true }, async (token) => {
      if (chrome.runtime.lastError) {
        console.error('Sign in failed:', chrome.runtime.lastError.message || chrome.runtime.lastError);
        this.showStatus(`Sign in failed: ${chrome.runtime.lastError.message || 'Unknown error'}`, 'error');
        return;
      }

      this.authToken = token;
      await this.fetchUserInfo(token);

      if (this.user && this.user.setupRequired) {
        this.showStatus('Please connect your calendar', 'processing');
      } else {
        this.showStatus('Successfully signed in!', 'success');
      }
    });
  }

  signOut() {
    if (this.authToken) {
      chrome.identity.removeCachedAuthToken({ token: this.authToken }, () => {
        this.user = null;
        this.authToken = null;
        this.updateUI();
        this.showStatus('Signed out successfully', 'success');
      });
    } else {
      this.user = null;
      this.updateUI();
    }
  }

  async processText() {
    const textInput = document.getElementById('textInput');
    const text = textInput.value.trim();

    if (!text) {
      return;
    }

    try {
      this.setButtonLoading('processTextBtn', true);

      // Send to Chrome extension API endpoint
      const response = await fetch(`${this.apiBaseUrl}/api/extension/process`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${this.authToken}`
        },
        body: JSON.stringify({
          text: text,
          // We don't strictly need user_email anymore as the token has it, 
          // but keeping it for compatibility if backend needs it for logging
          user_email: this.user.email,
          source: 'Chrome Extension Text Input'
        })
      });

      const result = await response.json();

      if (response.ok) {
        const totalEvents = result.total_events_extracted || 0;
        const syncedEvents = result.total_events_synced || 0;

        // Show success toast
        this.showToast(`Success! Extracted ${totalEvents} events, ${syncedEvents} synced to calendar`);

        textInput.value = ''; // Clear input
      } else {
        console.error('Text processing failed:', result.error);
        this.showStatus(`Error: ${result.error || 'Processing failed'}`, 'error');
      }
    } catch (error) {
      console.error('Text processing error:', error);
      this.showStatus('Network error. Please try again.', 'error');
    } finally {
      this.setButtonLoading('processTextBtn', false);
    }
  }

  async takeScreenshot() {
    try {
      this.setButtonLoading('screenshotBtn', true);

      // Capture the active tab
      const tab = await this.getCurrentTab();
      const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, {
        format: 'png',
        quality: 90
      });

      // Resize image for faster upload
      const optimizedBlob = await this.resizeImage(dataUrl, 1920);
      const blob = optimizedBlob;

      // Send to webhook endpoint with screenshot
      const formData = new FormData();
      formData.append('stripped-text', 'Screenshot taken from Chrome extension');
      formData.append('From', this.user.email);
      formData.append('Subject', 'Chrome Extension Screenshot');
      formData.append('attachment-1', blob, 'screenshot.jpg');

      const apiResponse = await fetch(`${this.apiBaseUrl}/api/extension/process`, {
        method: 'POST',
        body: formData,
        headers: {
          'Authorization': `Bearer ${this.authToken}`
        }
      });

      const result = await apiResponse.json();

      if (apiResponse.ok) {
        const totalEvents = result.total_events_extracted || 0;
        const syncedEvents = result.total_events_synced || 0;

        // Show success toast
        this.showToast(`Success! Extracted ${totalEvents} events from screenshot, ${syncedEvents} synced to calendar`);
      } else {
        console.error('Screenshot processing failed:', result.error);
        this.showStatus(`Error: ${result.error || 'Processing failed'}`, 'error');
      }
    } catch (error) {
      console.error('Screenshot error:', error);
      this.showStatus('Screenshot failed. Please try again.', 'error');
    } finally {
      this.setButtonLoading('screenshotBtn', false);
    }
  }

  async getCurrentTab() {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    return tab;
  }

  async resizeImage(dataUrl, maxWidth = 1920) {
    return new Promise((resolve, reject) => {
      try {
        const img = new Image();
        img.onload = () => {
          try {
            // Calculate new dimensions maintaining aspect ratio
            let { width, height } = img;

            if (width <= maxWidth) {
              // Image is already small enough, convert to JPEG for better compression
              const canvas = document.createElement('canvas');
              const ctx = canvas.getContext('2d');
              canvas.width = width;
              canvas.height = height;
              ctx.drawImage(img, 0, 0);

              canvas.toBlob(resolve, 'image/jpeg', 0.85);
              return;
            }

            // Resize maintaining aspect ratio
            const ratio = maxWidth / width;
            const newWidth = maxWidth;
            const newHeight = Math.round(height * ratio);

            // Create canvas and resize
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            canvas.width = newWidth;
            canvas.height = newHeight;

            // Use high-quality image rendering
            ctx.imageSmoothingEnabled = true;
            ctx.imageSmoothingQuality = 'high';

            // Draw resized image
            ctx.drawImage(img, 0, 0, newWidth, newHeight);

            // Convert to JPEG blob with good quality
            canvas.toBlob(resolve, 'image/jpeg', 0.85);

          } catch (error) {
            reject(error);
          }
        };

        img.onerror = () => reject(new Error('Failed to load image'));
        img.src = dataUrl;

      } catch (error) {
        reject(error);
      }
    });
  }

  openSettings() {
    // Always open settings directly without checking authentication
    chrome.tabs.create({ url: `${this.apiBaseUrl}/settings/calendars` });
  }

  async copyEmail() {
    const emailAddress = 'go@CalAutobot.com';
    const copyBtn = document.getElementById('copyEmailBtn');

    try {
      await navigator.clipboard.writeText(emailAddress);

      // Update button to show success
      const originalText = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      copyBtn.classList.add('copied');

      // Reset button after 2 seconds
      setTimeout(() => {
        copyBtn.textContent = originalText;
        copyBtn.classList.remove('copied');
      }, 2000);

      this.showStatus('Email address copied to clipboard!', 'success');
    } catch (error) {
      console.error('Failed to copy email:', error);
      this.showStatus('Failed to copy email. Please copy manually.', 'error');
    }
  }

  setButtonLoading(buttonId, loading) {
    const button = document.getElementById(buttonId);
    const buttonText = button.querySelector('.button-text');

    if (loading) {
      button.disabled = true;
      buttonText.innerHTML = '<span class="loading"></span>Processing...';
    } else {
      button.disabled = false;
      if (buttonId === 'processTextBtn') {
        buttonText.textContent = 'Extract Events';
      } else if (buttonId === 'screenshotBtn') {
        buttonText.textContent = 'Take Screenshot';
      }
    }
  }

  showStatus(message, type) {
    const statusElement = document.getElementById('statusMessage');
    statusElement.textContent = message;
    statusElement.className = `status ${type}`;
    statusElement.classList.remove('hidden');

    // Auto-hide success messages after 3 seconds
    if (type === 'success') {
      setTimeout(() => {
        statusElement.classList.add('hidden');
      }, 3000);
    }
  }

  showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('show');

    // Auto-hide after 4 seconds
    setTimeout(() => {
      toast.classList.remove('show');
      setTimeout(() => {
        toast.classList.add('hidden');
      }, 300); // Wait for animation to complete
    }, 4000);
  }
}

// Initialize popup when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new CalendarAIPopup();
});
