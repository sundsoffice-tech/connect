/* ============================================
   S&S CONNECT - Main JavaScript
   A11y-enhanced, SEO-aware
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {

  // Hoisted: werden von initHeroWords() benötigt, das via setLanguage() früh aufgerufen wird
  let heroWordIntervals = [];
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

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
  if (typeof gsap !== 'undefined' && typeof ScrollTrigger !== 'undefined') {
    gsap.registerPlugin(ScrollTrigger);

    // Im Hintergrund-Tab laeuft der GSAP-Ticker nicht (gemessen 01.09.2026: 4 Frames in 5 s),
    // die Startseite bliebe bis zum Tabwechsel leer. Dann ohne Einblend-Animation zeigen.
    const tabVerdeckt = document.visibilityState === 'hidden';

    if (!prefersReducedMotion && !tabVerdeckt) {
      // Hero-Elemente: Staggered fade-up mit premium Easing (nur auf der Startseite vorhanden)
      // Alle Reveals als fromTo mit expliziten Endwerten: ein from()-Tween liest seinen
      // Endwert beim ScrollTrigger-Refresh neu ein und kann dabei 0 erwischen.
      if (document.querySelector('.hero-content .reveal')) {
        gsap.fromTo('.hero-content .reveal', { y: 50, opacity: 0 }, {
          y: 0,
          opacity: 1,
          duration: 1,
          stagger: 0.15,
          ease: 'power4.out',
          delay: 0.3,
          clearProps: 'transform'
        });
      }

      // Section-Headers: Slide + leichte Skalierung
      gsap.utils.toArray('.section-header').forEach(header => {
        gsap.fromTo(header, { y: 60, opacity: 0, scale: 0.97 }, {
          y: 0,
          opacity: 1,
          scale: 1,
          duration: 0.9,
          ease: 'power3.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: header, start: 'top 85%', once: true }
        });
      });

      // Cards: Stagger von links nach rechts
      gsap.utils.toArray('.grid, .bento, .references-grid').forEach(grid => {
        const items = grid.querySelectorAll('.card, .reference-card');
        if (!items.length) return;
        gsap.fromTo(items, { y: 60, opacity: 0 }, {
          y: 0,
          opacity: 1,
          duration: 0.8,
          stagger: 0.1,
          ease: 'power3.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: grid, start: 'top 82%', once: true }
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
        gsap.fromTo(teaser, { scale: 0.92, opacity: 0 }, {
          scale: 1,
          opacity: 1,
          duration: 1,
          ease: 'power3.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: teaser, start: 'top 85%', once: true }
        });
      }

      // CTA-Section: Slide von unten
      const ctaSection = document.querySelector('.cta-section');
      if (ctaSection) {
        gsap.fromTo(ctaSection.querySelector('.container'), { y: 80, opacity: 0 }, {
          y: 0,
          opacity: 1,
          duration: 1,
          ease: 'power3.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: ctaSection, start: 'top 85%', once: true }
        });
      }

      // HACCA Inline: Reveal
      const haccaInline = document.querySelector('.hacca-inline__card');
      if (haccaInline) {
        gsap.fromTo(haccaInline, { y: 60, opacity: 0, scale: 0.95 }, {
          y: 0,
          opacity: 1,
          scale: 1,
          duration: 1,
          ease: 'power3.out',
          clearProps: 'transform',
          scrollTrigger: { trigger: haccaInline, start: 'top 85%', once: true }
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

  // aria-current="page" steht statisch im HTML jeder Seite; der fruehere Abgleich ueber
  // pathname.split('/').pop() traf bei Verzeichnis-URLs (/services/) nie und ist entfernt.

  // Herkunft des Besuchs (fuer den Lead-Endpunkt, Schluessel herkunft_web): nur was der
  // Browser ohnehin mitschickt (Referrer) oder in der URL steht (utm_*). Kein Cookie,
  // keine Drittanbieter-IDs; sessionStorage endet mit dem Tab.
  function merkeHerkunft() {
    try {
      if (sessionStorage.getItem('herkunft_web')) return;
      const q = new URLSearchParams(window.location.search);
      const cut = (v) => (v ? String(v).slice(0, 200) : null);
      sessionStorage.setItem('herkunft_web', JSON.stringify({
        referrer: cut(document.referrer) || null,
        utm_source: cut(q.get('utm_source')), utm_medium: cut(q.get('utm_medium')), utm_campaign: cut(q.get('utm_campaign')),
        utm_term: cut(q.get('utm_term')), utm_content: cut(q.get('utm_content')),
        erste_seite: cut(window.location.pathname), landete_auf: cut(window.location.pathname + window.location.search)
      }));
    } catch (e) { /* privater Modus o.ae.: dann ohne Herkunft */ }
  }
  function leseHerkunft() {
    try { const h = sessionStorage.getItem('herkunft_web'); return h ? JSON.parse(h) : null; } catch (e) { return null; }
  }
  merkeHerkunft();

  // --- Lead-Endpunkt (sunds-hub) — zweiter, unabhaengiger Zustellweg ---
  // Vertrag: SCHNITTSTELLE-LEADS.md (Repo) = /opt/sunds-hub/schnittstellen/connect-website-leads.md
  // Sendet ZUSAETZLICH zu Formspree, nie statt. Wirft nie; Erfolg = einer von beiden hat angenommen.
  const LEAD_ENDPUNKT = 'https://leads.sundsconnect.de/lead';
  const SUBJECT_LABELS = { general: 'Allgemeine Anfrage', vertrieb: 'Vertrieb & Sales', automation: 'Automation', ai: 'AI Infrastruktur', ads: 'Google Ads & AI Ads', webdesign: 'Webdesign', project: 'Projektanfrage' };

  function buildLeadPayload(fd) {
    const get = (k) => String(fd.get(k) || '').trim();
    const subject = get('subject');
    const kopf = get('message');
    const zusatz = ['— Angaben aus dem Formular —', 'Betreff: ' + (SUBJECT_LABELS[subject] || subject || '-')].join('\n');
    return {
      kunde: 'connect',
      name: get('name').slice(0, 120),
      telefon: get('phone').slice(0, 60),
      email: get('email').slice(0, 180),
      firma: '',
      plz: '',
      nachricht: (kopf + '\n\n' + zusatz).slice(0, 4000),
      seite: window.location.pathname.slice(0, 300),
      botcheck: get('_gotcha'),
      herkunft_web: leseHerkunft()
    };
  }

  function relayLeadToHub(fd) {
    try {
      return fetch(LEAD_ENDPUNKT, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(buildLeadPayload(fd)),
        keepalive: true
      }).then((r) => r.ok).catch(() => false);
    } catch (e) { return Promise.resolve(false); }
  }

  // --- Contact Form (Formspree + Lead-Endpunkt parallel) ---
  const form = document.querySelector('#contact-form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
      const btn = form.querySelector('button[type="submit"]');
      const statusEl = document.getElementById('form-status');
      const isDE = document.body.classList.contains('lang-de');
      let statusTimer = null;

      function zeigeStatus(text, art) {
        if (!statusEl) return;
        clearTimeout(statusTimer);
        statusEl.textContent = text;
        statusEl.className = 'form-status ' + art;
        statusEl.style.display = 'block';
        statusTimer = setTimeout(() => {
          statusEl.style.display = 'none';
          statusEl.className = 'form-status';
          statusEl.textContent = '';
        }, art === 'error' ? 8000 : 5000);
      }

      // Pflichtfelder pruefen. Das Formular traegt novalidate, damit die Meldung in der
      // gewaehlten Sprache erscheint; bis 01.09.2026 wurde dadurch GAR NICHTS geprueft und
      // ein leeres Formular ging an Formspree und den Lead-Endpunkt.
      const pflicht = Array.from(form.querySelectorAll('[required]'));
      pflicht.forEach((el) => el.removeAttribute('aria-invalid'));
      const fehlend = pflicht.filter((el) => {
        if (el.type === 'checkbox') return !el.checked;
        if (el.type === 'email') return !el.value.trim() || !el.checkValidity();
        return !el.value.trim();
      });
      if (fehlend.length) {
        fehlend.forEach((el) => el.setAttribute('aria-invalid', 'true'));
        const erstes = fehlend[0];
        if (erstes.type === 'checkbox') {
          zeigeStatus(isDE ? 'Bitte stimmen Sie der Datenschutzerklärung zu.' : 'Please agree to the privacy policy.', 'error');
        } else if (erstes.type === 'email' && erstes.value.trim()) {
          zeigeStatus(isDE ? 'Bitte geben Sie eine gültige E-Mail-Adresse an.' : 'Please enter a valid email address.', 'error');
        } else {
          zeigeStatus(isDE
            ? 'Bitte füllen Sie alle Pflichtfelder aus: Name, E-Mail, Betreff, Nachricht.'
            : 'Please fill in all required fields: name, email, subject, message.', 'error');
        }
        erstes.focus();
        return;
      }

      btn.setAttribute('disabled', 'true');

      const data = new FormData(form);

      const formspree = fetch(form.action, {
        method: 'POST',
        body: data,
        headers: { 'Accept': 'application/json' }
      }).then((r) => r.ok).catch(() => false);
      const hub = relayLeadToHub(data);

      Promise.all([formspree, hub]).then(([okFormspree, okHub]) => {
        if (okFormspree || okHub) {
          zeigeStatus(isDE ? 'Vielen Dank! Ihre Nachricht wurde gesendet.' : 'Thank you! Your message has been sent.', 'success');
          form.reset();
        } else {
          throw new Error('Form submission failed');
        }
      }).catch(() => {
        zeigeStatus(isDE ? 'Fehler beim Senden. Bitte versuchen Sie es erneut.' : 'Error sending message. Please try again.', 'error');
      }).finally(() => {
        btn.removeAttribute('disabled');
      });
    });
  }

  // Counter Animation ist jetzt in GSAP ScrollTrigger integriert (siehe oben)

  // --- Scroll Progress Bar ---
  const progressBar = document.querySelector('.scroll-progress');
  if (progressBar) {
    let scrollTicking = false;
    window.addEventListener('scroll', () => {
      if (!scrollTicking) {
        scrollTicking = true;
        requestAnimationFrame(() => {
          const pct = document.documentElement.scrollTop /
                      (document.documentElement.scrollHeight - window.innerHeight) * 100;
          progressBar.style.width = pct + '%';
          scrollTicking = false;
        });
      }
    }, { passive: true });
  }

  // --- Hero Word Rotation ---
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

      card.addEventListener('mouseenter', () => {
        card.classList.remove('is-settling');
        card.classList.add('is-tilting');
      });

      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const x = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        const y = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
        card.style.transform =
          `perspective(600px) rotateY(${x * 5}deg) rotateX(${-y * 5}deg) translateY(-6px) scale(1.01)`;
      });

      card.addEventListener('mouseleave', () => {
        card.style.transform = '';
        card.classList.remove('is-tilting');
        card.classList.add('is-settling');
        setTimeout(() => card.classList.remove('is-settling'), 450);
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

    if (hasWebGL && window.innerWidth > 768) {
      const iframe = heroCanvas.querySelector('iframe');
      if (iframe && iframe.dataset.src) iframe.src = iframe.dataset.src;
      if (iframe) iframe.onload = () => heroCanvas.classList.add('loaded');
      setTimeout(() => heroCanvas.classList.add('loaded'), 4000);

      // Forward mouse position to 3D hero iframe via postMessage
      if (iframe) {
        let lastMouse = { x: 0.5, y: 0.5 };
        let sendScheduled = false;
        document.addEventListener('mousemove', (e) => {
          lastMouse.x = e.clientX / window.innerWidth;
          lastMouse.y = e.clientY / window.innerHeight;
          if (!sendScheduled) {
            sendScheduled = true;
            requestAnimationFrame(() => {
              if (iframe.contentWindow) {
                iframe.contentWindow.postMessage(
                  { type: 'mousemove', x: lastMouse.x, y: lastMouse.y },
                  location.origin
                );
              }
              sendScheduled = false;
            });
          }
        });
      }
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
