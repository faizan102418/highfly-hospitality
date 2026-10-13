import React from 'react';
import './ui-foundation.css';

export type PMSView = 'Dashboard' | 'Rooms' | 'Guests' | 'Reservations' | 'Front Desk' | 'Housekeeping' | 'Reports' | 'Billing' | 'Backup';

type Props = {
  user: { username: string; role: string };
  view: PMSView;
  modules: PMSView[];
  onViewChange: (view: PMSView) => void;
  onLogout: () => void;
  error?: string;
  children: React.ReactNode;
};

const meta: Record<PMSView, { label: string; group: 'Daily work' | 'Management' }> = {
  Dashboard: { label: 'Dashboard', group: 'Daily work' },
  Rooms: { label: 'Rooms', group: 'Daily work' },
  Guests: { label: 'Guests', group: 'Daily work' },
  Reservations: { label: 'Reservations', group: 'Daily work' },
  'Front Desk': { label: 'Front desk', group: 'Daily work' },
  Housekeeping: { label: 'Housekeeping', group: 'Daily work' },
  Reports: { label: 'Reports', group: 'Management' },
  Billing: { label: 'Billing & folios', group: 'Management' },
  Backup: { label: 'Backup & recovery', group: 'Management' },
};

const icon: Record<PMSView, string> = {
  Dashboard: '⌂', Rooms: '▦', Guests: '♙', Reservations: '▤', 'Front Desk': '⇄',
  Housekeeping: '✓', Reports: '▥', Billing: '₨', Backup: '↥',
};

export default function PMSLayout({ user, view, modules, onViewChange, onLogout, error, children }: Props) {
  const daily = modules.filter(v => meta[v].group === 'Daily work');
  const management = modules.filter(v => meta[v].group === 'Management');

  const renderNav = (items: PMSView[]) => items.map(item => (
    <button key={item} type="button" className={`simple-nav-item ${view === item ? 'active' : ''}`} onClick={() => onViewChange(item)} aria-current={view === item ? 'page' : undefined}>
      <span className="simple-nav-icon" aria-hidden="true">{icon[item]}</span><span>{meta[item].label}</span>
      {view === item && <span className="simple-nav-current" aria-hidden="true">•</span>}
    </button>
  ));

  return <div className="simple-pms">
    <a className="ui-skip-link" href="#main-content">Skip to content</a>
    <aside className="simple-sidebar">
      <div className="simple-brand"><div className="simple-brand-mark" aria-hidden="true">H</div><div><strong>HIGHFLY</strong><small>Hospitality OS</small></div></div>
      <div className="simple-property">
        <small>WORKSPACE</small>
        <strong>Property operations</strong>
        <span>Manage your day, in one place</span>
      </div>
      <nav aria-label="Hotel modules">
        <div className="simple-nav-label">OPERATIONS</div>{renderNav(daily)}
        {management.length > 0 && <><div className="simple-nav-label">MANAGEMENT</div>{renderNav(management)}</>}
      </nav>
      <div className="simple-sidebar-bottom"><span className="simple-online-dot" /> Connected workspace</div>
    </aside>
    <div className="simple-main">
      <header className="simple-topbar">
        <div className="ui-heading-block"><div className="simple-page-kicker">HOSPITALITY OPERATIONS</div><h1>{meta[view].label}</h1></div>
        <div className="simple-account">
          <div className="simple-avatar" aria-hidden="true">{user.username.slice(0,1).toUpperCase()}</div>
          <div className="ui-account-copy"><strong>{user.username}</strong><small>{user.role.replace(/_/g, ' ')}</small></div>
          <button className="ui-logout" type="button" onClick={onLogout}>Log out <span aria-hidden="true">↗</span></button>
        </div>
      </header>
      {error && <div className="simple-error" role="alert"><span aria-hidden="true">!</span>{error}</div>}
      <main className="simple-content" id="main-content" tabIndex={-1}>{children}</main>
      <footer className="ui-footer"><span>HIGHFLY HOSPITALITY</span><span>Property operations workspace</span></footer>
    </div>
  </div>;
}
