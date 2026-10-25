import { NavLink, Route, Routes, useSearchParams } from 'react-router-dom'
import { CameraPage } from './pages/CameraPage'
import { GesturesPage } from './pages/GesturesPage'
import { SettingsPage } from './pages/SettingsPage'
import { TestPage } from './pages/TestPage'

function embedded(): boolean {
  const params = new URLSearchParams(window.location.search)
  if (params.get('embed') === '1') window.sessionStorage.setItem('synchro-embed', '1')
  return window.sessionStorage.getItem('synchro-embed') === '1'
}

export function App() {
  const [params] = useSearchParams()
  const insideMacApp = params.get('embed') === '1' || embedded()
  return (
    <div className={insideMacApp ? 'shell embed' : 'shell'}>
      {!insideMacApp && <aside className="sidebar">
        <div className="brand">
          <strong>Synchro</strong>
          <span>Camera and gestures</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end>Camera</NavLink>
          <NavLink to="/gestures">Gestures</NavLink>
          <NavLink to="/test">Test</NavLink>
        </nav>
        <div className="spacer" />
        <nav className="nav">
          <NavLink to="/settings">Settings</NavLink>
        </nav>
      </aside>}
      <main className="main">
        <Routes>
          <Route path="/" element={<CameraPage />} />
          <Route path="/gestures" element={<GesturesPage />} />
          <Route path="/test" element={<TestPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  )
}
