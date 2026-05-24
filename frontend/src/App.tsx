import * as Tooltip from '@radix-ui/react-tooltip'
import './App.css'
import { AppShell } from './app/AppShell'

function App() {
  return (
    <Tooltip.Provider delayDuration={260} skipDelayDuration={120}>
      <AppShell />
    </Tooltip.Provider>
  )
}

export default App
