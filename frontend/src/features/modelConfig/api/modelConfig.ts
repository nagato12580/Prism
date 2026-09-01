// Model provider + default model config against Backend `/model-providers` routes.
import { requestJSON } from '@/features/knowledge/api/client'

export interface ModelProvider {
  provider_id: string
  display_name: string
  provider_type: string
  base_url: string
  api_key_env: string | null
  has_api_key: boolean
  api_key_masked: string | null
  capabilities: Record<string, boolean> | null
  enabled_models: string[]
  is_enabled: boolean
  is_builtin: boolean
}

export interface ModelProviderCreate {
  provider_id: string
  display_name: string
  provider_type?: string
  base_url: string
  api_key_env?: string | null
  api_key?: string | null
  capabilities?: Record<string, boolean>
  enabled_models?: string[]
  is_enabled?: boolean
}

export interface ModelProviderUpdate {
  display_name?: string
  provider_type?: string
  base_url?: string
  api_key_env?: string | null
  api_key?: string | null
  capabilities?: Record<string, boolean>
  enabled_models?: string[]
  is_enabled?: boolean
}

export interface ModelRef {
  spec: string
  provider_id: string
  model_id: string
}

export interface ModelStatus {
  status: 'available' | 'unavailable' | 'error'
  reason?: string
}

export const modelConfigApi = {
  listProviders(): Promise<{ items: ModelProvider[] }> {
    return requestJSON('/model-providers/providers')
  },
  createProvider(data: ModelProviderCreate): Promise<ModelProvider> {
    return requestJSON('/model-providers/providers', { method: 'POST', body: JSON.stringify(data) })
  },
  updateProvider(providerId: string, data: ModelProviderUpdate): Promise<ModelProvider> {
    return requestJSON(`/model-providers/providers/${encodeURIComponent(providerId)}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
  deleteProvider(providerId: string): Promise<{ detail: string }> {
    return requestJSON(`/model-providers/providers/${encodeURIComponent(providerId)}`, { method: 'DELETE' })
  },
  listModels(): Promise<{ items: ModelRef[] }> {
    return requestJSON('/model-providers/models')
  },
  modelStatus(spec: string): Promise<ModelStatus> {
    return requestJSON(`/model-providers/models/status?spec=${encodeURIComponent(spec)}`)
  },
  getDefault(): Promise<{ spec: string | null }> {
    return requestJSON('/model-providers/config/default')
  },
  setDefault(spec: string): Promise<{ spec: string }> {
    return requestJSON('/model-providers/config/default', { method: 'PUT', body: JSON.stringify({ spec }) })
  },
  refreshCache(): Promise<{ detail: string }> {
    return requestJSON('/model-providers/cache/refresh', { method: 'POST' })
  },
}
