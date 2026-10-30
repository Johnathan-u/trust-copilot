/* TrustCopilot's local, read-only backlog view. All repository text is untrusted. */
(() => {
  'use strict';
  const data = window.TRUSTCOPILOT_BACKLOG;
  const main = document.getElementById('main');
  const dialog = document.getElementById('ticket-dialog');
  const titles = { overview: 'Release overview', backlog: 'Full backlog', epics: 'Epic portfolio', gates: 'Release gates', handoff: 'PM handoff', history: 'Change history' };
  const labels = {
    BASELINE_RECONCILIATION: 'Baseline pending', EVIDENCE_RECONCILIATION: 'Evidence review',
    IMPLEMENTATION_GAPS_IDENTIFIED: 'Gaps identified', IN_PROGRESS: 'In progress',
    READY: 'Ready', BLOCKED: 'Blocked', IN_REVIEW: 'In review', DONE: 'Done', REOPENED: 'Reopened',
    PENDING: 'Pending', NOT_ACCEPTED: 'Not accepted', ACCEPTED: 'Accepted', REVOKED: 'Revoked',
    NOT_VERIFIED: 'Not verified', VERIFIED: 'Verified', VERIFIED_ACCEPTED: 'Verified accepted',
    OPEN: 'Open', BLOCKED_EXTERNAL: 'External gate', PASSED: 'Passed', MERGED: 'Merged', CLOSED: 'Closed',
  };
  const statusOrder = ['BASELINE_RECONCILIATION', 'EVIDENCE_RECONCILIATION', 'IMPLEMENTATION_GAPS_IDENTIFIED', 'IN_PROGRESS', 'BLOCKED', 'READY', 'IN_REVIEW', 'REOPENED', 'DONE'];
  const filters = { search: '', epic: '', priority: '', status: '', owner: '' };
  let activeView = null;
  let activeTicket = null;
  let returnFocus = null;
  let focusMainOnRoute = false;

  function text(value, fallback = 'Not recorded') {
    if (value === null || value === undefined || value === '') return fallback;
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }
  function array(value) { return Array.isArray(value) ? value : []; }
  function plainSearchText(value) {
    if (typeof value === 'string' || typeof value === 'number') return String(value);
    if (Array.isArray(value)) return value.map(plainSearchText).join(' ');
    if (value && typeof value === 'object') return Object.values(value).map(plainSearchText).join(' ');
    return '';
  }
  function human(value) {
    const raw = text(value, 'Not recorded');
    return labels[raw.toUpperCase()] || raw.replace(/_/g, ' ').toLowerCase().replace(/^./, value => value.toUpperCase());
  }
  function number(value) { return Number.isFinite(value) ? value.toLocaleString('en-US') : '—'; }
  function element(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [name, value] of Object.entries(attrs)) {
      if (value !== null && value !== undefined && value !== false) node.setAttribute(name, String(value));
    }
    for (const child of children.flat(Infinity)) {
      if (child === null || child === undefined || child === false) continue;
      node.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return node;
  }
  function button(label, onClick, className = 'button') {
    const node = element('button', { type: 'button', class: className }, label);
    node.addEventListener('click', onClick);
    return node;
  }
  function icon(path) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    const shape = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    shape.setAttribute('d', path);
    svg.append(shape);
    return svg;
  }
  function tone(value) {
    const key = text(value, '').toUpperCase();
    if (['PASSED', 'DONE', 'ACCEPTED', 'VERIFIED', 'VERIFIED_ACCEPTED', 'READY', 'MERGED'].includes(key)) return 'teal';
    if (['BLOCKED', 'BLOCKED_EXTERNAL', 'REVOKED', 'NOT_ACCEPTED', 'P0'].includes(key)) return 'red';
    if (['IMPLEMENTATION_GAPS_IDENTIFIED', 'REOPENED', 'OPEN', 'P1'].includes(key)) return 'amber';
    if (['IN_PROGRESS', 'IN_REVIEW', 'EVIDENCE_RECONCILIATION'].includes(key)) return 'blue';
    return '';
  }
  function badge(value, label) { return element('span', { class: `badge ${tone(value)}` }, label || human(value)); }
  function externalURL(value) {
    try {
      const url = new URL(String(value));
      return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function link(value, label = value, className = '') {
    const href = externalURL(value);
    return href
      ? element('a', { href, target: '_blank', rel: 'noopener noreferrer', title: String(value), class: className }, text(label))
      : element('span', { class: 'muted' }, text(label));
  }
  function fileLink(path, label = path) {
    const value = text(path, '');
    const parts = value.split('/');
    const safe = value && !/^[\/\\]|[:\\?#\u0000-\u001f]/.test(value) && parts.every(part => part && part !== '..' && part !== '.');
    return safe
      ? element('a', { href: '../../' + parts.map(encodeURIComponent).join('/'), target: '_blank', rel: 'noopener noreferrer' }, text(label))
      : element('span', {}, text(label));
  }
  function urlLabel(value) {
    const href = externalURL(value);
    if (!href) return text(value);
    const url = new URL(href);
    const blob = url.pathname.match(/\/blob\/[^/]+\/(.+)$/);
    if (blob) {
      try { return decodeURI(blob[1]); } catch { return blob[1]; }
    }
    const pr = url.pathname.match(/\/pull\/(\d+)/);
    if (pr) return `Pull request #${pr[1]}`;
    const run = url.pathname.match(/\/actions\/runs\/(\d+)/);
    if (run) return `CI run ${run[1]}`;
    return url.hostname + url.pathname + url.hash;
  }
  function links(values) {
    return element('ul', { class: 'link-list' }, array(values).map(value => {
      const url = typeof value === 'string' ? value : value.url;
      return element('li', {}, link(url, typeof value === 'object' && value.title ? value.title : urlLabel(url)));
    }));
  }
  function date(value) {
    if (!value) return 'Not recorded';
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return text(value);
    return parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' }) + ' · ' + parsed.toISOString().slice(11, 16) + ' UTC';
  }
  function code(value, fallback) { return element('code', {}, text(value, fallback)); }
  function routeHash(view, ticket) { return ticket ? `#view=${encodeURIComponent(view)}&ticket=${encodeURIComponent(ticket)}` : `#${view}`; }
  function viewLink(label, view, className = 'text-link') { return element('a', { href: routeHash(view), class: className }, label); }
  function ticketLink(id, label = id, attrs = {}) {
    const node = element('a', { href: routeHash(activeView || 'backlog', id), 'data-open-ticket': id, ...attrs }, label);
    node.addEventListener('click', () => { if (!dialog.open) returnFocus = node; });
    return node;
  }
  function list(values, ordered = false, className = '') {
    const items = array(values);
    return items.length ? element(ordered ? 'ol' : 'ul', { class: className }, items.map(value => element('li', {}, text(value)))) : element('p', { class: 'muted' }, 'None recorded.');
  }
  function details(label, ...children) { return element('details', {}, element('summary', {}, label), children); }
  function rawDetails(label, value, note) {
    return element('details', { class: 'record-details' }, element('summary', {}, label), note ? element('p', {}, note) : null, element('pre', {}, JSON.stringify(value, null, 2)));
  }
  function definitionList(entries, className = 'detail-grid') {
    return element('dl', { class: className }, entries.map(([label, value, wide]) => element('div', { class: wide ? 'span-all' : null }, element('dt', {}, label), element('dd', {}, value))));
  }
  function section(title, ...children) { return element('section', { class: 'detail-section' }, element('h3', {}, title), children); }

  if (!data || !data.meta || !data.summary || !Array.isArray(data.tickets) || !Array.isArray(data.epics)) {
    main.replaceChildren(element('section', { class: 'empty-state' }, element('h1', {}, 'Snapshot unavailable'), element('p', {}, 'Generate the versioned backlog data, then open this page again.'), element('pre', {}, 'python scripts/backlog_tracker.py build'), element('p', {}, fileLink('docs/planning/backlog-state.json', 'Open the state ledger'))));
    return;
  }

  const tickets = new Map(data.tickets.map(ticket => [ticket.id, ticket]));
  const epics = new Map(data.epics.map(epic => [epic.id, epic]));
  const followups = array(data.followups);
  const followupMap = new Map(followups.map(ticket => [ticket.id, ticket]));
  const dependencyRulings = new Map(array(data.dependency_rulings).map(ruling => [ruling.id, ruling]));
  const initialAudit = data.audit_context || {};
  // Build once: requirements, paths, commands, and current evidence are searchable.
  const searchIndex = new Map(data.tickets.map(ticket => [ticket.id, [plainSearchText(ticket), epics.get(ticket.epic)?.title || '', human(ticket.current?.status), ticket.current?.owner || 'unassigned'].join(' ').toLowerCase()]));
  const summary = data.summary;
  const operating = data.operating || {};
  const baselineVerified = String(data.meta.baseline_status).toUpperCase() === 'VERIFIED' && Number.isFinite(summary.completion_percentage) && Number.isFinite(summary.accepted_points);
  const recordedStates = [...new Set(data.tickets.map(ticket => ticket.current?.status || 'BASELINE_RECONCILIATION'))];
  recordedStates.sort((a, b) => {
    const first = statusOrder.indexOf(a), second = statusOrder.indexOf(b);
    return (first < 0 ? 99 : first) - (second < 0 ? 99 : second) || a.localeCompare(b);
  });

  function initialAuditProvenance() {
    return element('p', { class: 'source-warning' }, element('strong', {}, 'Initial audit · '),
      element('time', { 'data-initial-audit-time': '', datetime: initialAudit.as_of_utc || '' }, date(initialAudit.as_of_utc)),
      ' · Source SHA ', element('code', { 'data-initial-audit-sha': '', title: text(initialAudit.source_sha) }, text(initialAudit.source_sha).slice(0, 12)),
      '. Later state updates do not refresh this initial audit record. Recheck its findings against current evidence.');
  }
  function snapshotNotice() {
    const ageHours = (Date.now() - new Date(data.meta.as_of_utc).getTime()) / 3600000;
    let warning = ' Reconcile current assignments, PR heads, and gates before acting.';
    if (ageHours > 24) warning = ` This snapshot is older than 24 hours (${Math.floor(ageHours / 24)} day${Math.floor(ageHours / 24) === 1 ? '' : 's'}). Reconcile and regenerate before acting.`;
    else if (ageHours < -1) warning = ' The source timestamp is ahead of this device’s clock; verify freshness before acting.';
    return element('div', { id: 'snapshot-notice', class: 'notice' }, element('span', { class: 'notice-icon', 'aria-hidden': 'true' }, 'i'), element('p', {}, element('strong', {}, 'Static snapshot.'), ' This page does not poll GitHub.', warning, ' ', link(operating.ledger_url, 'Open decision ledger #85 ↗')));
  }
  function exportSnapshot() {
    const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = element('a', { href: url, download: `trustcopilot-backlog-r${String(data.meta.revision).replace(/[^a-zA-Z0-9_-]/g, '')}.json` });
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    document.getElementById('announcer').textContent = 'Snapshot export started. This downloads a copy; it does not update repository state.';
  }
  function pageHeader(view, subtitle) {
    const exportButton = button('Export snapshot', exportSnapshot);
    exportButton.prepend(icon('M12 3v12m-4-4 4 4 4-4M5 15v5h14v-5'));
    return element('div', { class: 'page-header' }, element('div', {}, element('div', { class: 'eyebrow' }, 'Full-suite release / scope v' + text(data.meta.scope_version)), element('h1', { tabindex: '-1' }, titles[view]), element('p', {}, subtitle)), element('div', { class: 'header-actions' }, exportButton, viewLink(view === 'handoff' ? 'Browse backlog' : 'PM workflow', view === 'handoff' ? 'backlog' : 'handoff', 'button button-primary')));
  }
  function cardHeader(title, subtitle, action) { return element('div', { class: 'card-header' }, element('div', {}, element('h2', {}, title), subtitle ? element('p', {}, subtitle) : null), action); }
  function stat(label, value, note, key) { return element('div', { class: 'stat' }, element('span', { class: 'stat-label' }, label), element('strong', { class: 'stat-value', 'data-metric': key }, value), element('span', { class: 'stat-note' }, note)); }
  function resetFilters() { Object.assign(filters, { search: '', epic: '', priority: '', status: '', owner: '' }); }
  function showFiltered(patch) {
    resetFilters();
    Object.assign(filters, patch);
    if (activeView === 'backlog') renderView('backlog');
    else window.location.hash = '#backlog';
  }
  function countStatus(status) { return data.tickets.filter(ticket => ticket.current?.status === status).length; }
  function assessed(ticket) { return ['NOT_ACCEPTED', 'ACCEPTED', 'REVOKED'].includes(ticket.current?.acceptance?.state); }
  function progressMeter(value, total, label, pending = false) {
    const width = Number.isFinite(value) && total > 0 ? Math.max(0, Math.min(100, value / total * 100)) : 0;
    const meter = element('div', { class: `meter${pending ? ' is-pending' : ''}`, role: 'img', 'aria-label': label });
    if (!pending) {
      const bar = element('span');
      bar.style.width = width + '%';
      meter.append(bar);
    }
    return meter;
  }
  function overview() {
    const progress = element('section', { id: 'acceptance-progress', class: 'readiness-card' },
      element('div', { class: 'readiness-main' }, element('div', { class: 'eyebrow' }, 'Acceptance-based progress'),
        element('h2', {}, baselineVerified ? number(summary.completion_percentage) + '% accepted' : 'Baseline pending'),
        element('p', {}, baselineVerified ? 'Completion is weighted by the original parent points with recorded full-contract acceptance.' : 'The original acceptance baseline is still being reconciled. A completion percentage will be published after every original ticket has been assessed.'),
        element('div', { class: 'acceptance-value' }, element('span', {}, 'Accepted original-parent points'), element('strong', {}, (baselineVerified ? number(summary.accepted_points) : 'Unknown') + ' / ' + number(summary.total_points))),
        progressMeter(summary.accepted_points, summary.total_points, baselineVerified ? `${number(summary.completion_percentage)} percent accepted` : 'Completion percentage unavailable pending verified baseline', !baselineVerified),
        element('span', { class: 'metric-rule' }, 'Only full original-parent acceptance earns points. Supplemental work carries no additional weight.')),
      element('div', { class: 'coverage-panel' }, element('div', { class: 'eyebrow' }, 'Acceptance assessment coverage'), element('div', { class: 'coverage-value' }, number(summary.assessed_tickets), element('span', {}, ' / ' + number(summary.total_tickets))), element('p', {}, 'Original tickets with a recorded acceptance assessment, including incomplete work.'), progressMeter(summary.assessed_tickets, summary.total_tickets, `${summary.assessed_tickets} of ${summary.total_tickets} original tickets assessed`), viewLink('Review the original backlog →', 'backlog')));
    const states = element('section', { class: 'card' }, cardHeader('Recorded work', 'Status signals from the pinned evidence snapshot.', viewLink('All tickets →', 'backlog')),
      element('div', { class: 'status-list' }, recordedStates.map(status => {
        const row = button('', () => showFiltered({ status }), 'status-row');
        row.append(element('span', { class: `status-dot ${tone(status)}`, 'aria-hidden': 'true' }), element('span', {}, human(status)), element('strong', {}, number(countStatus(status))));
        return row;
      })), element('p', { class: 'fine-print' }, 'These signals do not establish full-ticket acceptance or an assigned owner.'));
    const gates = array(data.release_gates);
    const gatePreview = element('section', { class: 'card' }, cardHeader('Release gates', `${gates.filter(gate => gate.status !== 'PASSED').length} of ${gates.length} gates still require resolution.`, viewLink('View gates →', 'gates')),
      gates.slice(0, 4).map(gate => element('div', { class: 'gate-preview' }, element('span', { class: 'gate-id' }, gate.id), element('div', {}, element('h3', {}, gate.title), badge(gate.status)))));
    const active = data.tickets.filter(ticket => ['IN_PROGRESS', 'BLOCKED', 'IMPLEMENTATION_GAPS_IDENTIFIED', 'IN_REVIEW', 'REOPENED'].includes(ticket.current?.status));
    const work = element('section', { class: 'card' }, cardHeader('Work to reconcile', 'Recorded activity and implementation gaps. Confirm ownership in the decision ledger.', viewLink('Open backlog →', 'backlog')),
      active.length ? element('ul', { class: 'work-list' }, active.slice(0, 6).map(ticket => element('li', { class: 'work-item' }, ticketLink(ticket.id, [element('span', { class: 'ticket-id' }, ticket.id), ticket.title]), element('p', {}, text(ticket.current.next_action, 'No next action recorded.')), badge(ticket.current.status)))) : element('p', { class: 'muted' }, 'No activity or implementation gaps recorded in this snapshot.'));
    return [pageHeader('overview', 'The full release scope, acceptance evidence, and next decisions in one place.'), snapshotNotice(),
      element('div', { class: 'stats-grid' }, stat('Original tickets', number(summary.total_tickets), 'Complete canonical scope', 'tickets'), stat('Epics in scope', number(data.epics.length), 'Full-suite release', 'epics'), stat('Original story points', number(summary.total_points), 'Fixed progress denominator', 'points'), stat('Acceptance assessments', number(summary.assessed_tickets), 'Of ' + number(summary.total_tickets) + ' original tickets', 'assessed')),
      progress, element('div', { class: 'overview-columns' }, states, gatePreview), work,
      element('div', { class: 'handoff-strip' }, element('div', {}, element('h2', {}, 'A shared handoff for every PM'), element('p', {}, `Initial audit ${date(initialAudit.as_of_utc)} · ${number(array(data.pull_requests).length)} observed PR records · ${number(array(data.reconciliation_queue).length)} reconciliation entries`), element('p', {}, `${number(followups.length)} supplemental records in the state ledger`)), viewLink('Open PM handoff →', 'handoff', 'button'))];
  }

  function filterControl(label, key, choices, placeholder) {
    const select = element('select', { id: `filter-${key}` }, element('option', { value: '' }, placeholder), choices.map(([value, name]) => element('option', { value }, name)));
    select.value = filters[key];
    select.addEventListener('change', () => { filters[key] = select.value; renderBacklogResults(); });
    return element('div', {}, element('label', { class: 'field-label', for: `filter-${key}` }, label), select);
  }
  function supplementalRows(items) {
    return items.map(item => element('div', { class: 'followup-row' }, element('p', {}, link(item.source_url, `${item.id} · ${item.title}`)), element('small', {}, item.parent_id ? ['Original parent: ', tickets.has(item.parent_id) ? ticketLink(item.parent_id, item.parent_id) : text(item.parent_id), ' · '] : 'No original parent recorded · ', item.story_points == null ? 'Estimate not recorded' : `${number(item.story_points)} supplemental points`, ' · Excluded from original total')));
  }
  function backlog() {
    const search = element('input', { type: 'search', id: 'backlog-search', 'aria-label': 'Search backlog', 'aria-describedby': 'backlog-help', placeholder: 'Search tickets, requirements, files, commands, or current state…', autocomplete: 'off', spellcheck: 'false' });
    search.value = filters.search;
    search.addEventListener('input', () => { filters.search = search.value; renderBacklogResults(); });
    const owners = [...new Set(data.tickets.map(ticket => ticket.current?.owner).filter(Boolean))].sort();
    const controls = element('section', { class: 'filters', 'aria-label': 'Backlog filters' }, element('div', { class: 'search-wrap' }, icon('m21 21-6-6M10 18a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z'), search),
      element('div', { class: 'filter-grid' },
        filterControl('Epic', 'epic', data.epics.map(epic => [epic.id, `${epic.id} · ${epic.title}`]), 'All epics'),
        filterControl('Priority', 'priority', [...new Set(data.tickets.map(ticket => ticket.priority))].sort().map(value => [value, value]), 'All priorities'),
        filterControl('Recorded status', 'status', recordedStates.map(value => [value, human(value)]), 'All statuses'),
        filterControl('Assigned owner', 'owner', [['__unassigned__', 'Unassigned'], ...owners.map(value => [value, value])], 'All owners'),
        button('Reset filters', () => { resetFilters(); renderView('backlog'); document.getElementById('backlog-search').focus(); })),
      element('p', { id: 'backlog-help', class: 'fine-print' }, 'Search covers the complete original contract and current records. Filters use reconciled status and recorded assignments; historical planning metadata is preserved in each ticket.'));
    const supplemental = followups.length ? element('details', { class: 'record-details' }, element('summary', {}, `${followups.length} supplemental records · separate from original scope`), element('p', {}, 'Child and release follow-up estimates never increase the original progress denominator.'), element('div', { class: 'supplemental-scroll' }, supplementalRows(followups))) : null;
    return [pageHeader('backlog', 'Every original ticket, with its full delivery contract and current evidence.'), snapshotNotice(), controls, element('div', { id: 'backlog-results' }), supplemental];
  }
  function renderBacklogResults() {
    const container = document.getElementById('backlog-results');
    if (!container) return;
    const query = filters.search.trim();
    const exactTicket = tickets.get(query.toUpperCase());
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    const matching = data.tickets.filter(ticket => {
      const current = ticket.current || {};
      const searchable = searchIndex.get(ticket.id);
      return (exactTicket ? ticket.id === exactTicket.id : terms.every(term => searchable.includes(term))) && (!filters.epic || ticket.epic === filters.epic) && (!filters.priority || ticket.priority === filters.priority) && (!filters.status || current.status === filters.status) && (!filters.owner || (filters.owner === '__unassigned__' ? !current.owner : current.owner === filters.owner));
    });
    const toolbar = element('div', { class: 'results-toolbar' }, element('span', { id: 'backlog-count', role: 'status', 'aria-live': 'polite' }, element('strong', {}, `${number(matching.length)} of ${number(data.tickets.length)}`), ' original tickets'), element('span', {}, number(matching.reduce((total, ticket) => total + ticket.story_points, 0)) + ' original points in this view'));
    if (!matching.length) {
      container.replaceChildren(toolbar, element('div', { class: 'empty-state' }, element('h2', {}, 'No matching tickets'), element('p', {}, 'Try a broader search or clear the filters to see the full backlog.'), button('Reset filters', () => { resetFilters(); renderView('backlog'); document.getElementById('backlog-search').focus(); })));
      return;
    }
    const table = element('table', { class: 'backlog-table', role: 'table' }, element('caption', { class: 'visually-hidden' }, 'Original release tickets and recorded status'),
      element('thead', {}, element('tr', {}, ['Ticket / scope', 'Epic', 'Priority', 'Recorded status', 'Assigned owner', 'Points'].map(label => element('th', { scope: 'col' }, label)))),
      element('tbody', {}, matching.map(ticket => {
        const current = ticket.current || {};
        return element('tr', { 'data-ticket-row': ticket.id },
          element('td', { class: 'ticket-main', 'data-label': 'Ticket' }, ticketLink(ticket.id, [element('span', { class: 'ticket-id' }, ticket.id), element('span', { class: 'ticket-name' }, ticket.title)], { class: 'ticket-link' })),
          element('td', { 'data-label': 'Epic' }, element('span', { title: epics.get(ticket.epic)?.title }, ticket.epic)),
          element('td', { 'data-label': 'Priority' }, badge(ticket.priority, ticket.priority)),
          element('td', { 'data-label': 'Recorded status' }, badge(current.status || 'BASELINE_RECONCILIATION')),
          element('td', { 'data-label': 'Assigned owner', class: current.owner ? null : 'muted' }, text(current.owner, 'Unassigned')),
          element('td', { 'data-label': 'Original points' }, number(ticket.story_points)));
      })));
    container.replaceChildren(toolbar, element('div', { class: 'table-wrap' }, table));
  }

  function epicPortfolio() {
    return [pageHeader('epics', 'Thirty original delivery areas, with scope and acceptance review coverage.'), snapshotNotice(),
      element('div', { class: 'epics-grid' }, data.epics.map(epic => {
        const children = data.tickets.filter(ticket => ticket.epic === epic.id);
        const reviewed = Number.isFinite(epic.rollup?.assessed_tickets) ? epic.rollup.assessed_tickets : children.filter(assessed).length;
        const acceptedPoints = children.filter(ticket => ticket.current?.acceptance?.state === 'ACCEPTED').reduce((sum, ticket) => sum + ticket.story_points, 0);
        const more = details('Original epic contract & dependencies', element('p', {}, 'Use each ticket’s engineering prerequisites and release gates for scheduling.'), element('p', {}, element('strong', {}, 'Expected owner role: '), text(epic.owner)), element('p', {}, 'Historical planning status: ', text(epic.status)), element('h3', {}, 'Definition of done'), list(epic.definition_of_done), element('p', {}, 'Original epic dependencies: ', array(epic.depends_on).length ? array(epic.depends_on).map(id => {
          const target = button(id, () => showFiltered({ epic: id }), 'chip'); target.title = epics.get(id)?.title || id; return target;
        }) : 'No dependency recorded.'), rawDetails('Complete original epic record', epic));
        return element('article', { class: 'card epic-card' }, element('div', { class: 'epic-top' }, element('span', { class: 'epic-code' }, epic.id), badge(baselineVerified ? 'VERIFIED' : 'PENDING', baselineVerified ? `${number(acceptedPoints)} accepted points` : 'Acceptance pending')), element('h2', {}, epic.title), element('p', { class: 'epic-objective' }, epic.objective),
          element('div', { class: 'epic-stats' }, element('span', {}, element('strong', {}, number(children.length)), 'original tickets'), element('span', {}, element('strong', {}, number(epic.story_points)), 'original points')),
          element('div', { class: 'epic-bottom' }, element('span', {}, `${reviewed} / ${children.length} assessed`), button('View tickets →', () => showFiltered({ epic: epic.id }), 'button')), more);
      }))];
  }
  function gateCard(gate) {
    return element('article', { class: 'card gate-card' }, element('header', {}, element('div', {}, element('span', { class: 'ticket-id' }, gate.id), element('h3', {}, gate.title)), badge(gate.status)), element('p', { class: 'gate-note' }, text(gate.note)),
      element('div', { class: 'gate-meta' }, 'Assigned owner: ', text(gate.owner, 'Unassigned'), element('div', { class: 'chip-list' }, array(gate.ticket_ids).map(id => tickets.has(id) ? ticketLink(id, id, { class: 'chip' }) : element('span', { class: 'chip' }, id)))),
      array(gate.evidence_urls).length ? details(`${gate.evidence_urls.length} evidence references`, links(gate.evidence_urls)) : element('p', { class: 'fine-print' }, 'No evidence links recorded.'), gate.rule ? element('p', { class: 'fine-print' }, gate.rule) : null);
  }
  function gatesView() {
    return [pageHeader('gates', 'Release decisions and operational checks, tracked independently of point completion.'), snapshotNotice(),
      element('div', { class: 'section-intro' }, element('div', {}, element('h2', {}, 'Release qualification'), element('p', {}, 'Every gate requires its own evidence and recorded decision.'))),
      element('div', { class: 'gates-grid' }, array(data.release_gates).map(gateCard)),
      element('div', { class: 'section-intro' }, element('div', {}, element('h2', {}, 'Operational & external gates'), element('p', {}, 'Provider, rights, CI, and owner decisions remain visible alongside engineering work.'))),
      element('div', { class: 'gates-grid' }, array(data.operational_gates).map(gateCard))];
  }
  function prRecord(pr) {
    const parents = array(pr.mapped_original_parents).map(item => item.parent_id);
    return element('div', { class: 'followup-row' }, element('p', {}, link(pr.url, `#${text(pr.number, '?')} · ${text(pr.title, 'Pull request')}`), ' ', badge(pr.state), pr.draft ? [' ', badge('PENDING', 'Draft')] : null),
      element('small', {}, 'Recorded head: ', code(pr.head_sha), pr.merge_commit_sha ? [' · Merge SHA: ', code(pr.merge_commit_sha)] : null),
      pr.merged_at ? element('p', { class: 'fine-print' }, 'Merged: ', date(pr.merged_at)) : null,
      parents.length ? element('div', { class: 'chip-list' }, [...new Set(parents)].map(id => ticketLink(id, id, { class: 'chip' }))) : null,
      array(pr.description_caveats).length ? list(pr.description_caveats) : null);
  }
  function reconciliationRecord(item) {
    return element('div', { class: 'followup-row' }, element('h3', {}, text(item.queue_id), ' · ', tickets.has(item.existing_parent_id) ? ticketLink(item.existing_parent_id, item.existing_parent_id) : text(item.existing_parent_id)),
      element('p', {}, text(item.finding)), array(item.validation_required).length ? [element('h4', {}, 'Validation required'), list(item.validation_required)] : null,
      array(item.criterion_ids_to_reconcile).length ? element('p', { class: 'fine-print' }, 'Criteria: ', item.criterion_ids_to_reconcile.join(', ')) : null,
      links(item.source_urls), item.acceptance_effect ? element('p', { class: 'fine-print' }, item.acceptance_effect) : null,
      rawDetails('Full reconciliation record', item));
  }
  function handoff() {
    const commands = operating.commands || {};
    const observed = array(data.pull_requests);
    const open = observed.filter(pr => String(pr.state).toLowerCase() === 'open');
    const guide = fileLink(operating.guide_path, 'Shared PM protocol ↗');
    const commandNodes = Object.entries(commands).map(([name, command]) => element('div', {}, element('div', { class: 'command-label' }, human(name)), element('pre', {}, text(command))));
    const steps = element('div', { class: 'handoff-grid' },
      element('section', { class: 'card' }, element('span', { class: 'handoff-step' }, '01'), element('h2', {}, 'Reconcile before assigning'), element('p', {}, 'Codex and Grok PMs start with the same state ledger, the pinned source, and the current decision ledger.'),
        element('ol', {}, element('li', {}, 'Read ', guide, ' and the repository instructions.'), element('li', {}, 'Check current master, PR heads, and CI against this snapshot.'), element('li', {}, 'Reconcile ', link(operating.ledger_url, 'issue #85'), ' and verify the coordinator lease before publishing assignments.'))),
      element('section', { class: 'card' }, element('span', { class: 'handoff-step' }, '02'), element('h2', {}, 'Record evidence and next action'), element('p', {}, 'Update the versioned state with the validated CLI. Record the ticket status, assigned owner, blocker, next action, and evidence. Every update has an actor, a reason, and an expected revision.'), element('p', {}, 'This browser view is read only. A snapshot export downloads a copy. Changes become shared through the state file, validation, and the repository review workflow.')),
      element('section', { class: 'card' }, element('span', { class: 'handoff-step' }, '03'), element('h2', {}, 'Assess the complete parent'), element('p', {}, 'Inspect every original acceptance criterion and definition-of-done item. Link the evidence and tested SHA, identify the implementers, and record independent review.'), element('p', {}, 'Partial changes, retained artifacts, and child tickets remain traceable evidence. Only complete original-parent acceptance contributes to the fixed point total.')),
      element('section', { class: 'card' }, element('span', { class: 'handoff-step' }, '04'), element('h2', {}, 'Validate, review, and publish'), element('p', {}, 'Run the state checks, regenerate the snapshot, and submit the change through the existing repository process. The coordinator publishes shared state while holding the lease.'), element('p', {}, 'Independent review and the required CI checks for the exact final head remain mandatory. Follow ', fileLink('AGENTS.md', 'AGENTS.md'), ' for the complete merge protocol.')));
    const documents = element('section', { class: 'card command-block' }, cardHeader('Canonical files & update commands', `Snapshot revision ${text(data.meta.revision)}. Run commands from the repository root.`),
      element('div', { class: 'document-list' }, [['Original scope', operating.source_path], ['Execution state', operating.state_path], ['PM protocol', operating.guide_path]].map(([label, path]) => element('div', { class: 'document-row' }, element('strong', {}, label), fileLink(path)))),
      element('p', { class: 'fine-print' }, 'Use the current revision when applying a patch. The validator rejects stale updates, inconsistent scope, and acceptance without required evidence.'), element('div', { class: 'command-block' }, commandNodes));
    const prs = element('section', { id: 'initial-pr-registry', class: 'card command-block' }, cardHeader('Initial audit PR registry', `${open.length} PRs were open in that audit · ${observed.length} observed PRs total.`), initialAuditProvenance(),
      element('p', { class: 'fine-print' }, 'Current recorded PR links are available in each ticket’s state details. The registry below preserves the initial audit evidence.'),
      open.length ? open.map(prRecord) : element('p', { class: 'muted' }, 'No open PRs were recorded in the initial audit.'), details('All initial audit PR records', observed.map(pr => rawDetails(`#${pr.number} · ${pr.title}`, pr))));
    const queue = element('section', { id: 'initial-reconciliation-queue', class: 'card command-block' }, cardHeader('Initial audit reconciliation queue', 'Retained findings are linked to existing original parents and their full acceptance contracts.'), initialAuditProvenance(), array(data.reconciliation_queue).map(reconciliationRecord));
    return [pageHeader('handoff', 'One working agreement for Codex, Grok, and human project managers.'), snapshotNotice(), steps, documents, prs, queue,
      rawDetails('Historical source metadata', data.source_metadata || {}, 'This is the preserved original plan metadata. Current execution status comes from the versioned state ledger.'),
      rawDetails('Complete audit context', data.audit_context || {}, 'Pinned evidence and limitations retained from the source audit.')];
  }
  function historyView() {
    const events = [...array(data.history)].reverse();
    return [pageHeader('history', 'A durable record of state, evidence, and acceptance decisions.'), snapshotNotice(),
      element('div', { class: 'notice neutral' }, element('p', {}, 'History records saved decisions. Completion stays unknown for unverified baselines; historical percentages are never reconstructed from PR counts.')),
      events.length ? element('ol', { class: 'history-list' }, events.map(event => element('li', { class: 'card history-item' },
        element('div', { class: 'history-meta' }, badge('PENDING', 'Revision ' + text(event.revision)), element('time', { datetime: event.at || '' }, date(event.at)), element('span', {}, 'By ', text(event.actor))),
        element('h2', {}, text(event.reason, 'State update')), event.source_sha ? element('p', {}, 'Source SHA: ', code(event.source_sha)) : null,
        rawDetails('Recorded state and changes', event)))) : element('div', { class: 'empty-state' }, element('h2', {}, 'No changes recorded'), element('p', {}, 'Validated state updates will appear here.'))];
  }

  function criteria(title, values, ids, assessments) {
    const recorded = new Map(array(assessments).map(item => [item.id, item]));
    return section(title, element('ol', { class: 'criteria-list' }, array(values).map((value, index) => {
      const id = ids[index];
      const result = recorded.get(id);
      return element('li', {}, id ? element('span', { class: 'criterion-id' }, id) : null, text(value),
        element('div', { class: 'criteria-state' }, badge(result?.status || 'NOT_VERIFIED'), result?.tested_sha ? code('Tested: ' + result.tested_sha) : null),
        result ? links(result.evidence_urls) : null);
    })));
  }
  function fileGroup(title, values) {
    return [element('h4', {}, title), array(values).length ? element('ul', { class: 'file-list' }, array(values).map(path => element('li', {}, fileLink(path)))) : element('p', { class: 'muted' }, 'None recorded.')];
  }
  function dependencyLinks(ids, scope) {
    const entries = array(ids);
    const content = entries.length ? element('div', { class: 'chip-list' }, entries.map(id => {
      const attr = scope === 'original' ? 'data-original-dependency' : 'data-dependency';
      if (tickets.has(id)) return ticketLink(id, `${id} · ${tickets.get(id).title}`, { class: 'chip', [attr]: id });
      const supplemental = followupMap.get(id);
      if (supplemental) {
        const label = `${id} · ${text(supplemental.title)}`;
        const node = externalURL(supplemental.source_url) ? link(supplemental.source_url, label, 'chip') : fileLink(supplemental.source_path, label);
        node.classList.add('chip');
        node.setAttribute(attr, id);
        return node;
      }
      return element('span', { class: 'chip', [attr]: id }, `${id} · Reference not available in this snapshot`);
    })) : element('p', { class: 'muted' }, scope === 'engineering' ? 'No engineering prerequisite recorded in the governing projection.' : scope === 'release' ? 'No separate release-gate dependency recorded.' : 'No original dependency recorded.');
    return element('div', { 'data-dependency-scope': scope }, content);
  }
  function dependencySection(ticket) {
    const rulings = array(ticket.dependency_ruling_ids).map(id => dependencyRulings.get(id)).filter(Boolean);
    return section('Dependencies & scheduling', element('h4', {}, 'Engineering prerequisites'),
      Array.isArray(ticket.effective_depends_on) ? dependencyLinks(ticket.effective_depends_on, 'engineering') : element('p', { class: 'source-warning' }, 'Engineering prerequisites are not projected. Regenerate the snapshot to apply the governing dependency rulings.'),
      element('h4', {}, 'Release-gate dependencies'),
      Array.isArray(ticket.release_gate_dependencies) ? dependencyLinks(ticket.release_gate_dependencies, 'release') : element('p', { class: 'source-warning' }, 'Release-gate dependencies are not projected. Regenerate the snapshot before scheduling.'),
      rulings.map(ruling => element('div', { class: 'source-warning', 'data-dependency-ruling': ruling.id }, element('h4', {}, `${ruling.id} · ${text(ruling.title)}`), element('p', {}, text(ruling.note)), link(ruling.source_url, `Read scope-freeze ruling ${ruling.id}`))),
      element('details', { class: 'record-details' }, element('summary', {}, 'Original planning dependencies'), element('p', {}, 'Preserved for provenance. Engineering scheduling uses the governing prerequisites above.'), dependencyLinks(ticket.depends_on, 'original')));
  }
  function renderTicket(ticket) {
    const current = ticket.current || {};
    const acceptance = current.acceptance || {};
    const epic = epics.get(ticket.epic);
    const close = button('×', closeTicket, 'icon-button');
    close.setAttribute('aria-label', 'Close ticket');
    const header = element('div', { class: 'drawer-header' },
      element('div', { class: 'drawer-heading-line' }, element('div', { class: 'eyebrow' }, 'Original ticket / ' + ticket.epic), close),
      element('span', { class: 'ticket-id' }, ticket.id), element('h2', { id: 'ticket-title' }, ticket.title),
      element('div', { class: 'drawer-tags' }, badge(ticket.priority, ticket.priority), badge(current.status), element('span', { class: 'badge outline' }, number(ticket.story_points) + ' original points'), element('span', { class: 'badge outline' }, text(ticket.type))),
      element('div', { class: 'drawer-provenance' }, element('span', {}, 'Snapshot: ', date(data.meta.as_of_utc)), element('span', { title: text(data.meta.source_sha) }, 'Source SHA: ', code(String(data.meta.source_sha).slice(0, 12)))));
    const state = section('Current recorded state', definitionList([
      ['Assigned owner', text(current.owner, 'Unassigned — no assignment recorded')], ['Acceptance decision', badge(acceptance.state || 'PENDING')],
      ['Evidence state', human(current.evidence_state)], ['Last state update', date(current.updated_at)],
      ['Expected owner role', text(ticket.owner_role), true],
    ]), element('div', { class: 'next-action' }, element('h4', {}, 'Next action'), element('p', {}, text(current.next_action, 'No next action recorded. Reconcile with the decision ledger.'))), element('h4', {}, 'Recorded blockers'), array(current.blockers).length ? list(current.blockers) : element('p', { class: 'muted' }, 'No blockers recorded.'), element('p', { class: 'fine-print' }, 'This is a static evidence record. Check ', link(operating.ledger_url, 'issue #85'), ' before acting.'));
    const review = section('Acceptance & independent review', definitionList([
      ['Assessed by', text(acceptance.assessed_by)], ['Assessment date', date(acceptance.assessed_at)], ['Assessment SHA', code(acceptance.assessed_sha)], ['Tested SHA', code(acceptance.tested_sha)],
      ['Implementers', array(acceptance.implemented_by).length ? acceptance.implemented_by.join(', ') : 'Not recorded'], ['Independent reviewer', text(acceptance.independent_reviewer)], ['Review date', date(acceptance.reviewed_at)],
    ]), links(acceptance.assessment_evidence_urls), links(acceptance.review_evidence_urls));
    const prs = section('Current recorded PR links', element('p', { class: 'fine-print' }, 'From this ticket’s current state ledger. PR status is a static record; confirm the current head before acting.'), array(current.pr_links).length ? current.pr_links.map(prRecord) : element('p', { class: 'muted' }, 'No pull request links recorded.'), element('p', { class: 'fine-print' }, 'PR state and merge evidence alone do not establish complete original-parent acceptance.'));
    prs.setAttribute('data-current-pr-links', '');
    const evidence = section('Current evidence', array(current.evidence_links).length ? links(current.evidence_links) : element('p', { class: 'muted' }, 'No current evidence links recorded.'));
    const depends = dependencySection(ticket);
    const childRecords = [...new Map([...array(ticket.followups).map(item => typeof item === 'string' ? followupMap.get(item) : item), ...followups.filter(item => item.parent_id === ticket.id)].filter(Boolean).map(item => [item.id, item])).values()];
    const children = childRecords.length ? section('Supplemental child & release work', element('p', { class: 'muted' }, 'These records support the original parent. Their estimates are excluded from the original point denominator.'), supplementalRows(childRecords)) : null;
    const reconciliation = array(data.reconciliation_queue).filter(item => item.existing_parent_id === ticket.id);
    const body = element('div', { class: 'drawer-body' },
      element('p', {}, text(ticket.description)), state,
      reconciliation.length ? section('Initial audit reconciliation findings', initialAuditProvenance(), reconciliation.map(reconciliationRecord)) : null,
      depends, children,
      criteria('Acceptance criteria', ticket.acceptance_criteria, array(ticket.acceptance_ids), acceptance.criteria),
      criteria('Definition of done', ticket.definition_of_done, array(ticket.definition_of_done).map((_, index) => `${ticket.id}-DOD${index + 1}`), acceptance.definition_of_done),
      section('Definition of ready', list(ticket.definition_of_ready)),
      section('Implementation steps', list(ticket.implementation_steps, true)),
      section('Interfaces & deliverable', element('h4', {}, 'Consumes'), element('p', {}, text(ticket.interfaces?.consumes)), element('h4', {}, 'Produces'), element('p', {}, text(ticket.interfaces?.produces)), element('h4', {}, 'Interface contract'), element('p', {}, text(ticket.interface_contract)), element('h4', {}, 'Deliverable'), element('p', {}, text(ticket.deliverable))),
      section('Files & verification', fileGroup('Review or modify', ticket.files_review_modify), fileGroup('Create', ticket.files_create), fileGroup('Existing API modules', ticket.existing_api_modules), fileGroup('Coverage paths', ticket.coverage_paths), element('h4', {}, 'Original test command'), element('pre', {}, text(ticket.test_command))),
      review, prs, evidence,
      section('Historical planning metadata', definitionList([
        ['Original epic', `${ticket.epic} · ${text(epic?.title)}`], ['Historical planning status', text(ticket.status)], ['Planning slug', text(ticket.slug)], ['Estimate confidence', text(ticket.estimate_confidence)], ['Required for full release', ticket.required_for_full_release ? 'Yes' : 'No'],
        ['Legacy work packages', array(ticket.legacy_work_packages).join(', ') || 'None recorded'], ['Audit findings', array(ticket.audit_findings).join(', ') || 'None recorded'], ['Original dependency slugs', array(ticket.depends_on_slugs).join(', ') || 'None recorded'],
        ['Original planning state', text(ticket.current_state), true], ['Original notes', text(ticket.notes, 'None recorded'), true],
      ]), element('h4', {}, 'Original planning references'), links(ticket.evidence_links)),
      rawDetails('Complete ticket record (JSON)', ticket, 'The complete original contract plus current state, retained without abridging source fields.'));
    dialog.replaceChildren(header, body);
    return close;
  }
  function closeTicket() {
    history.replaceState(null, '', routeHash(activeView || 'backlog'));
    applyRoute();
  }
  function renderView(view) {
    const views = { overview, backlog, epics: epicPortfolio, gates: gatesView, handoff, history: historyView };
    main.replaceChildren(...views[view]().filter(Boolean));
    if (view === 'backlog') renderBacklogResults();
    document.title = `${titles[view]} · TrustCopilot`;
    document.getElementById('view-label').textContent = titles[view];
    for (const anchor of document.querySelectorAll('[data-view]')) {
      if (anchor.dataset.view === view) anchor.setAttribute('aria-current', 'page');
      else anchor.removeAttribute('aria-current');
    }
  }
  function applyRoute() {
    const raw = window.location.hash.slice(1);
    // A skip-link target is a document anchor, not a view change.
    if (raw === 'main') {
      if (!activeView) { activeView = 'overview'; renderView(activeView); }
      main.focus();
      return;
    }
    const params = new URLSearchParams(raw);
    const id = params.get('ticket');
    const requested = raw.includes('=') ? params.get('view') || (id ? 'backlog' : 'overview') : raw || 'overview';
    const view = Object.hasOwn(titles, requested) ? requested : 'overview';
    if (view !== activeView) {
      activeView = view;
      renderView(view);
      if (!id) window.scrollTo(0, 0);
    }
    if (id) {
      if (!dialog.open && !returnFocus) returnFocus = document.activeElement;
      if (id !== activeTicket || !dialog.open) {
        const ticket = tickets.get(id);
        let focus;
        if (ticket) focus = renderTicket(ticket);
        else {
          focus = button('Close ticket', closeTicket);
          dialog.replaceChildren(element('div', { class: 'drawer-header' }, element('h2', { id: 'ticket-title' }, 'Ticket not found'), focus), element('div', { class: 'drawer-body' }, element('p', {}, `No original ticket with ID ${id} exists in this snapshot.`)));
        }
        activeTicket = id;
        if (!dialog.open) dialog.showModal();
        dialog.querySelector('.drawer-body')?.scrollTo(0, 0);
        focus.focus();
      }
    } else if (dialog.open) {
      dialog.close();
      activeTicket = null;
      if (returnFocus?.isConnected && returnFocus !== document.body) returnFocus.focus({ preventScroll: true });
      else main.querySelector('h1')?.focus({ preventScroll: true });
      returnFocus = null;
    }
    if (focusMainOnRoute && !id) {
      main.querySelector('h1')?.focus({ preventScroll: true });
      focusMainOnRoute = false;
    }
  }

  document.getElementById('source-time').textContent = date(data.meta.as_of_utc);
  document.getElementById('source-time').title = text(data.meta.as_of_utc);
  document.getElementById('source-sha').textContent = 'SHA ' + text(data.meta.source_sha).slice(0, 12);
  document.getElementById('source-sha').title = text(data.meta.source_sha);
  document.getElementById('sidebar-version').textContent = `SCOPE V${text(data.meta.scope_version)}  /  REVISION ${text(data.meta.revision)}`;
  document.getElementById('nav-backlog-count').textContent = number(summary.total_tickets);
  document.getElementById('nav-epic-count').textContent = number(data.epics.length);
  for (const anchor of document.querySelectorAll('.project-nav a')) anchor.addEventListener('click', () => {
    focusMainOnRoute = anchor.dataset.view !== activeView;
    if (!focusMainOnRoute) main.querySelector('h1')?.focus();
  });
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeTicket(); });
  dialog.addEventListener('click', event => {
    if (event.target !== dialog) return;
    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) closeTicket();
  });
  window.addEventListener('hashchange', applyRoute);
  applyRoute();
})();
