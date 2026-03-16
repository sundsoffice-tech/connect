/* ============================================
   S&S CONNECT - Main JavaScript
   A11y-enhanced, SEO-aware
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {

  // --- Language Switcher ---
  const savedLang = localStorage.getItem('ss-lang') || 'de';
  setLanguage(savedLang);

  document.querySelectorAll('.lang-switch button').forEach(btn => {
    btn.addEventListener('click', () => {
      setLanguage(btn.dataset.lang);
    });
  });

  function setLanguage(lang) {
    const otherLang = lang === 'de' ? 'en' : 'de';
    document.body.classList.remove('lang-de', 'lang-en');
    document.body.classList.add(`lang-${lang}`);
    document.documentElement.setAttribute('lang', lang);
    localStorage.setItem('ss-lang', lang);

    document.querySelectorAll('.lang-switch button').forEach(b => {
      const isActive = b.dataset.lang === lang;
      b.setAttribute('aria-pressed', isActive);
    });

    // Show active lang, hide other + aria-hidden for screen readers
    document.querySelectorAll(`[lang="${lang}"]`).forEach(el => {
      el.removeAttribute('aria-hidden');
    });
    document.querySelectorAll(`[lang="${otherLang}"]`).forEach(el => {
      el.setAttribute('aria-hidden', 'true');
    });

    // Update page title based on language
    const titleDe = document.querySelector('meta[name="title-de"]');
    const titleEn = document.querySelector('meta[name="title-en"]');
    if (titleDe && titleEn) {
      document.title = lang === 'de' ? titleDe.content : titleEn.content;
    }

    // Update select options with translated text
    document.querySelectorAll('select[data-placeholder-de]').forEach(select => {
      const placeholder = select.querySelector('option[disabled]');
      if (placeholder) {
        placeholder.textContent = select.dataset[`placeholder${lang === 'de' ? 'De' : 'En'}`];
      }
      select.querySelectorAll('option[data-de]').forEach(opt => {
        opt.textContent = opt.dataset[lang];
      });
    });

    // Announce language change to screen readers
    const announcer = document.getElementById('sr-announcer');
    if (announcer) {
      announcer.textContent = lang === 'de'
        ? 'Sprache auf Deutsch geändert'
        : 'Language changed to English';
    }
  }

  // --- Navbar Scroll ---
  const nav = document.querySelector('.nav');
  const scrollThreshold = 50;

  function updateNav() {
    if (window.scrollY > scrollThreshold) {
      nav.classList.add('scrolled');
    } else {
      nav.classList.remove('scrolled');
    }
  }

  window.addEventListener('scroll', updateNav, { passive: true });
  updateNav();

  // --- Mobile Menu ---
  const hamburger = document.querySelector('.nav-hamburger');
  const navMenu = document.querySelector('.nav-menu');

  if (hamburger && navMenu) {
    hamburger.addEventListener('click', () => {
      const isOpen = hamburger.getAttribute('aria-expanded') === 'true';
      hamburger.setAttribute('aria-expanded', !isOpen);
      navMenu.setAttribute('aria-hidden', isOpen);
      document.body.style.overflow = isOpen ? '' : 'hidden';
    });

    // Close on link click
    navMenu.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', () => {
        hamburger.setAttribute('aria-expanded', 'false');
        navMenu.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
      });
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && hamburger.getAttribute('aria-expanded') === 'true') {
        hamburger.setAttribute('aria-expanded', 'false');
        navMenu.setAttribute('aria-hidden', 'true');
        document.body.style.overflow = '';
        hamburger.focus();
      }
    });
  }

  // --- Scroll Reveal ---
  const revealElements = document.querySelectorAll('.reveal');
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (prefersReducedMotion) {
    revealElements.forEach(el => el.classList.add('visible'));
  } else if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          observer.unobserve(entry.target);
        }
      });
    }, {
      threshold: 0.1,
      rootMargin: '0px 0px -40px 0px'
    });

    revealElements.forEach(el => observer.observe(el));
  } else {
    revealElements.forEach(el => el.classList.add('visible'));
  }

  // --- Active Navigation Link (aria-current) ---
  const currentPage = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-links a').forEach(link => {
    const href = link.getAttribute('href');
    if (href === currentPage || (currentPage === '' && href === 'index.html')) {
      link.setAttribute('aria-current', 'page');
    }
  });

  // --- Contact Form (Formspree) ---
  const form = document.querySelector('#contact-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const statusEl = document.getElementById('form-status');
      const isDE = document.body.classList.contains('lang-de');

      // Validate DSGVO checkbox
      const consent = form.querySelector('#dsgvo-consent');
      if (consent && !consent.checked) {
        if (statusEl) {
          statusEl.textContent = isDE
            ? 'Bitte stimmen Sie der Datenschutzerklärung zu.'
            : 'Please agree to the privacy policy.';
          statusEl.className = 'form-status error';
          statusEl.style.display = 'block';
          statusEl.style.background = 'rgba(255,80,80,0.1)';
          statusEl.style.borderColor = '#ff5050';
          statusEl.style.color = '#ff5050';
        }
        return;
      }

      btn.setAttribute('disabled', 'true');

      const data = new FormData(form);

      fetch(form.action, {
        method: 'POST',
        body: data,
        headers: { 'Accept': 'application/json' }
      }).then(response => {
        if (response.ok) {
          if (statusEl) {
            statusEl.textContent = isDE
              ? 'Vielen Dank! Ihre Nachricht wurde gesendet.'
              : 'Thank you! Your message has been sent.';
            statusEl.className = 'form-status success';
            statusEl.style.display = 'block';
            statusEl.style.background = '';
            statusEl.style.borderColor = '';
            statusEl.style.color = '';
          }
          form.reset();
        } else {
          throw new Error('Form submission failed');
        }
      }).catch(() => {
        if (statusEl) {
          statusEl.textContent = isDE
            ? 'Fehler beim Senden. Bitte versuchen Sie es erneut.'
            : 'Error sending message. Please try again.';
          statusEl.className = 'form-status error';
          statusEl.style.display = 'block';
          statusEl.style.background = 'rgba(255,80,80,0.1)';
          statusEl.style.borderColor = '#ff5050';
          statusEl.style.color = '#ff5050';
        }
      }).finally(() => {
        btn.removeAttribute('disabled');
        setTimeout(() => {
          if (statusEl) {
            statusEl.style.display = 'none';
            statusEl.textContent = '';
          }
        }, 5000);
      });
    });
  }

  // --- Counter Animation ---
  const counters = document.querySelectorAll('[data-count]');

  if (counters.length && 'IntersectionObserver' in window && !prefersReducedMotion) {
    const countObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          animateCounter(entry.target);
          countObserver.unobserve(entry.target);
        }
      });
    }, { threshold: 0.5 });

    counters.forEach(el => countObserver.observe(el));
  } else {
    counters.forEach(el => {
      const suffix = el.dataset.suffix || '';
      const prefix = el.dataset.prefix || '';
      el.textContent = prefix + el.dataset.count + suffix;
    });
  }

  function animateCounter(el) {
    const target = el.dataset.count;
    const suffix = el.dataset.suffix || '';
    const prefix = el.dataset.prefix || '';
    const numericTarget = parseFloat(target);
    const duration = 1500;
    const start = performance.now();

    function update(currentTime) {
      const elapsed = currentTime - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = Math.round(numericTarget * eased);

      el.textContent = prefix + current.toLocaleString() + suffix;

      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        el.textContent = prefix + target + suffix;
      }
    }

    requestAnimationFrame(update);
  }

  // --- Hacca Chat Promo Popup ---
  const haccaPopup = document.getElementById('hacca-popup');
  if (haccaPopup) {
    const HACCA_DISMISS_KEY = 'ss-hacca-popup-dismissed';
    const dismissed = sessionStorage.getItem(HACCA_DISMISS_KEY);

    if (!dismissed) {
      // Show popup after a short delay
      setTimeout(() => {
        haccaPopup.setAttribute('aria-hidden', 'false');
        haccaPopup.classList.add('visible');
        document.body.classList.add('hacca-popup-open');
      }, 5000);
    }

    function closeHaccaPopup() {
      haccaPopup.classList.remove('visible');
      haccaPopup.setAttribute('aria-hidden', 'true');
      document.body.classList.remove('hacca-popup-open');
      sessionStorage.setItem(HACCA_DISMISS_KEY, 'true');
    }

    // Close button
    const haccaClose = document.getElementById('hacca-popup-close');
    if (haccaClose) {
      haccaClose.addEventListener('click', closeHaccaPopup);
    }

    // "Later" button
    const haccaLater = document.getElementById('hacca-popup-later');
    if (haccaLater) {
      haccaLater.addEventListener('click', closeHaccaPopup);
    }

    // Close on backdrop click
    const haccaBackdrop = haccaPopup.querySelector('.hacca-popup-backdrop');
    if (haccaBackdrop) {
      haccaBackdrop.addEventListener('click', closeHaccaPopup);
    }

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && haccaPopup.classList.contains('visible')) {
        closeHaccaPopup();
      }
    });
  }

  // --- Cookie Consent & GA4 ---
  const GA4_ID = 'G-DFP092FTMJ';
  const CONSENT_KEY = 'ss-cookie-consent';

  function getConsent() {
    try {
      return JSON.parse(localStorage.getItem(CONSENT_KEY));
    } catch { return null; }
  }

  function saveConsent(analytics) {
    localStorage.setItem(CONSENT_KEY, JSON.stringify({
      analytics: analytics,
      timestamp: new Date().toISOString()
    }));
  }

  function loadGA4() {
    if (document.getElementById('ga4-script')) return;
    const s = document.createElement('script');
    s.id = 'ga4-script';
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + GA4_ID;
    document.head.appendChild(s);

    window.dataLayer = window.dataLayer || [];
    function gtag(){ window.dataLayer.push(arguments); }
    window.gtag = gtag;
    gtag('js', new Date());
    gtag('config', GA4_ID, { anonymize_ip: true });
  }

  function deleteGACookies() {
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
      var name = cookies[i].split('=')[0].trim();
      if (name === '_ga' || name.startsWith('_ga_')) {
        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=' + window.location.hostname;
        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/;domain=.' + window.location.hostname;
        document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
      }
    }
  }

  // Cookie banner logic
  const banner = document.getElementById('cookie-banner');
  if (banner) {
    const compact = banner.querySelector('.cookie-banner-compact');
    const details = banner.querySelector('.cookie-banner-details');
    const analyticsToggle = document.getElementById('cookie-analytics-toggle');

    const consent = getConsent();
    if (consent) {
      // Consent already given
      if (consent.analytics) loadGA4();
    } else {
      // Show banner
      banner.setAttribute('aria-hidden', 'false');
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          banner.classList.add('visible');
        });
      });
    }

    function hideBanner() {
      banner.classList.remove('visible');
      banner.setAttribute('aria-hidden', 'true');
    }

    // Accept all
    var acceptBtn = document.getElementById('cookie-accept-all');
    if (acceptBtn) {
      acceptBtn.addEventListener('click', function() {
        saveConsent(true);
        loadGA4();
        hideBanner();
      });
    }

    // Reject (essential only)
    var rejectBtn = document.getElementById('cookie-reject');
    if (rejectBtn) {
      rejectBtn.addEventListener('click', function() {
        saveConsent(false);
        hideBanner();
      });
    }

    // Settings toggle
    var settingsBtn = document.getElementById('cookie-settings-btn');
    if (settingsBtn && details) {
      settingsBtn.addEventListener('click', function() {
        var isHidden = details.hasAttribute('hidden');
        if (isHidden) {
          details.removeAttribute('hidden');
          settingsBtn.setAttribute('aria-expanded', 'true');
        } else {
          details.setAttribute('hidden', '');
          settingsBtn.setAttribute('aria-expanded', 'false');
        }
      });
    }

    // Save settings from detail view
    var saveSettingsBtn = document.getElementById('cookie-save-settings');
    if (saveSettingsBtn && analyticsToggle) {
      saveSettingsBtn.addEventListener('click', function() {
        var analyticsEnabled = analyticsToggle.checked;
        var previousConsent = getConsent();
        saveConsent(analyticsEnabled);

        if (analyticsEnabled) {
          loadGA4();
        } else if (previousConsent && previousConsent.analytics) {
          // Was enabled, now disabled → delete cookies and reload
          deleteGACookies();
          window.location.reload();
          return;
        }
        hideBanner();
      });
    }
  }

  // --- FAQ Accordion ---
  document.querySelectorAll('.faq-question').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var item = btn.closest('.faq-item');
      var isOpen = item.classList.contains('open');

      // Close all other items
      document.querySelectorAll('.faq-item.open').forEach(function(openItem) {
        if (openItem !== item) {
          openItem.classList.remove('open');
          openItem.querySelector('.faq-question').setAttribute('aria-expanded', 'false');
        }
      });

      // Toggle current item
      item.classList.toggle('open');
      btn.setAttribute('aria-expanded', !isOpen);
    });
  });

  // --- Sticky Mobile CTA ---
  var stickyCta = document.getElementById('sticky-cta');
  if (stickyCta) {
    var lastScrollY = 0;
    var ticking = false;

    function updateStickyCta() {
      if (window.scrollY > 600) {
        stickyCta.classList.add('visible');
      } else {
        stickyCta.classList.remove('visible');
      }
      ticking = false;
    }

    window.addEventListener('scroll', function() {
      if (!ticking) {
        requestAnimationFrame(updateStickyCta);
        ticking = true;
      }
    }, { passive: true });
  }

});
