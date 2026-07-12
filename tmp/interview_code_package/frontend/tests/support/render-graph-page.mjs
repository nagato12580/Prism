import { resolve } from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { createServer } from 'vite'

export async function renderGraphPage(props = {}) {
  const root = resolve(import.meta.dirname, '..', '..')
  const server = await createServer({
    configFile: resolve(root, 'vite.config.ts'),
    root,
    logLevel: 'error',
    server: { middlewareMode: true },
    appType: 'custom',
  })

  try {
    const mod = await server.ssrLoadModule('/src/pages/KnowledgeGraphPage.tsx')
    return renderToStaticMarkup(React.createElement(mod.KnowledgeGraphPage, props))
  } finally {
    await server.close()
  }
}
