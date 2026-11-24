import { spawn } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const frontendDir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(frontendDir, '..')

function isPortOpen(port, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const socket = net.createConnection({ port, host })
    socket.once('connect', () => {
      socket.destroy()
      resolve(true)
    })
    socket.once('error', () => {
      socket.destroy()
      resolve(false)
    })
  })
}

async function waitForPort(port, timeoutMs = 4000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await isPortOpen(port)) return true
    await new Promise((r) => setTimeout(r, 150))
  }
  return false
}

function resolveBackendPython() {
  const winVenv = path.join(repoRoot, 'backend', '.venv', 'Scripts', 'python.exe')
  if (fs.existsSync(winVenv)) return winVenv
  const posixVenv = path.join(repoRoot, 'backend', '.venv', 'bin', 'python')
  if (fs.existsSync(posixVenv)) return posixVenv
  return 'python'
}

function autoStartFlaskApi() {
  return {
    name: 'cabcompare-auto-backend',
    async configureServer(server) {
      if (await isPortOpen(5000)) return
      const pythonBin = resolveBackendPython()
      const apiProc = spawn(pythonBin, ['-m', 'backend.app'], {
        cwd: repoRoot,
        stdio: 'inherit',
        windowsHide: true,
      })
      apiProc.on('error', (err) => {
        console.warn(`[cabcompare-api] Could not auto-start Flask backend: ${err.message}`)
      })
      const stopBackend = () => {
        if (!apiProc.killed) apiProc.kill()
      }
      server.httpServer?.once('close', stopBackend)
      process.once('exit', stopBackend)
      const ready = await waitForPort(5000, 4000)
      if (ready) console.info('[cabcompare-api] Flask API ready on http://127.0.0.1:5000')
    },
  }
}

export default defineConfig({
  plugins: [react(), autoStartFlaskApi()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('error', (err) => {
            console.warn(`[cabcompare-proxy] /api error: ${err.message}`)
          })
        },
      },
    },
  },
})
