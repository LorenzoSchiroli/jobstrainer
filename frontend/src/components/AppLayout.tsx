import Sidebar from './Sidebar'
import { useSidebarOpen } from '../hooks/useSidebarOpen'

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { open, toggle } = useSidebarOpen()
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <Sidebar open={open} onToggle={toggle} />
      {!open && (
        <button onClick={toggle} aria-label="Open sidebar"
                style={{ position: 'fixed', top: 12, left: 12, zIndex: 20, background: '#1f1f1f', color: '#fff', border: '1px solid #2a2a2a', borderRadius: 6, padding: '0.35rem 0.6rem', cursor: 'pointer' }}>
          ☰
        </button>
      )}
      <main style={{
        flex: 1, minWidth: 0,
        marginLeft: open ? 240 : 0,
        transition: 'margin-left 200ms ease',
      }}>{children}</main>
    </div>
  )
}
