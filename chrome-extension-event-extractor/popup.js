// Calendar AI Chrome Extension - Popup Script

class CalendarAIPopup {
  constructor() {
    this.apiBaseUrl = 'https://calautobot.com';
    this.user = null;
    this.authToken = null;
    this.init();
  }

  async init() {
    await this.checkAuthStatus();
    this.setupEventListeners();
    this.updateUI();
  }

  async checkAuthStatus() {
    try {
      console.log('🔍 Checking authentication status...');

      // Try to get token non-interactively
      chrome.identity.getAuthToken({ interactive: false }, async (token) => {
        if (chrome.runtime.lastError || !token) {
          console.log('🔓 No token found or error:', chrome.runtime.lastError);
          this.user = null;
          this.authToken = null;
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
        this.updateUI();
      } else {
        console.log('❌ Failed to fetch user info, invalidating token');
        this.user = null;
        this.authToken = null;
        // Token might be invalid, remove it
        chrome.identity.removeCachedAuthToken({ token: token });
        this.updateUI();
      }
    } catch (error) {
      console.error('Error fetching user info:', error);
      this.user = null;
      this.authToken = null;
      this.updateUI();
    }
  }

  setupEventListeners() {
    // Authentication
    document.getElementById('authBtn').addEventListener('click', () => this.handleAuth());

    // Text processing
    document.getElementById('processTextBtn').addEventListener('click', () => this.processText());

    // Screenshot
    document.getElementById('screenshotBtn').addEventListener('click', () => this.takeScreenshot());

    // Quick actions
    document.getElementById('bookingsBtn').addEventListener('click', () => this.openBookings());

    // Copy email button
    document.getElementById('copyEmailBtn').addEventListener('click', () => this.copyEmail());
  }

  updateUI() {
    const authStatus = document.getElementById('authStatus');
    const authBtn = document.getElementById('authBtn');
    const mainSection = document.querySelector('.main-section');
    const processTextBtn = document.getElementById('processTextBtn');
    const screenshotBtn = document.getElementById('screenshotBtn');
    const textInput = document.getElementById('textInput');

    if (this.user) {
      authStatus.textContent = `Signed in as ${this.user.email}`;
      authStatus.className = 'auth-status authenticated';
      authBtn.textContent = 'Sign Out'; // Change button text
      authBtn.style.display = 'flex'; // Keep visible for sign out
      mainSection.classList.add('show');
      processTextBtn.disabled = false;
      screenshotBtn.disabled = false;
      textInput.disabled = false;
    } else {
      authStatus.className = 'auth-status unauthenticated';
      authStatus.textContent = 'Not signed in';
      authBtn.textContent = 'Sign in with Google';
      authBtn.style.display = 'flex';
      mainSection.classList.remove('show');
      processTextBtn.disabled = true;
      screenshotBtn.disabled = true;
      textInput.disabled = true;
    }
  }

  async handleAuth() {
    if (this.user) {
      // Sign out
      this.signOut();
    } else {
      // Sign in
      this.signIn();
    }
  }

  signIn() {
    this.showStatus('Signing in...', 'processing');
    chrome.identity.getAuthToken({ interactive: true }, async (token) => {
      if (chrome.runtime.lastError) {
        console.error('Sign in failed:', chrome.runtime.lastError);
        this.showStatus('Sign in failed. Please try again.', 'error');
        return;
      }

      this.authToken = token;
      await this.fetchUserInfo(token);
      this.showStatus('Successfully signed in!', 'success');
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

  openBookings() {
    // Always open bookings directly without checking authentication
    chrome.tabs.create({ url: `${this.apiBaseUrl}/bookings` });
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
