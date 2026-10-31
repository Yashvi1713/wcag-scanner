// In-page helpers for the interaction, layout, media and site-wide checks.
// Injected into every scanned page as window.__wcagProbe.
(() => {
  if (window.__wcagProbe) return;
  const P = {};
  let counter = 0;
  const keyOf = (el) => (el.__wcagKey ||= ++counter);
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();

  P.selector = (el) => {
    if (!(el instanceof Element)) return "";
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.documentElement && parts.length < 5) {
      if (node.id && document.querySelectorAll("#" + CSS.escape(node.id)).length === 1) {
        parts.unshift("#" + CSS.escape(node.id));
        break;
      }
      let part = node.localName;
      const parent = node.parentElement;
      if (parent) {
        const same = [...parent.children].filter((c) => c.localName === node.localName);
        if (same.length > 1) part += `:nth-of-type(${same.indexOf(node) + 1})`;
      }
      parts.unshift(part);
      node = parent;
    }
    return parts.join(" > ");
  };

  P.html = (el) => {
    const h = el.outerHTML || "";
    const end = h.indexOf(">");
    const open = end > 0 ? h.slice(0, end + 1) : h.slice(0, 200);
    return open.length > 250 ? open.slice(0, 250) + "…" : open;
  };

  P.name = (el) => {
    const label = clean(el.getAttribute("aria-label"));
    if (label) return label;
    const ids = el.getAttribute("aria-labelledby");
    if (ids) {
      const s = clean(ids.split(/\s+/).map((id) => document.getElementById(id)?.textContent || "").join(" "));
      if (s) return s;
    }
    if (el.labels && el.labels.length) return clean(el.labels[0].textContent);
    const text = clean(el.innerText || el.textContent);
    if (text) return text.slice(0, 120);
    const img = el.querySelector?.("img[alt]");
    if (img && clean(img.alt)) return clean(img.alt);
    return clean(el.getAttribute("title") || el.getAttribute("alt") || el.getAttribute("placeholder") || el.value || "");
  };

  // The area an element paints, including children: an inline <a> wrapping a floated
  // image has a zero-width box of its own, but the image is what the user sees.
  P.box = (el) => {
    let { top, left, bottom, right } = el.getBoundingClientRect();
    for (const child of [...el.querySelectorAll("*")].slice(0, 50)) {
      const r = child.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      top = Math.min(top, r.top); left = Math.min(left, r.left);
      bottom = Math.max(bottom, r.bottom); right = Math.max(right, r.right);
    }
    return { top, left, bottom, right, width: right - left, height: bottom - top };
  };

  P.visible = (el) => {
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return true;
    const b = P.box(el);
    return b.width > 0 && b.height > 0;
  };

  // ---- Keyboard walk -------------------------------------------------------
  // An element has a visible focus indicator if any of these styles (on it, its
  // pseudo-elements, its parent or next sibling) differ between focused and unfocused.
  const PROPS = [
    "outline-style", "outline-width", "outline-color", "box-shadow",
    "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
    "border-top-width", "border-bottom-width", "background-color", "background-image",
    "color", "text-decoration-line", "text-decoration-thickness", "transform", "filter", "opacity",
  ];
  const snapOne = (el, pseudo) => {
    if (!el) return "";
    const cs = getComputedStyle(el, pseudo);
    return PROPS.map((p) => cs.getPropertyValue(p)).join("|");
  };
  const snap = (el) => {
    const label = el.labels && el.labels[0];
    return [snapOne(el), snapOne(el, "::before"), snapOne(el, "::after"), snapOne(el.parentElement),
      snapOne(el.nextElementSibling), snapOne(label), label ? snapOne(label, "::before") : "",
      label ? snapOne(label, "::after") : ""].join("#");
  };
  // Custom checkboxes/radios hide the real input and draw everything on its label.
  const labelVisible = (el) => !!(el.labels && [...el.labels].some((l) => P.visible(l)));

  P.obscuredBy = (el) => {
    const r = P.box(el);
    if (r.width < 4 || r.height < 4) return null;
    const pts = [
      [r.left + r.width / 2, r.top + r.height / 2],
      [r.left + 2, r.top + 2], [r.right - 2, r.top + 2],
      [r.left + 2, r.bottom - 2], [r.right - 2, r.bottom - 2],
    ];
    let coverer = null;
    for (const [x, y] of pts) {
      if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return null;
      const hit = document.elementFromPoint(x, y);
      if (!hit || hit === el || el.contains(hit) || hit.contains(el)) return null;
      let n = hit;
      let fixed = null;
      while (n && n !== document.body) {
        const pos = getComputedStyle(n).position;
        if (pos === "fixed" || pos === "sticky") { fixed = n; break; }
        n = n.parentElement;
      }
      if (!fixed || fixed.contains(el)) return null;
      coverer = fixed;
    }
    return coverer ? P.selector(coverer) : null;
  };

  let prev = null;
  const byKey = new Map();
  P.resetFocusWalk = () => { prev = null; };

  P.focusStep = () => {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
    const out = { prevIndicator: null, current: null };
    if (prev && prev.el !== el) out.prevIndicator = snap(prev.el) !== prev.snap;
    if (!el || el === document.body || el === document.documentElement) { prev = null; return out; }
    if (prev && prev.el === el) { out.current = prev.info; return out; }
    const r = P.box(el);
    const flags = P.focusFlags(el);
    byKey.set(keyOf(el), el);
    const info = {
      key: keyOf(el),
      tag: el.localName,
      selector: P.selector(el),
      html: P.html(el),
      name: P.name(el).slice(0, 80),
      tabindex: el.getAttribute("tabindex"),
      href: el.localName === "a" ? el.getAttribute("href") : null,
      top: r.top + scrollY,
      left: r.left + scrollX,
      ...flags,
      obscuredBy: flags.offscreen ? null : P.obscuredBy(el),
      inMain: !!el.closest("main,[role=main]"),
    };
    prev = { el, snap: snap(el), info };
    out.current = info;
    return out;
  };

  P.focusFlags = (el) => {
    const r = P.box(el);
    return {
      offscreen: r.bottom <= 0 || r.right <= 0 || r.top >= innerHeight || r.left >= innerWidth,
      tiny: (r.width < 3 || r.height < 3) && !labelVisible(el),
      hidden: !P.visible(el) && !labelVisible(el),
    };
  };

  // Re-measure the focused element after scroll/fade-in animations have had time to finish.
  P.recheckFocus = () => {
    let el = document.activeElement;
    while (el && el.shadowRoot && el.shadowRoot.activeElement) el = el.shadowRoot.activeElement;
    if (!el || el === document.body) return null;
    const flags = { ...P.focusFlags(el) };
    flags.obscuredBy = flags.offscreen ? null : P.obscuredBy(el);
    if (prev && prev.el === el) Object.assign(prev.info, flags);
    return flags;
  };

  // For the pixel comparison: scroll an element into view, unfocus it, and return the area to capture.
  P.prepareFocusShot = (key) => {
    const el = byKey.get(key);
    if (!el || !el.isConnected) return null;
    el.scrollIntoView({ block: "center", inline: "nearest" });
    if (document.activeElement === el) el.blur();
    const r = P.box(el);
    const pad = 10;
    const x = Math.max(0, r.left - pad), y = Math.max(0, r.top - pad);
    const width = Math.min(innerWidth, r.right + pad) - x, height = Math.min(innerHeight, r.bottom + pad) - y;
    return width > 2 && height > 2 ? { x, y, width, height } : null;
  };
  P.focusByKey = (key) => byKey.get(key)?.focus({ preventScroll: true });

  P.skipTargetExists = (href) => {
    const id = decodeURIComponent(href.slice(1));
    return !!(document.getElementById(id) || document.getElementsByName(id).length);
  };

  // Tabs, menu items and options use "roving tabindex": one member is in the Tab order and
  // arrow keys move between the rest, so tabindex="-1" on the others is correct.
  const COMPOSITE = "[role=tablist],[role=listbox],[role=menu],[role=menubar],[role=radiogroup],[role=tree],[role=treegrid],[role=grid],[role=toolbar]";
  const reachableByArrows = (el) => {
    const group = el.closest(COMPOSITE);
    if (!group) return false;
    if (group.tabIndex >= 0 && group.hasAttribute("aria-activedescendant")) return true;
    return [...group.querySelectorAll("*")].some((m) => m !== el && m.tabIndex >= 0 && m.getAttribute("role") === el.getAttribute("role"));
  };

  const focusableAncestor = (el) => {
    for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) if (a.tabIndex >= 0) return true;
    return false;
  };

  // Elements that look clickable but can't be reached with Tab.
  P.mouseOnly = () => {
    const FOCUSABLE_INSIDE = 'a[href],button,input,select,textarea,summary,[tabindex]:not([tabindex="-1"]),[contenteditable="true"]';
    const out = [];
    for (const el of document.body.querySelectorAll("*")) {
      if (out.length >= 25) break;
      const onclick = el.hasAttribute("onclick");
      const role = el.getAttribute("role") || "";
      const widgetRole = /^(button|link|tab|menuitem|checkbox|switch|option|radio)$/.test(role);
      if (!onclick && !widgetRole) {
        if (getComputedStyle(el).cursor !== "pointer") continue;
        const parent = el.parentElement;
        if (parent && getComputedStyle(parent).cursor === "pointer") continue; // cursor is inherited: report the outermost only
      }
      if (el.tabIndex >= 0 || reachableByArrows(el)) continue;
      if (getComputedStyle(el).pointerEvents === "none") continue; // clicks pass through to what's underneath
      if (el.parentElement?.closest("a[href],button,label,summary,select")) continue;
      if (focusableAncestor(el)) continue; // e.g. a card wrapper with tabindex="0"
      if (el.querySelector(FOCUSABLE_INSIDE)) continue;
      if (/^(label|option|img|svg|path)$/.test(el.localName)) continue;
      if (!P.visible(el)) continue;
      out.push({ selector: P.selector(el), html: P.html(el), name: P.name(el).slice(0, 80), strong: onclick || widgetRole });
    }
    return out;
  };

  // ---- Forms ---------------------------------------------------------------
  // Fields whose only name is the placeholder, which disappears as soon as the user types.
  P.placeholderOnly = () => [...document.querySelectorAll("input:not([type=hidden]):not([type=submit]):not([type=button]),textarea")]
    .filter((f) => P.visible(f) && f.getAttribute("placeholder") && !(f.labels && f.labels.length)
      && !f.getAttribute("aria-label") && !f.getAttribute("aria-labelledby") && !f.getAttribute("title"))
    .slice(0, 20)
    .map((f) => ({ selector: P.selector(f), html: P.html(f), placeholder: f.getAttribute("placeholder") }));

  // ---- Layout --------------------------------------------------------------
  // Text that is cut off: partly visible, partly hidden by an overflow:hidden/clip container.
  // Text that is entirely hidden (a closed menu, an off-screen slide) or deliberately
  // visually hidden for screen readers is not "cut off".
  const srOnly = (a, cs) => a.clientWidth <= 2 || a.clientHeight <= 2 || cs.clip !== "auto" || cs.clipPath !== "none";
  const range = document.createRange();
  const partlyVisible = (textNode, box) => {
    range.selectNodeContents(textNode);
    const t = range.getBoundingClientRect();
    if (t.width === 0 || t.height === 0) return false;
    const w = Math.min(t.right, box.right) - Math.max(t.left, box.left);
    const h = Math.min(t.bottom, box.bottom) - Math.max(t.top, box.top);
    if (w <= 1 || h <= 1) return false;               // entirely outside: hidden, not cut off
    return w < t.width - 2 || h < t.height - 2;       // some of it is outside the visible box
  };

  P.clippedText = () => {
    const found = new Map();
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.textContent.trim().length > 1 ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_SKIP),
    });
    let n;
    let count = 0;
    while ((n = walker.nextNode()) && count++ < 5000) {
      const el = n.parentElement;
      if (!el || /^(script|style|noscript|option|textarea|title)$/.test(el.localName)) continue;
      let a = el;
      for (let depth = 0; a && a !== document.body && depth < 4; depth++, a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (!/(hidden|clip)/.test(cs.overflowX + cs.overflowY)) continue;
        if ((a.scrollHeight > a.clientHeight + 2 || a.scrollWidth > a.clientWidth + 2) && !srOnly(a, cs)
            && P.visible(a) && partlyVisible(n, a.getBoundingClientRect())) {
          found.set(keyOf(a), a);
        }
        break;
      }
    }
    return [...found.entries()].slice(0, 200).map(([key, a]) => ({
      key, selector: P.selector(a), html: P.html(a), text: clean(a.innerText).slice(0, 80),
    }));
  };

  P.reflow = () => {
    const vw = document.documentElement.clientWidth;
    const sw = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth);
    const offenders = [];
    if (sw > vw + 1) {
      for (const el of document.body.querySelectorAll("*")) {
        if (offenders.length >= 10) break;
        const r = el.getBoundingClientRect();
        if (r.right <= vw + 1 || r.width === 0 || r.height === 0) continue;
        const parent = el.parentElement;
        if (parent && parent !== document.body && parent.getBoundingClientRect().right > vw + 1) continue;
        // Fixed elements (e.g. a cart drawer slid off-screen) never make the page scroll sideways.
        let contained = getComputedStyle(el).position === "fixed";
        for (let a = el.parentElement; a && a !== document.body && !contained; a = a.parentElement) {
          const cs = getComputedStyle(a);
          if (cs.overflowX !== "visible" || cs.position === "fixed") contained = true;
        }
        if (contained) continue;
        offenders.push({
          selector: P.selector(el), html: P.html(el), width: Math.round(r.width),
          exempt: !!el.closest("table,pre,code,video,canvas,iframe,[role=toolbar],[role=application]"),
        });
      }
    }
    return { viewport: vw, scrollWidth: sw, offenders };
  };

  // ---- Media ---------------------------------------------------------------
  P.media = () => {
    const els = [...document.querySelectorAll("video,audio")];
    const embeds = [...document.querySelectorAll("iframe[src]")].filter((f) =>
      /youtube|youtu\.be|vimeo|wistia|dailymotion|soundcloud|spotify|brightcove|jwplayer/i.test(f.src));
    const media = els.map((m) => ({
      tag: m.localName, selector: P.selector(m), html: P.html(m),
      playing: !m.paused && !m.ended, muted: m.muted || m.volume === 0,
      duration: isFinite(m.duration) ? m.duration : -1, controls: m.controls, loop: m.loop,
    }));
    const targets = (document.getAnimations ? document.getAnimations() : [])
      .filter((a) => a.playState === "running" && a.effect && a.effect.getComputedTiming().iterations === Infinity)
      .map((a) => a.effect.target)
      .filter((el) => el instanceof Element && P.visible(el) && el.getBoundingClientRect().width * el.getBoundingClientRect().height > 2500);
    const animations = [...new Set(targets)].slice(0, 5).map((el) => ({ selector: P.selector(el), html: P.html(el) }));
    return { media, animations, count: els.length + embeds.length };
  };

  // ---- Site-wide signals ---------------------------------------------------
  P.signals = () => {
    const CHROME = "header,nav,footer,[role=banner],[role=navigation],[role=contentinfo]";
    const anchors = [...document.querySelectorAll("a[href]")].slice(0, 800);
    const links = anchors.map((a) => ({ href: a.href, name: P.name(a).slice(0, 80), chrome: !!a.closest(CHROME) }));
    // The main navigation: the visible <nav> with the most links (mobile menus are usually hidden).
    const navNames = [...document.querySelectorAll("nav,[role=navigation]")]
      .filter((n) => P.visible(n))
      .map((n) => [...n.querySelectorAll("a[href]")].map((a) => P.name(a).toLowerCase()).filter(Boolean).slice(0, 40))
      .sort((a, b) => b.length - a.length)[0] || [];
    const helpRe = /\b(contact|help|support|faq|chat|customer service)\b/i;
    const help = [];
    for (const l of links) {
      let label = null;
      if (l.href.startsWith("tel:")) label = "phone";
      else if (l.href.startsWith("mailto:")) label = "email";
      else if (helpRe.test(l.name)) label = l.name.toLowerCase().match(helpRe)[1];
      if (label && !help.includes(label)) help.push(label);
    }
    const hasSearch = !!document.querySelector(
      'input[type=search],[role=search],search,form[action*=search i],input[name=q],input[name=s],input[name=search],input[name=query]');
    return {
      title: clean(document.title),
      links,
      navNames,
      help,
      hasSearch,
      hasSitemapLink: links.some((l) => /site\s?map/i.test(l.name) || /sitemap/i.test(l.href)),
    };
  };

  // ---- AI review inputs ----------------------------------------------------
  P.aiData = () => {
    const vis = (el) => P.visible(el);
    const imgs = [...document.querySelectorAll("img,[role=img],svg[aria-label]")]
      .filter((el) => { const r = el.getBoundingClientRect(); return r.width >= 40 && r.height >= 40 && vis(el); })
      .slice(0, 8)
      .map((el, i) => {
        const id = "img-" + (i + 1);
        el.setAttribute("data-wcag-ai", id);
        const link = el.closest("a");
        return {
          id, alt: el.getAttribute("alt"), ariaLabel: el.getAttribute("aria-label"), role: el.getAttribute("role"),
          src: (el.currentSrc || el.getAttribute("src") || "").split("?")[0].split("/").pop().slice(0, 80),
          linkText: link ? P.name(link).slice(0, 60) : null, selector: P.selector(el),
        };
      });
    const links = [...document.querySelectorAll("a[href]")].filter(vis).slice(0, 60).map((a, i) => ({
      id: "link-" + (i + 1), name: P.name(a).slice(0, 80), href: (a.getAttribute("href") || "").slice(0, 100),
      context: clean(a.closest("p,li,td,article,section")?.innerText).slice(0, 140), selector: P.selector(a),
    }));
    const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]")].filter(vis).slice(0, 40).map((h, i) => ({
      id: "heading-" + (i + 1), level: h.getAttribute("aria-level") || h.localName.replace("h", ""),
      text: P.name(h).slice(0, 100), selector: P.selector(h),
    }));
    const fields = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")].filter(vis).slice(0, 30).map((f, i) => ({
      id: "field-" + (i + 1), type: f.type || f.localName, label: P.name(f).slice(0, 80),
      placeholder: f.getAttribute("placeholder"), selector: P.selector(f),
    }));
    const instructions = [...document.querySelectorAll("p,li,label,small,span")]
      .map((e) => clean(e.innerText))
      .filter((t) => t.length > 10 && t.length < 200 && /\b(red|green|blue|yellow|orange|colou?r|left|right|above|below|round|square|circle|star|asterisk|icon)\b/i.test(t))
      .filter((t, i, all) => all.indexOf(t) === i)
      .slice(0, 15);
    return { imgs, links, headings, fields, instructions };
  };

  // ---- Report screenshot ---------------------------------------------------
  P.annotate = (selectors) => {
    const style = document.createElement("style");
    style.textContent = "[data-wcag-flag]{outline:3px solid #d0021b !important;outline-offset:2px !important}";
    document.head.append(style);
    let n = 0;
    for (const s of selectors) {
      try { document.querySelectorAll(s).forEach((e) => { e.setAttribute("data-wcag-flag", ""); n++; }); } catch (_) {}
    }
    return n;
  };

  window.__wcagProbe = P;
})();
