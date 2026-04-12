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

    // Re-init hero word rotation for new language
    if (typeof initHeroWords === 'function') initHeroWords();
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

  // --- GSAP ScrollTrigger Reveals ---
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    if (!prefersReducedMotion) {
      // Hero-Elemente: Staggered fade-up mit premium Easing
      gsap.from('.hero-content .reveal', {
        y: 50,
        opacity: 0,
        duration: 1,
        stagger: 0.15,
        ease: 'power4.out',
        delay: 0.3
      });

      // Section-Headers: Slide + leichte Skalierung
      gsap.utils.toArray('.section-header').forEach(header => {
        gsap.from(header, {
          y: 60,
          opacity: 0,
          scale: 0.97,
          duration: 0.9,
          ease: 'power3.out',
          scrollTrigger: { trigger: header, start: 'top 85%' }
        });
      });

      // Cards: Stagger von links nach rechts
      gsap.utils.toArray('.grid, .bento, .references-grid').forEach(grid => {
        const items = grid.querySelectorAll('.card, .reference-card');
        if (!items.length) return;
        gsap.from(items, {
          y: 60,
          opacity: 0,
          duration: 0.8,
          stagger: 0.1,
          ease: 'power3.out',
          scrollTrigger: { trigger: grid, start: 'top 82%' }
        });
      });

      // Stats-Bar: Counter mit GSAP
      gsap.utils.toArray('[data-count]').forEach(stat => {
        const target = parseFloat(stat.dataset.count);
        const suffix = stat.dataset.suffix || '';
        const prefix = stat.dataset.prefix || '';
        ScrollTrigger.create({
          trigger: stat,
          start: 'top 90%',
          once: true,
          onEnter: () => {
            const obj = { val: 0 };
            gsap.to(obj, {
              val: target,
              duration: 1.8,
              ease: 'power2.out',
              onUpdate: () => {
                stat.textContent = prefix + Math.round(obj.val).toLocaleString() + suffix;
              },
              onComplete: () => {
                stat.textContent = prefix + target + suffix;
              }
            });
          }
        });
      });

      // Webdesign-Teaser: Scale-In
      const teaser = document.querySelector('.webdesign-teaser');
      if (teaser) {
        gsap.from(teaser, {
          scale: 0.92,
          opacity: 0,
          duration: 1,
          ease: 'power3.out',
          scrollTrigger: { trigger: teaser, start: 'top 85%' }
        });
      }

      // CTA-Section: Slide von unten
      const ctaSection = document.querySelector('.cta-section');
      if (ctaSection) {
        gsap.from(ctaSection.querySelector('.container'), {
          y: 80,
          opacity: 0,
          duration: 1,
          ease: 'power3.out',
          scrollTrigger: { trigger: ctaSection, start: 'top 85%' }
        });
      }

      // HACCA Inline: Reveal
      const haccaInline = document.querySelector('.hacca-inline__card');
      if (haccaInline) {
        gsap.from(haccaInline, {
          y: 60,
          opacity: 0,
          scale: 0.95,
          duration: 1,
          ease: 'power3.out',
          scrollTrigger: { trigger: haccaInline, start: 'top 85%' }
        });
      }

      // Parallax auf Section-Glows
      gsap.utils.toArray('.section').forEach(section => {
        const glow = section.querySelector('[class*="glow"]');
        if (glow) {
          gsap.to(glow, {
            y: -60,
            scrollTrigger: {
              trigger: section,
              start: 'top bottom',
              end: 'bottom top',
              scrub: 1.5
            }
          });
        }
      });

    } else {
      // Reduced motion: Alles sofort sichtbar
      document.querySelectorAll('.reveal').forEach(el => {
        el.style.opacity = '1';
        el.style.transform = 'none';
      });
      // Counter sofort setzen
      document.querySelectorAll('[data-count]').forEach(el => {
        el.textContent = (el.dataset.prefix || '') + el.dataset.count + (el.dataset.suffix || '');
      });
    }
  } else {
    // GSAP Fallback: Alles sichtbar machen
    document.querySelectorAll('.reveal').forEach(el => {
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
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

  // Counter Animation ist jetzt in GSAP ScrollTrigger integriert (siehe oben)

  // --- Scroll Progress Bar ---
  const progressBar = document.querySelector('.scroll-progress');
  if (progressBar) {
    window.addEventListener('scroll', () => {
      const pct = document.documentElement.scrollTop /
                  (document.documentElement.scrollHeight - window.innerHeight) * 100;
      progressBar.style.width = pct + '%';
    }, { passive: true });
  }

  // --- Hero Word Rotation ---
  let heroWordIntervals = [];

  function initHeroWords() {
    // Clear previous intervals (important for language switch re-init)
    heroWordIntervals.forEach(id => clearInterval(id));
    heroWordIntervals = [];

    if (prefersReducedMotion) return;

    // Only target visible containers (respects lang-toggle display:none)
    const activeLang = document.body.classList.contains('lang-de') ? 'de' : 'en';
    const containers = document.querySelectorAll(`[lang="${activeLang}"] .hero-words`);

    containers.forEach(container => {
      const items = container.querySelectorAll('.hero-words__item');
      if (items.length < 2) return;

      // Reset all to initial state
      items.forEach((item, i) => {
        item.classList.remove('active', 'exit');
        if (i === 0) item.classList.add('active');
      });

      let current = 0;

      function rotate() {
        const prev = items[current];
        prev.classList.remove('active');
        prev.classList.add('exit');
        current = (current + 1) % items.length;
        items[current].classList.add('active');
        setTimeout(() => prev.classList.remove('exit'), 600);
      }

      const intervalId = setInterval(rotate, 3000);
      heroWordIntervals.push(intervalId);
    });
  }

  // Pause/resume on tab visibility
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      heroWordIntervals.forEach(id => clearInterval(id));
      heroWordIntervals = [];
    } else {
      initHeroWords();
    }
  });

  initHeroWords();

  // --- Card Cursor Spotlight ---
  function initCardSpotlight() {
    if (window.matchMedia('(hover: none)').matches) return;
    document.querySelectorAll('.card').forEach(card => {
      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        card.style.setProperty('--spotlight-x', (e.clientX - rect.left) + 'px');
        card.style.setProperty('--spotlight-y', (e.clientY - rect.top) + 'px');
      });
    });
  }
  initCardSpotlight();

  // --- Card 3D Tilt ---
  function initCardTilt() {
    if (window.matchMedia('(hover: none)').matches) return;
    if (prefersReducedMotion) return;

    document.querySelectorAll('.card, .reference-card').forEach(card => {
      card.style.transformStyle = 'preserve-3d';
      card.style.transition = 'transform 0.15s ease-out';

      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        const y = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
        card.style.transform =
          `perspective(600px) rotateY(${x * 5}deg) rotateX(${-y * 5}deg) translateY(-6px) scale(1.01)`;
      });

      card.addEventListener('mouseleave', () => {
        card.style.transform = '';
        card.style.transition = 'transform 0.4s cubic-bezier(0.16, 1, 0.3, 1)';
        setTimeout(() => { card.style.transition = 'transform 0.15s ease-out'; }, 400);
      });
    });
  }
  // Delay tilt init so GSAP reveals finish first
  setTimeout(initCardTilt, 2000);

  // --- 3D Hero Canvas Loader ---
  const heroCanvas = document.querySelector('.hero-canvas');
  if (heroCanvas) {
    // WebGL feature detection
    const testCanvas = document.createElement('canvas');
    const hasWebGL = !!(testCanvas.getContext('webgl2') || testCanvas.getContext('webgl'));

    if (hasWebGL && window.innerWidth > 480) {
      const iframe = heroCanvas.querySelector('iframe');
      if (iframe) iframe.onload = () => heroCanvas.classList.add('loaded');
      setTimeout(() => heroCanvas.classList.add('loaded'), 4000);
    } else {
      heroCanvas.style.display = 'none';
    }
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
