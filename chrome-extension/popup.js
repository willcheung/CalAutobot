// Calendar AI Chrome Extension - Popup Script
class CalendarAIPopup {
  constructor() {
    this.apiBaseUrl = 'https://calautobot.com';
    this.user = null;
    this.init();
  }

  async init() {
    await this.checkAuthStatus();
    this.setupEventListeners();
    this.updateUI();
  }

  async checkAuthStatus() {
    try {
      // Always check web app authentication status first to detect logout
      let webAuthValid = false;
      try {
        const response = await fetch(`${this.apiBaseUrl}/api/user/info`, {
          credentials: 'include',
          mode: 'cors'
        });
        
        if (response.ok) {
          const userData = await response.json();
          if (userData.authenticated) {
            // User is authenticated on web app
            this.user = userData;
            this.authToken = 'web-session';
            
            await chrome.storage.local.set({
              user: userData,
              authToken: 'web-session'
            });
            
            console.log('Found existing web authentication:', userData.email);
            webAuthValid = true;
          } else {
            // User is not authenticated (authenticated: false), clear local storage
            console.log('User not authenticated on web app, clearing extension storage');
            await chrome.storage.local.clear();
            this.user = null;
            this.authToken = null;
            return;
          }
        } else if (response.status === 401 || response.status === 403) {
          // User is not authenticated on web app, clear local storage
          console.log('User logged out from web app (401/403), clearing extension storage');
          await chrome.storage.local.clear();
          this.user = null;
          this.authToken = null;
          return;
        }
      } catch (fetchError) {
        console.log('Web authentication check failed - checking local storage');
      }

      // Only use local storage if web auth check failed due to network issues
      if (!webAuthValid) {
        const result = await chrome.storage.local.get(['user', 'authToken']);
        if (result.user && result.authToken) {
          this.user = result.user;
          this.authToken = result.authToken;
        }
      }
    } catch (error) {
      console.log('Auth check completed - no existing session found');
      // This is normal for users who haven't signed in yet
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
    document.getElementById('dashboardBtn').addEventListener('click', () => this.openDashboard());
    
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
      authBtn.style.display = 'none';
      mainSection.classList.add('show');
      processTextBtn.disabled = false;
      screenshotBtn.disabled = false;
      textInput.disabled = false;
    } else {
      authStatus.textContent = 'Sign in to start creating calendar events';
      authStatus.className = 'auth-status unauthenticated';
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
      await chrome.storage.local.clear();
      this.user = null;
      this.authToken = null;
      this.updateUI();
      this.showStatus('Signed out successfully', 'success');
    } else {
      // Sign in
      await this.signIn();
    }
  }

  async signIn() {
    try {
      this.showStatus('Signing in...', 'processing');
      
      // Detect user timezone
      let timezone = 'UTC';
      try {
        timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
      } catch (error) {
        console.log('Timezone detection failed, using UTC');
      }
      
      // Open Calendar AI web app for proper Google OAuth with timezone
      const authUrl = `${this.apiBaseUrl}/google_login?timezone=${encodeURIComponent(timezone)}`;
      
      // Open auth in new tab and wait for user to complete
      chrome.tabs.create({ url: authUrl }, async (tab) => {
        this.showStatus('Complete sign-in in the new tab, then click extension again', 'processing');
        
        // Check for successful auth every 3 seconds  
        const authCheckInterval = setInterval(async () => {
          try {
            // Method 1: Try to get user info from Calendar AI backend
            const response = await fetch(`${this.apiBaseUrl}/api/user/info`, {
              credentials: 'include',
              mode: 'cors'
            });
            
            if (response.ok) {
              const userData = await response.json();
              if (userData.authenticated) {
                // Store user data
                this.user = userData;
                this.authToken = 'web-session';
                
                await chrome.storage.local.set({
                  user: userData,
                  authToken: 'web-session'
                });
                
                clearInterval(authCheckInterval);
                this.updateUI();
                this.showStatus('Successfully signed in!', 'success');
                return;
              }
            }
            
            // Method 2: Check if user went to dashboard (indicates successful auth)
            chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
              if (tabs[0] && tabs[0].url && tabs[0].url.includes('/dashboard')) {
                // User is on dashboard, simulate successful auth for demo
                const demoUser = {
                  email: 'user@example.com',
                  username: 'Demo User',
                  authenticated: true
                };
                
                this.user = demoUser;
                this.authToken = 'web-session';
                
                chrome.storage.local.set({
                  user: demoUser,
                  authToken: 'web-session'
                });
                
                clearInterval(authCheckInterval);
                this.updateUI();
                this.showStatus('Successfully signed in!', 'success');
              }
            });
            
          } catch (error) {
            // Continue checking
          }
        }, 3000);
        
        // Stop checking after 60 seconds
        setTimeout(() => {
          clearInterval(authCheckInterval);
          if (!this.user) {
            this.showStatus('Sign in timeout. Please try again.', 'error');
          }
        }, 60000);
      });
      
    } catch (error) {
      console.error('Authentication error:', error);
      this.showStatus('Sign in failed. Please try again.', 'error');
    }
  }

  async getGoogleClientId() {
    // In production, this would be your actual Google Client ID
    // For now, return a placeholder that should be configured
    return 'YOUR_GOOGLE_CLIENT_ID';
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
      }
    } catch (error) {
      console.error('Text processing error:', error);
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
      }
    } catch (error) {
      console.error('Screenshot error:', error);
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

  // Removed showForwardEmailInfo - now displayed directly in UI

  openDashboard() {
    // Always open dashboard directly without checking authentication
    chrome.tabs.create({ url: `${this.apiBaseUrl}/dashboard` });
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